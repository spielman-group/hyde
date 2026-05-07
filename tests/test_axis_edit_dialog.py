import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec, figure_ir_from_live_state
from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugin_tools import HydePluginManager
from hyde.user_interface.plugins.figure import Plugin as FigurePlugin
from hyde.user_interface.plugins.figure.window import FigureState, FigureWindow
from hyde.user_interface.plugins.figure_control_dialogs import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_control_dialogs.axis_edit_dialog import (
    AXIS_TAB_TITLES,
    AxisEditDialog,
)


_DEFAULT_FIGURE_IR = object()


def make_plugin_host(plugin_manager):
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
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
    app.process_tree = object()
    app.show_plugin_window = lambda key: key
    app.on_visible_command_executed = lambda message: message
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
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
    app.get_procedures_init = lambda: None
    app.get_shutting_down = lambda: False
    app.set_shutting_down = lambda value: value
    app.get_quit_command_sent = lambda: False
    app.set_quit_command_sent = lambda value: value
    app.begin_project_operation = lambda label: label
    app.project_target_needs_confirmation = lambda path: False
    app.confirm_overwrite_project = lambda path: False
    app.begin_shutdown_from_close_event = lambda: None
    app.finalize_quit = lambda: None
    app.reload_procedures = lambda: None
    app.on_kernel_ready = lambda: None
    app.on_kernel_crashed = lambda: None
    app.enter_no_project_state = lambda: None
    app.activate_project = lambda project_dir: project_dir
    app.on_project_state_result = lambda data: data
    app.request_gui_quit = lambda: None
    return app


def make_live_state(title="Figure0", items=("trace_a", "trace_b")):
    state = FigureState()
    state.set_title(title)
    state.set_x_name("x")
    state.set_items(list(items))
    return state.normalized_state()


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
            "zero_line": {
                "visible": True,
                "linestyle": "--",
                "linewidth": 2.0,
                "color": "#654321",
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
            "draw_between": (0.1, 0.9),
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
    subplot["axis_sides"]["left"].update(
        {
            "spine_width": 1.5,
        }
    )
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
    return FigureIRCodec.validate_state(figure_ir)


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
            "ticks": {
                "direction": "inside",
            },
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
    subplot["margins"].update(
        {
            "left": 0.125,
            "bottom": 0.11,
            "right": 0.9,
            "top": 0.88,
        }
    )
    return FigureIRCodec.validate_state(defaults)


def make_active_figure_window(
    mdi_area,
    services,
    figure_ir=_DEFAULT_FIGURE_IR,
    figure_defaults=None,
    resolved_axis_limits=None,
):
    services = dict(services)
    services.setdefault("send_figure_action", lambda figure_number, action: True)
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
                    make_figure_ir()
                    if figure_ir is _DEFAULT_FIGURE_IR
                    else figure_ir
                ),
                "figure_defaults": figure_defaults,
                "resolved_axis_limits": resolved_axis_limits,
                "live_state": None,
            },
        }
    )
    mdi_area.setActiveSubWindow(subwindow)
    return figure


class TestAxisEditPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_plugin_registers_modify_axis_action_in_figure_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "figure_control_dialogs": FigureControlPlugin({}),
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
            "figure_control_dialogs": FigureControlPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        make_active_figure_window(app.ui.mdiArea, manager.services)

        with patch.object(
            AxisEditDialog,
            "exec_",
            return_value=QtWidgets.QDialog.Accepted,
        ) as exec_:
            manager.services["lookup_menu_action"]("figure", "Modify Axis...").trigger()

        self.assertEqual(exec_.call_count, 1)

    def test_modify_axis_action_returns_false_without_active_figure(self):
        plugin = FigureControlPlugin({})
        plugin.services = {
            "mdi_area": QtWidgets.QMdiArea(),
            "ui": QtWidgets.QMainWindow(),
        }

        self.assertFalse(plugin.show_axis_edit_dialog())

    def test_modify_axis_action_requires_semantic_dispatch_for_active_figure(self):
        mdi_area = QtWidgets.QMdiArea()
        make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": None,
            },
        )
        plugin = FigureControlPlugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "ui": QtWidgets.QMainWindow(),
        }

        with patch.object(AxisEditDialog, "exec_") as exec_:
            self.assertFalse(plugin.show_axis_edit_dialog())

        self.assertEqual(exec_.call_count, 0)


class TestAxisEditDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_dialog_builds_broad_axis_shell_from_current_snapshot(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: True,
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            self.assertEqual(dialog.windowTitle(), "Modify Axis")
            self.assertEqual(
                [dialog.tab_widget.tabText(index) for index in range(dialog.tab_widget.count())],
                AXIS_TAB_TITLES,
            )
            self.assertEqual(
                [dialog.axis_selector.itemData(index) for index in range(dialog.axis_selector.count())],
                ["left", "bottom", "right", "top"],
            )
            self.assertEqual(dialog.axis_selector.currentData(), "bottom")
            self.assertTrue(dialog.live_update_checkbox.isChecked())
            self.assertFalse(dialog.help_button.isEnabled())
            self.assertEqual(dialog.axis_mode_combo.currentData(), "log2")
            self.assertEqual(dialog.log_tick_mode_combo.currentData(), "loglin")
            self.assertEqual(dialog.axis_label_edit.text(), "Delay")
            self.assertEqual(dialog.axis_label_preview.text(), "Delay")
            self.assertEqual(dialog.label_side_combo.currentData(), "mirror")
            self.assertEqual(dialog.label_position_mode_combo.currentData(), "manual")
            self.assertEqual(dialog.label_position_spin.value(), 0.35)
            self.assertEqual(dialog.label_offset_spin.value(), 14.0)
            self.assertEqual(dialog.label_rotation_spin.value(), 12.0)
            self.assertEqual(dialog.line_spacing_spin.value(), 1.6)
            self.assertEqual(dialog.axis_label_color_edit.text(), "#aa5500")
            self.assertEqual(dialog.axis_label_color_edit.swatch_color_text(), "#aa5500")
            self.assertEqual(dialog.autoscale_combo.currentData(), "tight")
            self.assertEqual(dialog.minimum_edit.text(), "1.0")
            self.assertEqual(dialog.maximum_edit.text(), "8.0")
            self.assertTrue(dialog.reverse_axis_checkbox.isChecked())
            self.assertFalse(dialog.side_visible_checkbox.isChecked())
            self.assertFalse(dialog.side_ticks_checkbox.isChecked())
            self.assertFalse(dialog.side_tick_labels_checkbox.isChecked())
            self.assertEqual(dialog.side_offset_spin.value(), 0.2)
            self.assertEqual(dialog.draw_between_min_spin.value(), 10.0)
            self.assertEqual(dialog.draw_between_max_spin.value(), 90.0)
            self.assertEqual(dialog.major_tick_mode_combo.currentData(), "manual")
            self.assertEqual(dialog.major_tick_positions_edit.text(), "1.0, 2.0, 4.0, 8.0")
            self.assertEqual(dialog.major_tick_labels_edit.text(), "1, 2, 4, 8")
            self.assertEqual(dialog.tick_direction_combo.currentData(), "both")
            self.assertEqual(dialog.formatter_style_combo.currentData(), "engineering")
            self.assertEqual(dialog.low_trip_spin.value(), -3.0)
            self.assertEqual(dialog.high_trip_spin.value(), 4.0)
            self.assertEqual(dialog.exponent_prescale_spin.value(), 3)
            self.assertTrue(dialog.use_thousands_separator_checkbox.isChecked())
            self.assertFalse(dialog.zero_as_zero_checkbox.isChecked())
            self.assertTrue(dialog.trim_trailing_zeros_checkbox.isChecked())
            self.assertTrue(dialog.trim_leading_zero_checkbox.isChecked())
            self.assertTrue(dialog.prefer_exponent_checkbox.isChecked())
            self.assertEqual(dialog.display_range_min_edit.text(), "0.5")
            self.assertEqual(dialog.display_range_max_edit.text(), "9.0")
            self.assertEqual(dialog.suppressed_values_edit.text(), "2.0, 8.0")
            self.assertEqual(dialog.max_log_cycles_minor_spin.value(), 5.0)
            self.assertEqual(dialog.max_log_cycles_minor_labels_spin.value(), 2.5)
            self.assertEqual(dialog.grid_which_combo.currentData(), "both")
            self.assertEqual(dialog.grid_style_combo.currentData(), "--")
            self.assertEqual(dialog.grid_width_spin.value(), 1.25)
            self.assertEqual(dialog.grid_color_edit.text(), "#123456")
            self.assertTrue(dialog.zero_line_visible_checkbox.isChecked())
            self.assertEqual(dialog.zero_line_style_combo.currentData(), ":")
            self.assertEqual(dialog.zero_line_width_spin.value(), 1.75)
            self.assertEqual(dialog.zero_line_color_edit.text(), "#335577")
            self.assertTrue(dialog.preview_pane.toPlainText())
            self.assertIn(
                "fig.subplots_adjust(left=0.12, bottom=0.2, right=0.97, top=0.98)",
                dialog.preview_pane.toPlainText(),
            )
        finally:
            dialog.close()

    def test_dialog_seeds_defaults_into_controls_and_replace_dispatch(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure_ir = figure_ir_from_live_state(make_live_state())
        subplot = figure_ir["layout"]["subplots"][0]
        subplot["axes"]["x"].update(
            {
                "label": {
                    "text": "Delay",
                    "visible": True,
                },
                "range": {
                    "reverse": True,
                },
            }
        )
        subplot["margins"].update({"bottom": 0.2})
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
            figure_ir=FigureIRCodec.validate_state(figure_ir),
            figure_defaults=make_figure_defaults(),
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            self.assertEqual(dialog.axis_label_edit.text(), "Delay")
            self.assertTrue(dialog.label_visible_checkbox.isChecked())
            self.assertEqual(dialog.label_offset_spin.value(), 9.0)
            self.assertEqual(dialog.label_rotation_spin.value(), 11.0)
            self.assertEqual(dialog.axis_label_color_edit.text(), "#654321")
            self.assertEqual(dialog.tick_direction_combo.currentData(), "inside")
            self.assertTrue(dialog.grid_visible_checkbox.isChecked())
            self.assertEqual(dialog.grid_width_spin.value(), 2.5)
            self.assertEqual(dialog.grid_color_edit.text(), "#123456")
            self.assertEqual(dialog.side_line_width_spin.value(), 3.0)
            self.assertEqual(dialog.side_color_edit.text(), "#abcdef")
            self.assertEqual(dialog.side_offset_spin.value(), 0.2)
            self.assertTrue(dialog.reverse_axis_checkbox.isChecked())

            dialog.axis_label_edit.setText("Delay [ms]")
            dialog.axis_label_edit.editingFinished.emit()
        finally:
            dialog.close()

        axis_actions = [action for _, action in sent if action["type"] == "set_axis_state"]
        side_actions = [
            action for _, action in sent if action["type"] == "set_axis_side_state"
        ]
        margin_actions = [
            action for _, action in sent if action["type"] == "set_subplot_margins"
        ]
        self.assertTrue(axis_actions)
        self.assertTrue(side_actions)
        self.assertTrue(margin_actions)
        self.assertEqual(axis_actions[-1]["state"]["label"]["offset"], 9.0)
        self.assertEqual(axis_actions[-1]["state"]["label"]["rotation"], 11.0)
        self.assertEqual(axis_actions[-1]["state"]["label"]["color"], "#654321")
        self.assertEqual(axis_actions[-1]["state"]["ticks"]["direction"], "inside")
        self.assertTrue(axis_actions[-1]["state"]["grid"]["visible"])
        self.assertEqual(axis_actions[-1]["state"]["grid"]["linewidth"], 2.5)
        self.assertEqual(axis_actions[-1]["state"]["grid"]["color"], "#123456")
        self.assertEqual(side_actions[-1]["state"]["spine_width"], 3.0)
        self.assertEqual(side_actions[-1]["state"]["spine_color"], "#abcdef")
        self.assertEqual(margin_actions[-1]["state"]["bottom"], 0.2)

    def test_label_visibility_defaults_checked_and_preview_changes_when_hidden(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: True,
            },
            figure_defaults=make_figure_defaults(),
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            self.assertTrue(dialog.label_visible_checkbox.isChecked())
            self.assertNotIn(
                "ax.xaxis.label.set_visible(False)",
                dialog.preview_pane.toPlainText(),
            )

            dialog.label_visible_checkbox.setChecked(False)

            self.assertIn(
                "ax.xaxis.label.set_visible(False)",
                dialog.preview_pane.toPlainText(),
            )
        finally:
            dialog.close()

    def test_side_visibility_controls_still_affect_preview_when_axis_has_label_text(self):
        mdi_area = QtWidgets.QMdiArea()
        figure_ir = FigureIRCodec.update_state(
            figure_ir_from_live_state(make_live_state()),
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {
                    "label": {
                        "text": "asdf",
                        "visible": True,
                        "side": "bottom",
                    }
                },
            },
        )
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: True,
            },
            figure_ir=figure_ir,
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.side_visible_checkbox.setChecked(False)
            dialog.side_ticks_checkbox.setChecked(False)
            dialog.side_tick_labels_checkbox.setChecked(False)

            preview = dialog.preview_pane.toPlainText()
            self.assertIn("ax.set_xlabel('asdf')", preview)
            self.assertIn("ax.spines['bottom'].set_visible(False)", preview)
            self.assertIn("bottom=False", preview)
            self.assertIn("labelbottom=False", preview)
        finally:
            dialog.close()

    def test_axis_selector_switches_between_mirrored_side_and_axis_state(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: True,
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.axis_selector.setCurrentIndex(dialog.axis_selector.findData("top"))
            self.assertEqual(dialog.axis_mode_combo.currentData(), "log2")
            self.assertEqual(dialog.axis_label_edit.text(), "Delay")
            self.assertTrue(dialog.side_visible_checkbox.isChecked())
            self.assertTrue(dialog.side_ticks_checkbox.isChecked())
            self.assertTrue(dialog.side_tick_labels_checkbox.isChecked())
            self.assertEqual(dialog.side_offset_spin.value(), 0.98)
            self.assertEqual(dialog.side_line_width_spin.value(), 2.5)
            self.assertTrue(dialog.draw_on_top_checkbox.isChecked())

            dialog.axis_selector.setCurrentIndex(dialog.axis_selector.findData("right"))
            self.assertEqual(dialog.axis_mode_combo.currentData(), "linear")
            self.assertEqual(dialog.axis_label_edit.text(), "Signal")
            self.assertEqual(dialog.label_side_combo.currentData(), "mirror")
            self.assertFalse(dialog.reverse_axis_checkbox.isChecked())
            self.assertTrue(dialog.side_visible_checkbox.isChecked())
            self.assertEqual(dialog.tick_label_rotation_spin.value(), 35.0)
            self.assertEqual(dialog.tick_label_offset_spin.value(), 4.5)
            self.assertEqual(dialog.side_color_edit.text(), "#ff00ff")
            self.assertEqual(dialog.tick_label_color_edit.text(), "#00aa00")
            self.assertIn("fig = plt.figure", dialog.preview_pane.toPlainText())
        finally:
            dialog.close()

    def test_live_update_dispatches_axis_and_side_state(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.axis_label_edit.setText("Delay [ms]")
            dialog.axis_label_edit.editingFinished.emit()
            dialog.side_visible_checkbox.setChecked(True)
        finally:
            dialog.close()

        self.assertEqual(len(sent), 6)
        self.assertEqual(sent[0][1]["type"], "set_axis_state")
        self.assertEqual(sent[0][1]["axis"], "x")
        self.assertEqual(sent[0][1]["state"]["label"]["text"], "Delay [ms]")
        self.assertTrue(sent[0][1]["replace"])
        self.assertEqual(sent[1][1]["type"], "set_axis_side_state")
        self.assertEqual(sent[1][1]["side"], "bottom")
        self.assertTrue(sent[1][1]["replace"])
        self.assertEqual(sent[2][1]["type"], "set_subplot_margins")
        self.assertEqual(sent[2][1]["state"]["bottom"], 0.2)
        self.assertEqual(sent[3][1]["type"], "set_axis_state")
        self.assertEqual(sent[4][1]["type"], "set_axis_side_state")
        self.assertEqual(sent[5][1]["type"], "set_subplot_margins")
        self.assertTrue(sent[4][1]["state"]["spine_visible"])

    def test_live_update_dispatches_extended_axis_state_fields(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.label_position_mode_combo.setCurrentIndex(
                dialog.label_position_mode_combo.findData("manual")
            )
            dialog.label_position_spin.setValue(0.6)
            dialog.axis_label_color_edit.setText("#111111")
            dialog.axis_label_color_edit.editingFinished.emit()
            dialog.major_tick_positions_edit.setText("1, 3, 9")
            dialog.major_tick_positions_edit.editingFinished.emit()
            dialog.major_tick_labels_edit.setText("one, three, nine")
            dialog.major_tick_labels_edit.editingFinished.emit()
            dialog.grid_style_combo.setCurrentIndex(dialog.grid_style_combo.findData(":"))
            dialog.zero_line_style_combo.setCurrentIndex(
                dialog.zero_line_style_combo.findData("--")
            )
        finally:
            dialog.close()

        axis_actions = [action for _, action in sent if action["type"] == "set_axis_state"]
        self.assertTrue(axis_actions)
        latest = axis_actions[-1]["state"]
        self.assertEqual(latest["label"]["position_mode"], "manual")
        self.assertEqual(latest["label"]["position"], 0.6)
        self.assertEqual(latest["label"]["color"], "#111111")
        self.assertEqual(latest["ticks"]["major"]["positions"], [1.0, 3.0, 9.0])
        self.assertEqual(latest["ticks"]["major"]["labels"], ["one", "three", "nine"])
        self.assertEqual(latest["grid"]["linestyle"], ":")
        self.assertEqual(latest["zero_line"]["linestyle"], "--")

    def test_axis_color_fields_accept_named_and_tuple_matplotlib_colors(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.axis_label_color_edit.setText("green")
            dialog.axis_label_color_edit.editingFinished.emit()
            self.assertEqual(dialog.axis_label_color_edit.text(), "#008000")
            self.assertEqual(dialog.axis_label_color_edit.swatch_color_text(), "#008000")

            dialog.grid_color_edit.setText("(0.4, 0.9, 1.0, 0.5)")
            dialog.grid_color_edit.editingFinished.emit()
            self.assertEqual(dialog.grid_color_edit.text(), "#66e6ff80")
            self.assertEqual(dialog.grid_color_edit.swatch_color_text(), "#66e6ff80")
        finally:
            dialog.close()

        axis_actions = [action for _, action in sent if action["type"] == "set_axis_state"]
        self.assertTrue(axis_actions)
        latest = axis_actions[-1]["state"]
        self.assertEqual(latest["label"]["color"], "#008000")
        self.assertEqual(latest["grid"]["color"], "#66e6ff80")

    def test_axis_color_swatch_opens_picker_and_commits_selected_color(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            swatch = dialog.axis_label_color_edit.findChild(QtWidgets.QToolButton)
            self.assertIsNotNone(swatch)

            with patch(
                "hyde.user_interface.matplotlib_color_picker.MatplotlibColorDialog.exec_",
                autospec=True,
                return_value=QtWidgets.QDialog.Accepted,
            ), patch(
                "hyde.user_interface.matplotlib_color_picker.MatplotlibColorDialog.selected_color_text",
                autospec=True,
                return_value="#112233",
            ):
                swatch.click()

            self.assertEqual(dialog.axis_label_color_edit.text(), "#112233")
            self.assertEqual(dialog.axis_label_color_edit.swatch_color_text(), "#112233")
        finally:
            dialog.close()

        axis_actions = [action for _, action in sent if action["type"] == "set_axis_state"]
        self.assertTrue(axis_actions)
        self.assertEqual(axis_actions[-1]["state"]["label"]["color"], "#112233")

    def test_preview_and_dispatch_support_mixed_auto_manual_range_modes(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.maximum_auto_checkbox.setChecked(True)
            dialog.minimum_edit.setText("0.5")
            dialog.minimum_edit.editingFinished.emit()
            self.assertIn("ax.autoscale(enable=True, axis='x')", dialog.preview_pane.toPlainText())
            self.assertIn("ax.set_xlim(left=0.5)", dialog.preview_pane.toPlainText())
        finally:
            dialog.close()

        axis_actions = [action for _, action in sent if action["type"] == "set_axis_state"]
        self.assertTrue(axis_actions)
        latest = axis_actions[-1]["state"]["range"]
        self.assertEqual(latest["limit_mode"], {"min": "manual", "max": "auto"})
        self.assertEqual(latest["limits"], (0.5, None))

    def test_set_to_autoscale_values_fills_numeric_bounds_and_sets_manual_modes(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
            resolved_axis_limits={"subplot0": {"x": (1.25, 9.75), "y": (-2.0, 3.0)}},
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            self.assertFalse(hasattr(dialog, "check_both_button"))
            self.assertFalse(hasattr(dialog, "uncheck_both_button"))

            dialog.set_autoscale_values_button.click()

            self.assertEqual(dialog.minimum_edit.text(), "1.25")
            self.assertEqual(dialog.maximum_edit.text(), "9.75")
            self.assertFalse(dialog.minimum_auto_checkbox.isChecked())
            self.assertFalse(dialog.maximum_auto_checkbox.isChecked())
            self.assertIn("ax.set_xlim(1.25, 9.75)", dialog.preview_pane.toPlainText())
        finally:
            dialog.close()

        axis_actions = [action for _, action in sent if action["type"] == "set_axis_state"]
        self.assertTrue(axis_actions)
        latest = axis_actions[-1]["state"]["range"]
        self.assertEqual(latest["limit_mode"], {"min": "manual", "max": "manual"})
        self.assertEqual(latest["limits"], (1.25, 9.75))

    def test_live_update_off_batches_until_do_it(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.live_update_checkbox.setChecked(False)
            dialog.axis_label_edit.setText("Delay [s]")
            dialog.axis_label_edit.editingFinished.emit()
            self.assertEqual(sent, [])
            dialog.do_it_button.click()
        finally:
            dialog.close()

        self.assertEqual(
            [action["type"] for _, action in sent],
            [
                "set_axis_state",
                "set_axis_state",
                "set_axis_side_state",
                "set_axis_side_state",
                "set_axis_side_state",
                "set_axis_side_state",
                "set_subplot_margins",
            ],
        )
        self.assertEqual(sent[0][1]["state"]["label"]["text"], "Delay [s]")
        bottom_side_actions = [
            action
            for _, action in sent
            if action["type"] == "set_axis_side_state" and action["side"] == "bottom"
        ]
        self.assertEqual(len(bottom_side_actions), 1)

    def test_cancel_restores_opening_snapshot_after_live_updates(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.axis_label_edit.setText("Delay [s]")
            dialog.axis_label_edit.editingFinished.emit()
            dialog.reject()
        finally:
            dialog.close()

        self.assertEqual(
            [action["type"] for _, action in sent[-7:]],
            [
                "set_axis_state",
                "set_axis_state",
                "set_axis_side_state",
                "set_axis_side_state",
                "set_axis_side_state",
                "set_axis_side_state",
                "set_subplot_margins",
            ],
        )
        self.assertEqual(sent[-7][1]["state"]["label"]["text"], "Delay")
        self.assertTrue(sent[-7][1]["replace"])

    def test_to_clip_copies_preview_source(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: True,
            },
        )

        dialog = AxisEditDialog(figure, parent=mdi_area)
        try:
            dialog.to_clip_button.click()
            clipboard = QtWidgets.QApplication.clipboard()
            self.assertIn("fig = plt.figure", clipboard.text())
        finally:
            dialog.close()
