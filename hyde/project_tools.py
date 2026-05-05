from __future__ import annotations

import builtins
import datetime
import importlib
import inspect
import os
import pickle
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import tomllib
import tomli_w

from .paths import DEFAULT_PROJECT_TEMPLATE

FORMAT_VERSION = 1
EXCLUDED_NAMES = {"In", "Out", "exit", "quit"}
TEMPLATE_IGNORE_PATTERNS = ("__pycache__", "*.pyc", ".gitkeep")
HYDE_MATPLOTLIB_BACKEND = "module://hyde.matplotlib_backend"


def resolve_project_dir(path=None):
    if path is None:
        return Path.cwd()
    return Path(path).expanduser().resolve()


def ensure_project_dirs(project_dir: Path):
    for relpath in ("data", "terminal", "procedures"):
        (project_dir / relpath).mkdir(parents=True, exist_ok=True)


def materialize_project_template(project_dir: Path, missing_only=False, create=True):
    project_dir = Path(project_dir)
    template_root = Path(DEFAULT_PROJECT_TEMPLATE)
    if not missing_only:
        shutil.copytree(
            template_root,
            project_dir,
            ignore=shutil.ignore_patterns(*TEMPLATE_IGNORE_PATTERNS),
        )
        return []

    created_paths = []
    for template_path in template_root.rglob("*"):
        relative_path = template_path.relative_to(template_root)
        if (
            "__pycache__" in relative_path.parts
            or template_path.suffix == ".pyc"
            or template_path.name == ".gitkeep"
        ):
            continue
        target_path = project_dir / relative_path
        if target_path.exists():
            continue
        created_paths.append(relative_path.as_posix())
        if not create:
            continue
        if template_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(template_path, target_path)
    return created_paths


def execute_procedures_bootstrap(project_dir, hyde_source_root, reset_namespace=False):
    import __main__

    if "__hyde_clean_dict__" not in __main__.__dict__:
        __main__.__dict__["__hyde_clean_cwd__"] = os.getcwd()
        __main__.__dict__["__hyde_clean_sys_path__"] = list(sys.path)
        __main__.__dict__["__hyde_clean_dict__"] = __main__.__dict__.copy()

    os.chdir(project_dir)
    project_root = os.getcwd()
    procedures_dir = os.path.join(project_root, "procedures")

    while procedures_dir in sys.path:
        sys.path.remove(procedures_dir)
    sys.path.insert(0, procedures_dir)

    while project_root in sys.path:
        sys.path.remove(project_root)
    sys.path.insert(1, project_root)

    while hyde_source_root in sys.path:
        sys.path.remove(hyde_source_root)
    sys.path.insert(2, hyde_source_root)

    if reset_namespace:
        clean_dict = __main__.__dict__.get("__hyde_clean_dict__")
        if clean_dict is None:
            clean_dict = __main__.__dict__.copy()
        __main__.__dict__.clear()
        __main__.__dict__.update(clean_dict)
        __main__.__dict__["__hyde_clean_dict__"] = clean_dict

    importlib.invalidate_caches()
    for name in list(sys.modules):
        if name == "procedures" or name.startswith("procedures."):
            del sys.modules[name]

    import hyde
    hyde.gui_mode(True)
    configure_gui_matplotlib_backend()
    import hyde.recreation_registry
    hyde.recreation_registry.clear_window_macros()

    import procedures
    previous_exports = set(__main__.__dict__.get("__hyde_procedures_exports__", ()))
    exports = {
        name: value
        for name, value in procedures.__dict__.items()
        if not name.startswith("_")
    }
    for name in previous_exports - set(exports):
        __main__.__dict__.pop(name, None)
    __main__.__dict__.update(exports)
    __main__.__hyde_procedures_exports__ = set(exports)
    hyde.recreation_registry.publish_table_macro_registry()
    hyde.recreation_registry.publish_figure_macro_registry()


def configure_gui_matplotlib_backend():
    import matplotlib

    if "matplotlib.pyplot" in sys.modules:
        return

    backend = str(matplotlib.get_backend() or "")
    if backend.lower() == HYDE_MATPLOTLIB_BACKEND.lower():
        return
    matplotlib.use(HYDE_MATPLOTLIB_BACKEND)


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
    main_module = sys.modules["__main__"]
    for name, value in sorted(main_module.__dict__.items()):
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
            value = pickle.load(handle)
        return _detach_matplotlib_runtime(value)
    raise ValueError(f"Unknown Hyde serializer {serializer!r}.")


def _detach_matplotlib_runtime(value):
    try:
        from matplotlib.axes import Axes
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib._pylab_helpers import Gcf
    except Exception:
        return value

    if isinstance(value, Figure):
        figure = value
    elif isinstance(value, Axes):
        figure = value.figure
    else:
        return value

    canvas = getattr(figure, "canvas", None)
    manager = None if canvas is None else getattr(canvas, "manager", None)
    if manager is not None:
        try:
            Gcf.destroy(manager.num)
        except Exception:
            pass
    FigureCanvasAgg(figure)
    return value


def clear_live_matplotlib_managers():
    try:
        from matplotlib._pylab_helpers import Gcf
    except Exception:
        return
    try:
        Gcf.figs.clear()
    except Exception:
        pass


def is_matplotlib_figure_type_name(python_type):
    return "Figure" in str(python_type or "")


def is_matplotlib_axes_type_name(python_type):
    return "Axes" in str(python_type or "")


def object_restore_priority(entry):
    python_type = str((entry or {}).get("python_type", ""))
    if is_matplotlib_figure_type_name(python_type):
        return (0, str((entry or {}).get("name", "")))
    if is_matplotlib_axes_type_name(python_type):
        return (2, str((entry or {}).get("name", "")))
    return (1, str((entry or {}).get("name", "")))


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
