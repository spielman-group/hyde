import os
import tempfile
import unittest

import hyde
import numpy as np
try:
    import matplotlib
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc
try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.recreation_registry import (
    clear,
    names,
    publish_registry,
    register_fit_function,
    reject_fit_function,
    serialize_registry,
)
from hyde.user_interface.plugins.table.window_macro_store import (
    BEGIN_MARKER,
    END_MARKER,
    inspect_macro_conflict,
    update_macro_source,
    validate_macro_name,
    write_macro_source,
)
from unittest.mock import patch


def build_table_macro_source(macro_name, names, name=None, geometry=None, column_widths=None):
    from hyde.user_interface.plugins.table.window import TableState

    state = TableState()
    state.set_items(names)
    state.set_name(name)
    state.set_geometry(geometry)
    state.set_column_widths(column_widths or {})
    return state.macro_source(macro_name)


class TestTableDecorator(unittest.TestCase):
    def setUp(self):
        clear()

    def test_table_decorator_registers_parameterized_macro(self):
        @hyde.table
        def Table0(a, b):
            return a, b

        self.assertEqual(names("table"), ("Table0",))
        self.assertEqual(
            tuple(serialize_registry("table")["entries"]),
            ({"name": "Table0", "args": ["a", "b"]},),
        )

    def test_table_decorator_can_skip_registration(self):
        @hyde.table(register=False)
        def Table0(a, b):
            return a, b

        self.assertEqual(names("table"), ())

    def test_table_decorator_accepts_window_state_metadata(self):
        with patch("hyde.signal_open_table") as signal_open_table:
            hyde.gui_mode(True)
            try:
                @hyde.table(window_state="minimized", register=False)
                def Table0(a):
                    hyde.create_table(a)

                Table0(np.array([1, 2, 3]))
            finally:
                hyde.gui_mode(False)

        signal_open_table.assert_called_once()
        self.assertEqual(signal_open_table.call_args.kwargs["window_state"], "minimized")

    def test_table_decorator_accepts_visible_and_maximized_window_state_metadata(self):
        for window_state in ("visible", "maximized"):
            with self.subTest(window_state=window_state):
                with patch("hyde.signal_open_table") as signal_open_table:
                    hyde.gui_mode(True)
                    try:
                        @hyde.table(window_state=window_state, register=False)
                        def Table0(a):
                            hyde.create_table(a)

                        Table0(np.array([1, 2, 3]))
                    finally:
                        hyde.gui_mode(False)

                signal_open_table.assert_called_once()
                self.assertEqual(
                    signal_open_table.call_args.kwargs["window_state"],
                    window_state,
                )

    def test_table_decorator_can_restore_stable_handle(self):
        with patch("hyde.signal_open_table") as signal_open_table:
            hyde.gui_mode(True)
            try:
                @hyde.table(register=False)
                def Table0(a):
                    hyde.create_table(a, name="Table0")

                Table0(np.array([1, 2, 3]))
            finally:
                hyde.gui_mode(False)

        signal_open_table.assert_called_once()
        self.assertEqual(signal_open_table.call_args.kwargs["name"], "Table0")

    def test_append_table_requires_separate_public_api(self):
        a = np.array([1, 2, 3])
        with patch("hyde.signal_append_table") as signal_append_table:
            hyde.gui_mode(True)
            try:
                hyde.append_table(a, name="Table0")
            finally:
                hyde.gui_mode(False)

        signal_append_table.assert_called_once_with(["a"], name="Table0")

    def test_table_api_rejects_direct_imperative_use(self):
        with self.assertRaises(TypeError):
            hyde.table(np.array([1, 2, 3]))

    def test_table_decorator_rejects_keyword_only_parameters(self):
        with self.assertRaises(TypeError):
            @hyde.table
            def Table0(*, a):
                return a

    def test_table_decorator_rejects_unknown_window_state(self):
        with self.assertRaises(TypeError):
            @hyde.table(window_state="hidden")
            def Table0(a):
                return a


