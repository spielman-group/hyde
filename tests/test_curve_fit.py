import os
import tempfile
import textwrap
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from qtutils.qt import QtWidgets

import hyde
from hyde import project_tools
from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugin_tools import HydePluginManager
from hyde.user_interface.plugins.curve_fit import Plugin as CurveFitPlugin
from hyde.user_interface.plugins.curve_fit.dialogs import CurveFitDialog
from hyde.user_interface.plugins.figure.window import FigureWindow


DEFAULT_PROCEDURES_SOURCE = """\
# Hyde Procedures Package
# Define the project environment in this package module.

import hyde
import numpy as np
import matplotlib
matplotlib.use("module://hyde.matplotlib_backend")
import matplotlib.pyplot as plt
plt.ion()
import lmfit
"""


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
    app.emit_plugin_event = lambda name, data=None: HydeApp.emit_plugin_event(
        app,
        name,
        data,
    )
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


class ProcedureExecutionHarness:
    def __init__(self, plugin):
        self.plugin = plugin
        self.tempdir = tempfile.TemporaryDirectory()
        self.project_dir = self.tempdir.name
        self.procedures_dir = os.path.join(self.project_dir, "procedures")
        os.makedirs(self.procedures_dir, exist_ok=True)
        self.procedures_init = os.path.join(self.procedures_dir, "__init__.py")
        self.write_procedures("")

    def close(self):
        hyde.gui_mode(False)
        clear_fit_functions = getattr(
            hyde.recreation_registry,
            "clear_fit_functions",
            None,
        )
        if callable(clear_fit_functions):
            clear_fit_functions()
        self.tempdir.cleanup()

    def write_procedures(self, extra_source):
        source = DEFAULT_PROCEDURES_SOURCE
        extra_text = textwrap.dedent(extra_source).strip()
        if extra_text:
            source = f"{source}\n\n{extra_text}\n"
        with open(self.procedures_init, "w", encoding="utf-8") as handle:
            handle.write(source)

    def write_procedures_module(self, relative_path, source):
        module_path = os.path.join(self.procedures_dir, relative_path)
        os.makedirs(os.path.dirname(module_path), exist_ok=True)
        with open(module_path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(source).lstrip("\n"))

    def _route_parent_message(self, message):
        task, data = message
        self.plugin.on_kernel_message({"task": task, "data": data})

    def execute_hidden(self, code, silent=True):
        del silent
        namespace = {}
        with patch("hyde.execution.ipc.put_parent_message", side_effect=self._route_parent_message), patch(
            "hyde.recreation_registry.put_parent_message",
            side_effect=self._route_parent_message,
        ):
            exec(code, namespace, namespace)
        return True

    def reload_procedures(self):
        with patch("hyde.execution.ipc.put_parent_message", side_effect=self._route_parent_message), patch(
            "hyde.recreation_registry.put_parent_message",
            side_effect=self._route_parent_message,
        ):
            project_tools.execute_procedures_bootstrap(
                self.project_dir,
                os.path.dirname(hyde.HYDE_DIR),
                reset_namespace=False,
            )


class FakeExecutionService:
    def __init__(self, harness):
        self.harness = harness

    def execute_hidden(self, code, silent=True):
        return self.harness.execute_hidden(code, silent=silent)


