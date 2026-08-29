import ast
import importlib
import importlib.util
import inspect
from pathlib import Path
import unittest

from hyde.features.base import (
    FeatureCodec,
    is_eligible_for_numeric_series,
    sorted_eligible_names,
)


HYDE_DIR = Path(__file__).resolve().parents[1] / "hyde"
FEATURES_DIR = HYDE_DIR / "features"
PLUGIN_PACKAGE = "hyde.user_interface.plugins"
QT_ROOT_PACKAGES = frozenset({"qtutils", "PyQt5", "PyQt6", "PySide2", "PySide6"})

# `hyde.__main__` is the GUI process entry point: it builds the QApplication and
# HydeApp, so it is the one module under `hyde/` outside `hyde.user_interface`
# that may import Qt.
GUI_ENTRY_POINT = "hyde.__main__"


def hyde_module_files():
    modules = {}
    for path in HYDE_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(HYDE_DIR.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def module_imports(module_name, modules):
    """Hyde modules and external root packages that importing `module_name` pulls in.

    Importing `a.b.c` also executes `a` and `a.b`, so ancestor packages are
    edges too. Ignoring that is what let a kernel-side module reach Qt through
    the `__init__.py` of a Qt-free-looking plugin submodule.
    """
    path = modules[module_name]
    is_package = path.name == "__init__.py"
    hyde_modules = set()
    external_roots = set()

    def add(target):
        if not target:
            return
        if not target.startswith("hyde"):
            external_roots.add(target.split(".")[0])
            return
        parts = target.split(".")
        for index in range(1, len(parts) + 1):
            ancestor = ".".join(parts[:index])
            if ancestor in modules:
                hyde_modules.add(ancestor)

    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module_name.split(".")
                if not is_package:
                    base = base[:-1]
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            add(target)
            for alias in node.names:
                add(f"{target}.{alias.name}")
    return hyde_modules, external_roots


def import_closure(module_name, modules):
    seen = set()
    pending = [module_name]
    while pending:
        current = pending.pop()
        if current in seen or current not in modules:
            continue
        seen.add(current)
        pending.extend(module_imports(current, modules)[0])
    return seen


class TestHydeFeatureModuleLayout(unittest.TestCase):
    def test_expected_feature_ir_modules_exist(self):
        required_files = {
            FEATURES_DIR / "hyde_ir.py",
            FEATURES_DIR / "matplotlib_ir.py",
            FEATURES_DIR / "lmfit_ir.py",
            FEATURES_DIR / "matplotlib_color.py",
            FEATURES_DIR / "matplotlib_figure_state.py",
            FEATURES_DIR / "matplotlib_figure_schema.py",
            FEATURES_DIR / "matplotlib_figure_records.py",
        }
        feature_files = set(FEATURES_DIR.glob("*.py"))
        self.assertTrue(
            required_files <= feature_files,
            f"Missing expected feature files: {sorted(required_files - feature_files)}",
        )

    def test_no_feature_module_redefines_another_feature_module_name(self):
        # A "move A to B" refactor that only greps B cannot tell a move from a
        # copy. Two modules defining the same top-level name means two
        # authorities, and the kernel and GUI can then normalize the same state
        # through different copies of it.
        definitions = {}
        for path in sorted(FEATURES_DIR.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names = [node.name]
                elif isinstance(node, ast.Assign):
                    names = [
                        target.id
                        for target in node.targets
                        if isinstance(target, ast.Name)
                    ]
                else:
                    continue
                for name in names:
                    definitions.setdefault(name, []).append(path.name)

        duplicated = {
            name: sorted(files)
            for name, files in definitions.items()
            if len(set(files)) > 1
        }
        self.assertEqual({}, duplicated)

    def test_hyde_features_is_an_importable_package(self):
        # Without __init__.py, setuptools drops hyde.features from every
        # non-editable install even though the IR authority lives there.
        self.assertTrue((FEATURES_DIR / "__init__.py").is_file())

    def test_kernel_side_modules_never_reach_gui_plugins_or_qt(self):
        modules = hyde_module_files()
        kernel_side = sorted(
            name
            for name in modules
            if not name.startswith("hyde.user_interface")
            and name != GUI_ENTRY_POINT
        )
        self.assertIn("hyde.matplotlib_backend", kernel_side)
        self.assertIn("hyde.features.matplotlib_ir", kernel_side)

        violations = []
        for name in kernel_side:
            closure = import_closure(name, modules)
            for reached in sorted(closure):
                if reached == PLUGIN_PACKAGE or reached.startswith(
                    f"{PLUGIN_PACKAGE}."
                ):
                    violations.append(f"{name} -> GUI plugin {reached}")
                qt = QT_ROOT_PACKAGES & module_imports(reached, modules)[1]
                for package in sorted(qt):
                    violations.append(f"{name} -> {reached} -> Qt ({package})")

        self.assertEqual([], sorted(set(violations)))

    def test_hyde_codec_rejects_non_hyde_mutation_feature_state(self):
        from hyde.features.hyde_features import HydeCodec

        with self.assertRaises(ValueError):
            HydeCodec.default_state(feature="mutation")

    def test_feature_modules_expose_one_package_local_codec_surface_each(self):
        for module_name, expected_codec in (
            ("hyde.features.hyde_features", "HydeCodec"),
            ("hyde.features.matplotlib_features", "MatplotlibCodec"),
        ):
            with self.subTest(module_name=module_name):
                spec = importlib.util.find_spec(module_name)
                self.assertIsNotNone(spec)

                module = importlib.import_module(module_name)
                codec_classes = [
                    value
                    for _, value in inspect.getmembers(module, inspect.isclass)
                    if issubclass(value, FeatureCodec) and value is not FeatureCodec
                ]

                self.assertEqual(
                    [codec.__name__ for codec in codec_classes],
                    [expected_codec],
                )

    def test_hyde_feature_module_owns_hyde_figure_lowerers(self):
        from hyde.features.hyde_features import (
            figure_decorator_source,
            figure_lookup_prelude_lines,
            figure_refresh_source,
            hyde_app_python_source,
            publish_registry_source,
            remove_traces_source,
        )

        self.assertEqual(figure_decorator_source(), "@hyde.figure")
        self.assertEqual(
            figure_decorator_source(register=False),
            "@hyde.figure(register=False)",
        )
        self.assertEqual(
            figure_lookup_prelude_lines("Figure9", include_axes=True),
            [
                "fig = hyde.get_figure('Figure9')",
                "ax = fig.axes[0]",
            ],
        )
        self.assertEqual(
            figure_refresh_source("DelayGraph", use_bound_values=True),
            "fig = hyde.get_figure('DelayGraph')\n"
            "hyde.refresh_figure(fig, use_bound_values=True)",
        )
        self.assertEqual(
            publish_registry_source("figure"),
            "hyde.recreation_registry.publish_registry('figure')",
        )
        self.assertEqual(
            remove_traces_source("Figure9", ("trace0", "trace1")),
            "fig = hyde.get_figure('Figure9')\n"
            "hyde.remove_traces(fig, 'trace0', 'trace1')",
        )
        self.assertEqual(
            hyde_app_python_source(
                command="new_project",
                target_project_dir="/tmp/demo.hy",
                load=False,
                overwrite=True,
            ),
            "hyde.new_project('/tmp/demo.hy', load=False, overwrite=True)",
        )
        self.assertEqual(
            hyde_app_python_source(
                command="save_project",
                target_project_dir="/tmp/copy.hy",
                save_mode="copy",
                overwrite=True,
            ),
            "hyde.save_project('/tmp/copy.hy', mode='copy', overwrite=True)",
        )
        self.assertEqual(
            hyde_app_python_source(
                command="reload_procedures",
                project_dir="/tmp/demo.hy",
                hyde_source_root="/tmp/hyde-src",
                reset_namespace=True,
            ),
            "import sys\n"
            "if '/tmp/hyde-src' not in sys.path:\n"
            "    sys.path.insert(0, '/tmp/hyde-src')\n"
            "from hyde.project_tools import execute_procedures_bootstrap\n"
            "execute_procedures_bootstrap('/tmp/demo.hy', '/tmp/hyde-src', reset_namespace=True)\n",
        )
        self.assertEqual(
            hyde_app_python_source(
                command="session_restore",
                session_source="value = 1",
            ),
            "import hyde\n"
            "try:\n"
            "    value = 1\n"
            "except Exception:\n"
            '    hyde.task_complete("session_restore", False)\n'
            "    raise\n"
            "else:\n"
            '    hyde.task_complete("session_restore", True)\n',
        )

    def test_numeric_series_eligibility_contract(self):
        eligible = {
            "delay": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "f", "ndim": 1},
            "count": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "i", "ndim": 1},
            "flags": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "b", "ndim": 1},
            "reading": {"python_type": "series", "numpy_type": "", "numpy_kind": "f", "ndim": 1},
        }
        ineligible = {
            "label": {"python_type": "str", "numpy_type": "", "numpy_kind": "U", "ndim": 0},
            "image": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "f", "ndim": 2},
            "phase": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "c", "ndim": 1},
            "scale": {"python_type": "float", "numpy_type": "", "numpy_kind": "f", "ndim": 0},
        }
        for name, metadata in eligible.items():
            with self.subTest(name=name):
                self.assertTrue(is_eligible_for_numeric_series(metadata))
        for name, metadata in ineligible.items():
            with self.subTest(name=name):
                self.assertFalse(is_eligible_for_numeric_series(metadata))

        self.assertEqual(
            sorted_eligible_names({**eligible, **ineligible}),
            ["count", "delay", "flags", "reading"],
        )

    def test_every_caller_classifies_numeric_series_identically(self):
        # Guards against a caller growing a second eligibility rule. Compares
        # classification results, not helper identity, so re-exporting a wrapper
        # is fine and a diverging reimplementation is not.
        from hyde.features import lmfit_features
        from hyde.user_interface.plugins.figure_interactive import (
            dialogs as figure_dialogs,
        )
        from hyde.user_interface.plugins.table_interactive import (
            dialogs as table_dialogs,
        )

        python_variables_tool = importlib.import_module(
            "hyde.user_interface.plugins.python_variables_tool"
        )

        metadata = {
            "delay": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "f", "ndim": 1},
            "label": {"python_type": "str", "numpy_type": "", "numpy_kind": "U", "ndim": 0},
            "count": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "i", "ndim": 1},
            "image": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "f", "ndim": 2},
        }
        expected_names = sorted_eligible_names(metadata)

        for module in (lmfit_features, figure_dialogs):
            with self.subTest(module=module.__name__):
                self.assertEqual(module.sorted_eligible_names(metadata), expected_names)

        for module in (table_dialogs, python_variables_tool):
            with self.subTest(module=module.__name__):
                for name, entry in metadata.items():
                    self.assertEqual(
                        module.is_eligible_for_numeric_series(entry),
                        is_eligible_for_numeric_series(entry),
                        f"{module.__name__} disagrees about {name!r}",
                    )