class TestFigureDecorator(unittest.TestCase):
    def setUp(self):
        clear()

    def tearDown(self):
        pyplot = getattr(matplotlib, "pyplot", None)
        if pyplot is not None:
            pyplot.close("all")

    def _configure_pyplot(self):
        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as pyplot

        return pyplot

    def test_figure_decorator_registers_parameterized_macro(self):
        @hyde.figure
        def Graph0(x, y):
            return x, y

        self.assertEqual(names("figure"), ("Graph0",))
        self.assertEqual(
            tuple(serialize_registry("figure")["entries"]),
            ({"name": "Graph0", "args": ["x", "y"]},),
        )

    def test_figure_decorator_accepts_window_pos_metadata(self):
        @hyde.figure(window_pos=(10, 20))
        def Graph0(x, y):
            return x, y

        self.assertEqual(names("figure"), ("Graph0",))
        self.assertEqual(
            tuple(serialize_registry("figure")["entries"]),
            ({"name": "Graph0", "args": ["x", "y"]},),
        )

    def test_figure_decorator_accepts_window_state_metadata(self):
        for window_state in ("minimized", "visible", "maximized"):
            with self.subTest(window_state=window_state):
                @hyde.figure(window_state=window_state)
                def Graph0(x, y):
                    return x, y

                self.assertEqual(names("figure"), ("Graph0",))
                self.assertEqual(
                    tuple(serialize_registry("figure")["entries"]),
                    ({"name": "Graph0", "args": ["x", "y"]},),
                )
                clear(kind="figure")

    def test_figure_decorator_rejects_keyword_only_parameters(self):
        with self.assertRaises(TypeError):
            @hyde.figure
            def Graph0(*, x):
                return x

    def test_figure_decorator_rejects_unknown_metadata_keywords(self):
        with self.assertRaises(TypeError):
            @hyde.figure(window_position=(10, 20))
            def Graph0(x):
                return x

    def test_figure_decorator_rejects_unknown_window_state(self):
        with self.assertRaises(TypeError):
            @hyde.figure(window_state="hidden")
            def Graph0(x):
                return x

    def test_decorated_builder_creates_first_class_figure_with_ir_and_command_log(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        self.assertTrue(getattr(figure, "_hyde_is_first_class", False))
        self.assertIn("layout", figure._hyde_ir)
        self.assertTrue(figure._hyde_command_log)
        self.assertIsNotNone(getattr(figure, "_hyde_source_artifact", None))
        self.assertIsNotNone(getattr(figure, "_hyde_ast_artifact", None))

    def test_decorated_builder_attaches_window_pos_metadata_to_figure(self):
        plt = self._configure_pyplot()

        @hyde.figure(window_pos=(10, 20))
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        self.assertEqual(getattr(figure, "_hyde_metadata", {}), {"window_pos": (10, 20)})

    def test_decorated_builder_attaches_window_state_metadata_to_figure(self):
        plt = self._configure_pyplot()

        @hyde.figure(window_state="minimized")
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        self.assertEqual(getattr(figure, "_hyde_metadata", {}), {"window_state": "minimized"})

    def test_decorated_builder_exposes_window_pos_metadata_before_return(self):
        plt = self._configure_pyplot()
        observed = {}

        @hyde.figure(window_pos=(10, 20))
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            observed["metadata"] = dict(getattr(fig, "_hyde_metadata", {}))
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            fig.show()
            return fig

        Graph0([0, 1, 2], [1, 4, 9])

        self.assertEqual(observed["metadata"], {"window_pos": (10, 20)})

    def test_figure_decorator_can_skip_registration(self):
        plt = self._configure_pyplot()

        @hyde.figure(window_pos=(10, 20), register=False)
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            fig.show()

        figure = Graph0([0, 1, 2], [1, 4, 9])

        self.assertEqual(names("figure"), ())
        self.assertTrue(getattr(figure, "_hyde_is_first_class", False))
        self.assertEqual(getattr(figure, "_hyde_metadata", {}), {"window_pos": (10, 20)})

    def test_decorated_builder_can_omit_return_for_single_created_figure(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")

        figure = Graph0([0, 1, 2], [1, 4, 9])

        self.assertEqual(figure.get_label(), "Graph0")
        self.assertTrue(getattr(figure, "_hyde_is_first_class", False))
        self.assertEqual(len(figure._hyde_ir["layout"]["subplots"]), 1)

    def test_decorated_figure_label_is_the_stable_figure_handle(self):
        plt = self._configure_pyplot()

        @hyde.figure(register=False)
        def Figure0(x):
            fig = plt.figure(len(plt.get_fignums()) + 1)
            fig.set_label("Figure0")
            ax = fig.add_subplot(111)
            ax.plot(x, label="x")
            return fig

        figure = Figure0([0, 1, 2])

        self.assertEqual(figure.get_label(), "Figure0")

    def test_decorated_figure_conflict_falls_forward_to_next_free_handle(self):
        from hyde.matplotlib_backend import FigureHyde, finalize_figure_build_session

        first = FigureHyde()
        first._hyde_is_first_class = True
        first.set_label("Figure0")
        first._hyde_ir["settings"]["title"] = "Figure0"

        second = FigureHyde()
        second.set_label("Figure0")

        session = type(
            "FakeSession",
            (),
            {
                "created_figures": [second],
                "source_artifact": None,
                "ast_artifact": None,
                "bound_values": {},
                "metadata": {},
            },
        )()
        manager = type(
            "FakeManager",
            (),
            {"canvas": type("FakeCanvas", (), {"figure": first})()},
        )()

        with patch(
            "matplotlib._pylab_helpers.Gcf.get_all_fig_managers",
            return_value=[manager],
        ):
            resolved = finalize_figure_build_session(session, second)

        self.assertEqual(first.get_label(), "Figure0")
        self.assertEqual(resolved.get_label(), "Figure1")
        self.assertEqual(first._hyde_ir["settings"]["title"], "Figure0")
        self.assertEqual(resolved._hyde_ir["settings"]["title"], "Figure1")

    def test_decorated_builder_raises_when_no_figure_is_created(self):
        self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            del x, y

        with self.assertRaisesRegex(
            ValueError,
            "must create exactly one figure",
        ):
            Graph0([0, 1, 2], [1, 4, 9])

    def test_decorated_builder_raises_when_multiple_figures_are_created(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            del x, y
            plt.figure("Graph0")
            plt.figure("Graph1")

        with self.assertRaisesRegex(
            ValueError,
            "must create exactly one figure",
        ):
            Graph0([0, 1, 2], [1, 4, 9])


class TestDecoratedProcedureRegistries(unittest.TestCase):
    def setUp(self):
        clear()

    def test_register_builtin_fit_functions_registers_hyde_defaults(self):
        names = hyde.register_builtin_fit_functions()

        self.assertEqual(
            names,
            ("line", "gaussian", "lorentzian", "exp", "sin", "power", "log"),
        )
        self.assertEqual(
            tuple(
                entry["name"]
                for entry in serialize_registry("fit_function")["entries"]
            ),
            names,
        )
        entries = {
            entry["name"]: entry for entry in serialize_registry("fit_function")["entries"]
        }
        self.assertEqual(
            {name: entries[name]["callable_ref"] for name in names},
            {name: f"hyde.{name}" for name in names},
        )
        self.assertEqual(entries["line"]["parameters"], ["a", "b"])
        self.assertEqual(
            entries["line"]["source_text"],
            "def line(x, a, b):\n    return a * x + b",
        )
        self.assertEqual(
            entries["gaussian"]["parameters"],
            ["a", "x0", "width", "y0"],
        )
        self.assertEqual(
            entries["lorentzian"]["parameters"],
            ["a", "x0", "width", "y0"],
        )
        self.assertEqual(entries["exp"]["parameters"], ["a", "width", "y0"])
        self.assertEqual(entries["sin"]["parameters"], ["a", "k", "phi", "y0"])
        self.assertEqual(entries["power"]["parameters"], ["a", "alpha", "y0"])
        self.assertEqual(entries["log"]["parameters"], ["a", "y0"])

    def test_hyde_builtin_fit_function_formulas(self):
        x = np.array([1.0, 2.0, 4.0])

        np.testing.assert_allclose(hyde.line(x, 2.0, 3.0), 2.0 * x + 3.0)
        np.testing.assert_allclose(
            hyde.gaussian(x, 5.0, 2.0, 4.0, 1.5),
            5.0 * np.exp(-((x - 2.0) ** 2) / (4.0**2)) + 1.5,
        )
        np.testing.assert_allclose(
            hyde.lorentzian(x, 5.0, 2.0, 4.0, 1.5),
            5.0 * (1.0 / (1.0 + ((x - 2.0) ** 2) / (4.0**2))) + 1.5,
        )
        np.testing.assert_allclose(
            hyde.exp(x, 5.0, 4.0, 1.5),
            5.0 * np.exp(-x / 4.0) + 1.5,
        )
        np.testing.assert_allclose(
            hyde.sin(x, 5.0, 0.5, 0.25, 1.5),
            5.0 * np.sin(0.5 * x + 0.25) + 1.5,
        )
        np.testing.assert_allclose(
            hyde.power(x, 5.0, 2.5, 1.5),
            5.0 * (x**2.5) + 1.5,
        )
        np.testing.assert_allclose(
            hyde.log(x, 5.0, 1.5),
            5.0 * np.log(x) + 1.5,
        )

    def test_fit_function_registry_is_isolated_from_window_macro_kinds(self):
        @hyde.table
        def Table0(a):
            return a

        @hyde.figure
        def Graph0(x):
            return x

        def line_fit(x, slope):
            return slope * x

        line_fit.__module__ = "procedures"
        register_fit_function(line_fit, independent_vars=("x",))

        def bad_fit(x, *coeffs):
            return x

        reject_fit_function(bad_fit, reason="bad signature")

        self.assertEqual(names("table"), ("Table0",))
        self.assertEqual(names("figure"), ("Graph0",))
        self.assertEqual(
            tuple(serialize_registry("fit_function")["entries"]),
            (
                {
                    "name": "line_fit",
                    "callable_ref": "line_fit",
                    "source_text": "def line_fit(x, slope):\n    return slope * x",
                    "independent_vars": ["x"],
                    "parameters": ["slope"],
                },
            ),
        )
        self.assertEqual(
            tuple(serialize_registry("fit_function")["rejected"]),
            ({"name": "bad_fit", "reason": "bad signature"},),
        )

        clear(kind="table")
        self.assertEqual(names("table"), ())
        self.assertEqual(names("figure"), ("Graph0",))
        self.assertEqual(
            tuple(serialize_registry("fit_function")["entries"]),
            (
                {
                    "name": "line_fit",
                    "callable_ref": "line_fit",
                    "source_text": "def line_fit(x, slope):\n    return slope * x",
                    "independent_vars": ["x"],
                    "parameters": ["slope"],
                },
            ),
        )
        self.assertEqual(
            tuple(serialize_registry("fit_function")["rejected"]),
            ({"name": "bad_fit", "reason": "bad signature"},),
        )

        clear(kind="fit_function")
        self.assertEqual(names("figure"), ("Graph0",))
        self.assertEqual(tuple(serialize_registry("fit_function")["entries"]), ())
        self.assertEqual(tuple(serialize_registry("fit_function")["rejected"]), ())

    def test_fit_function_registry_preserves_registration_order(self):
        def second_fit(x, slope):
            return slope * x

        second_fit.__module__ = "procedures"

        def first_fit(x, slope):
            return slope * x

        first_fit.__module__ = "procedures"

        register_fit_function(second_fit, independent_vars=("x",))
        register_fit_function(first_fit, independent_vars=("x",))

        self.assertEqual(
            tuple(entry["name"] for entry in serialize_registry("fit_function")["entries"]),
            ("second_fit", "first_fit"),
        )

    def test_clear_without_kind_resets_all_registries(self):
        @hyde.table
        def Table0(a):
            return a

        @hyde.figure
        def Graph0(x):
            return x

        def line_fit(x, slope):
            return slope * x

        line_fit.__module__ = "procedures"
        register_fit_function(line_fit, independent_vars=("x",))

        clear()

        self.assertEqual(names("table"), ())
        self.assertEqual(names("figure"), ())
        self.assertEqual(tuple(serialize_registry("fit_function")["entries"]), ())
        self.assertEqual(tuple(serialize_registry("fit_function")["rejected"]), ())

    def test_publish_registry_without_kind_publishes_all_registry_payloads(self):
        @hyde.table
        def Table0(a):
            return a

        @hyde.figure
        def Graph0(x):
            return x

        def line_fit(x, slope):
            return slope * x

        line_fit.__module__ = "procedures"
        register_fit_function(line_fit, independent_vars=("x",))

        with patch("hyde.recreation_registry.put_parent_message") as put_parent_message:
            publish_registry()

        self.assertEqual(
            [call.args[0][0] for call in put_parent_message.call_args_list],
            [
                "TABLE_MACROS_RESPONSE",
                "FIGURE_MACROS_RESPONSE",
                "FIT_FUNCTIONS_RESPONSE",
            ],
        )


class TestWindowMacroStore(unittest.TestCase):
    def _write_source(self, text):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = os.path.join(tmpdir.name, "__init__.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_validate_macro_name_rejects_invalid_identifiers(self):
        with self.assertRaises(ValueError):
            validate_macro_name("not valid")

    def test_insert_new_macro_adds_bounded_block(self):
        macro = build_table_macro_source("Table0", ["a", "b"])

        updated = update_macro_source("", "Table0", macro)

        self.assertIn(BEGIN_MARKER, updated)
        self.assertIn(END_MARKER, updated)
        self.assertIn("@hyde.table", updated)
        self.assertIn("def Table0(a, b):", updated)
        self.assertIn("hyde.create_table(a, b)", updated)
        self.assertNotIn("title='Table0'", updated)

    def test_insert_new_macro_preserves_optional_layout_kwargs(self):
        macro = build_table_macro_source(
            "Table0",
            ["delay2", "fit_delay2"],
            name="Table0",
            geometry=(5, 42, 510, 242),
            column_widths={"fit_delay2": 262},
        )

        updated = update_macro_source("", "Table0", macro)

        self.assertIn("geometry=(5, 42, 510, 242)", updated)
        self.assertIn("column_widths={'fit_delay2': 262}", updated)

    def test_write_macro_source_normalizes_duplicate_autogenerated_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            procedures_init = os.path.join(tmpdir, "__init__.py")
            with open(procedures_init, "w", encoding="utf-8") as handle:
                handle.write(
                    "import hyde\n\n"
                    f"{BEGIN_MARKER}\n"
                    "@hyde.table\n"
                    "def Table0(a):\n"
                    "    return 'old-1'\n\n"
                    "@hyde.table\n"
                    "def Table1(a):\n"
                    "    return 'other'\n\n"
                    "@hyde.table\n"
                    "def Table0(a):\n"
                    "    return 'old-2'\n"
                    f"{END_MARKER}\n"
                )

            macro = build_table_macro_source("Table0", ["a", "b"])
            write_macro_source(procedures_init, "Table0", macro)

            with open(procedures_init, "r", encoding="utf-8") as handle:
                updated = handle.read()

            self.assertEqual(updated.count("def Table0("), 1)
            self.assertEqual(updated.count("def Table0(a, b):"), 1)
            self.assertIn("def Table1(a):", updated)
            self.assertIn("hyde.create_table(a, b)", updated)
            self.assertNotIn("title='Table0'", updated)
            conflict = inspect_macro_conflict(procedures_init, "Table0")
            self.assertIsNotNone(conflict)
            self.assertTrue(conflict["in_autogenerated_block"])
            self.assertFalse(conflict["multiple_matches"])

    def test_write_macro_source_rejects_same_name_outside_autogenerated_block(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            procedures_init = os.path.join(tmpdir, "__init__.py")
            with open(procedures_init, "w", encoding="utf-8") as handle:
                handle.write(
                    "import hyde\n\n"
                    "def Table0(a):\n"
                    "    return 'user'\n"
                )

            macro = build_table_macro_source("Table0", ["a"])
            with self.assertRaises(ValueError):
                write_macro_source(procedures_init, "Table0", macro)

            with open(procedures_init, "r", encoding="utf-8") as handle:
                self.assertEqual(
                    handle.read(),
                    "import hyde\n\n"
                    "def Table0(a):\n"
                    "    return 'user'\n",
                )

if __name__ == "__main__":
    unittest.main()
