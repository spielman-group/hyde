"""Kernel-side project state persistence helpers."""

from __future__ import annotations

import builtins
import datetime as _dt
import inspect
import os
import pickle
import shutil
import types
from pathlib import Path

import __main__
import numpy as np
import tomllib
import tomli_w

from .execution.ipc import publish_project_state_result

FORMAT_VERSION = 1
EXCLUDED_NAMES = {"In", "Out", "exit", "quit"}


def _project_dir(path=None):
    if path is None:
        return Path.cwd()
    return Path(path).expanduser().resolve()


def _ensure_project_dirs(project_dir: Path):
    for relpath in ("data", "terminal", "procedures"):
        (project_dir / relpath).mkdir(parents=True, exist_ok=True)


def _is_package(value):
    return isinstance(value, types.ModuleType) and hasattr(value, "__path__")


def _is_excluded(name, value):
    if not name or name.startswith("_"):
        return True
    if name in EXCLUDED_NAMES:
        return True
    if isinstance(value, types.ModuleType) or _is_package(value):
        return True
    if inspect.isroutine(value) or inspect.isbuiltin(value) or inspect.ismethod(value):
        return True
    if inspect.isclass(value) or isinstance(value, type):
        return True
    builtins_exit = getattr(builtins, "exit", None)
    builtins_quit = getattr(builtins, "quit", None)
    if value is builtins_exit or value is builtins_quit:
        return True
    return False


def _iter_saveable_objects():
    for name, value in sorted(__main__.__dict__.items()):
        if _is_excluded(name, value):
            continue
        yield name, value


def _serialize_object(path: Path, value):
    if isinstance(value, np.ndarray):
        with path.open("wb") as handle:
            np.save(handle, value, allow_pickle=False)
        return "npy"
    with path.open("wb") as handle:
        pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return "pickle"


def _deserialize_object(path: Path, serializer):
    if serializer == "npy":
        with path.open("rb") as handle:
            return np.load(handle, allow_pickle=False)
    if serializer == "pickle":
        with path.open("rb") as handle:
            return pickle.load(handle)
    raise ValueError(f"Unknown Hyde serializer {serializer!r}.")


def _write_manifest(project_dir: Path, object_entries):
    manifest_path = project_dir / "manifest.toml"
    project_name = project_dir.name[:-3] if project_dir.name.endswith(".hy") else project_dir.name
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    manifest = {
        "format_version": FORMAT_VERSION,
        "project_name": project_name,
        "saved_at": timestamp,
        "objects": object_entries,
    }
    with manifest_path.open("wb") as handle:
        tomli_w.dump(manifest, handle)


def _read_manifest(project_dir: Path):
    manifest_path = project_dir / "manifest.toml"
    if not manifest_path.exists():
        return {"objects": []}
    with manifest_path.open("rb") as handle:
        return tomllib.load(handle)


def save_state(path=None):
    """
    Save the current kernel namespace into a Hyde project package.

    Args:
        path (str, optional): Target `.hy` project directory. Defaults to the
            current working directory inside the Hyde-managed kernel.
    """
    project_dir = _project_dir(path)
    errors = []
    object_entries = []
    success = True
    try:
        _ensure_project_dirs(project_dir)
        data_dir = project_dir / "data"
        if data_dir.exists():
            for child in data_dir.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child)

        for name, value in _iter_saveable_objects():
            serializer = "npy" if isinstance(value, np.ndarray) else "pickle"
            suffix = ".npy" if serializer == "npy" else ".pkl"
            relpath = Path("data") / f"{name}{suffix}"
            try:
                actual_serializer = _serialize_object(project_dir / relpath, value)
                object_entries.append(
                    {
                        "name": name,
                        "serializer": actual_serializer,
                        "path": relpath.as_posix(),
                        "python_type": type(value).__name__,
                    }
                )
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        _write_manifest(project_dir, object_entries)
    except Exception as exc:
        success = False
        errors.append(str(exc))
    publish_project_state_result(
        "save",
        str(project_dir),
        success=success,
        errors=errors,
        object_count=len(object_entries),
    )
    if not success:
        raise RuntimeError(f"Hyde save_state failed for {project_dir}: {errors}")
    return object_entries


def load_state(path=None):
    """
    Load saved kernel namespace objects from a Hyde project package.

    Args:
        path (str, optional): Source `.hy` project directory. Defaults to the
            current working directory inside the Hyde-managed kernel.
    """
    project_dir = _project_dir(path)
    errors = []
    loaded = 0
    success = True
    try:
        manifest = _read_manifest(project_dir)
        for entry in manifest.get("objects", []):
            name = entry["name"]
            serializer = entry["serializer"]
            object_path = project_dir / entry["path"]
            if not object_path.exists():
                errors.append(f"{name}: missing file {object_path}")
                continue
            try:
                __main__.__dict__[name] = _deserialize_object(object_path, serializer)
                loaded += 1
            except Exception as exc:
                errors.append(f"{name}: {exc}")
    except Exception as exc:
        success = False
        errors.append(str(exc))
    publish_project_state_result(
        "load",
        str(project_dir),
        success=success,
        errors=errors,
        object_count=loaded,
    )
    if not success:
        raise RuntimeError(f"Hyde load_state failed for {project_dir}: {errors}")
    return loaded
