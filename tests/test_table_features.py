import unittest

from qtutils.qt import QtCore

from hyde.features.hyde_features import (
    format_delete_indices_command,
    format_cell_append_command,
    format_cell_edit_command,
    format_entry_literal,
    format_new_array_command,
    suggest_new_array_name,
)
from hyde.user_interface.table import TableViewModel


class TestTableFeatureHelpers(unittest.TestCase):
    def test_format_entry_literal_preserves_python_literals(self):
        self.assertEqual(format_entry_literal("5"), "5")
        self.assertEqual(format_entry_literal("3.14"), "3.14")
        self.assertEqual(format_entry_literal("'abc'"), "'abc'")

    def test_format_entry_literal_treats_bare_text_as_string(self):
        self.assertEqual(format_entry_literal("abc"), "'abc'")

    def test_append_and_new_array_commands(self):
        self.assertEqual(
            format_cell_edit_command("wave0", 1, "abc"),
            "wave0[1] = 'abc'",
        )
        self.assertEqual(
            format_cell_append_command("wave0", "2"),
            "wave0 = np.concatenate((wave0, np.array([2], dtype=wave0.dtype)))",
        )
        self.assertEqual(
            format_new_array_command("textWave0", "abc"),
            "textWave0 = np.array(['abc'])",
        )
        self.assertEqual(
            format_delete_indices_command("wave0", {4, 1}),
            "wave0 = np.delete(wave0, [1, 4])",
        )

    def test_suggest_new_array_name_uses_type_inference(self):
        self.assertEqual(suggest_new_array_name({"wave0"}, "5"), "wave1")
        self.assertEqual(suggest_new_array_name({"textWave0"}, "abc"), "textWave1")


class TestTableViewModel(unittest.TestCase):
    def test_model_exposes_append_row_and_inactive_column(self):
        model = TableViewModel(["c"])
        model.update_data({"c": [5, 6]})

        self.assertEqual(model.rowCount(), 3)
        self.assertEqual(model.columnCount(), 3)
        self.assertEqual(
            model.headerData(2, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole),
            "",
        )
        self.assertEqual(
            model.data(model.index(2, 0), QtCore.Qt.DisplayRole),
            "",
        )

        append_index = model.index(2, 1)
        inactive_top_index = model.index(0, 2)
        inactive_other_index = model.index(1, 2)

        self.assertTrue(model.flags(append_index) & QtCore.Qt.ItemIsEditable)
        self.assertIsNotNone(model.data(append_index, QtCore.Qt.BackgroundRole))
        self.assertTrue(model.flags(inactive_top_index) & QtCore.Qt.ItemIsEditable)
        self.assertEqual(model.flags(inactive_other_index), QtCore.Qt.NoItemFlags)


if __name__ == "__main__":
    unittest.main()
