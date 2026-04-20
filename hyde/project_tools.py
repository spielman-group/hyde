from __future__ import annotations

import builtins
import datetime
import inspect
import pickle
import shutil
import types
from pathlib import Path

import __main__
import numpy as np
import tomllib
import tomli_w

from .paths import DEFAULT_PROJECT_TEMPLATE

FORMAT_VERSION = 1
EXCLUDED_NAMES = {"In", "Out", "exit", "quit"}


def resolve_project_dir(path=None):
    if path is None:
        return Path.cwd()
    return Path(path).expanduser().resolve()


def ensure_project_dirs(project_dir: Path):
    for relpath in ("data", "terminal", "procedures"):
        (project_dir / relpath).mkdir(parents=True, exist_ok=True)


def copy_project_template(project_dir: Path):
    shutil.copytree(
        DEFAULT_PROJECT_TEMPLATE,
        project_dir,
        ignore=shutil.ignore_patterns("__pycache__"),
    )


def copy_project_procedures(source_project_dir: Path, target_project_dir: Path):
    source_procedures = source_project_dir / "procedures"
    target_procedures = target_project_dir / "procedures"
    if target_procedures.exists():
        shutil.rmtree(target_procedures)
    if source_procedures.exists():
        shutil.copytree(
            source_procedures,
            target_procedures,
            ignore=shutil.ignore_patterns("__pycache__"),
        )


def is_package(value):
    return isinstance(value, types.ModuleType) and hasattr(value, "__path__")


def is_excluded(name, value):
    if not name or name.startswith("_"):
        return True
    if name in EXCLUDED_NAMES:
        return True
    if isinstance(value, types.ModuleType) or is_package(value):
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


def iter_saveable_objects():
    for name, value in sorted(__main__.__dict__.items()):
        if is_excluded(name, value):
            continue
        yield name, value


def serialize_object(path: Path, value):
    if isinstance(value, np.ndarray):
        with path.open("wb") as handle:
            np.save(handle, value, allow_pickle=False)
        return "npy"
    with path.open("wb") as handle:
        pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return "pickle"


def deserialize_object(path: Path, serializer):
    if serializer == "npy":
        with path.open("rb") as handle:
            return np.load(handle, allow_pickle=False)
    if serializer == "pickle":
        with path.open("rb") as handle:
            return pickle.load(handle)
    raise ValueError(f"Unknown Hyde serializer {serializer!r}.")


def write_manifest(project_dir: Path, object_entries):
    manifest_path = project_dir / "manifest.toml"
    project_name = project_dir.name[:-3] if project_dir.name.endswith(".hy") else project_dir.name
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest = {
        "format_version": FORMAT_VERSION,
        "project_name": project_name,
        "saved_at": timestamp,
        "objects": object_entries,
    }
    with manifest_path.open("wb") as handle:
        tomli_w.dump(manifest, handle)


def read_manifest(project_dir: Path):
    manifest_path = project_dir / "manifest.toml"
    if not manifest_path.exists():
        return {"objects": []}
    with manifest_path.open("rb") as handle:
        return tomllib.load(handle)
