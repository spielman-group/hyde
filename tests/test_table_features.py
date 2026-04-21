import copy
import unittest

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.table import TableViewModel


def make_table_codec_state(
    *,
    command="open",
    names=("a",),
    title=None,
    target=None,
    geometry=None,
    column_widths=None,
    request_id=None,
):
    from hyde.features.hyde_features import TableCodec

    state = copy.deepcopy(TableCodec.default_state())
    state["items"] = list(names)
    state["settings"].update(
        {
            "command": command,
            "title": title,
            "target": target,
            "geometry": geometry,
            "column_widths": dict(column_widths or {}),
            "request_id": request_id,
        }
    )
    return state


def make_mutation_codec_state(
    *,
    command,
    var_name=None,
    value_text=None,
    index=None,
    indices=None,
    existing_names=None,
):
    from hyde.features.hyde_features import MutationCodec

    state = copy.deepcopy(MutationCodec.default_state())
    state["settings"].update(
        {
            "command": command,
            "var_name": var_name,
            "value_text": value_text,
            "index": index,
            "indices": [] if indices is None else list(indices),
            "existing_names": [] if existing_names is None else list(existing_names),
        }
    )
    return state


class TestTableCodec(unittest.TestCase):
    def test_table_codec_open_generation_omits_default_layout_kwargs(self):
        from hyde.features.hyde_features import TableCodec

        state = make_table_codec_state(names=("delay2", "fit_delay2"), title="Table0")

        self.assertEqual(
            TableCodec.state_to_python(state),
            "hyde.table(delay2, fit_delay2, title='Table0')",
        )

    def test_table_codec_open_generation_includes_optional_layout_kwargs(self):
        from hyde.features.hyde_features import TableCodec

        state = make_table_codec_state(
            names=("delay2", "fit_delay2"),
            title="Table0",
            geometry=(5, 42, 510, 242),
            column_widths={"delay2": 140, "fit_delay2": 262},
        )

        source = TableCodec.state_to_python(state)

        self.assertIn("hyde.table(delay2, fit_delay2", source)
        self.assertIn("title='Table0'", source)
        self.assertIn("geometry=(5, 42, 510, 242)", source)
        self.assertIn("column_widths={'delay2': 140, 'fit_delay2': 262}", source)

    def test_table_codec_append_generation_ignores_layout_kwargs(self):
        from hyde.features.hyde_features import TableCodec

        state = make_table_codec_state(
            command="append",
            names=("a", "b"),
            target="Table0",
            geometry=(1, 2, 3, 4),
            column_widths={"a": 99},
        )

        source = TableCodec.state_to_python(state)

        self.assertEqual(source, "hyde.table(a, b, target='Table0')")
        self.assertNotIn("geometry=", source)
        self.assertNotIn("column_widths=", source)

    def test_table_codec_generates_background_table_data_command(self):
        from hyde.features.hyde_features import TableCodec

        state = make_table_codec_state(
            command="push_table_data",
            names=("a", "b"),
            request_id="req-1",
        )

        self.assertEqual(
            TableCodec.state_to_python(state),
            "hyde.execution.ipc.push_table_data(['a', 'b'], 'req-1')",
        )

    def test_table_codec_generates_background_macro_publish_command(self):
        from hyde.features.hyde_features import TableCodec

        state = make_table_codec_state(command="publish_table_macros")

        self.assertEqual(
            TableCodec.state_to_python(state),
            "hyde.table_macros.publish_table_macro_registry()",
        )


