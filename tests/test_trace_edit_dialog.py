import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtCore, QtWidgets

from tests.kernel_fakes import KernelRequestRecorder
from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.features.matplotlib_figure_state import FigureIRAuthority
from hyde.user_interface.main import HydeApp
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.plugins.figure_control_dialog import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_control_dialog.trace_edit_dialog import (
    TraceAppearanceDialog,
)
from hyde.user_interface.plugins.figure_interactive import Plugin as FigurePlugin
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow
from hyde.user_interface.plugins.remove_from_graph_dialog.dialogs import (
    RemoveFromGraphDialog,
)
from hyde.user_interface.shared.core import log_hyde_dispatch_debug
from hyde.user_interface.plugins.figure_control_dialog.figure_dialog_IR import (
    FigureDialogIR,
)
from hyde.user_interface.plugins.figure_interactive.context import EditableFigureContext
from hyde.user_interface.shared.plugin import HydePluginManager


_DEFAULT_FIGURE_IR = object()


class FakeExecutionService(KernelRequestRecorder):
    def __init__(self):
        self.hidden_calls = []

    def execute_hidden(self, code, silent=True):
        log_hyde_dispatch_debug("hidden", code)
        self.hidden_calls.append((str(code), bool(silent)))
        return True


class FakeVisibleTerminalService:
    def __init__(self):
        self.visible_calls = []

    def execute_visible(self, code):
        self.visible_calls.append(str(code))
        return True

def make_plugin_host(plugin_manager):
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
    main_window.menuEdit = main_window.menuBar().addMenu("Edit")
    main_window.menuAnalysis = main_window.menuBar().addMenu("Analysis")
    main_window.menuWindow = main_window.menuBar().addMenu("Windows")
    main_window.menuFigure = QtWidgets.QMenu("Figure", main_window.menuBar())
    main_window.menuTable = QtWidgets.QMenu("Table", main_window.menuBar())
    main_window.menuBar().addMenu(main_window.menuFigure)
    main_window.menuBar().addMenu(main_window.menuTable)
    main_window.mdiArea = QtWidgets.QMdiArea()
    main_window.setCentralWidget(main_window.mdiArea)

    app = type("DummyApp", (), {})()
    app.ui = main_window
    app.plugin_manager = plugin_manager
    app.configure_persistent_subwindow = lambda subwindow: None
    app.emit_plugin_event = lambda name, data=None: (name, data)
    app.show_status_message = lambda label: label
    app.show_transient_status_message = lambda label, timeout_ms: label
    app.clear_status_message = lambda label: None
    app.process_tree = object()
    app.show_plugin_window = lambda key: key
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
    app.get_current_app_ir = lambda: HydeAppIR(current_project_dir=None)
    app.lookup_menu_action = lambda location, name, path=(): (
        None
        if getattr(app, "menu_context", None) is None
        else app.menu_context.lookup_action(location, name, path=path)
    )
    app.show_menu = lambda location: HydeApp.show_menu(app, location)
    app.hide_menu = lambda location: HydeApp.hide_menu(app, location)
    app.popup_menu = lambda location, global_pos: HydeApp.popup_menu(
        app, location, global_pos
    )
    app.get_current_project_dir = lambda: None
    app.get_shutting_down = lambda: False
    app.set_shutting_down = lambda value: value
    app.get_quit_command_sent = lambda: False
    app.set_quit_command_sent = lambda value: value
    app.begin_project_operation = lambda label: label
    app.project_target_needs_confirmation = lambda path: False
    app.confirm_overwrite_project = lambda path: False
    app.begin_shutdown_from_close_event = lambda: None
    app.finalize_quit = lambda: None
    app.on_kernel_ready = lambda: None
    app.on_kernel_crashed = lambda: None
    app.enter_no_project_state = lambda: None
    app.activate_project = lambda project_dir: project_dir
    app.on_project_state_result = lambda data: data
    app.request_gui_quit = lambda: None
    return app


def make_live_state(title="Figure0", items=("trace_a", "trace_b")):
    return {
        "feature": "figure_command",
        "settings": {
            "command": "create",
            "title": title,
            "x_name": "x",
            "subplot_code": "111",
            "figsize": None,
        },
        "items": list(items),
        "ui": {},
    }


