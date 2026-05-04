import unittest
from unittest import mock

from qtutils.qt import QtCore, QtWidgets
try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.user_interface.base import MutationState
from hyde.user_interface.plugins.table import (
    Plugin as TablePlugin,
    TableFeatureService,
    TableWorkspaceService,
)
from hyde.user_interface.plugins.table.window import (
    TableState,
    TableViewModel,
    TableWidget,
)

class TestTableCodec(unittest.TestCase):
    def test_table_state_open_generation_omits_default_layout_kwargs(self):
        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_title("Table0")

        self.assertEqual(
            state.python_source(),
            "hyde.table(delay2, fit_delay2, title='Table0')",
        )

    def test_table_state_open_generation_includes_optional_layout_kwargs(self):
        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_title("Table0")
        state.set_geometry((5, 42, 510, 242))
        state.set_column_widths({"delay2": 140, "fit_delay2": 262})

        source = state.python_source()

        self.assertIn("hyde.table(delay2, fit_delay2", source)
        self.assertIn("title='Table0'", source)
        self.assertIn("geometry=(5, 42, 510, 242)", source)
        self.assertIn("column_widths={'delay2': 140, 'fit_delay2': 262}", source)

    def test_table_state_append_generation_ignores_layout_kwargs(self):
        state = TableState()
        state.set_items(["a", "b"])
        state.set_target("Table0")
        state.set_geometry((1, 2, 3, 4))
        state.set_column_widths({"a": 99})

        source = state.source_for_command("append")

        self.assertEqual(source, "hyde.table(a, b, target='Table0')")
        self.assertNotIn("geometry=", source)
        self.assertNotIn("column_widths=", source)

    def test_table_state_generates_background_table_data_command(self):
        state = TableState()
        state.set_items(["a", "b"])
        state.set_request_id("req-1")

        self.assertEqual(
            state.source_for_command("push_table_data"),
            "hyde.execution.ipc.push_table_data(['a', 'b'], 'req-1')",
        )

    def test_table_state_generates_background_macro_publish_command(self):
        state = TableState()

        self.assertEqual(
            state.source_for_command("publish_table_macros"),
            "hyde.recreation_registry.publish_table_macro_registry()",
        )


class TestMutationCodec(unittest.TestCase):
    def test_mutation_state_generates_edit_append_new_array_and_delete_commands(self):
        edit_state = MutationState()
        edit_state.set_edit_value("wave0", 1, "abc")
        append_state = MutationState()
        append_state.set_append_value("wave0", "2")
        create_state = MutationState()
        create_state.set_create_array("abc", ["textWave0"])
        delete_state = MutationState()
        delete_state.set_delete_indices("wave0", [4, 1])

        self.assertEqual(edit_state.python_source(), "wave0[1] = 'abc'")
        self.assertEqual(
            append_state.python_source(),
            "wave0 = np.concatenate((wave0, np.array([2], dtype=wave0.dtype)))",
        )
        self.assertEqual(
            create_state.python_source(),
            "textWave1 = np.array(['abc'])",
        )
        self.assertEqual(
            delete_state.python_source(),
            "wave0 = np.delete(wave0, [1, 4])",
        )

    def test_mutation_state_rejects_empty_value_text(self):
        state = MutationState()
        state.set_edit_value("wave0", 0, "   ")

        with self.assertRaises(ValueError):
            state.python_source()

    def test_mutation_state_uses_numeric_name_prefix_for_non_strings(self):
        state = MutationState()
        state.set_create_array("5", ["wave0"])

        self.assertEqual(
            state.python_source(),
            "wave1 = np.array([5])",
        )


class TestTableStates(unittest.TestCase):
    def test_table_state_exposes_layout_defaults_and_python_source(self):
        from hyde.features.hyde_features import TableCodec

        state = TableState()

        normalized = state.normalized_state()
        self.assertEqual(normalized["feature"], "table")
        self.assertIsNone(normalized["settings"].get("geometry"))
        self.assertEqual(normalized["settings"].get("column_widths"), {})
        self.assertIs(state.codec, TableCodec)

        state.set_items(["a"])
        state.set_title("Table0")
        self.assertEqual(state.python_source(), "hyde.table(a, title='Table0')")
        self.assertEqual(state.default_macro_name(), "Table0")

    def test_table_state_macro_source_includes_optional_layout_kwargs(self):
        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_title("Table0")
        state.set_geometry((5, 42, 510, 242))
        state.set_column_widths({"fit_delay2": 262})

        macro = state.macro_source("Table0")

        self.assertIn("@hyde.table", macro)
        self.assertIn("def Table0(delay2, fit_delay2):", macro)
        self.assertIn("title='Table0'", macro)
        self.assertIn("geometry=(5, 42, 510, 242)", macro)
        self.assertIn("column_widths={'fit_delay2': 262}", macro)

    def test_mutation_state_python_source_delegates_to_mutation_codec(self):
        from hyde.features.hyde_features import MutationCodec

        state = MutationState()
        state.set_append_value("wave0", "2")

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
        from hyde.user_interface.plugins.table.window import (
            SaveWindowDialog,
            TableState,
        )

        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_title("Table_Fun")
        state.set_geometry((5, 42, 510, 242))
        state.set_column_widths({"fit_delay2": 262})

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


