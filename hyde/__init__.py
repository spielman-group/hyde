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
    publish_registry,
    register_fit_function,
    register_macro,
    reject_fit_function,
)
from .execution.ipc import (
    signal_activate_project,
    signal_append_table,
    signal_enter_no_project_state,
    publish_project_state_result,
    signal_open_table,
    signal_quit_requested,
    signal_task_complete,
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
_TABLE_WINDOW_STATES = frozenset({"visible", "minimized", "maximized"})
_FIGURE_WINDOW_STATES = frozenset({"visible", "minimized", "maximized"})


def _normalize_window_state(window_state, owner, *, allowed_states):
    if window_state is None:
        return None
    if window_state not in allowed_states:
        choices = ", ".join(repr(state) for state in sorted(allowed_states))
        raise TypeError(
            f"{owner} window_state must be one of {choices} when provided."
        )
    return str(window_state)


def _build_window_metadata(
    owner,
    *,
    window_pos=None,
    window_state=None,
    allowed_window_states,
):
    metadata = {}
    if window_pos is not None:
        if not isinstance(window_pos, (list, tuple)) or len(window_pos) != 2:
            raise TypeError(f"{owner} window_pos must be a length-2 sequence.")
        metadata["window_pos"] = (int(window_pos[0]), int(window_pos[1]))
    normalized_window_state = _normalize_window_state(
        window_state,
        owner,
        allowed_states=allowed_window_states,
    )
    if normalized_window_state is not None:
        metadata["window_state"] = normalized_window_state
    return metadata


def gui_mode(enable=True):
    """Enable or disable Hyde GUI mode.

    Parameters
    ----------
    enable : bool, optional
        When ``True``, expose the Hyde public API in the interactive namespace
        and enable Hyde's GUI-facing signal handlers and IPC path. When
        ``False``, restore the non-GUI signal and builtin state.
    """
    global HYDE_GUI
    HYDE_GUI = bool(enable)
    main_module = sys.modules["__main__"]
    if HYDE_GUI:
        from .execution.kernel_signals import install_signal_marker_handlers

        install_signal_marker_handlers()
        # Importing labscript_utils.ls_zprocess installs zprocess KillLock's
        # SIGTERM handler. Enable ProcessTree IPC only after Hyde's marker is
        # installed so KillLock wraps Hyde rather than Hyde replacing KillLock.
        from .execution.ipc import enable_process_tree_ipc

        enable_process_tree_ipc()
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
        from .execution.kernel_signals import restore_signal_marker_handlers

        restore_signal_marker_handlers()
        if _ORIGINAL_BUILTINS_QUIT is not None:
            builtins.quit = _ORIGINAL_BUILTINS_QUIT
        if _ORIGINAL_BUILTINS_EXIT is not None:
            builtins.exit = _ORIGINAL_BUILTINS_EXIT


def task_complete(name, success=True):
    """Report completion of a named background task to the Hyde GUI.

    Parameters
    ----------
    name : str
        Stable task name understood by the GUI.
    success : bool, optional
        Whether the task completed successfully.
    """
    signal_task_complete(name, success=success)


def new_project(path, load=True, overwrite=False):
    """Create a new Hyde project directory.

    Parameters
    ----------
    path : str or path-like
        Target project directory.
    load : bool, optional
        When ``True``, load the new project after creating it.
    overwrite : bool, optional
        When ``True``, replace an existing path at ``path``.

    Raises
    ------
    RuntimeError
        If the target path already exists and ``overwrite`` is ``False``.
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
    """Recreate missing template files in an existing Hyde project directory.

    Parameters
    ----------
    path : str or path-like
        Existing Hyde project directory to heal.

    Returns
    -------
    list of str
        Relative paths recreated from the default project template.

    Raises
    ------
    RuntimeError
        If ``path`` does not resolve to an existing ``.hy`` project directory
        or if the healing operation fails.
    """
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
    """Save the current kernel namespace into a Hyde project package.

    Parameters
    ----------
    path : str or path-like, optional
        Target ``.hy`` project directory. By default, save into the active Hyde
        project when ``mode="save"``.
    mode : {"save", "copy", "save_as"}, optional
        Save mode to use.
    overwrite : bool, optional
        Whether to allow replacing an existing target for ``save_as`` or
        ``copy``.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If ``path`` and ``mode`` are inconsistent.
    RuntimeError
        If no Hyde project is active or the save operation fails.
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
    """Load saved kernel namespace objects from a Hyde project package.

    Parameters
    ----------
    path : str or path-like, optional
        Source ``.hy`` project directory. By default, load the active Hyde
        project.

    Returns
    -------
    int
        Number of objects restored into the kernel namespace.

    Raises
    ------
    RuntimeError
        If no Hyde project is active, required project files are missing, or
        the load operation fails.
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
    """Request an orderly Hyde shutdown.

    Returns
    -------
    None
        Returned when Hyde is running in GUI mode and the shutdown request has
        been sent to the parent GUI process.

    Raises
    ------
    SystemExit
        Raised outside GUI mode to exit the current interpreter immediately.
    """
    if HYDE_GUI:
        signal_enter_no_project_state()
        signal_quit_requested()
        return None
    raise SystemExit(0)


def create_table(
    *args,
    name=None,
    geometry=None,
    column_widths=None,
    window_state=None,
):
    """Open a Hyde table window for one or more kernel objects.

    Parameters
    ----------
    *args : object
        Supported one-dimensional kernel objects to show in the table.
    name : str, optional
        Requested stable table name.
    geometry : tuple, optional
        Saved window geometry to apply when opening the table.
    column_widths : sequence of int, optional
        Saved table column widths.
    window_state : {"visible", "minimized", "maximized"}, optional
        Requested window presentation state.

    Notes
    -----
    This is the table creation primitive used by direct interactive calls,
    table macros, and session restore source.
    """
    from .execution.helpers import resolve_names

    # Capture the caller's frame for name resolution
    frame = inspect.currentframe().f_back

    names = resolve_names(args, frame, validate_1d=True)
    metadata = dict(_TABLE_WINDOW_METADATA.get() or {})
    if window_state is None:
        window_state = metadata.get("window_state")
    window_state = _normalize_window_state(
        window_state,
        "hyde.create_table",
        allowed_states=_TABLE_WINDOW_STATES,
    )

    if HYDE_GUI:
        signal_open_table(
            names,
            name=name,
            geometry=geometry,
            column_widths=column_widths,
            window_state=window_state,
        )


def append_table(*args, name):
    """Append objects to an existing Hyde table window.

    Parameters
    ----------
    *args : object
        Supported one-dimensional kernel objects to append.
    name : str
        Stable name of the target table window.

    Raises
    ------
    TypeError
        If ``name`` is empty.
    """
    from .execution.helpers import resolve_names

    frame = inspect.currentframe().f_back
    names = resolve_names(args, frame, validate_1d=True)
    if not name:
        raise TypeError("hyde.append_table requires a non-empty name.")
    if HYDE_GUI:
        signal_append_table(
            names,
            name=name,
        )


def table(_func=None, *, window_state=None, register=True):
    """Register a Hyde table recreation macro.

    Parameters
    ----------
    _func : callable, optional
        Function being decorated when ``@hyde.table`` is used without
        arguments.
    window_state : {"visible", "minimized", "maximized"}, optional
        Saved window presentation state to apply when the macro runs.
    register : bool, optional
        When ``True``, publish the decorated function in
        ``Windows -> Table Macros``.

    Returns
    -------
    callable
        Decorator or wrapped macro function, depending on how
        ``hyde.table`` is invoked.

    Raises
    ------
    TypeError
        If called in a non-decorator form.
    """
    metadata = _build_window_metadata(
        "hyde.table",
        window_state=window_state,
        allowed_window_states=_TABLE_WINDOW_STATES,
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
            register_macro("table", wrapped)
            publish_registry("table")
        return wrapped

    if _func is None:
        return decorator

    if callable(_func):
        return decorator(_func)

    raise TypeError("hyde.table currently supports decorator registration only.")

def figure(_func=None, *, window_pos=None, window_state=None, register=True):
    """Register a Hyde figure recreation macro.

    Parameters
    ----------
    _func : callable, optional
        Function being decorated when ``@hyde.figure`` is used without
        arguments.
    window_pos : tuple of int, optional
        Saved window position to apply when the macro runs.
    window_state : {"visible", "minimized", "maximized"}, optional
        Saved window presentation state to apply when the macro runs.
    register : bool, optional
        When ``True``, publish the decorated function in
        ``Windows -> Graph Macros``.

    Returns
    -------
    callable
        Decorator or wrapped macro function, depending on how
        ``hyde.figure`` is invoked.

    Raises
    ------
    TypeError
        If called in a non-decorator form.
    """
    metadata = _build_window_metadata(
        "hyde.figure",
        window_pos=window_pos,
        window_state=window_state,
        allowed_window_states=_FIGURE_WINDOW_STATES,
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
            register_macro("figure", wrapped)
            publish_registry("figure")
        return wrapped

    if _func is None:
        return decorator

    if callable(_func):
        return decorator(_func)

    raise TypeError("hyde.figure currently supports decorator registration only.")


def fit_function(_func=None, *, independent_vars):
    """Register a curve-fit function for Hyde Curve Fit discovery.

    Parameters
    ----------
    _func : callable, optional
        Function being decorated when ``@hyde.fit_function`` is used without
        arguments.
    independent_vars : tuple of str
        Independent-variable parameter names that must appear first in the
        decorated function signature.

    Returns
    -------
    callable
        Decorator or decorated function, depending on how
        ``hyde.fit_function`` is invoked.

    Raises
    ------
    TypeError
        If called in a non-decorator form.

    Notes
    -----
    Supported first-pass signatures must begin with ``independent_vars`` in
    order, followed by explicitly named coefficient parameters. Unsupported
    forms are excluded from the Curve Fit chooser instead of aborting the
    procedures reload path.
    """

    def decorator(func):
        try:
            register_fit_function(func, independent_vars=independent_vars)
        except TypeError as exc:
            reject_fit_function(func, reason=exc)
        publish_registry("fit_function")
        return func

    if _func is None:
        return decorator

    if callable(_func):
        return decorator(_func)

    raise TypeError("hyde.fit_function currently supports decorator registration only.")


@fit_function(independent_vars=("x",))
def line(x, a, b):
    """Return a straight line.

    Parameters
    ----------
    x : array_like
        Independent-variable values.
    a : array_like
        Slope.
    b : array_like
        Intercept.

    Returns
    -------
    array_like
        Straight-line values ``a * x + b``.
    """
    return a * x + b


@fit_function(independent_vars=("x",))
def gaussian(x, a, x0, width, y0):
    """Return a Gaussian curve.

    Parameters
    ----------
    x : array_like
        Independent-variable values.
    a : array_like
        Peak amplitude.
    x0 : array_like
        Peak center.
    width : array_like
        Gaussian width parameter.
    y0 : array_like
        Constant offset.

    Returns
    -------
    array_like
        Gaussian-curve values.
    """
    return a * np.exp(-((x - x0) ** 2) / (width**2)) + y0


@fit_function(independent_vars=("x",))
def lorentzian(x, a, x0, width, y0):
    """Return a Lorentzian curve.

    Parameters
    ----------
    x : array_like
        Independent-variable values.
    a : array_like
        Peak amplitude.
    x0 : array_like
        Peak center.
    width : array_like
        Lorentzian width parameter.
    y0 : array_like
        Constant offset.

    Returns
    -------
    array_like
        Lorentzian-curve values.
    """
    return a * (1.0 / (1.0 + ((x - x0) ** 2) / (width**2))) + y0


@fit_function(independent_vars=("x",))
def exp(x, a, width, y0):
    """Return an exponential curve.

    Parameters
    ----------
    x : array_like
        Independent-variable values.
    a : array_like
        Amplitude.
    width : array_like
        Decay-width parameter.
    y0 : array_like
        Constant offset.

    Returns
    -------
    array_like
        Exponential-curve values.
    """
    return a * np.exp(-x / width) + y0


@fit_function(independent_vars=("x",))
def sin(x, a, k, phi, y0):
    """Return a sinusoid.

    Parameters
    ----------
    x : array_like
        Independent-variable values.
    a : array_like
        Amplitude.
    k : array_like
        Angular scaling factor applied to ``x``.
    phi : array_like
        Phase offset.
    y0 : array_like
        Constant offset.

    Returns
    -------
    array_like
        Sinusoidal values.
    """
    return a * np.sin(k * x + phi) + y0


@fit_function(independent_vars=("x",))
def power(x, a, alpha, y0):
    """Return a power-law curve.

    Parameters
    ----------
    x : array_like
        Independent-variable values.
    a : array_like
        Scale factor.
    alpha : array_like
        Power-law exponent.
    y0 : array_like
        Constant offset.

    Returns
    -------
    array_like
        Power-law values.
    """
    return a * (x**alpha) + y0


@fit_function(independent_vars=("x",))
def log(x, a, y0):
    """Return a logarithmic curve.

    Parameters
    ----------
    x : array_like
        Independent-variable values.
    a : array_like
        Scale factor.
    y0 : array_like
        Constant offset.

    Returns
    -------
    array_like
        Logarithmic-curve values.
    """
    return a * np.log(x) + y0


def register_builtin_fit_functions():
    """Re-register Hyde's built-in Curve Fit functions.

    Returns
    -------
    tuple of str
        Names of the built-in fit functions re-registered into the catalog.
    """
    builtin_fit_functions = (line, gaussian, lorentzian, exp, sin, power, log)
    decorator = fit_function(independent_vars=("x",))
    for func in builtin_fit_functions:
        decorator(func)
    return tuple(func.__name__ for func in builtin_fit_functions)


register_builtin_fit_functions()


def _resolve_matplotlib_figure(figure):
    if hasattr(figure, "canvas"):
        return figure

    from matplotlib._pylab_helpers import Gcf

    manager = Gcf.get_fig_manager(int(figure))
    if manager is None or getattr(manager, "canvas", None) is None:
        raise ValueError(f"Could not resolve matplotlib figure {figure!r}.")
    return manager.canvas.figure


def get_figure(name):
    """Return a live first-class Hyde figure by name.

    Parameters
    ----------
    name : str
        Canonical Hyde figure name.

    Returns
    -------
    matplotlib.figure.Figure
        Live first-class figure associated with ``name``.
    """
    from .matplotlib_backend import get_first_class_figure

    return get_first_class_figure(name)


def refresh_figure(figure, *, use_bound_values=False):
    """Regenerate a first-class Hyde figure from its kernel-owned figure IR.

    Parameters
    ----------
    figure : matplotlib.figure.Figure or int
        Live matplotlib figure or figure-manager number resolvable to a live
        figure.
    use_bound_values : bool, optional
        When ``True``, prefer operand values already bound on the live figure
        IR. When ``False``, re-resolve operands from the current kernel
        namespace where possible.

    Returns
    -------
    matplotlib.figure.Figure or None
        Refreshed live figure when ``figure`` is first-class, otherwise
        ``None``.
    """
    from .matplotlib_backend import regenerate_figure_from_ir

    resolved_figure = _resolve_matplotlib_figure(figure)
    if getattr(resolved_figure, "_hyde_is_first_class", False):
        regenerate_figure_from_ir(
            resolved_figure,
            use_bound_values=bool(use_bound_values),
        )
        return resolved_figure
    return None


def copy_figure(figure, *, format="pdf", dpi="figure", transparent=False):
    """Copy a live figure to the GUI clipboard.

    Rendering happens here, in the kernel, because the kernel owns the figure.
    The rendered bytes are handed to the GUI process, which owns the clipboard.
    This function must never touch the clipboard itself; `hyde` is imported by
    the kernel and may not depend on Qt.

    Parameters
    ----------
    figure : matplotlib.figure.Figure or int
        Live matplotlib figure or figure-manager number resolvable to a live
        figure.
    format : str, optional
        A matplotlib output format. Defaults to ``"pdf"``.
    dpi : int or str, optional
        Resolution for raster output. Defaults to ``"figure"``, matplotlib's own
        default, meaning the figure's own DPI is used.
    transparent : bool, optional
        Whether to render with a transparent background.

    Returns
    -------
    bool
        ``True`` when rendered bytes were handed to the GUI.
    """
    import base64
    import io

    from .execution.ipc import signal_copy_to_clipboard

    resolved_figure = _resolve_matplotlib_figure(figure)
    normalized_format = str(format or "pdf").strip().lower()
    # PGF is LaTeX source, so it travels as text rather than as an image.
    is_text = normalized_format == "pgf"

    buffer = io.BytesIO()
    resolved_figure.savefig(
        buffer,
        format=normalized_format,
        dpi=dpi,
        transparent=bool(transparent),
    )
    signal_copy_to_clipboard(
        base64.b64encode(buffer.getvalue()).decode("ascii"),
        output_format=normalized_format,
        is_text=is_text,
    )
    return True


def remove_traces(figure, *trace_ids):
    """Remove traces from a live first-class Hyde figure.

    Parameters
    ----------
    figure : matplotlib.figure.Figure or int
        Live matplotlib figure or figure-manager number resolvable to a live
        figure.
    *trace_ids : str
        Stable Hyde trace identifiers to remove. Missing trace identifiers are
        ignored.

    Returns
    -------
    matplotlib.figure.Figure
        Live figure after the requested trace removals have been applied.

    Raises
    ------
    ValueError
        If ``figure`` does not resolve to a first-class Hyde figure.
    """
    from .matplotlib_backend import remove_traces_from_figure

    resolved_figure = _resolve_matplotlib_figure(figure)
    return remove_traces_from_figure(resolved_figure, trace_ids)
