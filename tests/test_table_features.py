import unittest

from qtutils.qt import QtCore, QtWidgets
try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.user_interface.base import MutationState
from hyde.user_interface.plugins.table import (
    Plugin,
    TableWorkspaceService,
)
from hyde.user_interface.plugins.table.window import (
    TableState,
    TableWidget,
)

class TestTableCodec(unittest.TestCase):
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

class TestMutationCodec(unittest.TestCase):
    def test_mutation_state_generates_edit_append_new_array_and_delete_commands(self):
        edit_state = MutationState()
        edit_state.set_edit_value("array0", 1, "abc")
        append_state = MutationState()
        append_state.set_append_value("array0", "2")
        create_state = MutationState()
        create_state.set_create_array("abc", ["string_array0"])
        delete_state = MutationState()
        delete_state.set_delete_indices("array0", [4, 1])

        self.assertEqual(edit_state.python_source(), "array0[1] = 'abc'")
        self.assertEqual(
            append_state.python_source(),
            "array0 = np.concatenate((array0, np.array([2], dtype=array0.dtype)))",
        )
        self.assertEqual(
            create_state.python_source(),
            "string_array1 = np.array(['abc'])",
        )
        self.assertEqual(
            delete_state.python_source(),
            "array0 = np.delete(array0, [1, 4])",
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
            self.assertEqual(queued, [("array0 = np.array([5])", True)])
            self.assertEqual(widget.names, ["a"])

            namespace_service.emit(
                {
                    "a": {"type": "ndarray"},
                    "array0": {"type": "ndarray"},
                }
            )

            self.assertEqual(widget.names, ["a", "array0"])
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

    def test_table_refresh_detects_in_place_namespace_metadata_mutation(self):
        queued = []
        shared_view = ["[1 2 3]"]
        namespace_service = FakeNamespaceViewService(
            {"a": {"type": "ndarray", "view": shared_view}}
        )
        widget = TableWidget(
            "Table0",
            ["a"],
            services={
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            queued.clear()
            shared_view[0] = "[1 99 3]"
            namespace_service.emit({"a": {"type": "ndarray", "view": shared_view}})

            self.assertEqual(len(queued), 1)
            self.assertIn("hyde.execution.ipc.push_table_data(['a'],", queued[0][0])
        finally:
            widget.shutdown_client()
            widget.close()

    def test_table_refresh_recovers_after_timed_out_request(self):
        queued = []
        namespace_service = FakeNamespaceViewService(
            {"a": {"type": "ndarray", "view": "[1 2 3]"}}
        )
        widget = TableWidget(
            "Table0",
            ["a"],
            services={
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.refresh_data()
            self.assertTrue(widget._refresh_in_flight)

            widget._on_refresh_timeout()
            self.assertFalse(widget._refresh_in_flight)

            namespace_service.emit({"a": {"type": "ndarray", "view": "[1 9 3]"}})

            self.assertEqual(len(queued), 2)
            self.assertIn("hyde.execution.ipc.push_table_data(['a'],", queued[1][0])
        finally:
            widget.shutdown_client()
            widget.close()

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

    def test_table_plugin_session_routes_keep_tables_out_of_toml_and_emit_restore_source(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = Plugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "queue_background_command": lambda code, silent=True: True,
            "namespace_view_service": FakeNamespaceViewService(),
            "get_current_project_dir": lambda: "/tmp/demo.hy",
        }

        table = plugin.workspace.open_table(
            ["a", "b"],
            visible_title="Table_Fun",
            geometry=(5, 42, 510, 242),
            column_widths={"a": 120, "b": 260},
        )
        table.ui.tableView.setColumnWidth(1, 120)
        table.ui.tableView.setColumnWidth(2, 260)
        table.capture_layout_state()
        plugin.workspace.active_table_handle = "Table0"

        toml_data = plugin.get_session_toml_data()
        session_source = plugin.get_session_restore_source()

        self.assertEqual(toml_data, {"table_counter": 1})
        self.assertIn("@hyde.table(register=False)", session_source)
        self.assertIn("def Table0(a, b):", session_source)
        self.assertIn("Table0(a, b)", session_source)
        self.assertIn("title='Table_Fun'", session_source)
        self.assertIn("geometry=(5, 42, 510, 242)", session_source)
        self.assertIn("column_widths={'a': 120, 'b': 260}", session_source)

        plugin.workspace.clear()
        mdi_area.close()

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


if __name__ == "__main__":
    unittest.main()
