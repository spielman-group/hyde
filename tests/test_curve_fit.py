import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from qtutils.qt import QtWidgets

from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugin_tools import HydePluginManager
from hyde.user_interface.plugins.figure.window import FigureWindow
from hyde.user_interface.plugins.curve_fit import Plugin as CurveFitPlugin
from hyde.user_interface.plugins.curve_fit.dialogs import CurveFitDialog


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


def trigger_curve_fit_action_and_capture_dialog(manager):
    launched = {}

    def record_exec(dialog):
        launched["dialog"] = dialog
        dialog.show()
        QtWidgets.QApplication.processEvents()
        return QtWidgets.QDialog.Accepted

    with patch.object(CurveFitDialog, "exec_", new=record_exec):
        action = manager.services["lookup_menu_action"]("analysis", "Curve Fit...")
        assert action is not None
        action.trigger()

    return launched["dialog"]


def tab_titles(dialog):
    return [dialog.tab_widget.tabText(index) for index in range(dialog.tab_widget.count())]


def show_output_options_tab(dialog):
    dialog.tab_widget.setCurrentIndex(3)
    QtWidgets.QApplication.processEvents()


def figure_ir_without_traces():
    return {"layout": {"subplots": [{"traces": []}]}}


class TestCurveFitPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_plugin_registers_curve_fit_action_in_analysis_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "curve_fit": CurveFitPlugin({}),
        }
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertEqual(
            [action.text() for action in app.ui.menuAnalysis.actions()],
            ["Curve Fit..."],
        )

    def test_curve_fit_action_with_no_active_figure_opens_unattached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "curve_fit": CurveFitPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        dialog = trigger_curve_fit_action_and_capture_dialog(manager)

        self.assertIsNone(dialog.figure_window)
        self.assertTrue(dialog.isModal())
        self.assertEqual(
            tab_titles(dialog),
            [
                "Function and Data",
                "Data Options",
                "Coefficients",
                "Output Options",
            ],
        )
        self.assertEqual(
            [dialog.preview_mode_combo.itemText(index) for index in range(dialog.preview_mode_combo.count())],
            ["Commands", "Equation"],
        )
        self.assertTrue(dialog.preview_text.isReadOnly())
        self.assertEqual(dialog.status_label.text(), "")
        self.assertEqual(dialog.do_it_button.text(), "Do It")
        self.assertEqual(dialog.to_clip_button.text(), "To Clip")
        self.assertEqual(dialog.cancel_button.text(), "Cancel")
        show_output_options_tab(dialog)
        self.assertTrue(dialog.show_fit_checkbox.isVisible())
        self.assertFalse(dialog.show_fit_checkbox.isEnabled())
        self.assertTrue(dialog.show_residuals_checkbox.isVisible())
        self.assertFalse(dialog.show_residuals_checkbox.isEnabled())
        dialog.close()

    def test_curve_fit_action_with_active_figure_opens_attached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "curve_fit": CurveFitPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        # Create active figure window
        services = {"send_figure_action": lambda figure_number, action: True}
        figure_window = FigureWindow(figure_number=7, services=services)
        class MockSnapshotState:
            def figure_ir(self):
                return {"some": "data"}
        figure_window.snapshot_state = MockSnapshotState()

        subwindow = app.ui.mdiArea.addSubWindow(figure_window)
        subwindow.show()
        app.ui.mdiArea.setActiveSubWindow(subwindow)

        dialog = trigger_curve_fit_action_and_capture_dialog(manager)

        self.assertIs(dialog.figure_window, figure_window)
        self.assertTrue(dialog.isModal())
        self.assertEqual(
            tab_titles(dialog),
            [
                "Function and Data",
                "Data Options",
                "Coefficients",
                "Output Options",
            ],
        )
        show_output_options_tab(dialog)
        self.assertTrue(dialog.show_fit_checkbox.isVisible())
        self.assertTrue(dialog.show_fit_checkbox.isEnabled())
        self.assertTrue(dialog.show_residuals_checkbox.isVisible())
        self.assertTrue(dialog.show_residuals_checkbox.isEnabled())
        dialog.close()

    def test_curve_fit_action_with_active_figure_and_no_traces_still_opens_attached_dialog(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "curve_fit": CurveFitPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        services = {"send_figure_action": lambda figure_number, action: True}
        figure_window = FigureWindow(figure_number=7, services=services)

        class MockSnapshotState:
            def figure_ir(self):
                return figure_ir_without_traces()

        figure_window.snapshot_state = MockSnapshotState()

        subwindow = app.ui.mdiArea.addSubWindow(figure_window)
        subwindow.show()
        app.ui.mdiArea.setActiveSubWindow(subwindow)

        dialog = trigger_curve_fit_action_and_capture_dialog(manager)

        self.assertIs(dialog.figure_window, figure_window)
        show_output_options_tab(dialog)
        self.assertTrue(dialog.show_fit_checkbox.isEnabled())
        self.assertTrue(dialog.show_residuals_checkbox.isEnabled())
        dialog.close()

    def test_curve_fit_action_with_unsupported_active_window_opens_unattached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "curve_fit": CurveFitPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        # Create unsupported window (standard QWidget)
        widget = QtWidgets.QWidget()
        subwindow = app.ui.mdiArea.addSubWindow(widget)
        subwindow.show()
        app.ui.mdiArea.setActiveSubWindow(subwindow)

        dialog = trigger_curve_fit_action_and_capture_dialog(manager)

        self.assertIsNone(dialog.figure_window)
        self.assertFalse(dialog.show_fit_checkbox.isEnabled())
        self.assertFalse(dialog.show_residuals_checkbox.isEnabled())
        dialog.close()

    def test_curve_fit_action_with_figure_window_no_ir_opens_unattached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "curve_fit": CurveFitPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        # Create active figure window with no figure_ir
        services = {"send_figure_action": lambda figure_number, action: True}
        figure_window = FigureWindow(figure_number=7, services=services)
        class MockSnapshotState:
            def figure_ir(self):
                return None
        figure_window.snapshot_state = MockSnapshotState()

        subwindow = app.ui.mdiArea.addSubWindow(figure_window)
        subwindow.show()
        app.ui.mdiArea.setActiveSubWindow(subwindow)

        dialog = trigger_curve_fit_action_and_capture_dialog(manager)

        self.assertIsNone(dialog.figure_window)
        self.assertFalse(dialog.show_fit_checkbox.isEnabled())
        self.assertFalse(dialog.show_residuals_checkbox.isEnabled())
        dialog.close()

    def test_curve_fit_action_with_figure_window_without_dispatch_opens_unattached_dialog(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "curve_fit": CurveFitPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        figure_window = FigureWindow(figure_number=7, services={})

        class MockSnapshotState:
            def figure_ir(self):
                return {"some": "data"}

        figure_window.snapshot_state = MockSnapshotState()

        subwindow = app.ui.mdiArea.addSubWindow(figure_window)
        subwindow.show()
        app.ui.mdiArea.setActiveSubWindow(subwindow)

        dialog = trigger_curve_fit_action_and_capture_dialog(manager)

        self.assertIsNone(dialog.figure_window)
        show_output_options_tab(dialog)
        self.assertFalse(dialog.show_fit_checkbox.isEnabled())
        self.assertFalse(dialog.show_residuals_checkbox.isEnabled())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