class FakeNamespaceViewService:
    def __init__(self, view=None):
        self._view = dict(view or {})
        self._callbacks = []

    def namespace_view(self):
        return dict(self._view)

    def connect_namespace_view_updated(self, callback):
        self._callbacks.append(callback)

    def disconnect_namespace_view_updated(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, view):
        self._view = dict(view)
        for callback in list(self._callbacks):
            callback(dict(self._view))


class FakeTablePlugin:
    def __init__(self, mdi_area, save_result=True):
        self.services = {
            "mdi_area": mdi_area,
            "queue_background_command": lambda code, silent=True: None,
        }
        self.prompted_states = []
        self.save_result = save_result

    def request_save_table_macro(self, table_state):
        self.prompted_states.append(table_state)
        return self.save_result


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


class TestTableWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_new_column_is_added_only_after_namespace_confirms_creation(self):
        executed = []
        queued = []
        namespace_service = FakeNamespaceViewService({"a": {"type": "ndarray"}})
        widget = TableWidget(
            "Table0",
            ["a"],
            services={
                "execute_command": lambda code, visible=False: executed.append(
                    (code, visible)
                ),
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.model.update_data({"a": [1]})
            widget.ui.tableView.setCurrentIndex(widget.model.index(0, 2))
            widget.ui.valueEdit.setReadOnly(False)
            widget.ui.valueEdit.setText("5")

            self.assertTrue(widget._submit_value_edit())
            self.assertEqual(executed, [])
            self.assertEqual(queued, [("wave0 = np.array([5])", True)])
            self.assertEqual(widget.names, ["a"])

            namespace_service.emit(
                {
                    "a": {"type": "ndarray"},
                    "wave0": {"type": "ndarray"},
                }
            )

            self.assertEqual(widget.names, ["a", "wave0"])
            self.assertGreaterEqual(len(queued), 2)
        finally:
            widget.shutdown_client()
            widget.close()

    def test_edit_submission_queues_mutation_before_refresh_and_ignores_stale_reply(self):
        executed = []
        queued = []
        namespace_service = FakeNamespaceViewService({"a": {"type": "ndarray"}})
        widget = TableWidget(
            "Table0",
            ["a"],
            services={
                "execute_command": lambda code, visible=False: executed.append(
                    (code, visible)
                ),
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.model.update_data({"a": [0]})
            widget.refresh_data()
            first_request_id = widget._current_request_id

            widget.ui.tableView.setCurrentIndex(widget.model.index(0, 1))
            widget.ui.valueEdit.setReadOnly(False)
            widget.ui.valueEdit.setText("9")

            self.assertTrue(widget._submit_value_edit())
            self.assertEqual(executed, [])
            self.assertEqual(len(queued), 3)
            self.assertEqual(queued[0][1], True)
            self.assertEqual(queued[1][1], True)
            self.assertEqual(queued[2][1], True)
            self.assertEqual(queued[1][0], "a[0] = 9")
            second_request_id = widget._current_request_id
            self.assertEqual(
                queued[2][0],
                widget.table_state.source_for_command(
                    "push_table_data",
                    request_id=second_request_id,
                ),
            )
            self.assertNotEqual(second_request_id, first_request_id)
            self.assertFalse(widget._refresh_requested)

            widget.on_data_received({"a": [1]}, first_request_id)

            self.assertEqual(widget.model.data_cache["a"], [0])

            widget.on_data_received({"a": [9]}, second_request_id)

            self.assertEqual(widget.model.data_cache["a"], [9])
            self.assertFalse(widget._refresh_in_flight)
        finally:
            widget.shutdown_client()
            widget.close()

    def test_append_submission_queues_refresh_without_namespace_metadata_change(self):
        executed = []
        queued = []
        namespace_service = FakeNamespaceViewService({"a": {"type": "ndarray"}})
        widget = TableWidget(
            "Table0",
            ["a"],
            services={
                "execute_command": lambda code, visible=False: executed.append(
                    (code, visible)
                ),
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.model.update_data({"a": [1]})
            widget.ui.tableView.setCurrentIndex(widget.model.index(1, 1))
            widget.ui.valueEdit.setReadOnly(False)
            widget.ui.valueEdit.setText("9")

            self.assertTrue(widget._submit_value_edit())

            self.assertEqual(executed, [])
            self.assertEqual(len(queued), 2)
            self.assertEqual(
                queued[0][0],
                "a = np.concatenate((a, np.array([9], dtype=a.dtype)))",
            )
            self.assertIn(
                "hyde.execution.ipc.push_table_data(['a'],",
                queued[1][0],
            )
        finally:
            widget.shutdown_client()
            widget.close()


class TestTablePlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_plugin_uses_action_lookup_service_for_new_table_action(self):
        main_window = QtWidgets.QMainWindow()
        main_window.menuWindow = QtWidgets.QMenu("Window", main_window)
        mdi_area = QtWidgets.QMdiArea()
        sentinel_action = QtWidgets.QAction("New Table...", main_window)
        plugin = TablePlugin({})

        services = {
            "ui": main_window,
            "mdi_area": mdi_area,
            "lookup_menu_action": lambda location, name, path=(): (
                sentinel_action
                if (location, name, tuple(path) if not isinstance(path, str) else (path,))
                == ("window", "New Table...", ())
                else None
            ),
            "get_current_project_dir": lambda: None,
            "queue_background_command": lambda code, silent=True: None,
            "execute_command": lambda code, visible=True: None,
            "reload_procedures": lambda: None,
            "get_procedures_init": lambda: None,
        }

        plugin.plugin_setup_complete({"services": services})

        self.assertIs(plugin._new_table_action, sentinel_action)
        self.assertEqual(plugin._macro_menu.title(), "Table Macros")


class TestTableWorkspaceService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _drain_events(self):
        self.qapp.processEvents()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.qapp.processEvents()

    def test_subwindow_close_uses_table_widget_close_path(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(["a"])
        subwindow = table.parentWidget()

        self.assertTrue(subwindow.testAttribute(QtCore.Qt.WA_DeleteOnClose))

        subwindow.close()
        self._drain_events()

        self.assertEqual(len(plugin.prompted_states), 1)
        self.assertTrue(table._closed)
        self.assertIsNone(workspace.lookup_table("Table0"))
        self.assertEqual(mdi_area.subWindowList(), [])

    def test_new_tables_keep_unique_handles_when_visible_titles_match(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        first = workspace.open_table(["a"], visible_title="Shared")
        second = workspace.open_table(["b"], visible_title="Shared")

        self.assertEqual(first.handle, "Table0")
        self.assertEqual(second.handle, "Table1")
        self.assertEqual(first.parentWidget().windowTitle(), "Shared")
        self.assertEqual(second.parentWidget().windowTitle(), "Shared")

        workspace.clear()
        self._drain_events()

    def test_subwindow_deactivation_clears_active_table_handle(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        plugin.services["execute_command"] = mock.Mock()
        workspace = TableWorkspaceService(plugin)
        plugin.workspace = workspace
        table_feature = TableFeatureService(plugin)

        table = workspace.open_table(["a"])

        workspace.on_subwindow_activated(table.parentWidget())
        self.assertEqual(workspace.active_table_handle, "Table0")

        workspace.on_subwindow_activated(None)

        self.assertIsNone(workspace.active_table_handle)
        self.assertFalse(table_feature.append_to_active_table(["b"]))
        plugin.services["execute_command"].assert_not_called()

        workspace.clear()
        self._drain_events()

    def test_subwindow_close_honors_table_prompt_cancel(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=False)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(["a"])
        subwindow = table.parentWidget()
        subwindow.close()
        self._drain_events()

        self.assertEqual(len(plugin.prompted_states), 1)
        self.assertFalse(table._closed)
        self.assertIs(workspace.lookup_table("Table0"), table)
        self.assertIn(subwindow, mdi_area.subWindowList())

        workspace.clear()
        self._drain_events()

    def test_shift_close_skips_prompt_but_still_removes_table(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(["a"])
        subwindow = table.parentWidget()

        with mock.patch.object(
            QtWidgets.QApplication,
            "keyboardModifiers",
            return_value=QtCore.Qt.ShiftModifier,
        ):
            subwindow.close()
        self._drain_events()

        self.assertEqual(plugin.prompted_states, [])
        self.assertTrue(table._closed)
        self.assertIsNone(workspace.lookup_table("Table0"))
        self.assertEqual(mdi_area.subWindowList(), [])

    def test_clear_removes_hidden_table_subwindows(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(["a"])
        subwindow = table.parentWidget()
        subwindow.hide()

        workspace.clear()
        self._drain_events()

        self.assertEqual(plugin.prompted_states, [])
        self.assertEqual(workspace.tables, {})
        self.assertEqual(mdi_area.subWindowList(), [])


if __name__ == "__main__":
    unittest.main()
