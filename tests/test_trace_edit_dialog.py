import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hyde
import matplotlib
from matplotlib import colors as mcolors
from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec, figure_ir_from_live_state
from hyde.matplotlib_backend import apply_figure_action
from hyde.user_interface.main import HydeApp
from hyde.user_interface.shared.plugin import HydePluginManager
from hyde.user_interface.shared.figure import supported_trace_records_from_figure_ir
from hyde.user_interface.plugins.figure import Plugin as FigurePlugin
from hyde.user_interface.plugins.figure.window import FigureState, FigureWindow
from hyde.user_interface.plugins.figure_control_dialogs import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_control_dialogs.trace_edit_dialog import (
    TraceAppearanceDialog,
)


_DEFAULT_FIGURE_IR = object()


class FakeFigureActionService:
    def __init__(self, callback=None):
        self._callback = callback or (lambda figure_number, action: True)

    def request_figure_action(self, figure_number, action):
        return bool(self._callback(figure_number, action))


class FakeEditableFigureContext:
    def __init__(
        self,
        *,
        figure_number=7,
        figure_ir=_DEFAULT_FIGURE_IR,
        figure_defaults=None,
        trace_styles=None,
        request_action=None,
    ):
        self.figure_number = int(figure_number)
        self._figure_ir = (
            make_figure_ir() if figure_ir is _DEFAULT_FIGURE_IR else figure_ir
        )
        self._figure_defaults = figure_defaults
        self._trace_styles = {} if trace_styles is None else trace_styles
        self._request_action = request_action or (lambda action: True)

    def figure_ir(self):
        return self._figure_ir

    def figure_defaults(self):
        return self._figure_defaults

    def trace_styles(self):
        return self._trace_styles

    def supported_trace_records(self):
        return supported_trace_records_from_figure_ir(self.figure_ir())

    def has_supported_traces(self):
        return bool(self.supported_trace_records())

    def request_figure_action(self, action):
        return bool(self._request_action(dict(action or {})))


def make_figure_action_service(callback=None):
    return FakeFigureActionService(callback)


def make_plugin_host(plugin_manager):
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
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
    app.process_tree = object()
    app.show_plugin_window = lambda key: key
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
    state = FigureState()
    state.set_title(title)
    state.set_x_name("x")
    state.set_items(list(items))
    return state.normalized_state()


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
    return FigureIRCodec.validate_state(figure_ir)


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
    return FigureIRCodec.validate_state(defaults)


def make_figure_ir_without_supported_traces():
    figure_ir = figure_ir_from_live_state(make_live_state(items=()))
    return FigureIRCodec.validate_state(figure_ir)