def configure_curve_fit_runtime(app, manager):
    plugin = manager.plugins["curve_fit"]
    harness = ProcedureExecutionHarness(plugin)
    app.get_current_project_dir = lambda: harness.project_dir
    app.get_procedures_init = lambda: harness.procedures_init
    app.reload_procedures = harness.reload_procedures

    HydeApp.setup_plugins(app)

    execution_service = FakeExecutionService(harness)
    manager.services["python_execution_service"] = execution_service
    plugin.services["python_execution_service"] = execution_service
    plugin.services["get_procedures_init"] = app.get_procedures_init
    plugin.services["reload_procedures"] = app.reload_procedures
    harness.reload_procedures()
    return harness


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
    return [
        dialog.tab_widget.tabText(index)
        for index in range(dialog.tab_widget.count())
    ]


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
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertEqual(
            [action.text() for action in app.ui.menuAnalysis.actions()],
            ["Curve Fit..."],
        )

    def test_curve_fit_action_with_no_active_figure_opens_unattached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
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
                [
                    dialog.preview_mode_combo.itemText(index)
                    for index in range(dialog.preview_mode_combo.count())
                ],
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
        finally:
            harness.close()

    def test_curve_fit_action_with_active_figure_opens_attached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
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
        finally:
            harness.close()

    def test_curve_fit_action_with_active_figure_and_no_traces_still_opens_attached_dialog(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
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
        finally:
            harness.close()

    def test_curve_fit_action_with_unsupported_active_window_opens_unattached_dialog(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            widget = QtWidgets.QWidget()
            subwindow = app.ui.mdiArea.addSubWindow(widget)
            subwindow.show()
            app.ui.mdiArea.setActiveSubWindow(subwindow)

            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            self.assertIsNone(dialog.figure_window)
            self.assertFalse(dialog.show_fit_checkbox.isEnabled())
            self.assertFalse(dialog.show_residuals_checkbox.isEnabled())
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_action_with_figure_window_no_ir_opens_unattached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
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
        finally:
            harness.close()

    def test_curve_fit_action_with_figure_window_without_dispatch_opens_unattached_dialog(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
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
        finally:
            harness.close()

    def test_curve_fit_dialog_discovers_supported_fit_functions_and_surfaces_rejections(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            harness.write_procedures(
                """
                def plain_line(x, slope, offset):
                    return slope * x + offset

                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset

                @hyde.fit_function(independent_vars=("x", "y"))
                def plane_fit(x, y, amplitude, offset):
                    return amplitude * (x + y) + offset

                @hyde.fit_function(independent_vars=("x",))
                def bad_fit(x, *coeffs):
                    return x
                """
            )
            harness.reload_procedures()

            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            self.assertEqual(
                [
                    dialog.fit_function_combo.itemText(index)
                    for index in range(dialog.fit_function_combo.count())
                ],
                ["line_fit", "plane_fit"],
            )
            plane_entry = dialog.fit_function_combo.itemData(1)
            self.assertEqual(plane_entry["independent_vars"], ["x", "y"])
            self.assertEqual(plane_entry["parameters"], ["amplitude", "offset"])
            self.assertNotIn("plain_line", dialog.status_label.text())
            self.assertIn("bad_fit", dialog.status_label.text())
            self.assertIn("*args or **kwargs", dialog.status_label.text())
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_excludes_imported_helper_fit_functions(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            harness.write_procedures_module(
                "fit_helpers.py",
                """
                import hyde

                @hyde.fit_function(independent_vars=("x",))
                def helper_fit(x, slope):
                    return slope * x
                """,
            )
            harness.write_procedures(
                """
                from procedures.fit_helpers import helper_fit

                @hyde.fit_function(independent_vars=("x",))
                def local_fit(x, slope):
                    return slope * x
                """
            )
            harness.reload_procedures()

            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            self.assertEqual(
                [
                    dialog.fit_function_combo.itemText(index)
                    for index in range(dialog.fit_function_combo.count())
                ],
                ["local_fit"],
            )
            self.assertNotIn("helper_fit", dialog.status_label.text())
            dialog.close()
        finally:
            harness.close()

    def test_new_fit_function_button_scaffolds_reloads_and_selects_new_function(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            with patch.object(
                QtWidgets.QInputDialog,
                "getText",
                return_value=("FitFunction0", True),
            ):
                dialog.new_fit_function_button.click()
                QtWidgets.QApplication.processEvents()

            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.fit_function_combo.currentText(), "FitFunction0")
            with open(harness.procedures_init, "r", encoding="utf-8") as handle:
                procedures_source = handle.read()
            self.assertIn("# --- Hyde Fit Functions: BEGIN ---", procedures_source)
            self.assertIn(
                '@hyde.fit_function(independent_vars=("x",))',
                procedures_source,
            )
            self.assertIn("def FitFunction0(x, c0):", procedures_source)
            dialog.close()
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