def make_figure_ir():
    figure_ir = figure_ir_from_live_state(make_live_state())
    subplot = figure_ir["layout"]["subplots"][0]
    subplot["traces"][0]["kwargs"].update(
        {
            "color": "#123456",
            "marker": "s",
            "linestyle": "--",
            "linewidth": 2.5,
            "alpha": 0.4,
            "markersize": 8.0,
        }
    )
    subplot["traces"][1]["kwargs"].update(
        {
            "marker": "o",
            "linestyle": "None",
        }
    )
    return FigureIRAuthority.validate_state(figure_ir)


def make_figure_defaults():
    defaults = figure_ir_from_live_state(make_live_state())
    subplot = defaults["layout"]["subplots"][0]
    subplot["traces"][0]["kwargs"].update(
        {
            "color": "#445566",
            "linestyle": "--",
            "linewidth": 4.0,
            "markersize": 9.0,
        }
    )
    subplot["traces"][1]["kwargs"].update(
        {
            "color": "#778899",
            "marker": "^",
            "linestyle": ":",
            "linewidth": 2.25,
        }
    )
    return FigureIRAuthority.validate_state(defaults)


def make_figure_ir_without_supported_traces():
    figure_ir = figure_ir_from_live_state(make_live_state(items=()))
    return FigureIRAuthority.validate_state(figure_ir)


def make_active_figure_window(
    mdi_area,
    services,
    figure_ir=_DEFAULT_FIGURE_IR,
    figure_defaults=None,
):
    services = dict(services)
    figure = FigureWindow(figure_number=7, services=services)
    subwindow = mdi_area.addSubWindow(figure)
    figure.bind_subwindow(subwindow)
    subwindow.show()
    figure.update_payload(
        {
            "figure_number": 7,
            "title": "Figure0",
            "snapshot": {
                "is_first_class": True,
                "figure_ir": (
                    make_figure_ir() if figure_ir is _DEFAULT_FIGURE_IR else figure_ir
                ),
                "figure_defaults": figure_defaults,
                "live_state": None,
                "trace_styles": None,
            },
        }
    )
    mdi_area.setActiveSubWindow(subwindow)
    return figure


class TestTraceAppearancePlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_plugin_registers_modify_data_appearance_action_in_figure_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "figure_control_dialog": FigureControlPlugin({}),
        }
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertEqual(
            [action.text() for action in app.ui.menuFigure.actions()],
            ["Modify Data Appearance...", "Modify Axis..."],
        )

    def test_modify_data_appearance_action_uses_active_figure_window(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "figure_control_dialog": FigureControlPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        make_active_figure_window(
            app.ui.mdiArea,
            {
                **manager.services,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        launched = {}

        def record_exec(dialog):
            launched["dialog"] = dialog
            return QtWidgets.QDialog.Accepted

        with patch.object(TraceAppearanceDialog, "exec", new=record_exec):
            manager.services["lookup_menu_action"](
                "figure", "Modify Data Appearance..."
            ).trigger()

        self.assertIsInstance(launched["dialog"], TraceAppearanceDialog)
        self.assertIsNotNone(launched["dialog"].figure_context)

    def test_modify_data_appearance_action_returns_false_without_supported_traces(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "figure_control_dialog": FigureControlPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        make_active_figure_window(
            app.ui.mdiArea,
            {
                **manager.services,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
            figure_ir=make_figure_ir_without_supported_traces(),
        )

        with patch.object(
            TraceAppearanceDialog,
            "exec",
            side_effect=AssertionError("Dialog should not execute without supported traces."),
        ):
            self.assertFalse(
                manager.plugins["figure_control_dialog"].show_trace_appearance_dialog()
            )


class TestTraceAppearanceDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_dialog_seeds_trace_list_and_controls_from_snapshot(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            self.assertIsInstance(dialog.widget_ir, FigureDialogIR)
            self.assertIsInstance(dialog.widget_ir.opening_figure_ir, FigureIR)
            self.assertIsInstance(dialog.widget_ir.current_figure_ir, FigureIR)
            self.assertEqual(dialog.ui.trace_list.count(), 2)
            self.assertEqual(
                dialog.ui.trace_list.currentItem().text(),
                "trace_a: trace_a vs x",
            )
            self.assertTrue(dialog.ui.live_update_checkbox.isChecked())
            self.assertEqual(dialog.ui.line_color_edit.text(), "#123456")
            self.assertEqual(dialog.ui.line_style_combo.currentData(), "--")
            self.assertEqual(dialog.ui.line_width_spin.value(), 2.5)
            self.assertEqual(dialog.ui.marker_combo.currentData(), "s")
            self.assertEqual(dialog.lower_text_edit.toPlainText(), "")
        finally:
            dialog.close()

    def test_trace_dialog_refresh_supported_trace_list_restores_selection_by_trace_id(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        extra_list = QtWidgets.QListWidget()
        extra_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        try:
            dialog.refresh_supported_trace_list(
                extra_list,
                selected_trace_ids=("trace0", "trace1"),
                current_trace_id="trace1",
            )

            self.assertEqual(
                [extra_list.item(index).text() for index in range(extra_list.count())],
                ["trace_a: trace_a vs x", "trace_b: trace_b vs x"],
            )
            self.assertEqual(
                dialog.selected_supported_trace_ids(extra_list),
                ("trace0", "trace1"),
            )
            self.assertEqual(
                dialog.current_supported_trace_id(extra_list),
                "trace1",
            )
        finally:
            extra_list.close()
            dialog.close()

    def test_trace_dialog_uses_canonical_supported_trace_rows_keyed_by_trace_id(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            expected_rows = dialog.supported_trace_records()
            self.assertEqual(
                [dialog.ui.trace_list.item(index).text() for index in range(dialog.ui.trace_list.count())],
                [row["display_name"] for row in expected_rows],
            )
            self.assertEqual(
                [
                    dialog.ui.trace_list.item(index).data(QtCore.Qt.UserRole)
                    for index in range(dialog.ui.trace_list.count())
                ],
                [row["trace_id"] for row in expected_rows],
            )
        finally:
            dialog.close()

    def test_trace_selection_surfaces_share_canonical_display_names(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        trace_dialog = TraceAppearanceDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        remove_dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            expected_names = [
                record["display_name"] for record in trace_dialog.supported_trace_records()
            ]

            self.assertEqual(
                [
                    trace_dialog.ui.trace_list.item(index).text()
                    for index in range(trace_dialog.ui.trace_list.count())
                ],
                expected_names,
            )
            self.assertEqual(
                [
                    remove_dialog.ui.trace_list.item(index).text()
                    for index in range(remove_dialog.ui.trace_list.count())
                ],
                expected_names,
            )
        finally:
            remove_dialog.close()
            trace_dialog.close()

    def test_live_applied_trace_state_keeps_last_patch_preview_and_ok_only_closes(self):
        execution = FakeExecutionService()
        terminal = FakeVisibleTerminalService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": terminal,
            },
        )

        dialog = TraceAppearanceDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.line_color_edit.setText("#abcdef")
            dialog.ui.line_color_edit.editingFinished.emit()

            preview = dialog.lower_text_edit.toPlainText()
            self.assertEqual(dialog.widget_ir.current_figure_ir.trace_style("trace0", "color"), "#abcdef")
            self.assertEqual(
                preview,
                dialog.widget_ir.opening_figure_ir.current_diff(dialog.widget_ir.current_figure_ir)
                .as_patch("Figure0")
                .python_source(log=False),
            )
            self.assertIn("line.set_color('#abcdef')", preview)
            self.assertNotIn("fig._hyde_ir", preview)
            self.assertNotIn("_figure_defaults_snapshot", preview)
            self.assertTrue(dialog.to_ipython_button.isEnabled())

            dialog.to_ipython_button.click()
            self.assertEqual(terminal.visible_calls[-1], preview)

            hidden_count = len(execution.hidden_calls)
            dialog.ok_button.click()
            self.assertEqual(len(execution.hidden_calls), hidden_count)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
        finally:
            dialog.close()

        self.assertTrue(execution.hidden_calls)
        self.assertIn("line.set_color('#abcdef')", execution.hidden_calls[-1][0])

    def test_live_update_reverting_trace_to_opening_state_clears_preview(self):
        execution = FakeExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            dialog.ui.line_color_edit.setText("#abcdef")
            dialog.ui.line_color_edit.editingFinished.emit()
            preview = dialog.lower_text_edit.toPlainText()
            self.assertIn("line.set_color('#abcdef')", preview)

            dialog.ui.line_color_edit.setText("#123456")
            dialog.ui.line_color_edit.editingFinished.emit()
            self.assertEqual(dialog.lower_text_edit.toPlainText(), "")
            self.assertEqual(dialog.preview_string(), "")
        finally:
            dialog.close()

    def test_trace_preview_does_not_remove_hidden_legend_for_style_only_edit(self):
        execution = FakeExecutionService()
        terminal = FakeVisibleTerminalService()
        mdi_area = QtWidgets.QMdiArea()
        single_trace_ir = figure_ir_from_live_state(make_live_state(items=("trace_a",)))
        single_trace_ir = FigureIRAuthority.validate_state(single_trace_ir)
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": terminal,
            },
            figure_ir=single_trace_ir,
        )

        dialog = TraceAppearanceDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            dialog.ui.line_color_edit.setText("#abcdef")
            dialog.ui.line_color_edit.editingFinished.emit()

            preview = dialog.lower_text_edit.toPlainText()
            self.assertIn("line.set_color('#abcdef')", preview)
            self.assertNotIn("ax.legend()", preview)
            self.assertNotIn("ax.get_legend()", preview)
        finally:
            dialog.close()

    def test_trace_dialog_seeds_from_figure_defaults(self):
        mdi_area = QtWidgets.QMdiArea()
        figure_ir = figure_ir_from_live_state(make_live_state())
        subplot = figure_ir["layout"]["subplots"][0]
        subplot["traces"][0]["kwargs"].update({"marker": "s", "linestyle": "None"})
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
            figure_ir=FigureIRAuthority.validate_state(figure_ir),
            figure_defaults=make_figure_defaults(),
        )

        dialog = TraceAppearanceDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            self.assertEqual(dialog.ui.line_color_edit.text(), "#445566")
            self.assertEqual(dialog.ui.line_width_spin.value(), 4.0)
            self.assertEqual(dialog.ui.marker_size_spin.value(), 9.0)
            self.assertEqual(dialog.ui.line_style_combo.currentData(), "None")
            self.assertEqual(dialog.ui.marker_combo.currentData(), "s")
        finally:
            dialog.close()

    def test_live_update_uses_hidden_python_patch(self):
        execution = FakeExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.mode_combo.setCurrentIndex(dialog.ui.mode_combo.findData("markers"))
        finally:
            dialog.close()

        self.assertTrue(execution.hidden_calls)
        command = execution.hidden_calls[-1][0]
        self.assertIn("line = ax.lines[0]", command)
        self.assertIn("line.set_linestyle('None')", command)

    def test_live_update_off_batches_until_ok(self):
        execution = FakeExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            dialog.ui.live_update_checkbox.setChecked(False)
            dialog.ui.line_color_edit.setText("#abcdef")
            dialog.ui.line_color_edit.editingFinished.emit()
            self.assertEqual(execution.hidden_calls, [])

            expected = dialog.lower_text_edit.toPlainText()
            dialog.ok_button.click()
        finally:
            dialog.close()

        self.assertEqual(len(execution.hidden_calls), 1)
        self.assertEqual(execution.hidden_calls[0][0], expected)

    def test_cancel_executes_python_rollback_for_touched_trace(self):
        execution = FakeExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.line_width_spin.setValue(4.0)
            dialog.reject()
        finally:
            dialog.close()

        self.assertEqual(len(execution.hidden_calls), 2)
        self.assertIn("line.set_linewidth(4.0)", execution.hidden_calls[0][0])
        self.assertIn("line.set_linewidth(2.5)", execution.hidden_calls[1][0])

    def test_hidden_trace_patch_logs_through_transport_debug_channel(self):
        execution = FakeExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = TraceAppearanceDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            with self.assertLogs("hyde", level="DEBUG") as logs:
                dialog.ui.line_color_edit.setText("#abcdef")
                dialog.ui.line_color_edit.editingFinished.emit()
        finally:
            dialog.close()

        output = "\n".join(logs.output)
        self.assertIn("[Hyde state] TransportDispatchState", output)
        self.assertIn("'mode': 'hidden'", output)
        self.assertIn("python:\n", output)
        self.assertIn("line.set_color('#abcdef')", output)
