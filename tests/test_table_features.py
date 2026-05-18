import os
import unittest
from unittest.mock import patch

import numpy as np
import hyde

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtCore, QtGui, QtWidgets
try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.user_interface.base import MutationState
from hyde.user_interface.hyde_interactive_widget import HydeInteractiveWidget
from hyde.user_interface.plugins.table import (
    Plugin,
    TableWorkspaceService,
)
from hyde.user_interface.plugins.table.window import (
    TableState,
    TableWidget,
)

class TestTableCodec(unittest.TestCase):
    def test_create_table_accepts_mixed_numeric_and_string_arrays(self):
        x = np.array([1.0, 2.0, 3.0])
        string_array0 = np.array(["a", "b", "c"])

        with patch.object(hyde, "HYDE_GUI", True), patch.object(
            hyde,
            "signal_open_table",
        ) as signal_open_table:
            hyde.create_table(
                x,
                string_array0,
                name="Table0",
                column_widths={"x": 100, "string_array0": 100},
            )

        signal_open_table.assert_called_once_with(
            ["x", "string_array0"],
            name="Table0",
            geometry=None,
            column_widths={"x": 100, "string_array0": 100},
            window_state=None,
        )

    def test_create_table_rejects_geometry_minimized(self):
        x = np.array([1.0, 2.0, 3.0])

        with self.assertRaises(TypeError):
            hyde.create_table(
                x,
                name="Table0",
                geometry=(5, 42, 510, 242),
                geometry_minimized=(40, 50, 180, 30),
                column_widths={"x": 100},
                window_state="minimized",
            )

    def test_table_state_open_generation_includes_optional_layout_kwargs(self):
        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_name("Table7")
        state.set_geometry((5, 42, 510, 242))
        state.set_column_widths({"delay2": 140, "fit_delay2": 262})

        source = state.python_source()

        self.assertIn("hyde.create_table(delay2, fit_delay2", source)
        self.assertIn("name='Table7'", source)
        self.assertIn("geometry=(5, 42, 510, 242)", source)
        self.assertIn("column_widths={'delay2': 140, 'fit_delay2': 262}", source)

    def test_table_state_open_generation_omits_name_when_not_explicit(self):
        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_geometry((5, 42, 510, 242))

        source = state.python_source()

        self.assertIn("hyde.create_table(delay2, fit_delay2", source)
        self.assertNotIn("name=", source)

    def test_table_recreation_sources_preserve_requested_name(self):
        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_name("Table0")
        state.set_geometry((5, 42, 510, 242))
        state.set_column_widths({"delay2": 140, "fit_delay2": 262})

        macro = state.macro_source("Table0")
        session_function = state.recreation_function_source("Table0")

        self.assertIn("name='Table0'", macro)
        self.assertIn("name='Table0'", session_function)

    def test_table_state_append_generation_uses_append_table_api(self):
        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_command("append")
        state.set_name("Table7")

        source = state.python_source()

        self.assertEqual(
            source,
            "hyde.append_table(delay2, fit_delay2, name='Table7')",
        )

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

    def test_save_window_dialog_uses_provided_saveable(self):
        from hyde.user_interface.plugins.save_window_dialog import SaveWindowDialog

        state = TableState()
        state.set_items(["delay2", "fit_delay2"])
        state.set_name("Table_Fun")
        state.set_geometry((5, 42, 510, 242))
        state.set_column_widths({"fit_delay2": 262})

        dialog = SaveWindowDialog(saveable=state)
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


class FakeExecutionService:
    def __init__(self, hidden_calls=None, visible_calls=None):
        self.hidden_calls = hidden_calls if hidden_calls is not None else []
        self.visible_calls = visible_calls if visible_calls is not None else []

    def execute_hidden(self, code, silent=True):
        self.hidden_calls.append((code, silent))
        return True

    def execute_visible(self, code):
        self.visible_calls.append(code)
        return True


