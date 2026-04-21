import os
import tempfile
import unittest
import copy

import hyde
from hyde.table_macros import clear_table_macros, table_macro_entries, table_macro_names
from hyde.user_interface.window_macro_store import (
    BEGIN_MARKER,
    END_MARKER,
    inspect_macro_conflict,
    update_macro_source,
    validate_macro_name,
    write_macro_source,
)


def build_table_macro_source(macro_name, names, title=None, geometry=None, column_widths=None):
    from hyde.features.hyde_features import TableCodec
    from hyde.user_interface.table import TableState

    state = TableState()
    state._state = copy.deepcopy(TableCodec.default_state())
    state._state["items"] = list(names)
    state._state["settings"].update(
        {
            "command": "open",
            "title": title,
            "geometry": geometry,
            "column_widths": dict(column_widths or {}),
        }
    )
    return state.macro_source(macro_name)


class TestTableDecorator(unittest.TestCase):
    def setUp(self):
        clear_table_macros()

    def test_table_decorator_registers_parameterized_macro(self):
        @hyde.table
        def Table0(a, b):
            return a, b

        self.assertEqual(table_macro_names(), ("Table0",))
        self.assertEqual(
            table_macro_entries(),
            ({"name": "Table0", "args": ["a", "b"]},),
        )

    def test_table_decorator_rejects_keyword_only_parameters(self):
        with self.assertRaises(TypeError):
            @hyde.table
            def Table0(*, a):
                return a


class TestWindowMacroStore(unittest.TestCase):
    def test_validate_macro_name_rejects_invalid_identifiers(self):
        with self.assertRaises(ValueError):
            validate_macro_name("not valid")

    def test_insert_new_macro_adds_bounded_block(self):
        macro = build_table_macro_source("Table0", ["a", "b"], title="Table0")

        updated = update_macro_source("", "Table0", macro)

        self.assertIn(BEGIN_MARKER, updated)
        self.assertIn(END_MARKER, updated)
        self.assertIn("@hyde.table", updated)
        self.assertIn("def Table0(a, b):", updated)
        self.assertIn("hyde.table(a, b, title='Table0')", updated)

    def test_overwrite_existing_function_in_place(self):
        source = (
            "import hyde\n\n"
            "@hyde.table\n"
            "def Table0(a):\n"
            "    hyde.table(a)\n"
        )
        macro = build_table_macro_source("Table0", ["a", "b"], title="Table0")

        updated = update_macro_source(source, "Table0", macro)

        self.assertEqual(updated.count("def Table0(a, b):"), 1)
        self.assertIn("hyde.table(a, b, title='Table0')", updated)
        conflict = inspect_macro_conflict_from_text(updated, "Table0")
        self.assertIsNotNone(conflict)

    def test_insert_new_macro_preserves_optional_layout_kwargs(self):
        macro = build_table_macro_source(
            "Table0",
            ["delay2", "fit_delay2"],
            title="Table0",
            geometry=(5, 42, 510, 242),
            column_widths={"fit_delay2": 262},
        )

        updated = update_macro_source("", "Table0", macro)

        self.assertIn("geometry=(5, 42, 510, 242)", updated)
        self.assertIn("column_widths={'fit_delay2': 262}", updated)

    def test_write_macro_source_replaces_existing_named_function(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            procedures_init = os.path.join(tmpdir, "__init__.py")
            with open(procedures_init, "w", encoding="utf-8") as handle:
                handle.write(
                    "import hyde\n\n"
                    "def Table0(a):\n"
                    "    return 'old'\n"
                )

            macro = build_table_macro_source("Table0", ["a"], title="Table0")
            write_macro_source(procedures_init, "Table0", macro)

            with open(procedures_init, "r", encoding="utf-8") as handle:
                updated = handle.read()

            self.assertEqual(updated.count("def Table0(a):"), 1)
            self.assertIn("@hyde.table", updated)
            self.assertIn("hyde.table(a, title='Table0')", updated)


def inspect_macro_conflict_from_text(text, name):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "__init__.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return inspect_macro_conflict(path, name)


if __name__ == "__main__":
    unittest.main()
