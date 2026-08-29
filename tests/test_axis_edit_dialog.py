import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtWidgets

from tests.kernel_fakes import KernelRequestRecorder
from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.features.matplotlib_figure_state import FigureIRAuthority
from hyde.user_interface.main import HydeApp
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.plugins.figure_control_dialog import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_control_dialog.axis_edit_dialog import (
    AXIS_TAB_TITLES,
    AxisEditDialog,
)
from hyde.user_interface.plugins.figure_interactive import Plugin as FigurePlugin
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow
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
    app.clear_status_message = lambda: None
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
    subplot["axes"]["x"].update(
        {
            "scale_mode": "log2",
            "log_tick_mode": "loglin",
            "label": {
                "text": "Delay",
                "visible": True,
                "side": "top",
                "position_mode": "manual",
                "position": 0.35,
                "offset": 14.0,
                "rotation": 12.0,
                "line_spacing": 1.6,
                "color": "#aa5500",
            },
            "range": {
                "limits": (1.0, 8.0),
                "limit_mode": {"min": "manual", "max": "manual"},
                "autoscale": "tight",
                "reverse": True,
            },
            "ticks": {
                "major": {
                    "mode": "manual",
                    "count": 4,
                    "step": 2.0,
                    "positions": [1.0, 2.0, 4.0, 8.0],
                    "labels": ["1", "2", "4", "8"],
                },
                "minor": {"visible": True},
                "direction": "both",
                "formatter": {
                    "style": "engineering",
                    "low_trip": -3.0,
                    "high_trip": 4.0,
                    "exponent_prescale": 3.0,
                    "use_thousands_separator": True,
                    "zero_as_zero": False,
                    "trim_trailing_zeros": True,
                    "trim_leading_zero": True,
                    "prefer_exponent": True,
                },
                "suppressed_values": [2.0, 8.0],
                "display_range": (0.5, 9.0),
                "max_log_cycles_minor": 5.0,
                "max_log_cycles_minor_labels": 2.5,
            },
            "grid": {
                "visible": True,
                "which": "both",
                "linestyle": "--",
                "linewidth": 1.25,
                "color": "#123456",
            },
            "zero_line": {
                "visible": True,
                "linestyle": ":",
                "linewidth": 1.75,
                "color": "#335577",
            },
        }
    )
    subplot["axes"]["y"].update(
        {
            "label": {
                "text": "Signal",
                "visible": True,
                "side": "right",
            },
            "range": {
                "limits": (-2.5, 2.5),
                "limit_mode": {"min": "manual", "max": "manual"},
                "autoscale": "data",
                "reverse": False,
            },
        }
    )
    subplot["margins"].update(
        {
            "left": 0.12,
            "bottom": 0.2,
            "right": 0.97,
            "top": 0.98,
        }
    )
    subplot["axis_sides"]["bottom"].update(
        {
            "spine_visible": False,
            "ticks_visible": False,
            "tick_labels_visible": False,
            "offset": 12.0,
        }
    )
    subplot["axis_sides"]["top"].update(
        {
            "spine_visible": True,
            "ticks_visible": True,
            "tick_labels_visible": True,
            "spine_width": 2.5,
            "offset": 18.0,
            "draw_on_top": True,
        }
    )
    subplot["axis_sides"]["left"].update({"spine_width": 1.5})
    subplot["axis_sides"]["right"].update(
        {
            "spine_visible": True,
            "ticks_visible": True,
            "tick_labels_visible": True,
            "spine_color": "#ff00ff",
            "tick_label_color": "#00aa00",
            "tick_label_rotation": 35.0,
            "tick_label_offset": 4.5,
        }
    )
    return FigureIRAuthority.validate_state(figure_ir)


def make_figure_defaults():
    defaults = figure_ir_from_live_state(make_live_state())
    subplot = defaults["layout"]["subplots"][0]
    subplot["axes"]["x"].update(
        {
            "label": {
                "offset": 9.0,
                "rotation": 11.0,
                "color": "#654321",
            },
            "ticks": {"direction": "inside"},
            "grid": {
                "visible": True,
                "linewidth": 2.5,
                "color": "#123456",
            },
        }
    )
    subplot["axis_sides"]["bottom"].update(
        {
            "spine_width": 3.0,
            "spine_color": "#abcdef",
            "offset": 12.0,
        }
    )
    return FigureIRAuthority.validate_state(defaults)


