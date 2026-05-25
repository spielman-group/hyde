import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import matplotlib
    matplotlib.use("Agg")
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

import hyde

from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec, figure_ir_from_live_state
from hyde.matplotlib_backend import figure_snapshot_payload
from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugins.figure_control_dialog import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_control_dialog.trace_edit_dialog import (
    TraceAppearanceDialog,
)
from hyde.user_interface.plugins.figure_interactive import Plugin as FigurePlugin
from hyde.user_interface.plugins.figure_interactive.window import FigureState, FigureWindow
from hyde.user_interface.plugins.remove_from_graph_dialog import Plugin as RemoveFromGraphPlugin
from hyde.user_interface.plugins.remove_from_graph_dialog.dialogs import (
    RemoveFromGraphDialog,
)
from hyde.user_interface.shared.figure import EditableFigureContext
from hyde.user_interface.shared.plugin import HydePluginManager


_DEFAULT_FIGURE_IR = object()


class FakeExecutionService:
    def __init__(self):
        self.hidden_calls = []

    def execute_hidden(self, code, silent=True):
        self.hidden_calls.append((str(code), bool(silent)))
        return True


class EvaluatingExecutionService(FakeExecutionService):
    def execute_hidden(self, code, silent=True):
        super().execute_hidden(code, silent=silent)
        exec(str(code), {"__builtins__": __builtins__, "hyde": hyde}, {})
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
    return FigureIRCodec.validate_state(figure_ir_from_live_state(make_live_state()))


def make_figure_ir_without_supported_traces():
    return FigureIRCodec.validate_state(figure_ir_from_live_state(make_live_state(items=())))


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


def make_live_first_class_figure():
    matplotlib.use("module://hyde.matplotlib_backend", force=True)
    import matplotlib.pyplot as live_pyplot

    @hyde.figure(register=False)
    def Figure0(x, trace_a, trace_b):
        fig = live_pyplot.figure("Figure0")
        ax = fig.add_subplot(111)
        ax.plot(x, trace_a, label="trace_a")
        ax.plot(x, trace_b, label="trace_b")
        return fig

    figure = Figure0([0, 1, 2], [1, 4, 9], [9, 4, 1])
    return figure, figure_snapshot_payload(figure, 7)


class TestRemoveFromGraphPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_plugin_registers_remove_from_graph_first_in_figure_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "figure_control_dialog": FigureControlPlugin({}),
            "remove_from_graph_dialog": RemoveFromGraphPlugin({}),
        }
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertEqual(
            [action.text() for action in app.ui.menuFigure.actions()],
            ["Remove from Graph...", "Modify Data Appearance...", "Modify Axis..."],
        )

    def test_remove_from_graph_action_opens_even_without_supported_traces(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "figure_control_dialog": FigureControlPlugin({}),
            "remove_from_graph_dialog": RemoveFromGraphPlugin({}),
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

        launched = {}

        def record_exec(dialog):
            launched["dialog"] = dialog
            return QtWidgets.QDialog.Accepted

        with patch.object(RemoveFromGraphDialog, "exec_", new=record_exec):
            manager.services["lookup_menu_action"](
                "figure", "Remove from Graph..."
            ).trigger()

        self.assertIsInstance(launched["dialog"], RemoveFromGraphDialog)
        self.assertEqual(launched["dialog"].ui.trace_list.count(), 0)


class TestRemoveFromGraphDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def tearDown(self):
        import matplotlib.pyplot as pyplot

        pyplot.close("all")

    def test_dialog_handles_empty_supported_trace_list(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
            figure_ir=make_figure_ir_without_supported_traces(),
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            self.assertEqual(dialog.ui.trace_list.count(), 0)
            self.assertIsNone(dialog.ui.trace_list.currentItem())
            self.assertEqual(
                dialog.selected_supported_trace_ids(dialog.ui.trace_list),
                (),
            )
            self.assertEqual(
                dialog.lower_text_edit.toPlainText(),
                "No supported traces available to remove.",
            )
            self.assertFalse(dialog.do_it_button.isEnabled())
            self.assertFalse(dialog.to_cmd_line_button.isEnabled())
            self.assertFalse(dialog.to_clip_button.isEnabled())
        finally:
            dialog.close()

    def test_dialog_opens_with_no_initial_selection_and_uses_one_preview_string(self):
        terminal = FakeVisibleTerminalService()
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": terminal,
            },
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            self.assertEqual(dialog.ui.trace_list.count(), 2)
            self.assertIsNone(dialog.ui.trace_list.currentItem())
            self.assertEqual(
                dialog.selected_supported_trace_ids(dialog.ui.trace_list),
                (),
            )
            self.assertEqual(
                dialog.lower_text_edit.toPlainText(),
                "Select one or more traces to remove.",
            )
            self.assertFalse(dialog.do_it_button.isEnabled())

            dialog.ui.trace_list.item(0).setSelected(True)
            dialog.ui.trace_list.item(1).setSelected(True)
            self.qapp.processEvents()

            preview = dialog.preview_string()
            self.assertEqual(dialog.lower_text_edit.toPlainText(), preview)
            self.assertIn("fig = hyde.get_figure('Figure0')", preview)
            self.assertIn("hyde.remove_traces(fig, 'trace0', 'trace1')", preview)
            self.assertNotIn("fig._hyde_ir", preview)
            self.assertNotIn("_figure_defaults_snapshot", preview)
            self.assertNotIn("ax.legend()", preview)
            self.assertNotIn("ax.get_legend()", preview)
            self.assertTrue(dialog.do_it_button.isEnabled())
            self.assertTrue(dialog.to_cmd_line_button.isEnabled())
            self.assertTrue(dialog.to_clip_button.isEnabled())

            dialog.to_cmd_line_button.click()
            self.assertEqual(terminal.visible_calls, [preview])

            dialog.to_clip_button.click()
            self.assertEqual(
                QtWidgets.QApplication.clipboard().text(),
                preview,
            )
        finally:
            dialog.close()

    def test_do_it_removes_selected_traces_from_live_first_class_figure(self):
        live_figure, snapshot = make_live_first_class_figure()
        execution = EvaluatingExecutionService()
        terminal = FakeVisibleTerminalService()
        mdi_area = QtWidgets.QMdiArea()
        figure_window = FigureWindow(
            figure_number=7,
            services={
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": terminal,
            },
        )
        subwindow = mdi_area.addSubWindow(figure_window)
        figure_window.bind_subwindow(subwindow)
        subwindow.show()
        figure_window.update_payload(
            {
                "figure_number": 7,
                "title": "Figure0",
                "snapshot": snapshot,
            }
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure_window),
            services=figure_window.services,
            parent=mdi_area,
        )
        try:
            self.assertEqual(len(live_figure.axes[0].lines), 2)
            dialog.ui.trace_list.item(0).setSelected(True)
            self.qapp.processEvents()

            expected_command = dialog.preview_string()
            dialog.do_it_button.click()

            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
            self.assertEqual(execution.hidden_calls[-1][0], expected_command)
            self.assertEqual(len(live_figure.axes[0].lines), 1)
            self.assertEqual(
                [line.get_label() for line in live_figure.axes[0].lines],
                ["trace_b"],
            )
            self.assertEqual(
                [getattr(line, "_hyde_trace_id", None) for line in live_figure.axes[0].lines],
                ["trace1"],
            )
            self.assertEqual(
                tuple(
                    trace["id"]
                    for trace in live_figure._hyde_ir["layout"]["subplots"][0]["traces"]
                ),
                ("trace1",),
            )
            self.assertEqual(
                tuple(
                    trace["id"]
                    for trace in figure_snapshot_payload(live_figure, 7)["figure_ir"][
                        "layout"
                    ]["subplots"][0]["traces"]
                ),
                ("trace1",),
            )
        finally:
            dialog.close()
            live_figure.canvas.manager.destroy()

    def test_backend_payload_after_remove_unblocks_next_trace_dialog(self):
        live_figure, snapshot = make_live_first_class_figure()
        execution = EvaluatingExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure_window = FigureWindow(
            figure_number=7,
            services={
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )
        subwindow = mdi_area.addSubWindow(figure_window)
        figure_window.bind_subwindow(subwindow)
        subwindow.show()
        figure_window.update_payload(
            {
                "figure_number": 7,
                "title": "Figure0",
                "snapshot": snapshot,
            }
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure_window),
            services=figure_window.services,
            parent=mdi_area,
        )
        try:
            dialog.ui.trace_list.item(0).setSelected(True)
            self.qapp.processEvents()
            dialog.do_it_button.click()

            figure_window.update_payload(
                {
                    "figure_number": 7,
                    "title": "Figure0",
                    "snapshot": figure_snapshot_payload(live_figure, 7),
                }
            )

            trace_dialog = TraceAppearanceDialog(
                EditableFigureContext(figure_window),
                services=figure_window.services,
                parent=mdi_area,
            )
            try:
                self.assertEqual(trace_dialog.ui.trace_list.count(), 1)
                self.assertEqual(
                    trace_dialog.ui.trace_list.item(0).text(),
                    "trace_b: trace_b vs x",
                )
                self.assertEqual(
                    trace_dialog.supported_trace_records()[0]["trace_id"],
                    "trace1",
                )
            finally:
                trace_dialog.close()
        finally:
            dialog.close()
            live_figure.canvas.manager.destroy()

    def test_do_it_refreshes_existing_live_legend(self):
        live_figure, snapshot = make_live_first_class_figure()
        live_figure.axes[0].legend()
        execution = EvaluatingExecutionService()
        mdi_area = QtWidgets.QMdiArea()
        figure_window = FigureWindow(
            figure_number=7,
            services={
                "mdi_area": mdi_area,
                "python_execution_service": execution,
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )
        subwindow = mdi_area.addSubWindow(figure_window)
        figure_window.bind_subwindow(subwindow)
        subwindow.show()
        figure_window.update_payload(
            {
                "figure_number": 7,
                "title": "Figure0",
                "snapshot": snapshot,
            }
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure_window),
            services=figure_window.services,
            parent=mdi_area,
        )
        try:
            self.assertIsNotNone(live_figure.axes[0].get_legend())
            dialog.ui.trace_list.item(0).setSelected(True)
            self.qapp.processEvents()

            dialog.do_it_button.click()

            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
            self.assertIsNotNone(live_figure.axes[0].get_legend())
            self.assertEqual(
                [text.get_text() for text in live_figure.axes[0].get_legend().get_texts()],
                ["trace_b"],
            )
        finally:
            dialog.close()
            live_figure.canvas.manager.destroy()

    def test_figure_session_remove_traces_is_a_first_class_mutation(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        session = figure.open_edit_session()
        opening_state = session.opening_effective_state()

        session.remove_traces(("trace1", "trace0"))

        self.assertEqual(session.trace_ids(), ())
        self.assertEqual(session.supported_trace_records(), ())
        self.assertEqual(
            session.current_effective_state()["layout"]["subplots"][0]["traces"],
            [],
        )
        self.assertEqual(
            [trace["id"] for trace in opening_state["layout"]["subplots"][0]["traces"]],
            ["trace0", "trace1"],
        )

    def test_valid_regex_filter_updates_visible_trace_list_live(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            self.assertEqual(dialog.ui.trace_list.count(), 2)

            dialog.ui.filter_edit.setText("trace_b")
            self.qapp.processEvents()

            self.assertEqual(dialog.ui.trace_list.count(), 1)
            self.assertEqual(
                dialog.ui.trace_list.item(0).text(),
                "trace_b: trace_b vs x",
            )
            self.assertEqual(
                dialog.lower_text_edit.toPlainText(),
                "Select one or more traces to remove.",
            )
        finally:
            dialog.close()

    def test_invalid_regex_shows_error_and_leaves_current_filtered_list_unchanged(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            dialog.ui.trace_list.item(0).setSelected(True)
            dialog.ui.filter_edit.setText("trace_a")
            self.qapp.processEvents()

            expected_preview = dialog.preview_string()
            expected_row_text = dialog.ui.trace_list.item(0).text()

            dialog.ui.filter_edit.setText("[")
            self.qapp.processEvents()

            self.assertEqual(dialog.ui.trace_list.count(), 1)
            self.assertEqual(dialog.ui.trace_list.item(0).text(), expected_row_text)
            self.assertEqual(dialog.preview_string(), expected_preview)
            self.assertIn(
                "Invalid regex:",
                dialog.lower_text_edit.toPlainText(),
            )
            self.assertTrue(dialog.do_it_button.isEnabled())
            self.assertTrue(dialog.to_cmd_line_button.isEnabled())
            self.assertTrue(dialog.to_clip_button.isEnabled())
        finally:
            dialog.close()

    def test_valid_filter_drops_hidden_selection_and_preserves_visible_selection(self):
        mdi_area = QtWidgets.QMdiArea()
        figure = make_active_figure_window(
            mdi_area,
            {
                "mdi_area": mdi_area,
                "python_execution_service": FakeExecutionService(),
                "visible_terminal_service": FakeVisibleTerminalService(),
            },
        )

        dialog = RemoveFromGraphDialog(
            EditableFigureContext(figure),
            services=figure.services,
            parent=mdi_area,
        )
        try:
            dialog.ui.trace_list.item(0).setSelected(True)
            dialog.ui.trace_list.item(1).setSelected(True)
            self.qapp.processEvents()

            dialog.ui.filter_edit.setText("trace_b")
            self.qapp.processEvents()

            self.assertEqual(dialog.ui.trace_list.count(), 1)
            self.assertEqual(
                dialog.selected_supported_trace_ids(dialog.ui.trace_list),
                ("trace1",),
            )
            self.assertNotIn("'trace0'", dialog.preview_string())
            self.assertIn("hyde.remove_traces(fig, 'trace1')", dialog.preview_string())
        finally:
            dialog.close()
