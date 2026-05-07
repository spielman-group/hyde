"""
Hyde: A modern, Pythonic data analysis and plotting environment for the labscript-suite.
"""

from __future__ import annotations

import inspect
import functools
import os
import shutil
import sys
import contextvars
import builtins
import __main__
from pathlib import Path

import numpy as np

from .paths import HYDE_DIR
from . import project_tools
from .recreation_registry import (
    publish_figure_macro_registry,
    publish_table_macro_registry,
    register_figure_macro,
    register_table_macro,
)
from .execution.ipc import (
    signal_activate_project,
    signal_enter_no_project_state,
    publish_project_state_result,
    signal_open_table,
    signal_quit_requested,
)

__version__ = "0.1.0.dev0"

HYDE_GUI = False
HYDE_DEBUG = True
HYDE_PROJECT_DIR = None
_ORIGINAL_BUILTINS_QUIT = getattr(builtins, "quit", None)
_ORIGINAL_BUILTINS_EXIT = getattr(builtins, "exit", None)
_TABLE_WINDOW_METADATA = contextvars.ContextVar(
    "hyde_table_window_metadata",
    default=None,
)


def _normalize_window_state(window_state, owner):
    if window_state is None:
        return None
    if window_state != "minimized":
        raise TypeError(
            f"{owner} window_state must be 'minimized' when provided."
        )
    return "minimized"


def _build_window_metadata(owner, *, window_pos=None, window_state=None):
    metadata = {}
    if window_pos is not None:
        if not isinstance(window_pos, (list, tuple)) or len(window_pos) != 2:
            raise TypeError(f"{owner} window_pos must be a length-2 sequence.")
        metadata["window_pos"] = (int(window_pos[0]), int(window_pos[1]))
    normalized_window_state = _normalize_window_state(window_state, owner)
    if normalized_window_state is not None:
        metadata["window_state"] = normalized_window_state
    return metadata


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
        if "__hyde_clean_dict__" not in main_module.__dict__:
            main_module.__dict__["__hyde_clean_cwd__"] = os.getcwd()
            main_module.__dict__["__hyde_clean_sys_path__"] = list(sys.path)
            main_module.__dict__["__hyde_clean_dict__"] = main_module.__dict__.copy()
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

        project_tools.materialize_project_template(project_dir)
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


def heal_project(path):
    """Fill in missing template files for an existing Hyde project directory."""
    project_dir = project_tools.resolve_project_dir(path)
    errors = []
    healed_paths = []
    success = True
    try:
        if not project_dir.exists():
            raise RuntimeError(f"Cannot heal project: '{project_dir}' does not exist.")
        if not project_dir.is_dir():
            raise RuntimeError(f"Cannot heal project: '{project_dir}' is not a directory.")
        if project_dir.suffix != ".hy":
            raise RuntimeError(f"Cannot heal project: '{project_dir}' is not a .hy directory.")
        healed_paths = project_tools.materialize_project_template(
            project_dir,
            missing_only=True,
            create=True,
        )
        if healed_paths:
            message = (
                f"Recreated missing project files in {project_dir}: "
                + ", ".join(healed_paths)
                + " (from the default template)"
            )
            print(message)
            errors.append(message)
    except Exception as exc:
        success = False
        errors.append(str(exc))

    publish_project_state_result(
        "heal",
        str(project_dir),
        success=success,
        errors=errors,
        object_count=0,
        mode="heal",
    )
    if not success:
        raise RuntimeError(f"Hyde heal_project failed for {project_dir}: {errors}")
    return healed_paths


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
        HYDE_PROJECT_DIR = None
        signal_enter_no_project_state()
        if not project_dir.exists():
            raise RuntimeError(f"Hyde project does not exist: '{project_dir}'.")
        if not project_dir.is_dir():
            raise RuntimeError(f"Hyde project path is not a directory: '{project_dir}'.")
        procedures_init = project_dir / "procedures" / "__init__.py"
        if not procedures_init.exists():
            raise RuntimeError(
                f"Missing required project file: '{procedures_init}'. "
                f"Run hyde.heal_project({str(project_dir)!r}) to recreate missing template files."
            )
        project_tools.execute_procedures_bootstrap(
            str(project_dir),
            os.path.dirname(HYDE_DIR),
            reset_namespace=True,
        )
        manifest = project_tools.read_manifest(project_dir)
        restored_axis_entries = []
        for entry in sorted(
            manifest.get("objects", []),
            key=project_tools.object_restore_priority,
        ):
            name = entry["name"]
            serializer = entry["serializer"]
            object_path = project_dir / entry["path"]
            if not object_path.exists():
                errors.append(f"{name}: missing file {object_path}")
                continue
            try:
                sys.modules["__main__"].__dict__[name] = project_tools.deserialize_object(object_path, serializer)
                loaded += 1
                if project_tools.is_matplotlib_axes_type_name(entry.get("python_type")):
                    restored_axis_entries.append(name)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        missing_axis_entries = [
            entry
            for entry in manifest.get("objects", [])
            if project_tools.is_matplotlib_axes_type_name(entry.get("python_type"))
            and entry.get("name") not in sys.modules["__main__"].__dict__
        ]
        if missing_axis_entries:
            figures = [
                value
                for value in sys.modules["__main__"].__dict__.values()
                if project_tools.is_matplotlib_figure_type_name(type(value).__name__)
            ]
            recovered_axes = []
            for figure in figures:
                recovered_axes.extend(list(getattr(figure, "axes", ())))
            if len(recovered_axes) >= len(missing_axis_entries):
                for entry, axis in zip(missing_axis_entries, recovered_axes):
                    sys.modules["__main__"].__dict__[entry["name"]] = axis
                    restored_axis_entries.append(entry["name"])
                    loaded += 1
        if restored_axis_entries:
            errors = [
                error
                for error in errors
                if not any(error.startswith(f"{name}:") for name in restored_axis_entries)
            ]
        project_tools.clear_live_matplotlib_managers()
        HYDE_PROJECT_DIR = str(project_dir)
    except Exception as exc:
        success = False
        if HYDE_PROJECT_DIR is None:
            clean_cwd = __main__.__dict__.get("__hyde_clean_cwd__")
            clean_sys_path = __main__.__dict__.get("__hyde_clean_sys_path__")
            if clean_cwd is not None:
                try:
                    os.chdir(clean_cwd)
                except Exception:
                    pass
            if clean_sys_path is not None:
                sys.path[:] = list(clean_sys_path)
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