def make_active_figure_window(
    mdi_area,
    services,
    figure_ir=_DEFAULT_FIGURE_IR,
    figure_defaults=None,
    resolved_axis_limits=None,
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
                "resolved_axis_limits": resolved_axis_limits,
                "live_state": None,
                "trace_styles": None,
            },
        }
    )
    mdi_area.setActiveSubWindow(subwindow)
    return figure


class TestAxisEditDialogPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_plugin_registers_modify_axis_action_in_figure_menu(self):
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

    def test_modify_axis_action_uses_active_figure_window(self):
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

        with patch.object(AxisEditDialog, "exec", new=record_exec):
            manager.services["lookup_menu_action"]("figure", "Modify Axis...").trigger()

        self.assertIsInstance(launched["dialog"], AxisEditDialog)
        self.assertIsNotNone(launched["dialog"].figure_context)

    def test_modify_axis_action_works_without_figure_action_service(self):
        execution = FakeExecutionService()
        terminal = FakeVisibleTerminalService()
        mdi_area = QtWidgets.QMdiArea()
        make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "figure_action_service": None,
                "python_execution_service": execution,
                "visible_terminal_service": terminal,
            },
        )
        plugin = FigureControlPlugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "ui": QtWidgets.QMainWindow(),
            "figure_context_service": type(
                "FigureContextService",
                (),
                {"active_editable_figure": lambda _self: None},
            )(),
        }
        figure = mdi_area.activeSubWindow().widget()
        plugin.services["figure_context_service"] = type(
            "FigureContextService",
            (),
            {"active_editable_figure": lambda _self: EditableFigureContext(figure)},
        )()

        with patch.object(AxisEditDialog, "exec", return_value=QtWidgets.QDialog.Accepted):
            self.assertTrue(plugin.show_axis_edit_dialog())


class TestAxisEditDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_dialog_builds_controls_from_current_snapshot(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            self.assertEqual(dialog.windowTitle(), "Modify Axis")
            self.assertEqual(
                [dialog.ui.tab_widget.tabText(index) for index in range(dialog.ui.tab_widget.count())],
                AXIS_TAB_TITLES,
            )
            self.assertEqual(dialog.ui.axis_selector.currentData(), "bottom")
            self.assertTrue(dialog.ui.live_update_checkbox.isChecked())
            self.assertEqual(dialog.ui.axis_mode_combo.currentData(), "log2")
            self.assertEqual(dialog.ui.axis_label_edit.text(), "Delay")
            self.assertEqual(dialog.ui.label_side_combo.currentData(), "mirror")
            self.assertEqual(dialog.ui.autoscale_combo.currentData(), "tight")
            self.assertEqual(dialog.ui.minimum_edit.text(), "1.0")
            self.assertEqual(dialog.ui.maximum_edit.text(), "8.0")
            self.assertFalse(dialog.ui.side_visible_checkbox.isChecked())
            self.assertEqual(dialog.lower_text_edit.toPlainText(), "")
        finally:
            dialog.close()

    def test_axis_dialog_exposes_shared_figure_dialog_state_contract(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = AxisEditDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            self.assertIsInstance(dialog.widget_ir, FigureDialogIR)
            self.assertIsInstance(dialog.widget_ir.opening_figure_ir, FigureIR)
            self.assertIsInstance(dialog.widget_ir.current_figure_ir, FigureIR)
            self.assertIsInstance(dialog.current_figure_ir, FigureIR)
            self.assertNotIn("initial_ir", vars(dialog))
            self.assertNotIn("current_ir", vars(dialog))
            self.assertEqual(
                dialog.supported_trace_records()[0]["trace_id"],
                "trace0",
            )
            self.assertEqual(
                [record["display_name"] for record in dialog.supported_trace_records()],
                ["trace_a: trace_a vs x", "trace_b: trace_b vs x"],
            )
            self.assertEqual(
                dialog.opening_effective_state()["settings"]["title"],
                "Figure0",
            )
            self.assertEqual(
                dialog.applied_effective_state()["settings"]["title"],
                "Figure0",
            )
            self.assertEqual(dialog.widget_ir.opening_figure_ir.default_macro_name(), "Figure0")
            self.assertEqual(dialog.widget_ir.current_figure_ir.default_macro_name(), "Figure0")
        finally:
            dialog.close()

    def test_preview_and_send_to_ipython_use_same_canonical_patch_block(self):
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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.live_update_checkbox.setChecked(False)
            dialog.ui.axis_label_edit.setText("Delay [s]")
            dialog.ui.axis_label_edit.editingFinished.emit()

            preview = dialog.lower_text_edit.toPlainText()
            self.assertEqual(dialog.widget_ir.current_figure_ir.axis_label("x"), "Delay [s]")
            self.assertEqual(
                preview,
                dialog.widget_ir.opening_figure_ir.current_diff(dialog.widget_ir.current_figure_ir)
                .as_patch("Figure0")
                .python_source(log=False),
            )
            self.assertIn("fig = hyde.get_figure('Figure0')", preview)
            self.assertIn("ax = fig.axes[0]", preview)
            self.assertIn("ax.set_xlabel('Delay [s]')", preview)
            self.assertNotIn("fig._hyde_ir", preview)
            self.assertNotIn("_figure_defaults_snapshot", preview)
            self.assertTrue(dialog.to_ipython_button.isEnabled())

            dialog.to_ipython_button.click()

            self.assertEqual(terminal.visible_calls[-1], preview)
            self.assertEqual(execution.hidden_calls, [])
        finally:
            dialog.close()

    def test_preview_uses_next_patch_block_after_live_update_has_applied(self):
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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.axis_label_edit.setText("Delay [ms]")
            dialog.ui.axis_label_edit.editingFinished.emit()
            self.assertTrue(execution.hidden_calls)
            self.assertIn("ax.set_xlabel('Delay [ms]')", execution.hidden_calls[-1][0])

            dialog.ui.live_update_checkbox.setChecked(False)
            dialog.ui.side_visible_checkbox.setChecked(True)

            preview = dialog.lower_text_edit.toPlainText()
            self.assertIn("ax.spines['bottom'].set_visible(True)", preview)
            self.assertNotIn("ax.set_xlabel('Delay [ms]')", preview)

            dialog.to_ipython_button.click()
            self.assertEqual(terminal.visible_calls[-1], preview)

            dialog.ok_button.click()
        finally:
            dialog.close()

        self.assertEqual(execution.hidden_calls[-1][0], preview)

    def test_live_applied_axis_state_keeps_last_patch_preview_and_ok_only_closes(self):
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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.axis_label_edit.setText("Delay [ms]")
            dialog.ui.axis_label_edit.editingFinished.emit()

            preview = dialog.lower_text_edit.toPlainText()
            self.assertIn("ax.set_xlabel('Delay [ms]')", preview)
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
        self.assertIn("ax.set_xlabel('Delay [ms]')", execution.hidden_calls[-1][0])

    def test_unsupported_log_tick_mode_change_shows_message_instead_of_blank_preview(self):
        execution = FakeExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
            figure_ir=make_figure_ir(),
        )

        dialog = AxisEditDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            self.assertEqual(dialog.ui.log_tick_mode_combo.currentData(), "loglin")

            dialog.ui.log_tick_mode_combo.setCurrentIndex(
                dialog.ui.log_tick_mode_combo.findData("plain")
            )

            self.assertEqual(
                dialog.lower_text_edit.toPlainText(),
                "Current changes are not yet representable as a Hyde figure command.",
            )
            self.assertEqual(execution.hidden_calls, [])
        finally:
            dialog.close()

    def test_live_update_executes_hidden_python_patch(self):
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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.axis_label_edit.setText("Delay [ms]")
            dialog.ui.axis_label_edit.editingFinished.emit()
            dialog.ui.side_visible_checkbox.setChecked(True)
        finally:
            dialog.close()

        self.assertTrue(execution.hidden_calls)
        emitted = "\n".join(code for code, _silent in execution.hidden_calls)
        self.assertIn("fig = hyde.get_figure('Figure0')", emitted)
        self.assertIn("ax.set_xlabel('Delay [ms]')", emitted)
        self.assertIn("ax.spines['bottom'].set_visible(True)", emitted)

    def test_extended_axis_patch_uses_standard_matplotlib_calls(self):
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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.live_update_checkbox.setChecked(False)
            dialog.ui.label_position_mode_combo.setCurrentIndex(
                dialog.ui.label_position_mode_combo.findData("manual")
            )
            dialog.ui.label_position_spin.setValue(0.6)
            dialog.ui.axis_label_color_edit.setText("#111111")
            dialog.ui.axis_label_color_edit.editingFinished.emit()
            dialog.ui.major_tick_positions_edit.setText("1, 3, 9")
            dialog.ui.major_tick_positions_edit.editingFinished.emit()
            dialog.ui.major_tick_labels_edit.setText("one, three, nine")
            dialog.ui.major_tick_labels_edit.editingFinished.emit()
            dialog.ui.grid_style_combo.setCurrentIndex(dialog.ui.grid_style_combo.findData(":"))
            dialog.ui.zero_line_style_combo.setCurrentIndex(
                dialog.ui.zero_line_style_combo.findData("--")
            )
            dialog.ok_button.click()
        finally:
            dialog.close()

        command = execution.hidden_calls[-1][0]
        self.assertIn("import matplotlib.ticker as mticker", command)
        self.assertIn("ax.xaxis.set_label_coords(0.6", command)
        self.assertIn("ax.xaxis.label.set_color('#111111')", command)
        self.assertIn("mticker.FixedLocator([1.0, 3.0, 9.0])", command)
        self.assertIn("mticker.FixedFormatter(['one', 'three', 'nine'])", command)
        self.assertIn("ax.grid(True, axis='x', which='both', linestyle=':'", command)
        self.assertIn("ax.axvline(0, linestyle='--'", command)

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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.live_update_checkbox.setChecked(False)
            dialog.ui.axis_label_edit.setText("Delay [s]")
            dialog.ui.axis_label_edit.editingFinished.emit()
            self.assertEqual(execution.hidden_calls, [])

            expected = dialog.lower_text_edit.toPlainText()
            dialog.ok_button.click()
        finally:
            dialog.close()

        self.assertEqual(len(execution.hidden_calls), 1)
        self.assertEqual(execution.hidden_calls[0][0], expected)

    def test_cancel_after_live_update_executes_python_rollback(self):
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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.axis_label_edit.setText("Delay [s]")
            dialog.ui.axis_label_edit.editingFinished.emit()
            dialog.reject()
        finally:
            dialog.close()

        self.assertEqual(len(execution.hidden_calls), 2)
        self.assertIn("ax.set_xlabel('Delay [s]')", execution.hidden_calls[0][0])
        self.assertIn("ax.set_xlabel('Delay')", execution.hidden_calls[1][0])

    def test_hidden_axis_patch_logs_through_transport_debug_channel(self):
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

        dialog = AxisEditDialog(EditableFigureContext(figure), services=figure.services, parent=mdi_area)
        try:
            dialog.ui.live_update_checkbox.setChecked(False)
            dialog.ui.axis_label_edit.setText("Delay [ms]")
            dialog.ui.axis_label_edit.editingFinished.emit()
            with self.assertLogs("hyde", level="DEBUG") as logs:
                dialog.ok_button.click()
        finally:
            dialog.close()

        output = "\n".join(logs.output)
        self.assertIn("[Hyde state] TransportDispatchState", output)
        self.assertIn("'mode': 'hidden'", output)
        self.assertIn("python:\n", output)
        self.assertIn("ax.set_xlabel('Delay [ms]')", output)
