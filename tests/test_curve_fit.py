import copy
import contextlib
import io
import os
import tempfile
import textwrap
import unittest
import numpy as np
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from qtutils.qt import QtWidgets

import hyde
from hyde import project_tools
from hyde.features.matplotlib_features import FigureIRCodec
from hyde.features.lmfit_features import CALCULATED_X_NAME, LmfitCodec
from hyde.matplotlib_backend import apply_figure_action, figure_snapshot_payload
from hyde.user_interface.base_hyde_widgets import active_interactive_window
from hyde.user_interface.main import HydeApp
from hyde.user_interface.shared.core import RuntimeCommandState
from hyde.user_interface.shared.figure import supported_trace_records_from_figure_ir
from hyde.user_interface.shared.plugin import HydePluginManager
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


class ProcedureExecutionHarness:
    def __init__(self, plugin):
        self.plugin = plugin
        self.tempdir = tempfile.TemporaryDirectory()
        self.project_dir = self.tempdir.name
        self.procedures_dir = os.path.join(self.project_dir, "procedures")
        os.makedirs(self.procedures_dir, exist_ok=True)
        self.procedures_init = os.path.join(self.procedures_dir, "__init__.py")
        self.namespace = {}
        self.last_error_message = ""
        self.write_procedures("")

    def close(self):
        hyde.gui_mode(False)
        hyde.recreation_registry.clear(kind="fit_function")
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
        self.last_error_message = ""
        try:
            with patch("hyde.execution.ipc.put_parent_message", side_effect=self._route_parent_message), patch(
                "hyde.recreation_registry.put_parent_message",
                side_effect=self._route_parent_message,
            ), contextlib.redirect_stdout(io.StringIO()):
                exec(code, self.namespace, self.namespace)
        except Exception as exc:
            self.last_error_message = str(exc)
            return False
        return True

    def reload_procedures(self):
        with patch("hyde.execution.ipc.put_parent_message", side_effect=self._route_parent_message), patch(
            "hyde.recreation_registry.put_parent_message",
            side_effect=self._route_parent_message,
        ):
            project_tools.execute_procedures_bootstrap(
                self.project_dir,
                os.path.dirname(hyde.HYDE_DIR),
                reset_namespace=True,
            )
        self.namespace = __import__("__main__").__dict__

    def set_namespace_value(self, name, value):
        self.namespace[str(name)] = value


class FakeExecutionService:
    def __init__(self, harness):
        self.harness = harness
        self.calls = []
        self.visible_calls = []
        self.last_error_message = ""

    def execute_hidden(self, code, silent=True):
        self.calls.append({"code": code, "silent": silent})
        result = self.harness.execute_hidden(code, silent=silent)
        self.last_error_message = self.harness.last_error_message
        return result

    def execute_visible(self, code):
        self.visible_calls.append(str(code))
        return True


class FakeProjectProceduresService:
    def __init__(self, procedures_init, reload_procedures, project_dir=None):
        self._procedures_init = procedures_init
        self._reload_procedures = reload_procedures
        self._project_dir = project_dir

    def current_project_dir(self):
        return self._project_dir

    def procedures_init(self):
        return self._procedures_init()

    def reload_procedures(self):
        return self._reload_procedures()


def configure_curve_fit_runtime(app, manager):
    plugin = manager.plugins["curve_fit"]
    harness = ProcedureExecutionHarness(plugin)
    procedures_service = FakeProjectProceduresService(
        lambda: harness.procedures_init,
        harness.reload_procedures,
        project_dir=harness.project_dir,
    )
    app.get_current_project_dir = lambda: harness.project_dir
    app.build_plugin_services = lambda: {
        **HydeApp.build_plugin_services(app),
        "project_procedures_service": procedures_service,
    }

    HydeApp.setup_plugins(app)

    execution_service = FakeExecutionService(harness)
    harness.execution_service = execution_service
    manager.services["python_execution_service"] = execution_service
    plugin.services["python_execution_service"] = execution_service
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


def combo_items(combo):
    return [combo.itemText(index) for index in range(combo.count())]


def coefficient_row_index(dialog, parameter_name):
    for row in range(dialog.coefficients_table.rowCount()):
        item = dialog.coefficients_table.item(row, 0)
        if item is not None and item.text() == parameter_name:
            return row
    raise AssertionError(f"Coefficient row not found: {parameter_name!r}")


def coefficient_row_widgets(dialog, parameter_name):
    row = coefficient_row_index(dialog, parameter_name)
    return {
        "row": row,
        "name": dialog.coefficients_table.item(row, 0),
        "initial": dialog.coefficients_table.cellWidget(row, 1),
        "vary": dialog.coefficients_table.cellWidget(row, 2),
        "lower": dialog.coefficients_table.cellWidget(row, 3),
        "upper": dialog.coefficients_table.cellWidget(row, 4),
        "expr": dialog.coefficients_table.cellWidget(row, 5),
    }


def finish_line_edit(edit, text):
    edit.setText(text)
    edit.editingFinished.emit()
    QtWidgets.QApplication.processEvents()


def figure_ir_without_traces():
    return {"layout": {"subplots": [{"traces": []}]}}


def figure_ir_with_named_trace(x_name, y_name):
    return {
        "layout": {
            "subplots": [
                {
                    "id": "subplot0",
                    "traces": [
                        {
                            "id": "trace0",
                            "kind": "line",
                            "x_source": {"kind": "name", "value": x_name},
                            "y_source": {"kind": "name", "value": y_name},
                            "kwargs": {"label": y_name},
                        }
                    ],
                }
            ]
        }
    }


def figure_ir_with_implicit_x_trace(y_name):
    return {
        "layout": {
            "subplots": [
                {
                    "id": "subplot0",
                    "traces": [
                        {
                            "id": "trace0",
                            "kind": "line",
                            "x_source": None,
                            "y_source": {"kind": "name", "value": y_name},
                            "kwargs": {"label": y_name},
                        }
                    ],
                }
            ]
        }
    }


class FakeNamespaceViewService:
    def __init__(self, view=None):
        self._view = dict(view or {})

    def namespace_view(self):
        return dict(self._view)

    def connect_namespace_view_updated(self, callback):
        del callback
        return True

    def disconnect_namespace_view_updated(self, callback):
        del callback
        return True


def attach_namespace_view_service(manager, view):
    service = FakeNamespaceViewService(view)
    manager.services["namespace_view_service"] = service
    manager.plugins["curve_fit"].services["namespace_view_service"] = service
    return service


class FakeFigureActionService:
    def __init__(self, callback=None):
        self._callback = callback or (lambda figure_number, action: True)

    def request_figure_action(self, figure_number, action):
        return bool(self._callback(figure_number, action))


def make_figure_action_service(callback=None):
    return FakeFigureActionService(callback)


class FakeEditableFigureContext:
    def __init__(self, *, figure_number=7, figure_ir=None, request_action=None):
        self.figure_number = int(figure_number)
        self._figure_ir = (
            figure_ir_without_traces() if figure_ir is None else figure_ir
        )
        self._request_action = request_action or (lambda action: True)

    def figure_ir(self):
        return self._figure_ir

    def supported_trace_records(self):
        return supported_trace_records_from_figure_ir(self.figure_ir())

    def request_figure_action(self, action):
        return bool(self._request_action(dict(action or {})))


