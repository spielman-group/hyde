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
PLUGINS_DIR = HYDE_DIR / "user_interface" / "plugins"
PLUGIN_PACKAGE = "hyde.user_interface.plugins"
QT_ROOT_PACKAGES = frozenset({"qtutils", "PyQt5", "PyQt6", "PySide2", "PySide6"})

# `hyde.__main__` is the GUI process entry point: it builds the QApplication and
# HydeApp, so it is the one module under `hyde/` outside `hyde.user_interface`
# that may import Qt.
GUI_ENTRY_POINT = "hyde.__main__"


def dotted_module_name(path):
    parts = list(path.relative_to(HYDE_DIR.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def hyde_module_files():
    modules = {}
    for path in HYDE_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        modules[dotted_module_name(path)] = path
    return modules


def python_files(directory):
    return sorted(
        path
        for path in directory.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def is_gui_plugin_module(target):
    return target == PLUGIN_PACKAGE or target.startswith(f"{PLUGIN_PACKAGE}.")


def top_level_definitions(path):
    """Names `path` binds at module scope by defining them.

    Covers `async def` and annotated or unpacked assignment as well as the
    plain forms, because a guard that walks only some node types is exactly the
    hole it thinks it is closing: `NAME: dict = {...}` defines `NAME` just as
    `NAME = {...}` does.
    """
    names = set()
    for node in ast.parse(path.read_text(), filename=str(path)).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            pending = list(node.targets)
            while pending:
                target = pending.pop()
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    pending.extend(target.elts)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def imported_targets(path):
    """Every `(module, symbol)` pair an import statement in `path` names.

    Walks the whole tree rather than `tree.body`, so an import deferred into a
    function body or an `if TYPE_CHECKING:` block counts too. `symbol` is None
    for `import a.b.c`, which names no symbol. Relative imports are resolved,
    since `from ..user_interface.plugins.x import y` reaches the same module as
    the absolute spelling.
    """
    parts = dotted_module_name(path).split(".")
    package = parts if path.name == "__init__.py" else parts[:-1]
    targets = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            targets.extend((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            targets.extend((module, alias.name) for alias in node.names)
    return targets


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
            for name in top_level_definitions(path):
                definitions.setdefault(name, []).append(path.name)

        duplicated = {
            name: sorted(files)
            for name, files in definitions.items()
            if len(set(files)) > 1
        }
        self.assertEqual({}, duplicated)

    def test_no_public_name_lives_in_both_a_feature_module_and_a_gui_plugin(self):
        """One public name, one home, across the feature/plugin boundary.

        Deliberately an architecture-contract assertion. The house rule is that
        tests assert what the code does and not how it is - *except* to the
        extent the codebase must follow its own modular structure, and this is
        that exception. Do not delete it as a structural assertion; asserting
        the structure is the whole job.

        This is the forked-copy shape, which no import rule can see. A shim
        re-export at least leaves an import statement to find. Re-typing a
        plugin's policy as a literal back in `hyde/features/` imports nothing,
        so `test_no_feature_module_imports_gui_plugin_code` is blind to it and
        only the name collision gives it away. Whichever side owns a contract,
        the other side imports it rather than keeping a second copy.

        Public names only. A private top-level name cannot be a second
        authority over a shared contract, because nothing outside its own
        module can reference it, and two unrelated private helpers that happen
        to share a name are not an architecture violation. The honest cost is
        that a copy renamed on the way in escapes this guard - a name-based
        rule can only see names.
        """
        homes = {}
        for directory in (FEATURES_DIR, PLUGINS_DIR):
            for path in python_files(directory):
                for name in top_level_definitions(path):
                    if name.startswith("_"):
                        continue
                    homes.setdefault(name, {}).setdefault(directory, []).append(
                        str(path.relative_to(HYDE_DIR.parent))
                    )

        shared = sorted(name for name, sides in homes.items() if len(sides) > 1)
        self.assertEqual(
            [],
            shared,
            "these public names are defined on both sides of the "
            "feature/plugin boundary, so the same contract has two homes:\n  "
            + "\n  ".join(
                f"{name}: "
                + " and ".join(
                    sorted(
                        file
                        for files in homes[name].values()
                        for file in files
                    )
                )
                for name in shared
            ),
        )

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

    def test_no_feature_module_imports_gui_plugin_code(self):
        """Dependencies run plugin -> feature, never the reverse.

        Deliberately an architecture-contract assertion, for the reason given
        in `test_no_public_name_lives_in_both_a_feature_module_and_a_gui_plugin`.
        Do not delete it as a structural assertion.

        IR-CONTROL puts feature lowerers under `hyde/features/` and widget
        workflow IR plugin-local under `hyde/user_interface/plugins/`, with the
        plugin composing the feature family. A feature module importing a
        plugin inverts that. It also re-opens an import path a move was
        supposed to retire, which is a forwarding shim under another name, and
        it hands the kernel side a GUI import path.

        `hyde/user_interface/shared/core` is out of scope and must stay out:
        the `HydeIR` / `HydeIRDiff` base contract lives there and the package
        IR modules subclass it, so the rule is scoped to `plugins/` rather than
        to `hyde/user_interface/` as a whole.

        `test_kernel_side_modules_never_reach_gui_plugins_or_qt` asserts this
        same direction over whole import closures and does catch a re-export,
        but it reports a closure edge from whichever root reaches it and never
        names the symbol. This one names the file, the symbol and the plugin
        module, so a failure says which line to delete.

        Blind spot: a dynamic `importlib.import_module("hyde.user_interface...")`
        is a string, not an import node, and no AST guard here sees it.
        """
        violations = []
        for path in sorted(FEATURES_DIR.glob("*.py")):
            for module, symbol in imported_targets(path):
                if symbol is None:
                    if is_gui_plugin_module(module):
                        violations.append(
                            f"{path.name} imports the GUI plugin module {module}"
                        )
                elif is_gui_plugin_module(module) or is_gui_plugin_module(
                    f"{module}.{symbol}"
                ):
                    violations.append(
                        f"{path.name} imports {symbol!r} from GUI plugin {module}"
                    )

        self.assertEqual(
            [],
            violations,
            "feature modules must not import GUI plugin code:\n  "
            + "\n  ".join(violations),
        )

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
            "value = 1\n",
        )

    def test_session_restore_source_runs_a_session_file_as_written(self):
        """session.py is user-editable, so lowering it must not rewrite it.

        It used to be indented to fit inside a `try:` block, which broke a
        `__future__` import, rewrote the contents of multi-line strings, and
        failed to compile at all when the file held only comments. Nothing is
        added to it now either, so a traceback names the line the user would
        find in the file.
        """
        from hyde.features.hyde_features import hyde_app_python_source

        for description, session_source in (
            ("comments only", "# written when the project is saved\n"),
            ("blank", "\n\n"),
            ("real source", "value = 1\n"),
            ("trailing blank lines", "value = 1\n\n\n"),
            ("__future__ import", "from __future__ import annotations\nvalue = 1\n"),
        ):
            with self.subTest(session_source=description):
                compile(
                    hyde_app_python_source(
                        command="session_restore",
                        session_source=session_source,
                    ),
                    "<session_restore>",
                    "exec",
                )

    def test_session_restore_source_reports_the_users_own_line_numbers(self):
        from hyde.features.hyde_features import hyde_app_python_source

        source = hyde_app_python_source(
            command="session_restore",
            session_source="value = 1\nraise ValueError('here')\n",
        )
        try:
            exec(compile(source, "<session_restore>", "exec"), {})
        except ValueError:
            import sys

            line = sys.exc_info()[2].tb_next.tb_lineno
        self.assertEqual(2, line, "reported line does not match session.py")

    def test_session_restore_source_preserves_multiline_string_contents(self):
        from hyde.features.hyde_features import hyde_app_python_source

        namespace = {}
        exec(
            compile(
                hyde_app_python_source(
                    command="session_restore",
                    session_source='note = """\nline one\n"""\n',
                ),
                "<session_restore>",
                "exec",
            ),
            namespace,
        )

        self.assertEqual("\nline one\n", namespace["note"])

    def test_session_source_statement_check_classifies_real_session_files(self):
        """Whether to run session.py is a dispatch decision the GUI makes.

        Source that will not parse counts as something to run: the kernel's
        error is more use than silently restoring nothing.
        """
        from hyde.features.hyde_features import session_source_has_statements

        for description, session_source, expected in (
            ("comments only", "# written when the project is saved\n", False),
            ("blank", "\n\n", False),
            ("empty", "", False),
            ("real source", "value = 1\n", True),
            ("will not parse", "def f(:\n", True),
        ):
            with self.subTest(session_source=description):
                self.assertIs(expected, session_source_has_statements(session_source))

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