def create_table(
    *args,
    target=None,
    title=None,
    geometry=None,
    column_widths=None,
    window_state=None,
):
    """
    Open or append to a Hyde table window.

    This is the table creation/update primitive used by direct interactive
    calls as well as saved table macros and session restore source.
    """
    from .execution.helpers import resolve_names

    # Capture the caller's frame for name resolution
    frame = inspect.currentframe().f_back

    names = resolve_names(args, frame, validate_1d=True)
    metadata = dict(_TABLE_WINDOW_METADATA.get() or {})
    if window_state is None:
        window_state = metadata.get("window_state")
    window_state = _normalize_window_state(window_state, "hyde.create_table")

    if HYDE_GUI:
        signal_open_table(
            names,
            target,
            title=title,
            geometry=geometry,
            column_widths=column_widths,
            window_state=window_state,
        )


def table(_func=None, *, window_state=None, register=True):
    """
    Register a Hyde table recreation macro.

    This public Hyde API currently supports decorator registration only:

    ``@hyde.table``

    Decorated functions are published into `Windows -> Table Macros` unless
    ``register=False`` is provided. Internal restore paths may also pass
    ``window_state='minimized'`` to restore saved GUI state.
    """
    metadata = _build_window_metadata(
        "hyde.table",
        window_state=window_state,
    )

    def decorator(func):
        @functools.wraps(func)
        def wrapped(*wrapper_args, **wrapper_kwargs):
            token = _TABLE_WINDOW_METADATA.set(dict(metadata))
            try:
                return func(*wrapper_args, **wrapper_kwargs)
            finally:
                _TABLE_WINDOW_METADATA.reset(token)

        try:
            wrapped.__signature__ = inspect.signature(func)
        except (TypeError, ValueError):
            pass
        if register:
            register_table_macro(wrapped)
            publish_table_macro_registry()
        return wrapped

    if _func is None:
        return decorator

    if callable(_func):
        return decorator(_func)

    raise TypeError("hyde.table currently supports decorator registration only.")

def figure(_func=None, *, window_pos=None, window_state=None, register=True):
    """
    Register a Hyde figure recreation macro.

    This public Hyde API currently supports decorator registration only:

    ``@hyde.figure``

    Decorated functions are published into `Windows -> Graph Macros` after the
    procedures package reload path rebuilds the registry unless
    ``register=False`` is provided. Internal restore paths may also pass
    ``window_pos=...`` and ``window_state='minimized'`` to restore saved GUI
    state.
    """
    metadata = _build_window_metadata(
        "hyde.figure",
        window_pos=window_pos,
        window_state=window_state,
    )

    def decorator(func):
        figure_metadata = dict(metadata)

        @functools.wraps(func)
        def wrapped(*wrapper_args, **wrapper_kwargs):
            from .matplotlib_backend import (
                begin_figure_build_session,
                end_figure_build_session,
                finalize_figure_build_session,
            )

            session = begin_figure_build_session(
                func,
                wrapper_args,
                wrapper_kwargs,
                metadata=figure_metadata,
            )
            try:
                result = func(*wrapper_args, **wrapper_kwargs)
            finally:
                end_figure_build_session(session)
            return finalize_figure_build_session(session, result)

        try:
            wrapped.__signature__ = inspect.signature(func)
        except (TypeError, ValueError):
            pass

        if register:
            register_figure_macro(wrapped)
            publish_figure_macro_registry()
        return wrapped

    if _func is None:
        return decorator

    if callable(_func):
        return decorator(_func)

    raise TypeError("hyde.figure currently supports decorator registration only.")


def _resolve_matplotlib_figure(figure):
    if hasattr(figure, "canvas"):
        return figure

    from matplotlib._pylab_helpers import Gcf

    manager = Gcf.get_fig_manager(int(figure))
    if manager is None or getattr(manager, "canvas", None) is None:
        raise ValueError(f"Could not resolve matplotlib figure {figure!r}.")
    return manager.canvas.figure


def track_figure(figure, state):
    from .features.matplotlib_features import FigureCodec

    resolved_figure = _resolve_matplotlib_figure(figure)
    resolved_figure._hyde_live_state = FigureCodec.validate_state(state)
    resolved_figure.canvas.draw_idle()
    return resolved_figure


def refresh_figure(figure):
    from .features.matplotlib_features import apply_figure_state
    from .matplotlib_backend import apply_figure_action

    resolved_figure = _resolve_matplotlib_figure(figure)
    if getattr(resolved_figure, "_hyde_is_first_class", False):
        apply_figure_action(
            resolved_figure,
            {"type": "regenerate_from_ir", "use_bound_values": False},
        )
        return resolved_figure
    state = getattr(resolved_figure, "_hyde_live_state", None)
    if state is None:
        return None
    apply_figure_state(
        resolved_figure,
        state,
        sys.modules["__main__"].__dict__,
    )
    return resolved_figure