def make_active_figure_window(
    mdi_area,
    services,
    figure_ir=_DEFAULT_FIGURE_IR,
    figure_defaults=None,
    trace_styles=None,
):
    services = dict(services)
    if "figure_action_service" not in services:
        send_figure_action = services.pop("send_figure_action", None)
        services["figure_action_service"] = make_figure_action_service(
            send_figure_action
        )
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
                "live_state": None,
                "trace_styles": trace_styles,
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
            "figure_control_dialogs": FigureControlPlugin({}),
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
            "figure_control_dialogs": FigureControlPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        make_active_figure_window(app.ui.mdiArea, manager.services)

        launched = {}

        def record_exec(dialog):
            launched["dialog"] = dialog
            return QtWidgets.QDialog.Accepted

        with patch.object(TraceAppearanceDialog, "exec_", new=record_exec):
            manager.services["lookup_menu_action"](
                "figure", "Modify Data Appearance..."
            ).trigger()

        self.assertIsInstance(launched["dialog"], TraceAppearanceDialog)
        self.assertIsNotNone(launched["dialog"].figure_context)

    def test_modify_data_appearance_action_returns_false_without_supported_traces(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "figure_control_dialogs": FigureControlPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        make_active_figure_window(
            app.ui.mdiArea,
            manager.services,
            figure_ir=make_figure_ir_without_supported_traces(),
        )

        with patch.object(
            TraceAppearanceDialog,
            "exec_",
            side_effect=AssertionError(
                "Dialog should not execute when no supported traces exist."
            ),
        ):
            self.assertFalse(
                manager.plugins["figure_control_dialogs"].show_trace_appearance_dialog()
            )

    def test_modify_data_appearance_action_returns_false_without_active_figure(self):
        plugin = FigureControlPlugin({})
        plugin.services = {
            "mdi_area": QtWidgets.QMdiArea(),
            "ui": QtWidgets.QMainWindow(),
        }

        self.assertFalse(plugin.show_trace_appearance_dialog())

    def test_modify_data_appearance_action_requires_semantic_dispatch_for_active_figure(
        self,
    ):
        mdi_area = QtWidgets.QMdiArea()
        make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "figure_action_service": None,
            },
        )
        plugin = FigureControlPlugin({})
        plugin.services = {
            "mdi_area": mdi_area,
            "ui": QtWidgets.QMainWindow(),
        }

        self.assertFalse(plugin.show_trace_appearance_dialog())

    def test_trace_dialog_dispatches_live_updates_through_figure_context_boundary(self):
        sent = []
        mdi_area = QtWidgets.QMdiArea()
        figure_context = FakeEditableFigureContext(
            request_action=lambda action: sent.append(dict(action or {})) or True
        )

        dialog = TraceAppearanceDialog(figure_context, parent=mdi_area)
        try:
            sent.clear()
            dialog.hide_trace_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            self.assertTrue(sent)
            self.assertEqual(sent[0]["type"], "set_trace_style")
        finally:
            dialog.close()


class TestTraceAppearanceDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_dialog_seeds_trace_list_and_controls_from_snapshot(self):
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

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            self.assertEqual(dialog.trace_list.count(), 2)
            self.assertEqual(dialog.trace_list.currentItem().text(), "trace_a")
            self.assertEqual(dialog.line_color_edit.text(), "#123456")
            self.assertEqual(dialog.marker_face_color_edit.text(), "auto")
            self.assertEqual(dialog.marker_face_color_edit.swatch_color_text(), "#123456")
            self.assertEqual(dialog.marker_edge_color_edit.swatch_color_text(), "#123456")
            self.assertEqual(dialog.line_style_combo.currentData(), "--")
            self.assertEqual(dialog.line_width_spin.value(), 2.5)
            self.assertEqual(dialog.marker_combo.currentData(), "s")
            self.assertEqual(dialog.mode_combo.currentData(), "lines+markers")
        finally:
            dialog.close()

    def test_dialog_uses_shared_shell_for_preview_and_footer_actions(self):
        clipboard = QtWidgets.QApplication.clipboard()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: True,
            },
        )

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            dialog.show()
            self.qapp.processEvents()

            self.assertFalse(hasattr(dialog, "button_box"))
            self.assertEqual(
                dialog.lower_text_edit.toPlainText(),
                dialog.canonical_text_payload(),
            )
            self.assertIn("fig = plt.figure(", dialog.lower_text_edit.toPlainText())
            self.assertIn("ax.plot(", dialog.lower_text_edit.toPlainText())
            self.assertFalse(dialog.to_cmd_line_button.isEnabled())
            self.assertTrue(dialog.to_cmd_line_button.isVisibleTo(dialog))
            self.assertTrue(dialog.to_clip_button.isEnabled())

            dialog.to_clip_button.click()

            self.assertEqual(
                clipboard.text(),
                dialog.lower_text_edit.toPlainText(),
            )
        finally:
            dialog.close()

    def test_dialog_seeds_from_figure_defaults_before_current_trace_state(self):
        mdi_area = QtWidgets.QMdiArea()
        figure_ir = figure_ir_from_live_state(make_live_state())
        subplot = figure_ir["layout"]["subplots"][0]
        subplot["traces"][0]["kwargs"].update(
            {
                "marker": "s",
                "linestyle": "None",
            }
        )
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "send_figure_action": lambda figure_number, action: True,
            },
            figure_ir=FigureIRCodec.validate_state(figure_ir),
            figure_defaults=make_figure_defaults(),
            trace_styles=None,
        )

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            self.assertEqual(dialog.line_color_edit.text(), "#445566")
            self.assertEqual(dialog.line_width_spin.value(), 4.0)
            self.assertEqual(dialog.marker_size_spin.value(), 9.0)
            self.assertEqual(dialog.line_style_combo.currentData(), "None")
            self.assertEqual(dialog.marker_combo.currentData(), "s")
            self.assertEqual(dialog.mode_combo.currentData(), "markers")
        finally:
            dialog.close()

    def test_dialog_sends_live_trace_style_updates(self):
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

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            dialog.line_color_edit.setText("#abcdef")
            dialog.line_color_edit.editingFinished.emit()
            dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData("markers"))
        finally:
            dialog.close()

        self.assertEqual(
            sent,
            [
                (
                    7,
                    {
                        "type": "set_trace_style",
                        "subplot_id": "subplot0",
                        "trace_id": "trace0",
                        "style": {"color": "#abcdef"},
                    },
                ),
                (
                    7,
                    {
                        "type": "set_trace_style",
                        "subplot_id": "subplot0",
                        "trace_id": "trace0",
                        "style": {"marker": "s", "linestyle": "None"},
                    },
                ),
            ],
        )
        self.assertEqual(dialog.line_style_combo.currentData(), "None")
        self.assertEqual(dialog.marker_combo.currentData(), "s")

    def test_dialog_accepts_named_matplotlib_line_color(self):
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

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            dialog.line_color_edit.setText("green")
            dialog.line_color_edit.editingFinished.emit()
            self.assertEqual(dialog.line_color_edit.text(), "#008000")
            self.assertEqual(dialog.marker_face_color_edit.swatch_color_text(), "#008000")
        finally:
            dialog.close()

        self.assertEqual(
            sent[-1],
            (
                7,
                {
                    "type": "set_trace_style",
                    "subplot_id": "subplot0",
                    "trace_id": "trace0",
                    "style": {"color": "#008000"},
                },
            ),
        )

    def test_invalid_line_color_input_reverts_without_dispatching(self):
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

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            dialog.line_color_edit.setText("not-a-color")
            dialog.line_color_edit.editingFinished.emit()
            self.assertEqual(dialog.line_color_edit.text(), "#123456")
        finally:
            dialog.close()

        self.assertEqual(sent, [])

    def test_cancel_reverts_each_touched_trace_to_opening_style_snapshot(self):
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

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            dialog.line_width_spin.setValue(4.0)
            dialog.trace_list.setCurrentRow(1)
            dialog.marker_combo.setCurrentIndex(dialog.marker_combo.findData("^"))
            dialog.reject()
        finally:
            dialog.close()

        self.assertEqual(
            sent,
            [
                (
                    7,
                    {
                        "type": "set_trace_style",
                        "subplot_id": "subplot0",
                        "trace_id": "trace0",
                        "style": {"linewidth": 4.0},
                    },
                ),
                (
                    7,
                    {
                        "type": "set_trace_style",
                        "subplot_id": "subplot0",
                        "trace_id": "trace1",
                        "style": {"marker": "^"},
                    },
                ),
                (
                    7,
                    {
                        "type": "set_trace_style",
                        "subplot_id": "subplot0",
                        "trace_id": "trace0",
                        "style": {
                            "visible": True,
                            "linestyle": "--",
                            "linewidth": 2.5,
                            "alpha": 0.4,
                            "drawstyle": "default",
                            "marker": "s",
                            "markersize": 8.0,
                            "markerfacecolor": "auto",
                            "markeredgecolor": "auto",
                            "markeredgewidth": 1.0,
                            "color": "#123456",
                        },
                        "replace": True,
                    },
                ),
                (
                    7,
                    {
                        "type": "set_trace_style",
                        "subplot_id": "subplot0",
                        "trace_id": "trace1",
                        "style": {
                            "visible": True,
                            "linestyle": "None",
                            "linewidth": 1.5,
                            "alpha": 1.0,
                            "drawstyle": "default",
                            "marker": "o",
                            "markersize": 6.0,
                            "markerfacecolor": "auto",
                            "markeredgecolor": "auto",
                            "markeredgewidth": 1.0,
                            "color": "#ff7f0e",
                        },
                        "replace": True,
                    },
                ),
            ],
        )

    def test_apply_keeps_live_updates_without_reverting_opening_snapshot(self):
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

        dialog = TraceAppearanceDialog(figure, parent=mdi_area)
        try:
            dialog.line_width_spin.setValue(4.0)
            dialog.accept()
        finally:
            dialog.close()

        self.assertEqual(
            sent,
            [
                (
                    7,
                    {
                        "type": "set_trace_style",
                        "subplot_id": "subplot0",
                        "trace_id": "trace0",
                        "style": {"linewidth": 4.0},
                    },
                ),
            ],
        )


class TestTraceAppearanceBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def tearDown(self):
        pyplot = getattr(matplotlib, "pyplot", None)
        if pyplot is not None:
            pyplot.close("all")

    def _configure_pyplot(self):
        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as pyplot

        return pyplot

    def test_apply_figure_action_supports_extended_trace_style_properties(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        apply_figure_action(
            figure,
            {
                "type": "set_trace_style",
                "subplot_id": "subplot0",
                "trace_id": "trace0",
                "style": {
                    "visible": False,
                    "alpha": 0.4,
                    "drawstyle": "steps-mid",
                    "markersize": 9.0,
                    "markerfacecolor": "#abcdef",
                    "markeredgecolor": "#fedcba",
                    "markeredgewidth": 2.0,
                },
            },
        )

        trace = figure._hyde_ir["layout"]["subplots"][0]["traces"][0]
        line = figure.axes[0].lines[0]

        self.assertFalse(trace["kwargs"]["visible"])
        self.assertEqual(trace["kwargs"]["drawstyle"], "steps-mid")
        self.assertEqual(trace["kwargs"]["markersize"], 9.0)
        self.assertEqual(trace["kwargs"]["markeredgewidth"], 2.0)
        self.assertFalse(line.get_visible())
        self.assertEqual(line.get_alpha(), 0.4)
        self.assertEqual(line.get_drawstyle(), "steps-mid")
        self.assertEqual(line.get_markersize(), 9.0)
        self.assertEqual(mcolors.to_hex(line.get_markerfacecolor()), "#abcdef")
        self.assertEqual(mcolors.to_hex(line.get_markeredgecolor()), "#fedcba")
        self.assertEqual(line.get_markeredgewidth(), 2.0)

    def test_replace_trace_style_restores_original_ir_backed_trace_style(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        apply_figure_action(
            figure,
            {
                "type": "set_trace_style",
                "subplot_id": "subplot0",
                "trace_id": "trace0",
                "style": {"color": "#abcdef", "marker": "s", "linewidth": 3.0},
            },
        )
        apply_figure_action(
            figure,
            {
                "type": "set_trace_style",
                "subplot_id": "subplot0",
                "trace_id": "trace0",
                "style": {"label": "y"},
                "replace": True,
            },
        )

        trace = figure._hyde_ir["layout"]["subplots"][0]["traces"][0]
        line = figure.axes[0].lines[0]

        self.assertEqual(trace["kwargs"], {"label": "y"})
        self.assertEqual(line.get_label(), "y")
        self.assertNotEqual(mcolors.to_hex(line.get_color()), "#abcdef")
        self.assertIn(line.get_marker(), ("None", "none", None, ""))
        self.assertNotEqual(line.get_linewidth(), 3.0)

if __name__ == "__main__":
    unittest.main()
