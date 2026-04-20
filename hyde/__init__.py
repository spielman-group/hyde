"""
Hyde: A modern, Pythonic data analysis and plotting environment for the labscript-suite.
"""

from __future__ import annotations

import inspect
import os
import shutil
import sys
import builtins
from pathlib import Path

import numpy as np

from .paths import HYDE_DIR
from . import project_tools
from .table_macros import publish_table_macro_registry, register_table_macro
from .execution.ipc import (
    signal_activate_project,
    signal_enter_no_project_state,
    publish_project_state_result,
    signal_open_table,
    signal_quit_requested,
)

__version__ = "0.1.0.dev0"

HYDE_GUI = False
HYDE_PROJECT_DIR = None
_ORIGINAL_BUILTINS_QUIT = getattr(builtins, "quit", None)
_ORIGINAL_BUILTINS_EXIT = getattr(builtins, "exit", None)


def gui_mode(enable=True):
    """
    Set whether Hyde is running within the managed GUI environment.
    This flag controls whether public helpers attempt to send IPC signals to the GUI.
    When enabled, the Hyde module is also exposed in the interactive kernel
    namespace as `hyde` so visible commands can use the public API directly.
    """
    global HYDE_GUI
    HYDE_GUI = bool(enable)
    main_module = sys.modules["__main__"]
    if HYDE_GUI:
        hyde_module = sys.modules[__name__]
        main_module.__dict__["hyde"] = hyde_module
        main_module.__dict__["quit"] = quit
        main_module.__dict__["exit"] = quit
        builtins.hyde = hyde_module
        builtins.quit = quit
        builtins.exit = quit
    else:
        if _ORIGINAL_BUILTINS_QUIT is not None:
            builtins.quit = _ORIGINAL_BUILTINS_QUIT
        if _ORIGINAL_BUILTINS_EXIT is not None:
            builtins.exit = _ORIGINAL_BUILTINS_EXIT


def new_project(path, load=True, overwrite=False):
    """
    Creates a new empty Hyde project at the specified path and optionally injects it as the active session.
    """
    project_dir = project_tools.resolve_project_dir(path)
    try:
        if project_dir.exists():
            if not overwrite:
                raise RuntimeError(f"Cannot create new project: '{project_dir}' already exists.")
            if project_dir.is_dir():
                shutil.rmtree(project_dir)
            else:
                project_dir.unlink()

        project_tools.copy_project_template(project_dir)
    except Exception as exc:
        publish_project_state_result(
            "new",
            str(project_dir),
            success=False,
            errors=[str(exc)],
            object_count=0,
            mode="new",
        )
        raise

    if load:
        load_project(path=str(project_dir))
    else:
        publish_project_state_result(
            "new",
            str(project_dir),
            success=True,
            errors=[],
            object_count=0,
            mode="new",
        )


def save_project(path=None, mode="save", overwrite=False):
    """
    Save the current kernel namespace into a Hyde project package.

    Args:
        path (str, optional): Target `.hy` project directory. Defaults to the
            active Hyde project when ``mode="save"``.
        mode (str): One of "save", "copy", or "save_as".
        overwrite (bool): Allow replacing an existing target for ``save_as`` or ``copy``.
    """
    if mode not in ("save", "copy", "save_as"):
        raise ValueError("save_project mode must be 'save', 'copy', or 'save_as'")
        
    if mode == "save" and path is not None:
        raise ValueError("Cannot provide path with mode='save'. Use mode='save_as' or mode='copy'.")
        
    if mode in ("save_as", "copy") and path is None:
        raise ValueError(f"Path required for mode={mode!r}.")
        
    global HYDE_PROJECT_DIR

    if HYDE_PROJECT_DIR is None:
        raise RuntimeError("No Hyde project is active.")

    source_project_dir = project_tools.resolve_project_dir(HYDE_PROJECT_DIR)
    project_dir = project_tools.resolve_project_dir(
        HYDE_PROJECT_DIR if mode == "save" and path is None else path
    )
    errors = []
    object_entries = []
    success = True
    try:
        if mode in ("save_as", "copy") and project_dir != source_project_dir:
            if project_dir.exists() and not project_dir.is_dir():
                if not overwrite:
                    raise RuntimeError(f"Target path already exists: '{project_dir}'.")
                project_dir.unlink()
            elif project_dir.exists() and any(project_dir.iterdir()) and not overwrite:
                raise RuntimeError(f"Target project already exists and is not empty: '{project_dir}'.")
        project_tools.ensure_project_dirs(project_dir)
        if mode in ("save_as", "copy") and project_dir != source_project_dir:
            project_tools.copy_project_procedures(source_project_dir, project_dir)
        data_dir = project_dir / "data"
        if data_dir.exists():
            for child in data_dir.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child)

        for name, value in project_tools.iter_saveable_objects():
            serializer = "npy" if isinstance(value, np.ndarray) else "pickle"
            suffix = ".npy" if serializer == "npy" else ".pkl"
            relpath = Path("data") / f"{name}{suffix}"
            try:
                actual_serializer = project_tools.serialize_object(project_dir / relpath, value)
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

        project_tools.write_manifest(project_dir, object_entries)
        if mode == "save":
            HYDE_PROJECT_DIR = str(project_dir)
        if mode == "save_as" and project_dir != source_project_dir:
            os.chdir(project_dir)
            HYDE_PROJECT_DIR = str(project_dir)
            signal_activate_project(str(project_dir))
    except Exception as exc:
        success = False
        errors.append(str(exc))

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
    return None


def load_project(path=None):
    """
    Load saved kernel namespace objects from a Hyde project package.

    Args:
        path (str, optional): Source `.hy` project directory. Defaults to the
            active Hyde project.
    """
    global HYDE_PROJECT_DIR

    errors = []
    loaded = 0
    success = True
    project_dir = None
    try:
        if path is None and HYDE_PROJECT_DIR is None:
            raise RuntimeError("No Hyde project is active.")

        project_dir = project_tools.resolve_project_dir(HYDE_PROJECT_DIR if path is None else path)
        from .features.hyde_features import execute_procedures_bootstrap

        HYDE_PROJECT_DIR = None
        signal_enter_no_project_state()
        execute_procedures_bootstrap(
            str(project_dir),
            os.path.dirname(HYDE_DIR),
            reset_namespace=True,
        )
        manifest = project_tools.read_manifest(project_dir)
        for entry in manifest.get("objects", []):
            name = entry["name"]
            serializer = entry["serializer"]
            object_path = project_dir / entry["path"]
            if not object_path.exists():
                errors.append(f"{name}: missing file {object_path}")
                continue
            try:
                sys.modules["__main__"].__dict__[name] = project_tools.deserialize_object(object_path, serializer)
                loaded += 1
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        HYDE_PROJECT_DIR = str(project_dir)
    except Exception as exc:
        success = False
        errors.append(str(exc))

    if success:
        signal_activate_project(str(project_dir))
    publish_project_state_result(
        "load",
        str(project_dir if project_dir is not None else path),
        success=success,
        errors=errors,
        object_count=loaded,
        mode="load",
    )
    if not success:
        raise RuntimeError(f"Hyde load_project failed for {project_dir}: {errors}")
    return loaded


def quit():
    """
    Request an orderly Hyde shutdown.

    In Hyde GUI mode this asks the parent GUI process to tear down the kernel
    clients and child process before exiting the application. Outside GUI mode
    it exits the current interpreter.
    """
    if HYDE_GUI:
        signal_enter_no_project_state()
        signal_quit_requested()
        return None
    raise SystemExit(0)


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