class TestMutationCodec(unittest.TestCase):
    def test_mutation_codec_generates_edit_append_new_array_and_delete_commands(self):
        from hyde.features.hyde_features import MutationCodec

        edit_state = make_mutation_codec_state(
            command="edit_value",
            var_name="wave0",
            index=1,
            value_text="abc",
        )
        append_state = make_mutation_codec_state(
            command="append_value",
            var_name="wave0",
            value_text="2",
        )
        create_state = make_mutation_codec_state(
            command="create_array",
            value_text="abc",
            existing_names=["textWave0"],
        )
        delete_state = make_mutation_codec_state(
            command="delete_indices",
            var_name="wave0",
            indices=[4, 1],
        )

        self.assertEqual(MutationCodec.state_to_python(edit_state), "wave0[1] = 'abc'")
        self.assertEqual(
            MutationCodec.state_to_python(append_state),
            "wave0 = np.concatenate((wave0, np.array([2], dtype=wave0.dtype)))",
        )
        self.assertEqual(
            MutationCodec.state_to_python(create_state),
            "textWave1 = np.array(['abc'])",
        )
        self.assertEqual(
            MutationCodec.state_to_python(delete_state),
            "wave0 = np.delete(wave0, [1, 4])",
        )

    def test_mutation_codec_rejects_empty_value_text(self):
        from hyde.features.hyde_features import MutationCodec

        state = make_mutation_codec_state(
            command="edit_value",
            var_name="wave0",
            index=0,
            value_text="   ",
        )

        with self.assertRaises(ValueError):
            MutationCodec.state_to_python(state)

    def test_mutation_codec_uses_numeric_name_prefix_for_non_strings(self):
        from hyde.features.hyde_features import MutationCodec

        state = make_mutation_codec_state(
            command="create_array",
            value_text="5",
            existing_names=["wave0"],
        )

        self.assertEqual(
            MutationCodec.state_to_python(state),
            "wave1 = np.array([5])",
        )


class TestTableStates(unittest.TestCase):
    def test_table_state_exposes_layout_defaults_and_python_source(self):
        from hyde.features.hyde_features import TableCodec
        from hyde.user_interface.table import TableState

        state = TableState()

        normalized = state.normalized_state()
        self.assertEqual(normalized["feature"], "table")
        self.assertIsNone(normalized["settings"].get("geometry"))
        self.assertEqual(normalized["settings"].get("column_widths"), {})
        self.assertIs(state.codec, TableCodec)

        state._state = make_table_codec_state(names=("a",), title="Table0")
        self.assertEqual(state.python_source(), "hyde.table(a, title='Table0')")
        self.assertEqual(state.default_macro_name(), "Table0")

    def test_table_state_macro_source_includes_optional_layout_kwargs(self):
        from hyde.user_interface.table import TableState

        state = TableState()
        state._state = make_table_codec_state(
            names=("delay2", "fit_delay2"),
            title="Table0",
            geometry=(5, 42, 510, 242),
            column_widths={"fit_delay2": 262},
        )

        macro = state.macro_source("Table0")

        self.assertIn("@hyde.table", macro)
        self.assertIn("def Table0(delay2, fit_delay2):", macro)
        self.assertIn("title='Table0'", macro)
        self.assertIn("geometry=(5, 42, 510, 242)", macro)
        self.assertIn("column_widths={'fit_delay2': 262}", macro)

    def test_mutation_state_python_source_delegates_to_mutation_codec(self):
        from hyde.features.hyde_features import MutationCodec
        from hyde.user_interface.base import MutationState

        state = MutationState()
        state._state = make_mutation_codec_state(
            command="append_value",
            var_name="wave0",
            value_text="2",
        )

        self.assertIs(state.codec, MutationCodec)
        self.assertEqual(
            state.python_source(),
            "wave0 = np.concatenate((wave0, np.array([2], dtype=wave0.dtype)))",
        )


class TestSaveWindowDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_save_window_dialog_uses_provided_table_state(self):
        from hyde.user_interface.save_window_dialog import SaveWindowDialog
        from hyde.user_interface.table import TableState

        state = TableState()
        state._state = make_table_codec_state(
            names=("delay2", "fit_delay2"),
            title="Table_Fun",
            geometry=(5, 42, 510, 242),
            column_widths={"fit_delay2": 262},
        )

        dialog = SaveWindowDialog(table_state=state)
        try:
            self.assertEqual(dialog.macro_name(), "Table_Fun")
            dialog.ui.nameEdit.setText("Table_Save")
            macro = dialog.macro_source()
        finally:
            dialog.close()

        self.assertIn("def Table_Save(delay2, fit_delay2):", macro)
        self.assertIn("geometry=(5, 42, 510, 242)", macro)
        self.assertIn("column_widths={'fit_delay2': 262}", macro)


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