class FakeSaveWindowDialogService:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def prompt_to_save_window_macro(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeInteractiveWidget(HydeInteractiveWidget):
    def __init__(self, services=None):
        super().__init__(services=services, initial_window_name="Table0")
        self.capture_calls = 0
        self.final_close_calls = 0

    def capture_layout_state(self):
        self.capture_calls += 1

    def saveable_decorator_name(self):
        return "@hyde.fake"

    def saveable_default_macro_name(self):
        return "FallbackWidget"

    def macro_definition_source(self, macro_name, *, handle):
        del handle
        return (
            "@hyde.fake\n"
            f"def {macro_name}():\n"
            "    return 'macro'\n"
        )

    def session_restore_definition_source(self, handle):
        return (
            "@hyde.fake\n"
            f"def {handle}(alpha, beta):\n"
            "    return 'restore'\n"
        )

    def session_restore_arguments(self):
        return ("alpha", "beta")

    def macro_window_metadata(self, geometry, window_state):
        del geometry, window_state
        return {"window_pos": (3, 4), "window_state": "maximized"}

    def session_restore_window_metadata(self, geometry, window_state):
        del geometry, window_state
        return {"window_pos": (7, 8), "window_state": "minimized"}

    def finalize_interactive_close(self, event):
        self.final_close_calls += 1
        event.accept()


class FakeTablePlugin:
    def __init__(self, mdi_area, save_result=True):
        self.save_window_dialog_service = FakeSaveWindowDialogService(save_result)
        self.services = {
            "mdi_area": mdi_area,
            "python_execution_service": FakeExecutionService(),
            "ui": object(),
            "get_procedures_init": lambda: "/tmp/project.hy/procedures/__init__.py",
            "reload_procedures": lambda: None,
            "save_window_dialog_service": self.save_window_dialog_service,
        }


class TestTableWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_constructor_preserves_qwidget_parent_and_flags(self):
        parent = QtWidgets.QWidget()
        widget = TableWidget(
            "Table0",
            ["a"],
            None,
            None,
            None,
            parent,
            flags=QtCore.Qt.Tool,
        )
        try:
            self.assertIs(widget.parentWidget(), parent)
            self.assertTrue(widget.windowFlags() & QtCore.Qt.Tool)
        finally:
            widget.shutdown_client()
            widget.close()
            parent.close()

    def test_new_column_is_added_only_after_namespace_confirms_creation(self):
        executed = []
        queued = []
        namespace_service = FakeNamespaceViewService({"a": {"type": "ndarray"}})
        widget = TableWidget(
            "Table0",
            ["a"],
            services={
                "python_execution_service": FakeExecutionService(queued, executed),
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
                "python_execution_service": FakeExecutionService(queued, executed),
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
                "python_execution_service": FakeExecutionService(queued, executed),
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
                "python_execution_service": FakeExecutionService(queued),
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

    def test_deleted_namespace_column_is_removed_from_table_headers(self):
        queued = []
        namespace_service = FakeNamespaceViewService({"x": {"type": "ndarray"}})
        widget = TableWidget(
            "Table0",
            ["x"],
            services={
                "python_execution_service": FakeExecutionService(queued),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.model.update_data({"x": [1, 2, 3]})
            queued.clear()

            namespace_service.emit({})

            self.assertEqual(widget.names, [])
            self.assertEqual(widget.table_state.normalized_state()["items"], [])
            self.assertEqual(
                widget.model.headerData(1, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole),
                "",
            )
            self.assertEqual(queued, [])
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
                "python_execution_service": FakeExecutionService(queued),
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

    def test_activate_popup_menu_activates_bound_subwindow(self):
        popup_calls = []
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        table = TableWidget(
            "Table0",
            ["a"],
            services={
                "mdi_area": mdi_area,
                "popup_menu": lambda location, global_pos: popup_calls.append(
                    (location, global_pos)
                ),
            },
        )
        other = QtWidgets.QWidget()
        other_subwindow = mdi_area.addSubWindow(other)
        subwindow = mdi_area.addSubWindow(table)
        other_subwindow.show()
        subwindow.show()
        table.bind_subwindow(subwindow)
        self.qapp.processEvents()
        mdi_area.setActiveSubWindow(other_subwindow)

        try:
            menu_pos = QtCore.QPoint(20, 30)

            self.assertTrue(table.activate_popup_menu("table", menu_pos))
            self.assertIs(mdi_area.activeSubWindow(), subwindow)
            self.assertEqual(popup_calls, [("table", menu_pos)])
        finally:
            table.shutdown_client()
            table.close()
            other.close()
            mdi_area.close()


class TestHydeInteractiveWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_close_event_prompts_before_subclass_final_close(self):
        save_window_dialog_service = FakeSaveWindowDialogService(result=True)
        widget = FakeInteractiveWidget(
            services={
                "save_window_dialog_service": save_window_dialog_service,
                "get_procedures_init": lambda: "/tmp/project.hy/procedures/__init__.py",
                "reload_procedures": lambda: None,
            }
        )

        event = QtGui.QCloseEvent()
        widget.closeEvent(event)

        self.assertEqual(widget.capture_calls, 1)
        self.assertEqual(widget.final_close_calls, 1)
        self.assertTrue(event.isAccepted())
        self.assertEqual(len(save_window_dialog_service.calls), 1)
        self.assertIs(save_window_dialog_service.calls[0]["saveable"], widget)

    def test_close_event_shift_bypasses_prompt_and_uses_subclass_final_close(self):
        save_window_dialog_service = FakeSaveWindowDialogService(result=False)
        widget = FakeInteractiveWidget(
            services={
                "save_window_dialog_service": save_window_dialog_service,
                "get_procedures_init": lambda: "/tmp/project.hy/procedures/__init__.py",
                "reload_procedures": lambda: None,
            }
        )

        event = QtGui.QCloseEvent()
        with patch.object(
            QtWidgets.QApplication,
            "keyboardModifiers",
            return_value=QtCore.Qt.ShiftModifier,
        ):
            widget.closeEvent(event)

        self.assertEqual(widget.capture_calls, 0)
        self.assertEqual(widget.final_close_calls, 1)
        self.assertTrue(event.isAccepted())
        self.assertEqual(save_window_dialog_service.calls, [])

    def test_default_macro_name_prefers_bound_window_handle(self):
        widget = FakeInteractiveWidget()
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setObjectName("Table7")
        try:
            widget.bind_subwindow(subwindow)

            self.assertEqual(widget.default_macro_name(), "Table7")
        finally:
            widget.close()
            mdi_area.close()

    def test_macro_source_uses_shared_saveable_contract(self):
        widget = FakeInteractiveWidget()

        source = widget.macro_source("SavedWidget")

        self.assertEqual(widget.capture_calls, 1)
        self.assertIn(
            "@hyde.fake(window_pos=(3, 4), window_state='maximized')",
            source,
        )
        self.assertIn("def SavedWidget():", source)
        self.assertIn("return 'macro'", source)

    def test_session_restore_source_uses_shared_saveable_contract(self):
        widget = FakeInteractiveWidget()
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setObjectName("Table7")
        try:
            widget.bind_subwindow(subwindow)

            source = widget.session_restore_source()

            self.assertEqual(widget.capture_calls, 1)
            self.assertIn(
                "@hyde.fake(window_pos=(7, 8), window_state='minimized', register=False)",
                source,
            )
            self.assertIn("def Table7(alpha, beta):", source)
            self.assertIn("return 'restore'", source)
            self.assertIn("Table7(alpha, beta)", source)
        finally:
            widget.close()
            mdi_area.close()

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

        self.assertEqual(len(plugin.save_window_dialog_service.calls), 1)
        self.assertIs(plugin.save_window_dialog_service.calls[0]["saveable"], table)
        self.assertTrue(table._closed)
        self.assertIsNone(workspace.lookup_table("Table0"))
        self.assertEqual(mdi_area.subWindowList(), [])

    def test_new_tables_keep_unique_handles_when_requested_names_conflict(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        first = workspace.open_table(["a"], name="Table0")
        second = workspace.open_table(["b"], name="Table0")

        self.assertEqual(first.window_handle(), "Table0")
        self.assertEqual(second.window_handle(), "Table1")
        self.assertEqual(first.parentWidget().objectName(), "Table0")
        self.assertEqual(second.parentWidget().objectName(), "Table1")
        self.assertEqual(first.parentWidget().windowTitle(), "Table0")
        self.assertEqual(second.parentWidget().windowTitle(), "Table1")

        workspace.clear()
        self._drain_events()

    def test_open_table_uses_stable_name_as_window_title(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(["a", "b"])

        self.assertEqual(table.window_handle(), "Table0")
        self.assertEqual(table.parentWidget().windowTitle(), "Table0")
        self.assertIn("name='Table0'", table.session_restore_source())

        workspace.clear()
        self._drain_events()

    def test_bind_subwindow_keeps_existing_object_name_as_table_identity(self):
        table = TableWidget("LegacyHandle", ["a"])
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(table)
        subwindow.setObjectName("Table7")

        try:
            table.bind_subwindow(subwindow)

            self.assertEqual(subwindow.objectName(), "Table7")
            self.assertEqual(table.window_handle(), "Table7")
            self.assertIn("name='Table7'", table.session_restore_source())
        finally:
            table.close()
            mdi_area.close()
            self._drain_events()

    def test_session_restore_source_uses_subwindow_object_name_as_table_identity(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(["a", "b"], name="Table_Fun")
        subwindow = table.parentWidget()
        subwindow.setObjectName("Table7")

        source = table.session_restore_source()

        self.assertEqual(table.window_handle(), "Table7")
        self.assertIn("def Table7(a, b):", source)
        self.assertIn("Table7(a, b)", source)
        self.assertIn("name='Table7'", source)

        workspace.clear()
        self._drain_events()

    def test_open_table_restores_minimized_state_from_kwarg(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(
            ["a"],
            name="Table_Fun",
            geometry=(5, 42, 510, 242),
            window_state="minimized",
        )
        self._drain_events()

        self.assertEqual(
            table.table_state.normalized_state()["settings"]["geometry"],
            (5, 42, 510, 242),
        )
        self.assertTrue(table.parentWidget().isMinimized())

        workspace.clear()
        mdi_area.close()
        self._drain_events()

    def test_open_table_restores_minimized_state_without_separate_titlebar_geometry(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)
        normal_geometry = (5, 42, 510, 242)

        table = workspace.open_table(
            ["a"],
            name="Table_Fun",
            geometry=normal_geometry,
            window_state="minimized",
        )
        subwindow = table.parentWidget()
        self._drain_events()

        self.assertTrue(subwindow.isMinimized())

        subwindow.showNormal()
        self._drain_events()

        self.assertEqual(
            [subwindow.geometry().x(), subwindow.geometry().y(), subwindow.geometry().width(), subwindow.geometry().height()],
            list(normal_geometry),
        )

        workspace.clear()
        mdi_area.close()
        self._drain_events()

    def test_capture_geometry_returns_last_normal_geometry_while_minimized(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)
        normal_geometry = (5, 42, 510, 242)

        table = workspace.open_table(
            ["a"],
            name="Table_Fun",
            geometry=normal_geometry,
        )
        subwindow = table.parentWidget()
        self._drain_events()

        subwindow.showMinimized()
        self._drain_events()

        self.assertEqual(table.capture_geometry(), list(normal_geometry))

        workspace.clear()
        mdi_area.close()
        self._drain_events()

    def test_open_table_requires_save_window_dialog_service(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "python_execution_service": FakeExecutionService(),
            "namespace_view_service": FakeNamespaceViewService(),
        }
        workspace = TableWorkspaceService(plugin)

        with self.assertRaises(KeyError):
            workspace.open_table(["a"])

    def test_table_plugin_session_routes_keep_tables_out_of_toml_and_emit_restore_source(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = Plugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "python_execution_service": FakeExecutionService(),
            "namespace_view_service": FakeNamespaceViewService(),
            "get_current_project_dir": lambda: "/tmp/demo.hy",
            "save_window_dialog_service": FakeSaveWindowDialogService(),
        }

        table = plugin.workspace.open_table(
            ["a", "b"],
            name="Table_Fun",
            geometry=(5, 42, 510, 242),
            column_widths={"a": 120, "b": 260},
        )
        table.ui.tableView.setColumnWidth(1, 120)
        table.ui.tableView.setColumnWidth(2, 260)
        table.capture_layout_state()
        subwindow = table.parentWidget()
        subwindow.show()
        self.qapp.processEvents()
        subwindow.showMinimized()
        self.qapp.processEvents()

        toml_data = plugin.get_session_toml_data()
        session_source = plugin.get_session_restore_source()

        self.assertEqual(toml_data, {})
        self.assertIn("def Table_Fun(a, b):", session_source)
        self.assertIn("Table_Fun(a, b)", session_source)
        self.assertIn("name='Table_Fun'", session_source)
        self.assertIn("geometry=(5, 42, 510, 242)", session_source)
        self.assertIn("column_widths={'a': 120, 'b': 260}", session_source)
        self.assertIn(
            "@hyde.table(window_state='minimized', register=False)",
            session_source,
        )
        self.assertNotIn("hidden=", session_source)
        self.assertNotIn("visible=", session_source)

        plugin.workspace.clear()
        mdi_area.close()

    def test_table_plugin_session_restore_source_preserves_minimized_metadata(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = Plugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "python_execution_service": FakeExecutionService(),
            "namespace_view_service": FakeNamespaceViewService(),
            "get_current_project_dir": lambda: "/tmp/demo.hy",
            "save_window_dialog_service": FakeSaveWindowDialogService(),
        }

        table = plugin.workspace.open_table(
            ["a", "b"],
            name="Table_Fun",
            geometry=(5, 42, 510, 242),
            column_widths={"a": 120, "b": 260},
        )
        table.parentWidget().show()
        self.qapp.processEvents()
        table.parentWidget().showMinimized()
        self.qapp.processEvents()

        session_source = plugin.get_session_restore_source()

        self.assertIn(
            "@hyde.table(window_state='minimized', register=False)",
            session_source,
        )

        plugin.workspace.clear()
        mdi_area.close()

    def test_table_session_restore_source_omits_minimized_geometry_and_macro_does_too(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = Plugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "python_execution_service": FakeExecutionService(),
            "namespace_view_service": FakeNamespaceViewService(),
            "get_current_project_dir": lambda: "/tmp/demo.hy",
            "save_window_dialog_service": FakeSaveWindowDialogService(),
        }

        table = plugin.workspace.open_table(
            ["a", "b"],
            name="Table_Fun",
            geometry=(5, 42, 510, 242),
            column_widths={"a": 120, "b": 260},
        )
        table.ui.tableView.setColumnWidth(1, 120)
        table.ui.tableView.setColumnWidth(2, 260)
        subwindow = table.parentWidget()
        subwindow.show()
        self.qapp.processEvents()
        subwindow.showMinimized()
        self.qapp.processEvents()

        session_source = table.session_restore_source()
        macro_source = table.macro_source("Table_Fun")

        self.assertIn("geometry=(5, 42, 510, 242)", session_source)
        self.assertIn(
            "@hyde.table(window_state='minimized', register=False)",
            session_source,
        )
        self.assertNotIn("geometry_minimized", session_source)
        self.assertNotIn("geometry_minimized", macro_source)

        plugin.workspace.clear()
        mdi_area.close()
        self._drain_events()

    def test_table_session_restore_source_preserves_maximized_metadata(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = Plugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "python_execution_service": FakeExecutionService(),
            "namespace_view_service": FakeNamespaceViewService(),
            "get_current_project_dir": lambda: "/tmp/demo.hy",
            "save_window_dialog_service": FakeSaveWindowDialogService(),
        }

        table = plugin.workspace.open_table(
            ["a", "b"],
            name="Table_Fun",
            geometry=(5, 42, 510, 242),
        )
        table.parentWidget().show()
        self.qapp.processEvents()
        table.parentWidget().showMaximized()
        self.qapp.processEvents()

        session_source = plugin.get_session_restore_source()

        self.assertIn(
            "@hyde.table(window_state='maximized', register=False)",
            session_source,
        )

        plugin.workspace.clear()
        mdi_area.close()

    def test_append_to_active_table_uses_append_table_api(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = Plugin({})
        execution = FakeExecutionService()
        plugin.services = {
            "mdi_area": mdi_area,
            "python_execution_service": execution,
            "namespace_view_service": FakeNamespaceViewService(),
            "get_current_project_dir": lambda: "/tmp/demo.hy",
            "save_window_dialog_service": FakeSaveWindowDialogService(),
        }

        table = plugin.workspace.open_table(["a"])
        subwindow = table.parentWidget()
        subwindow.setObjectName("Table7")

        plugin.workspace.on_subwindow_activated(subwindow)
        appended = plugin.table_feature.append_to_active_table(["b"])

        self.assertTrue(appended)
        self.assertEqual(len(execution.visible_calls), 1)
        self.assertEqual(
            execution.visible_calls[0],
            "hyde.append_table(b, name='Table7')",
        )

        plugin.workspace.clear()
        self._drain_events()

    def test_workspace_opens_minimized_table_window(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = FakeTablePlugin(mdi_area, save_result=True)
        workspace = TableWorkspaceService(plugin)

        table = workspace.open_table(["a"], window_state="minimized")
        self.qapp.processEvents()

        self.assertTrue(table.parentWidget().isMinimized())

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

        self.assertEqual(len(plugin.save_window_dialog_service.calls), 1)
        self.assertIs(plugin.save_window_dialog_service.calls[0]["saveable"], table)
        self.assertFalse(table._closed)
        self.assertIs(workspace.lookup_table("Table0"), table)
        self.assertIn(subwindow, mdi_area.subWindowList())

        workspace.clear()
        self._drain_events()


if __name__ == "__main__":
    unittest.main()