class LiveEditableFigureContext:
    def __init__(self, *, figure_number, figure_ir, request_action):
        self.figure_number = int(figure_number)
        self._figure_ir = figure_ir
        self._request_action = request_action

    def figure_ir(self):
        return self._figure_ir()

    def supported_trace_records(self):
        return supported_trace_records_from_figure_ir(self.figure_ir())

    def request_figure_action(self, action):
        return bool(self._request_action(dict(action or {})))


class DeferredFigureContext:
    def __init__(self, *, figure_number=7, figure_ir=None):
        self.figure_number = int(figure_number)
        self._figure_ir = (
            figure_ir_without_traces() if figure_ir is None else copy.deepcopy(figure_ir)
        )
        self.pending_actions = []

    def figure_ir(self):
        return copy.deepcopy(self._figure_ir)

    def supported_trace_records(self):
        return supported_trace_records_from_figure_ir(self.figure_ir())

    def request_figure_action(self, action):
        self.pending_actions.append(dict(action or {}))
        return True

    def flush_actions(self):
        while self.pending_actions:
            self._figure_ir = FigureIRCodec.update_state(
                self._figure_ir,
                self.pending_actions.pop(0),
            )


def attach_figure_context_service(manager, figure_context):
    figure_context_service = type(
        "FigureContextService",
        (),
        {"active_editable_figure": (lambda _self: figure_context)},
    )()
    manager.services["figure_context_service"] = figure_context_service
    manager.plugins["curve_fit"].services["figure_context_service"] = (
        figure_context_service
    )
    return figure_context_service


def make_figure_window(figure_ir):
    services = {
        "figure_action_service": make_figure_action_service(
            lambda figure_number, action: True
        )
    }
    figure_window = FigureWindow(figure_number=7, services=services)

    class MockSnapshotState:
        def figure_ir(self):
            return figure_ir

    figure_window.snapshot_state = MockSnapshotState()
    return figure_window


def create_curve_fit_dialog(plugin, app, *, figure_context=None, figure_window=None):
    if figure_context is None and figure_window is not None:
        figure_context = LiveEditableFigureContext(
            figure_number=figure_window.figure_number,
            figure_ir=figure_window.figure_ir,
            request_action=figure_window.request_figure_action,
        )
    dialog = CurveFitDialog(
        figure_context=figure_context,
        services=plugin.services,
        parent=app.ui,
    )
    dialog.show()
    QtWidgets.QApplication.processEvents()
    return dialog


def configure_line_fit_dialog(dialog):
    dialog.fit_function_combo.setCurrentIndex(dialog.fit_function_combo.findText("line_fit"))
    QtWidgets.QApplication.processEvents()
    finish_line_edit(
        coefficient_row_widgets(dialog, "slope")["initial"],
        "2.0",
    )
    finish_line_edit(
        coefficient_row_widgets(dialog, "offset")["initial"],
        "1.0",
    )


def attached_display_trace_id(result_name, kind, suffix=None):
    trace_id = result_name if kind == "fit" else f"{result_name}_residuals"
    if suffix is not None:
        trace_id = f"{trace_id}_{suffix}"
    return trace_id


class AttachedFigureHarness:
    def __init__(
        self,
        x_values,
        y_values,
        *,
        y_label="signal",
        fail_trace_ids=None,
        implicit_x=False,
    ):
        import matplotlib

        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as plt

        self._pyplot = plt
        self.action_log = []
        self.fail_trace_ids = {str(trace_id) for trace_id in (fail_trace_ids or ())}
        self.namespace = {
            "time": np.array(x_values, copy=True),
            "signal": np.array(y_values, copy=True),
        }

        @hyde.figure
        def CurveFitAttachedFigure(time, signal):
            fig = plt.figure("CurveFitAttachedFigure")
            ax = fig.add_subplot(111)
            if implicit_x:
                ax.plot(signal, label=y_label)
            else:
                ax.plot(time, signal, label=y_label)
            return fig

        self.figure = CurveFitAttachedFigure(
            self.namespace["time"],
            self.namespace["signal"],
        )
        self.figure_window = FigureWindow(
            figure_number=self.figure.number,
            services={
                "figure_action_service": make_figure_action_service(
                    self._send_figure_action
                )
            },
        )
        self.refresh_snapshot()

    def refresh_snapshot(self):
        self.figure_window.update_payload(
            {
                "figure_number": self.figure.number,
                "snapshot": figure_snapshot_payload(self.figure, self.figure.number),
            }
        )

    def _send_figure_action(self, figure_number, action):
        self.action_log.append(
            {
                "figure_number": int(figure_number),
                "action": dict(action or {}),
            }
        )
        if (
            action.get("type") == "set_trace"
            and str(action.get("trace_id")) in self.fail_trace_ids
        ):
            return False
        apply_figure_action(self.figure, action)
        self.refresh_snapshot()
        return True

    def close(self):
        self._pyplot.close(self.figure)


def create_configured_line_fit_dialog(
    *,
    include_weights=False,
    figure_context=None,
    figure_window=None,
):
    manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
    manager.plugins = {"curve_fit": CurveFitPlugin({})}
    app = make_plugin_host(manager)
    harness = configure_curve_fit_runtime(app, manager)
    namespace_view = {
        "signal": {
            "python_type": "ndarray",
            "numpy_type": "Array",
            "ndim": 1,
            "numpy_kind": "f",
        },
        "time": {
            "python_type": "ndarray",
            "numpy_type": "Array",
            "ndim": 1,
            "numpy_kind": "f",
        },
    }
    if include_weights:
        namespace_view["weights"] = {
            "python_type": "ndarray",
            "numpy_type": "Array",
            "ndim": 1,
            "numpy_kind": "f",
        }
    attach_namespace_view_service(manager, namespace_view)
    harness.write_procedures(
        """
        @hyde.fit_function(independent_vars=("x",))
        def line_fit(x, slope, offset):
            return slope * x + offset
        """
    )
    harness.reload_procedures()
    harness.set_namespace_value("signal", np.array([1.0, 3.0, 5.0, 7.0]))
    harness.set_namespace_value("time", np.array([0.0, 1.0, 2.0, 3.0]))
    if include_weights:
        harness.set_namespace_value("weights", np.array([1.0, 1.0]))

    dialog = create_curve_fit_dialog(
        manager.plugins["curve_fit"],
        app,
        figure_context=figure_context,
        figure_window=figure_window,
    )
    configure_line_fit_dialog(dialog)
    return manager, app, harness, dialog


class TestCurveFitPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_active_interactive_window_returns_active_typed_widget_without_figure_policy(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        app = make_plugin_host(manager)
        figure_window = FigureWindow(figure_number=7, services={})
        subwindow = app.ui.mdiArea.addSubWindow(figure_window)
        subwindow.show()
        app.ui.mdiArea.setActiveSubWindow(subwindow)

        self.assertIs(
            active_interactive_window({"mdi_area": app.ui.mdiArea}, FigureWindow),
            figure_window,
        )

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

            self.assertIsNone(dialog.figure_context)
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
            self.assertTrue(dialog.lower_text_edit.isReadOnly())
            self.assertEqual(
                [
                    dialog.preview_mode_combo.itemText(index)
                    for index in range(dialog.preview_mode_combo.count())
                ],
                ["Commands", "Equation"],
            )
            self.assertEqual(dialog.preview_mode_combo.currentText(), "Commands")
            self.assertEqual(dialog.status_label.text(), "Select Y data.")
            self.assertEqual(
                dialog.status_strip.layout().itemAt(0).widget().text(),
                "Status",
            )
            self.assertEqual(dialog.do_it_button.text(), "Do It")
            self.assertEqual(dialog.to_cmd_line_button.text(), "To Cmd Line")
            self.assertFalse(dialog.to_cmd_line_button.isEnabled())
            self.assertTrue(dialog.to_cmd_line_button.isVisibleTo(dialog))
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

    def test_curve_fit_action_with_active_figure_context_opens_attached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            figure_context = FakeEditableFigureContext(figure_ir={"some": "data"})
            attach_figure_context_service(manager, figure_context)

            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            self.assertIs(dialog.figure_context, figure_context)
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
            self.assertTrue(dialog.show_fit_checkbox.isChecked())
            self.assertTrue(dialog.show_residuals_checkbox.isVisible())
            self.assertTrue(dialog.show_residuals_checkbox.isEnabled())
            self.assertFalse(dialog.show_residuals_checkbox.isChecked())
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_action_with_active_figure_context_and_no_traces_still_opens_attached_dialog(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            figure_context = FakeEditableFigureContext(
                figure_ir=figure_ir_without_traces()
            )
            attach_figure_context_service(manager, figure_context)

            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            self.assertIs(dialog.figure_context, figure_context)
            show_output_options_tab(dialog)
            self.assertTrue(dialog.show_fit_checkbox.isEnabled())
            self.assertTrue(dialog.show_residuals_checkbox.isEnabled())
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_action_without_editable_figure_context_opens_unattached_dialog(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_figure_context_service(manager, None)

        try:
            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            self.assertIsNone(dialog.figure_context)
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

            discovered_names = combo_items(dialog.fit_function_combo)
            self.assertIn("line", discovered_names)
            self.assertIn("line_fit", discovered_names)
            self.assertIn("plane_fit", discovered_names)
            self.assertLess(
                discovered_names.index("line_fit"),
                discovered_names.index("plane_fit"),
            )
            self.assertNotIn("plain_line", dialog.status_label.text())
            self.assertIn("bad_fit", dialog.status_label.text())
            self.assertIn("*args or **kwargs", dialog.status_label.text())
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_includes_imported_helper_fit_functions(self):
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

            discovered_names = combo_items(dialog.fit_function_combo)
            self.assertIn("local_fit", discovered_names)
            self.assertIn("helper_fit", discovered_names)
            dialog.close()
        finally:
            harness.close()

    def test_hyde_builtin_fit_functions_are_discovered_after_bootstrap(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            dialog = trigger_curve_fit_action_and_capture_dialog(manager)
            discovered_names = combo_items(dialog.fit_function_combo)
            self.assertEqual(discovered_names[0], "line")
            self.assertIn("exp", discovered_names)
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_builtin_line_fit_executes_with_implicit_x(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )
        harness.set_namespace_value("signal", np.array([1.0, 3.0, 5.0, 7.0]))

        try:
            dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit"],
                app,
                figure_window=make_figure_window(
                    figure_ir_with_implicit_x_trace("signal")
                ),
            )
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line")
                )
                QtWidgets.QApplication.processEvents()

                self.assertIn(
                    "lmfit.Model(hyde.line, independent_vars=['x'])",
                    dialog.lower_text_edit.toPlainText(),
                )
                self.assertEqual(
                    dialog.x_data_rows[0]["combo"].currentText(),
                    CALCULATED_X_NAME,
                )

                finish_line_edit(
                    coefficient_row_widgets(dialog, "a")["initial"],
                    "2.0",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "b")["initial"],
                    "1.0",
                )

                dialog.do_it_button.click()
                QtWidgets.QApplication.processEvents()

                self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
                self.assertIn("signal_fit_result", harness.namespace)
                self.assertEqual(harness.execution_service.last_error_message, "")
            finally:
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
            self.assertNotIn("# --- Hyde Fit Functions: BEGIN ---", procedures_source)
            self.assertIn(
                '@hyde.fit_function(independent_vars=("x",))',
                procedures_source,
            )
            self.assertIn("def FitFunction0(x, c0):", procedures_source)
            dialog.close()
        finally:
            harness.close()

    def test_new_fit_function_button_rejects_real_conflicts_and_keeps_dialog_open(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def ExistingFit(x, c0):
                    return c0 * x
                """
            )
            harness.reload_procedures()
            dialog = trigger_curve_fit_action_and_capture_dialog(manager)
            original_items = combo_items(dialog.fit_function_combo)
            original_selection = dialog.fit_function_combo.currentText()
            with open(harness.procedures_init, "r", encoding="utf-8") as handle:
                original_source = handle.read()

            with patch.object(
                QtWidgets.QInputDialog,
                "getText",
                return_value=("ExistingFit", True),
            ), patch.object(QtWidgets.QMessageBox, "warning") as warning:
                dialog.new_fit_function_button.click()
                QtWidgets.QApplication.processEvents()

            warning.assert_called_once()
            self.assertTrue(dialog.isVisible())
            self.assertEqual(combo_items(dialog.fit_function_combo), original_items)
            self.assertEqual(dialog.fit_function_combo.currentText(), original_selection)
            with open(harness.procedures_init, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original_source)
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_catalog_service_refreshes_entries_and_default_name(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def FitFunction0(x, c0):
                    return c0 * x

                @hyde.fit_function(independent_vars=("x",))
                def FitFunction1(x, *coeffs):
                    return x
                """
            )
            harness.reload_procedures()
            catalog_service = manager.services["curve_fit_catalog_service"]
            execution_service = manager.services["python_execution_service"]
            expected_refresh_state = RuntimeCommandState()
            expected_refresh_state.set_callable_invocation(
                "hyde.recreation_registry.publish_registry",
                [repr("fit_function")],
            )
            expected_refresh_command = expected_refresh_state.python_source()

            catalog_service.replace_catalog([], [])
            self.assertTrue(catalog_service.refresh())

            self.assertIn(
                "FitFunction0",
                [entry["name"] for entry in catalog_service.fit_functions()],
            )
            self.assertIn(
                "FitFunction1",
                [entry["name"] for entry in catalog_service.rejected_fit_functions()],
            )
            self.assertEqual(
                catalog_service.default_new_fit_function_name(),
                "FitFunction2",
            )
            self.assertEqual(
                execution_service.calls[-1]["code"],
                expected_refresh_command,
            )
        finally:
            harness.close()

    def test_curve_fit_catalog_service_scaffolds_through_project_procedures_service(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        plugin = manager.plugins["curve_fit"]
        harness = ProcedureExecutionHarness(plugin)
        procedures_service = FakeProjectProceduresService(
            lambda: harness.procedures_init,
            harness.reload_procedures,
            project_dir=harness.project_dir,
        )
        app.get_current_project_dir = lambda: harness.project_dir
        app.build_plugin_services = lambda: {
            **HydeApp.build_plugin_services(app),
            "project_procedures_service": procedures_service,
        }

        try:
            HydeApp.setup_plugins(app)
            execution_service = FakeExecutionService(harness)
            harness.execution_service = execution_service
            manager.services["python_execution_service"] = execution_service
            plugin.services["python_execution_service"] = execution_service
            harness.reload_procedures()
            catalog_service = manager.services["curve_fit_catalog_service"]

            self.assertEqual(
                catalog_service.scaffold_new_fit_function("FitFunction0"),
                "FitFunction0",
            )
            self.assertIn(
                "FitFunction0",
                [entry["name"] for entry in catalog_service.fit_functions()],
            )
        finally:
            harness.close()

    def test_curve_fit_dialog_multivariate_selection_reshapes_x_controls_and_preview(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "detuning": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "iteration": {"python_type": "int"},
            },
        )

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x", "z"))
                def plane_fit(x, z, amplitude, offset):
                    return amplitude * x + offset * z
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit"],
                app,
                figure_window=make_figure_window(
                    figure_ir_with_named_trace("time", "signal")
                ),
            )
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("plane_fit")
                )
                QtWidgets.QApplication.processEvents()

                self.assertEqual(combo_items(dialog.y_data_combo), ["signal"])
                self.assertEqual(
                    [row["name"] for row in dialog.x_data_rows],
                    ["x", "z"],
                )
                self.assertEqual(dialog.x_data_rows[0]["combo"].currentText(), "time")
                self.assertEqual(
                    dialog.x_data_rows[1]["combo"].currentText(),
                    "detuning",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "amplitude")["initial"],
                    "1",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "offset")["initial"],
                    "0",
                )
                self.assertIn(
                    "lmfit.Model(plane_fit, independent_vars=['x', 'z'])",
                    dialog.lower_text_edit.toPlainText(),
                )
                self.assertIn(
                    "signal_fit_result = signal_fit_model.fit("
                    "signal, params=signal_fit_params, x=time, z=detuning)",
                    dialog.lower_text_edit.toPlainText(),
                )
                self.assertIn(
                    "print(signal_fit_result.fit_report())",
                    dialog.lower_text_edit.toPlainText(),
                )
                dialog.preview_mode_combo.setCurrentText("Equation")
                QtWidgets.QApplication.processEvents()
                self.assertEqual(
                    dialog.lower_text_edit.toPlainText().strip(),
                    (
                        "def plane_fit(x, z, amplitude, offset):\n"
                        "    return amplitude * x + offset * z"
                    ),
                )

                dialog.from_target_checkbox.setChecked(False)
                QtWidgets.QApplication.processEvents()
                self.assertEqual(
                    combo_items(dialog.y_data_combo),
                    ["detuning", "signal", "time"],
                )
                self.assertEqual(
                    combo_items(dialog.x_data_rows[0]["combo"]),
                    [CALCULATED_X_NAME, "detuning", "signal", "time"],
                )
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_defaults_x_to_calculated_for_implicit_target_trace(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )

        try:
            clipboard = QtWidgets.QApplication.clipboard()
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit"],
                app,
                figure_window=make_figure_window(
                    figure_ir_with_implicit_x_trace("signal")
                ),
            )
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                self.assertEqual(
                    combo_items(dialog.x_data_rows[0]["combo"]),
                    [CALCULATED_X_NAME, "signal", "time"],
                )
                self.assertEqual(
                    dialog.x_data_rows[0]["combo"].currentText(),
                    CALCULATED_X_NAME,
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "slope")["initial"],
                    "1",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "offset")["initial"],
                    "0",
                )
                self.assertIn(
                    "signal_fit_result = signal_fit_model.fit("
                    "signal, params=signal_fit_params, "
                    "x=np.arange(len(signal)))",
                    dialog.lower_text_edit.toPlainText(),
                )
                self.assertIn(
                    "print(signal_fit_result.fit_report())",
                    dialog.lower_text_edit.toPlainText(),
                )
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_defaults_result_target_from_y_name_with_unique_fall_forward(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "signal_fit_result": {"python_type": "ModelResult"},
            },
        )

        try:
            clipboard = QtWidgets.QApplication.clipboard()
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                self.assertEqual(dialog.y_data_combo.currentText(), "signal")
                self.assertEqual(
                    dialog.fit_result_target_combo.currentText(),
                    "signal_fit_result0",
                )

                dialog.y_data_combo.setCurrentIndex(dialog.y_data_combo.findText("time"))
                QtWidgets.QApplication.processEvents()
                self.assertEqual(
                    dialog.fit_result_target_combo.currentText(),
                    "time_fit_result",
                )
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_to_clip_copies_canonical_lower_text(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )

        try:
            clipboard = QtWidgets.QApplication.clipboard()
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                dialog.weighting_combo.setCurrentIndex(
                    dialog.weighting_combo.findText("time")
                )
                QtWidgets.QApplication.processEvents()
                self.assertIn(
                    "signal_fit_model = lmfit.Model(",
                    dialog.lower_text_edit.toPlainText(),
                )
                dialog.preview_mode_combo.setCurrentText("Equation")
                QtWidgets.QApplication.processEvents()
                self.assertIn(
                    "def line_fit(x, slope, offset):",
                    dialog.lower_text_edit.toPlainText(),
                )

                dialog.to_clip_button.click()
                self.assertEqual(clipboard.text(), dialog.lower_text_edit.toPlainText())
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_requires_usable_free_parameter_values_for_do_it(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                self.assertEqual(dialog.coefficients_table.rowCount(), 2)
                self.assertFalse(dialog.do_it_button.isEnabled())
                self.assertIn("slope", dialog.status_label.text())
                self.assertIn("initial value", dialog.status_label.text())
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_expr_owned_parameter_stays_visible_and_disables_manual_controls(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                finish_line_edit(
                    coefficient_row_widgets(dialog, "offset")["initial"],
                    "1.5",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "slope")["expr"],
                    "2 * offset",
                )

                slope_widgets = coefficient_row_widgets(dialog, "slope")
                self.assertEqual(dialog.coefficients_table.rowCount(), 2)
                self.assertEqual(
                    dialog.coefficients_table.item(slope_widgets["row"], 0).text(),
                    "slope",
                )
                self.assertFalse(slope_widgets["initial"].isEnabled())
                self.assertFalse(slope_widgets["vary"].isEnabled())
                self.assertFalse(slope_widgets["lower"].isEnabled())
                self.assertFalse(slope_widgets["upper"].isEnabled())
                self.assertTrue(slope_widgets["expr"].isEnabled())
                self.assertTrue(dialog.do_it_button.isEnabled())
                self.assertEqual(dialog.status_label.text(), "")
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_invalid_free_parameter_does_not_preview_executable_fit(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                finish_line_edit(
                    coefficient_row_widgets(dialog, "slope")["expr"],
                    "2 * offset",
                )

                self.assertFalse(dialog.do_it_button.isEnabled())
                self.assertIn("offset", dialog.status_label.text())
                self.assertNotIn(".fit(", dialog.lower_text_edit.toPlainText())
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_invalid_result_target_name_disables_commit_and_omits_invalid_assignment(
        self,
    ):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            dialog.fit_result_target_combo.setEditText("bad-name")
            QtWidgets.QApplication.processEvents()

            self.assertFalse(dialog.do_it_button.isEnabled())
            self.assertIn(
                "valid Python identifier",
                dialog.status_label.text(),
            )
            self.assertNotIn("bad-name =", dialog.lower_text_edit.toPlainText())
            self.assertNotIn(".fit(", dialog.lower_text_edit.toPlainText())

            dialog.to_clip_button.click()
            clipboard = QtWidgets.QApplication.clipboard()
            self.assertEqual(clipboard.text(), dialog.lower_text_edit.toPlainText())
            self.assertNotIn("bad-name =", clipboard.text())
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_valid_custom_result_target_name_stays_enabled_and_lowers_normally(
        self,
    ):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            dialog.fit_result_target_combo.setEditText("custom_fit_result")
            QtWidgets.QApplication.processEvents()

            self.assertTrue(dialog.do_it_button.isEnabled())
            self.assertEqual(dialog.status_label.text(), "")
            self.assertIn(
                "custom_fit_result = custom_fit_model.fit(",
                dialog.lower_text_edit.toPlainText(),
            )
            self.assertIn(
                "print(custom_fit_result.fit_report())",
                dialog.lower_text_edit.toPlainText(),
            )
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_uses_shared_shell_for_canonical_text(self):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            clipboard = QtWidgets.QApplication.clipboard()

            self.assertFalse(dialog.to_cmd_line_button.isEnabled())
            self.assertTrue(dialog.to_cmd_line_button.isVisibleTo(dialog))
            self.assertIn(
                "signal_fit_result = signal_fit_model.fit(",
                dialog.lower_text_edit.toPlainText(),
            )

            dialog.to_clip_button.click()

            self.assertEqual(
                clipboard.text(),
                dialog.lower_text_edit.toPlainText(),
            )
            self.assertIn(
                "signal_fit_result = signal_fit_model.fit(",
                dialog.lower_text_edit.toPlainText(),
            )
        finally:
            dialog.close()
            harness.close()

    def test_lmfit_codec_expression_owned_coefficients_feed_preview_and_commit_lowering(self):
        array_metadata = {
            "python_type": "ndarray",
            "numpy_type": "Array",
            "ndim": 1,
            "numpy_kind": "f",
        }
        state = {
            "settings": {
                "fit_function_name": "line_fit",
                "y_name": "signal",
                "x_names": {"x": "time"},
                "fit_result_name": "signal_fit_result",
                "fit_result_name_locked": True,
                "coefficients": {
                    "slope": {"expr": "2 * offset"},
                    "offset": {"initial_value": "1.5"},
                },
            }
        }
        context = {
            "fit_functions": [
                {
                    "name": "line_fit",
                    "callable_ref": "line_fit",
                    "independent_vars": ["x"],
                    "parameters": ["slope", "offset"],
                }
            ],
            "namespace_view": {"signal": array_metadata, "time": array_metadata},
            "trace_records": [],
        }

        commit_preview = LmfitCodec.state_to_commit_python(state, context=context)
        guessed_preview = LmfitCodec.state_to_preview_python(
            state,
            context=context,
            preview_target_name="_preview_fit",
        )

        self.assertIn(
            "signal_fit_params.add('slope', expr='2 * offset')",
            commit_preview,
        )
        self.assertIn(
            "signal_fit_params.add('offset', value=1.5, vary=True)",
            commit_preview,
        )
        self.assertIn(
            "signal_fit_result = signal_fit_model.fit(signal, params=signal_fit_params, x=time)",
            commit_preview,
        )
        self.assertIn(
            "_preview_fit.best_fit = line_fit(x=time, slope=2 * offset, offset=1.5)",
            guessed_preview,
        )

    def test_curve_fit_dialog_data_options_update_preview_and_execution_mode_without_running(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "weights": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                finish_line_edit(
                    coefficient_row_widgets(dialog, "slope")["initial"],
                    "2.0",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "offset")["initial"],
                    "1.0",
                )
                harness.execution_service.calls.clear()
                dialog.weighting_combo.setCurrentText("weights")
                QtWidgets.QApplication.processEvents()

                self.assertTrue(dialog.suppress_screen_updates_checkbox.isChecked())
                self.assertEqual(dialog.execution_mode(), "suppressed")
                self.assertIn("weights=weights", dialog.lower_text_edit.toPlainText())
                self.assertEqual(harness.execution_service.calls, [])
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_suppressed_do_it_runs_one_hidden_fit_and_creates_result_object(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()
            harness.set_namespace_value("signal", np.array([1.0, 3.0, 5.0, 7.0]))
            harness.set_namespace_value("time", np.array([0.0, 1.0, 2.0, 3.0]))

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                finish_line_edit(
                    coefficient_row_widgets(dialog, "slope")["initial"],
                    "2.0",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "offset")["initial"],
                    "1.0",
                )
                dialog.suppress_screen_updates_checkbox.setChecked(True)
                QtWidgets.QApplication.processEvents()

                harness.execution_service.calls.clear()
                preview_command = dialog.lower_text_edit.toPlainText()
                self.assertNotIn("signal_fit_result", harness.namespace)

                dialog.do_it_button.click()
                QtWidgets.QApplication.processEvents()

                self.assertEqual(len(harness.execution_service.calls), 1)
                self.assertEqual(
                    harness.execution_service.calls[0]["code"],
                    preview_command,
                )
                self.assertEqual(harness.execution_service.visible_calls, [])
                self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
                result = harness.namespace["signal_fit_result"]
                self.assertEqual(type(result).__name__, "ModelResult")
                self.assertTrue(hasattr(result, "best_fit"))
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_suppressed_do_it_recreates_existing_result_target_once(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "signal_fit_result": {"python_type": "ModelResult"},
            },
        )

        try:
            harness.write_procedures(
                """
                @hyde.fit_function(independent_vars=("x",))
                def line_fit(x, slope, offset):
                    return slope * x + offset
                """
            )
            harness.reload_procedures()
            harness.set_namespace_value("signal", np.array([1.0, 3.0, 5.0, 7.0]))
            harness.set_namespace_value("time", np.array([0.0, 1.0, 2.0, 3.0]))
            previous_result = object()
            harness.set_namespace_value("signal_fit_result", previous_result)

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                finish_line_edit(
                    coefficient_row_widgets(dialog, "slope")["initial"],
                    "2.0",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "offset")["initial"],
                    "1.0",
                )
                dialog.fit_result_target_combo.setEditText("signal_fit_result")
                QtWidgets.QApplication.processEvents()
                dialog.suppress_screen_updates_checkbox.setChecked(True)
                QtWidgets.QApplication.processEvents()

                harness.execution_service.calls.clear()
                self.assertIs(harness.namespace["signal_fit_result"], previous_result)

                dialog.do_it_button.click()
                QtWidgets.QApplication.processEvents()

                self.assertEqual(len(harness.execution_service.calls), 1)
                self.assertIsNot(harness.namespace["signal_fit_result"], previous_result)
                self.assertEqual(
                    type(harness.namespace["signal_fit_result"]).__name__,
                    "ModelResult",
                )
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_live_mode_reruns_immediately_and_do_it_does_not_rerun(
        self,
    ):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            harness.execution_service.calls.clear()
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(dialog.execution_mode(), "live")
            self.assertEqual(len(harness.execution_service.calls), 1)
            first_result = harness.namespace["signal_fit_result"]
            self.assertEqual(type(first_result).__name__, "ModelResult")

            finish_line_edit(
                coefficient_row_widgets(dialog, "offset")["initial"],
                "0.5",
            )

            self.assertEqual(len(harness.execution_service.calls), 2)
            self.assertIsNot(harness.namespace["signal_fit_result"], first_result)

            dialog.do_it_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(harness.execution_service.calls), 2)
            self.assertEqual(harness.execution_service.visible_calls, [])
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_cancel_restores_live_edited_result_target(self):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            previous_result = object()
            harness.set_namespace_value("signal_fit_result", previous_result)

            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(type(harness.namespace["signal_fit_result"]).__name__, "ModelResult")
            self.assertIsNot(harness.namespace["signal_fit_result"], previous_result)

            dialog.cancel_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertIs(harness.namespace["signal_fit_result"], previous_result)
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_cancel_restores_all_live_touched_result_targets(self):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            previous_signal_result = object()
            previous_alternate_result = object()
            harness.set_namespace_value("signal_fit_result", previous_signal_result)
            harness.set_namespace_value(
                "alternate_fit_result",
                previous_alternate_result,
            )

            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(type(harness.namespace["signal_fit_result"]).__name__, "ModelResult")
            self.assertIs(
                harness.namespace["alternate_fit_result"],
                previous_alternate_result,
            )

            dialog.fit_result_target_combo.setEditText("alternate_fit_result")
            QtWidgets.QApplication.processEvents()

            self.assertIs(
                harness.namespace["signal_fit_result"],
                previous_signal_result,
            )
            self.assertEqual(
                type(harness.namespace["alternate_fit_result"]).__name__,
                "ModelResult",
            )
            self.assertIsNot(
                harness.namespace["alternate_fit_result"],
                previous_alternate_result,
            )

            dialog.cancel_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertIs(
                harness.namespace["signal_fit_result"],
                previous_signal_result,
            )
            self.assertIs(
                harness.namespace["alternate_fit_result"],
                previous_alternate_result,
            )
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_attached_show_fit_renders_derived_trace_from_current_result(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            dialog.show_fit_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            result = harness.namespace["signal_fit_result"]
            subplot = attached_figure.figure_window.snapshot_state.figure_ir()[
                "layout"
            ]["subplots"][0]

            self.assertEqual(len(subplot["traces"]), 2)
            self.assertEqual(len(attached_figure.figure.axes), 1)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_xdata(),
                harness.namespace["time"],
            )
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                result.best_fit,
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_attached_display_trace_uses_generic_figure_ir_action(self):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertIn("signal_fit_result", harness.namespace)

            fit_trace_id = attached_display_trace_id("signal_fit_result", "fit")
            attached_figure.action_log.clear()
            attached_figure.figure_window.request_figure_action(
                {
                    "type": "set_trace",
                    "subplot_id": "subplot0",
                    "trace_id": fit_trace_id,
                    "trace": {
                        "kind": "line",
                        "x_source": {"kind": "name", "value": "time"},
                        "y_source": {
                            "kind": "attribute_path",
                            "root": {"kind": "name", "value": "signal_fit_result"},
                            "path": ["best_fit"],
                        },
                        "kwargs": {"label": "Fit", "linestyle": "--"},
                    },
                }
            )
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            fit_trace = subplot["traces"][-1]
            self.assertEqual(fit_trace["id"], fit_trace_id)
            self.assertEqual(fit_trace["y_source"]["kind"], "attribute_path")
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_xdata(),
                harness.namespace["time"],
            )
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                harness.namespace["signal_fit_result"].best_fit,
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_display_uses_generic_trace_actions(self):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            self.assertTrue(dialog.show_fit_checkbox.isChecked())
            self.assertEqual(
                [entry["action"]["type"] for entry in attached_figure.action_log],
                ["set_trace"],
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_display_uses_implicit_x_for_calculated_selection(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            dialog.x_data_rows[0]["combo"].setCurrentText(CALCULATED_X_NAME)
            QtWidgets.QApplication.processEvents()
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            dialog.show_fit_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            fit_trace = subplot["traces"][-1]
            self.assertIsNone(fit_trace["x_source"])
            self.assertEqual(fit_trace["kwargs"]["label"], "signal_fit_result")
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_xdata(),
                np.arange(len(harness.namespace["signal_fit_result"].best_fit)),
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_show_fit_previews_function_guesses_not_fit_result(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0, 4.0]),
            np.array([0.0, 1.0, 4.0, 9.0, 15.0]),
        )
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )
        harness.set_namespace_value("signal", np.array([0.0, 1.0, 4.0, 9.0, 15.0]))
        harness.set_namespace_value("time", np.array([0.0, 1.0, 2.0, 3.0, 4.0]))
        try:
            dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit"],
                app,
                figure_window=attached_figure.figure_window,
            )
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("exp")
                )
                QtWidgets.QApplication.processEvents()
                finish_line_edit(
                    coefficient_row_widgets(dialog, "a")["initial"],
                    "1.0",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "width")["initial"],
                    "-1.0",
                )
                finish_line_edit(
                    coefficient_row_widgets(dialog, "y0")["initial"],
                    "0.0",
                )
                dialog.suppress_screen_updates_checkbox.setChecked(False)
                QtWidgets.QApplication.processEvents()
                dialog.show_fit_checkbox.setChecked(True)
                QtWidgets.QApplication.processEvents()

                preview_line = attached_figure.figure.axes[0].lines[-1]
                np.testing.assert_allclose(
                    preview_line.get_ydata(),
                    hyde.exp(harness.namespace["time"], 1.0, -1.0, 0.0),
                )
                self.assertFalse(
                    np.allclose(
                        preview_line.get_ydata(),
                        harness.namespace["signal_fit_result"].best_fit,
                    )
                )

                finish_line_edit(
                    coefficient_row_widgets(dialog, "width")["initial"],
                    "-0.5",
                )
                QtWidgets.QApplication.processEvents()

                np.testing.assert_allclose(
                    attached_figure.figure.axes[0].lines[-1].get_ydata(),
                    hyde.exp(harness.namespace["time"], 1.0, -0.5, 0.0),
                )
            finally:
                dialog.close()
        finally:
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_suppressed_parameter_edits_update_preview(self):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            self.assertEqual(dialog.execution_mode(), "suppressed")
            self.assertTrue(dialog.show_fit_checkbox.isChecked())
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            self.assertNotIn("signal_fit_result", harness.namespace)

            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                2.0 * harness.namespace["time"] + 1.0,
            )

            finish_line_edit(
                coefficient_row_widgets(dialog, "offset")["initial"],
                "0.5",
            )
            QtWidgets.QApplication.processEvents()

            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                2.0 * harness.namespace["time"] + 0.5,
            )
            self.assertNotIn("signal_fit_result", harness.namespace)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_suppressed_show_fit_previews_without_committing_result(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            self.assertEqual(dialog.execution_mode(), "suppressed")
            self.assertTrue(dialog.show_fit_checkbox.isChecked())
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            self.assertNotIn("signal_fit_result", harness.namespace)

            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                2.0 * harness.namespace["time"] + 1.0,
            )
            self.assertNotIn("signal_fit_result", harness.namespace)

            attached_figure.action_log.clear()
            dialog.do_it_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertEqual([entry["action"]["type"] for entry in attached_figure.action_log], ["set_trace"])
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                harness.namespace["signal_fit_result"].best_fit,
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_sync_failure_surfaces_hidden_execution_failure(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
            fail_trace_ids={attached_display_trace_id("signal_fit_result", "res")},
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            previous_result = object()
            harness.set_namespace_value("signal_fit_result", previous_result)
            dialog.show_fit_checkbox.setChecked(True)
            dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            attached_figure.action_log.clear()
            dialog.do_it_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertEqual(dialog.result(), 0)
            self.assertIs(harness.namespace["signal_fit_result"], previous_result)
            self.assertEqual(
                dialog.status_label.text(),
                "Curve Fit attached display update failed.",
            )
            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertEqual([trace["id"] for trace in subplot["traces"]], ["trace0"])
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 1)
            self.assertTrue(
                any(
                    entry["action"]["trace_id"]
                    == attached_display_trace_id("signal_fit_result", "res")
                    for entry in attached_figure.action_log
                )
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_sync_failure_rolls_back_replaced_trace_ids(
        self,
    ):
        colliding_fit_id = attached_display_trace_id("signal_fit_result", "fit")
        colliding_residual_id = attached_display_trace_id("signal_fit_result", "res")
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            for trace_id in (colliding_fit_id, colliding_residual_id):
                attached_figure.figure_window.request_figure_action(
                    {
                        "type": "set_trace",
                        "subplot_id": "subplot0",
                        "trace_id": trace_id,
                        "trace": {
                            "kind": "line",
                            "x_source": {"kind": "name", "value": "time"},
                            "y_source": {"kind": "name", "value": "signal"},
                            "kwargs": {"label": trace_id},
                        },
                    }
                )
            QtWidgets.QApplication.processEvents()
            attached_figure.fail_trace_ids = {colliding_residual_id}

            previous_result = object()
            harness.set_namespace_value("signal_fit_result", previous_result)
            dialog.show_fit_checkbox.setChecked(True)
            dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            attached_figure.action_log.clear()
            dialog.do_it_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertEqual(dialog.result(), 0)
            self.assertIs(harness.namespace["signal_fit_result"], previous_result)
            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertEqual(
                sorted(trace["id"] for trace in subplot["traces"]),
                sorted(["trace0", colliding_fit_id, colliding_residual_id]),
            )
            self.assertTrue(
                any(
                    entry["action"]["trace_id"] == colliding_residual_id
                    for entry in attached_figure.action_log
                )
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_show_residuals_uses_existing_axes(self):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            dialog.show_fit_checkbox.setChecked(True)
            dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            result = harness.namespace["signal_fit_result"]
            figure_ir = attached_figure.figure_window.snapshot_state.figure_ir()

            self.assertEqual(len(figure_ir["layout"]["subplots"]), 1)
            self.assertEqual(len(attached_figure.figure.axes), 1)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 3)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                result.residual,
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_cancel_from_blank_opening_state_removes_introduced_attached_display(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )
        harness.write_procedures(
            """
            @hyde.fit_function(independent_vars=("x",))
            def line_fit(x, slope, offset):
                return slope * x + offset
            """
        )
        harness.reload_procedures()
        harness.set_namespace_value("signal", np.array([1.0, 3.0, 5.0, 7.0]))
        harness.set_namespace_value("time", np.array([0.0, 1.0, 2.0, 3.0]))
        dialog = create_curve_fit_dialog(
            manager.plugins["curve_fit"],
            app,
            figure_window=attached_figure.figure_window,
        )
        try:
            opening_subplot = attached_figure.figure_window.snapshot_state.figure_ir()[
                "layout"
            ]["subplots"][0]
            self.assertEqual(len(opening_subplot["traces"]), 1)
            self.assertFalse(opening_subplot["legend"])

            configure_line_fit_dialog(dialog)
            dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(attached_figure.figure.axes[0].lines), 3)

            dialog.reject()
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertEqual(len(subplot["traces"]), 1)
            self.assertFalse(subplot["legend"])
            self.assertEqual(len(attached_figure.figure.axes), 1)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 1)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_cancel_from_blank_opening_state_removes_introduced_attached_display_for_implicit_x(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
            implicit_x=True,
        )
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
                "time": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )
        harness.write_procedures(
            """
            @hyde.fit_function(independent_vars=("x",))
            def line_fit(x, slope, offset):
                return slope * x + offset
            """
        )
        harness.reload_procedures()
        harness.set_namespace_value("signal", np.array([1.0, 3.0, 5.0, 7.0]))
        harness.set_namespace_value("time", np.array([0.0, 1.0, 2.0, 3.0]))
        dialog = create_curve_fit_dialog(
            manager.plugins["curve_fit"],
            app,
            figure_window=attached_figure.figure_window
        )
        try:
            opening_subplot = attached_figure.figure_window.snapshot_state.figure_ir()[
                "layout"
            ]["subplots"][0]
            self.assertEqual(len(opening_subplot["traces"]), 1)
            self.assertIsNone(opening_subplot["traces"][0]["x_source"])

            configure_line_fit_dialog(dialog)
            self.assertEqual(
                dialog.x_data_rows[0]["combo"].currentText(),
                CALCULATED_X_NAME,
            )
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)

            dialog.cancel_button.click()
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertEqual(len(subplot["traces"]), 1)
            self.assertIsNone(subplot["traces"][0]["x_source"])
            self.assertEqual(len(attached_figure.figure.axes), 1)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 1)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_cancel_removes_preview_when_figure_snapshot_lags_behind_actions(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)
        attach_namespace_view_service(
            manager,
            {
                "signal": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                },
            },
        )
        harness.write_procedures(
            """
            @hyde.fit_function(independent_vars=("x",))
            def line_fit(x, slope, offset):
                return slope * x + offset
            """
        )
        harness.reload_procedures()
        harness.set_namespace_value("signal", np.array([1.0, 3.0, 5.0, 7.0]))
        figure_context = DeferredFigureContext(
            figure_ir=figure_ir_with_implicit_x_trace("signal")
        )
        dialog = create_curve_fit_dialog(
            manager.plugins["curve_fit"],
            app,
            figure_context=figure_context,
        )
        try:
            configure_line_fit_dialog(dialog)

            self.assertEqual(len(figure_context.pending_actions), 1)
            figure_context.flush_actions()
            self.assertEqual(
                len(figure_context.figure_ir()["layout"]["subplots"][0]["traces"]),
                2,
            )

            dialog.cancel_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(figure_context.pending_actions), 1)
            figure_context.flush_actions()
            self.assertEqual(
                len(figure_context.figure_ir()["layout"]["subplots"][0]["traces"]),
                1,
            )
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_cancel_restores_opening_attached_display_state(self):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        manager, app, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        reopening_dialog = None
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            dialog.show_fit_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()
            dialog.do_it_button.click()
            QtWidgets.QApplication.processEvents()

            reopening_dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit"],
                app,
                figure_window=attached_figure.figure_window,
            )
            configure_line_fit_dialog(reopening_dialog)
            reopening_dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            reopening_dialog.show_fit_checkbox.setChecked(False)
            reopening_dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                harness.namespace["signal_fit_result"].residual,
            )

            reopening_dialog.cancel_button.click()
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertEqual(len(subplot["traces"]), 2)
            self.assertEqual(len(attached_figure.figure.axes), 1)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                harness.namespace["signal_fit_result"].best_fit,
            )
        finally:
            if reopening_dialog is not None:
                reopening_dialog.close()
            else:
                dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_reopen_with_hidden_legend_preserves_hidden_legend_state(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        manager, app, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        reopening_dialog = None
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            dialog.show_fit_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()
            dialog.accept()
            dialog.close()

            attached_figure.figure_window.request_figure_action(
                {
                    "type": "set_legend_visible",
                    "subplot_id": "subplot0",
                    "visible": False,
                }
            )
            hidden_legend_subplot = attached_figure.figure_window.snapshot_state.figure_ir()[
                "layout"
            ]["subplots"][0]
            self.assertFalse(hidden_legend_subplot["legend"])
            self.assertEqual(len(hidden_legend_subplot["traces"]), 2)

            reopening_dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit"],
                app,
                figure_window=attached_figure.figure_window,
            )
            configure_line_fit_dialog(reopening_dialog)
            reopening_dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertFalse(subplot["legend"])
            self.assertEqual(len(subplot["traces"]), 2)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)

            finish_line_edit(
                coefficient_row_widgets(reopening_dialog, "offset")["initial"],
                "0.5",
            )

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertFalse(subplot["legend"])
            self.assertEqual(len(subplot["traces"]), 2)
        finally:
            if reopening_dialog is not None:
                reopening_dialog.close()
            else:
                dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_live_target_change_restores_previous_target_before_handoff(
        self,
    ):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            previous_signal_result = object()
            previous_alternate_result = object()
            harness.set_namespace_value("signal_fit_result", previous_signal_result)
            harness.set_namespace_value(
                "alternate_fit_result",
                previous_alternate_result,
            )

            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(type(harness.namespace["signal_fit_result"]).__name__, "ModelResult")

            harness.execution_service.calls.clear()
            dialog.fit_result_target_combo.setEditText("alternate_fit_result")
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(harness.execution_service.calls), 1)
            self.assertIs(
                harness.namespace["signal_fit_result"],
                previous_signal_result,
            )
            self.assertIsNot(
                harness.namespace["alternate_fit_result"],
                previous_alternate_result,
            )
            self.assertEqual(
                type(harness.namespace["alternate_fit_result"]).__name__,
                "ModelResult",
            )
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_live_failure_retains_last_successful_result_and_blocks_do_it_until_valid_again(
        self,
    ):
        _, _, harness, dialog = create_configured_line_fit_dialog(include_weights=True)
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            successful_result = harness.namespace["signal_fit_result"]
            harness.execution_service.calls.clear()
            dialog.weighting_combo.setCurrentText("weights")
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(harness.execution_service.calls), 1)
            self.assertIs(harness.namespace["signal_fit_result"], successful_result)
            self.assertEqual(dialog.result(), 0)
            self.assertFalse(dialog.do_it_button.isEnabled())
            self.assertIn("Curve Fit execution failed:", dialog.status_label.text())
            self.assertIn(
                harness.execution_service.last_error_message.strip(),
                dialog.status_label.text(),
            )

            harness.execution_service.calls.clear()
            dialog.weighting_combo.setCurrentText("")
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(harness.execution_service.calls), 1)
            self.assertTrue(dialog.do_it_button.isEnabled())
            self.assertEqual(dialog.status_label.text(), "")
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_live_target_handoff_failure_restores_previous_target_and_preserves_new_target_opening_state(
        self,
    ):
        _, _, harness, dialog = create_configured_line_fit_dialog(include_weights=True)
        try:
            original_signal_result = object()
            original_alternate_result = object()
            harness.set_namespace_value("signal_fit_result", original_signal_result)
            harness.set_namespace_value(
                "alternate_fit_result",
                original_alternate_result,
            )

            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(
                type(harness.namespace["signal_fit_result"]).__name__,
                "ModelResult",
            )
            self.assertIs(
                harness.namespace["alternate_fit_result"],
                original_alternate_result,
            )

            harness.execution_service.calls.clear()
            dialog.suppress_screen_updates_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()
            dialog.weighting_combo.setCurrentText("weights")
            QtWidgets.QApplication.processEvents()
            dialog.fit_result_target_combo.setEditText("alternate_fit_result")
            QtWidgets.QApplication.processEvents()
            harness.execution_service.calls.clear()

            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(harness.execution_service.calls), 1)
            self.assertIs(
                harness.namespace["signal_fit_result"],
                original_signal_result,
            )
            self.assertIs(
                harness.namespace["alternate_fit_result"],
                original_alternate_result,
            )
            self.assertFalse(dialog.do_it_button.isEnabled())
            self.assertIn("Curve Fit execution failed:", dialog.status_label.text())
            self.assertIn(
                harness.execution_service.last_error_message.strip(),
                dialog.status_label.text(),
            )
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_dialog_leaving_live_mode_clears_stale_live_failure_status(
        self,
    ):
        _, _, harness, dialog = create_configured_line_fit_dialog(include_weights=True)
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            dialog.weighting_combo.setCurrentText("weights")
            QtWidgets.QApplication.processEvents()

            self.assertFalse(dialog.do_it_button.isEnabled())
            self.assertIn("Curve Fit execution failed:", dialog.status_label.text())

            dialog.suppress_screen_updates_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(dialog.execution_mode(), "suppressed")
            self.assertTrue(dialog.do_it_button.isEnabled())
            self.assertEqual(dialog.status_label.text(), "")
        finally:
            dialog.close()
            harness.close()


if __name__ == "__main__":
    unittest.main()
