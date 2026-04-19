"""
Hyde: A modern, Pythonic data analysis and plotting environment for the labscript-suite.
"""

from __future__ import annotations

import builtins
import datetime
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

from .table_macros import publish_table_macro_registry, register_table_macro
from .execution.ipc import publish_project_state_result, signal_open_table

__version__ = "0.1.0.dev0"

HYDE_GUI = False
FORMAT_VERSION = 1
EXCLUDED_NAMES = {"In", "Out", "exit", "quit"}


def gui_mode(enable=True):
    """
    Set whether Hyde is running within the managed GUI environment.
    This flag controls whether public helpers attempt to send IPC signals to the GUI.
    """
    global HYDE_GUI
    HYDE_GUI = bool(enable)


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
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
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


def new_project(path, load=True):
    """
    Creates a new empty Hyde project at the specified path and optionally injects it as the active session.
    """
    project_dir = _project_dir(path)
    if project_dir.exists():
        raise RuntimeError(f"Cannot create new project: '{project_dir}' already exists.")
    
    _ensure_project_dirs(project_dir)
    _write_manifest(project_dir, [])
    
    master_path = project_dir / "procedures" / "master.py"
    with master_path.open("w", encoding="utf-8") as f:
        f.write('"""Master initialization script for Hyde project."""\n\n')
    
    if load:
        load_project(path=str(project_dir))


def save_project(path=None, mode="save"):
    """
    Save the current kernel namespace into a Hyde project package.

    Args:
        path (str, optional): Target `.hy` project directory. Defaults to the
            current working directory inside the Hyde-managed kernel if mode="save".
        mode (str): One of "save", "copy", or "save_as".
    """
    if mode not in ("save", "copy", "save_as"):
        raise ValueError("save_project mode must be 'save', 'copy', or 'save_as'")
        
    if mode == "save" and path is not None:
        raise ValueError("Cannot provide path with mode='save'. Use mode='save_as' or mode='copy'.")
        
    if mode in ("save_as", "copy") and path is None:
        raise ValueError(f"Path required for mode={mode!r}.")
        
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
        
    if HYDE_GUI:
        publish_project_state_result(
            "save",
            str(project_dir),
            success=success,
            errors=errors,
            object_count=len(object_entries),
            mode=mode,
        )
    if not success:
        raise RuntimeError(f"Hyde save_project failed for {project_dir}: {errors}")
    return object_entries


def load_project(path=None):
    """
    Load saved kernel namespace objects from a Hyde project package.

    Args:
        path (str, optional): Source `.hy` project directory. Defaults to the
            current working directory inside the Hyde-managed kernel.
    """
    project_dir = _project_dir(path)
    
    if HYDE_GUI:
        publish_project_state_result("purge", str(project_dir))
        
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
        
    if HYDE_GUI:
        publish_project_state_result(
            "load",
            str(project_dir),
            success=success,
            errors=errors,
            object_count=loaded,
        )
    if not success:
        raise RuntimeError(f"Hyde load_project failed for {project_dir}: {errors}")
    return loaded


def table(*args, target=None, title=None):
    """
    Open or append to a Hyde table window, or register a recreation macro.

    This public Hyde API supports two forms:

    1. Direct call form:
       ``hyde.table(a, b, target=..., title=...)``
       Opens a new table or appends to an existing one.
    2. Decorator form:
       ``@hyde.table``
       Registers a parameterized table recreation macro.

    Args:
        *args: Live Python objects to include in the table, or one function in
            decorator form.
        target (str, optional): The unique handle of an existing table (e.g., 'Table0')
            to which these objects should be appended. If None, a new table
            window is created.
        title (str, optional): A user-friendly visible title for a new table. 
            If provided, this label is used in the window title bar.

    Behavior:
        - Resolves each object's top-level name in the caller's namespace by identity (`is`).
        - Searches the caller's locals, then globals.
        - Validates that each object is a supported 1D numeric array-like.
        - Signals the Hyde executor to open or update a table via the ProcessTree.
        - Registers decorated functions as table recreation macros whose
          parameters name the live kernel objects needed to recreate the table.

    Failure Modes:
        - Raises TypeError if a positional argument is not a 1D numeric array-like.
        - Raises TypeError if decorator form uses unsupported non-positional parameters.
        - Raises ValueError if an object cannot be uniquely resolved to a top-level name.
    """
    if not args and target is None and title is None:
        def decorator(func):
            register_table_macro(func)
            publish_table_macro_registry()
            return func

        return decorator

    if (
        len(args) == 1
        and callable(args[0])
        and target is None
        and title is None
    ):
        register_table_macro(args[0])
        publish_table_macro_registry()
        return args[0]

    from .execution.helpers import resolve_names
    
    # Capture the caller's frame for name resolution
    frame = inspect.currentframe().f_back
    
    names = resolve_names(args, frame, validate_1d=True)
    
    if HYDE_GUI:
        # Signal the parent executor (Watchdog) to relay the open intent to the GUI
        signal_open_table(names, target, title=title)
