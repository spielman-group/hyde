import copy
import contextlib
import io
import os
import sys
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
from hyde.user_interface.plugins.kernel_runtime import KernelRequest
from tests.kernel_fakes import KernelRequestRecorder
from hyde import project_tools
from hyde.features.lmfit_features import CALCULATED_X_NAME
from hyde.matplotlib_backend import (
    _import_first_class_figure_ir,
    figure_snapshot_payload,
)
from hyde.user_interface.base_hyde_widgets import active_interactive_window
from hyde.user_interface.main import HydeApp
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.shared.core import log_hyde_dispatch_debug
from hyde.user_interface.plugins.figure_control_dialog.figure_dialog_IR import (
    FigureDialogIR,
)
from hyde.user_interface.plugins.figure_interactive.context import EditableFigureContext
from hyde.user_interface.shared.plugin import HydePluginManager
from hyde.user_interface.plugins.curve_fit_dialog import Plugin as CurveFitPlugin
from hyde.user_interface.plugins.curve_fit_dialog.curve_fit_IR import CurveFitIR
from hyde.user_interface.plugins.curve_fit_dialog.dialogs import CurveFitDialog
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow


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

ATTACHED_FIGURE_HARNESSES = []


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
    app.emit_plugin_event = lambda name, data=None: HydeApp.emit_plugin_event(
        app,
        name,
        data,
    )
    app.show_status_message = lambda label: label
    app.clear_status_message = lambda: None
    app.process_tree = object()
    app.show_plugin_window = lambda key: key
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
    app.get_current_app_ir = lambda: HydeAppIR(
        current_project_dir=app.get_current_project_dir()
    )
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


class ProcedureExecutionHarness(KernelRequestRecorder):
    def __init__(self, plugin):
        self.plugin = plugin
        # execute_procedures_bootstrap deliberately chdirs into the project and
        # puts it on sys.path, and deliberately never undoes that: a running
        # Hyde GUI resolves `procedures/` imports from there. This harness
        # points that behaviour at a temporary directory it later deletes, so
        # it has to restore the process itself. Leaving the CWD inside a
        # deleted directory makes os.getcwd() raise, which kills every test
        # module imported after this one in the same process.
        self.entry_cwd = os.getcwd()
        self.entry_sys_path = list(sys.path)
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
        # Restore before the delete: chdir out of the directory first, or the
        # process is left standing in a path that no longer exists.
        os.chdir(self.entry_cwd)
        sys.path[:] = self.entry_sys_path
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
            for attached_figure in list(ATTACHED_FIGURE_HARNESSES):
                attached_figure.refresh_snapshot()
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


class FakeExecutionService(KernelRequestRecorder):
    def __init__(self, harness):
        self.harness = harness
        self.calls = []
        self.visible_calls = []
        self.last_error_message = ""

    def execute_hidden(self, code, silent=True):
        log_hyde_dispatch_debug("hidden", code)
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
    plugin = manager.plugins["curve_fit_dialog"]
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

    with patch.object(CurveFitDialog, "exec", new=record_exec):
        action = manager.services["lookup_menu_action"]("analysis", "Curve Fit...")
        assert action is not None
        action.trigger()

    return launched["dialog"]


def tab_titles(dialog):
    return [
        dialog.ui.tab_widget.tabText(index)
        for index in range(dialog.ui.tab_widget.count())
    ]


def show_output_options_tab(dialog):
    dialog.ui.tab_widget.setCurrentIndex(3)
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
    manager.plugins["curve_fit_dialog"].services["namespace_view_service"] = service
    return service


class FakeEditableFigureContext:
    def __init__(self, *, figure_number=7, figure_ir=None):
        self.figure_number = int(figure_number)
        self._figure_ir = FigureIR(
            figure_state=(
                copy.deepcopy(
                    figure_ir_without_traces() if figure_ir is None else figure_ir
                )
            ),
            figure_number=self.figure_number,
        )

    def current_figure_ir(self):
        return copy.deepcopy(self._figure_ir)

    def current_size_inches(self):
        size = self._figure_ir.figure_size()
        if size in (None, ""):
            return None
        return (float(size[0]), float(size[1]))

    def has_supported_traces(self):
        return self._figure_ir.has_supported_traces()

    def supported_trace_records(self):
        return self._figure_ir.supported_trace_records()

    def figure_name(self):
        return f"Figure{self.figure_number}"


class FigureIROnlyContext:
    def __init__(self, figure_ir, *, figure_name=None):
        self._figure_ir = copy.deepcopy(figure_ir)
        self.figure_number = int(self._figure_ir.figure_number)
        self._figure_name = (
            str(figure_name)
            if figure_name is not None
            else f"Figure{self.figure_number}"
        )

    def current_figure_ir(self):
        return copy.deepcopy(self._figure_ir)

    def current_size_inches(self):
        size = self._figure_ir.figure_size()
        if size in (None, ""):
            return None
        return (float(size[0]), float(size[1]))

    def has_supported_traces(self):
        return self._figure_ir.has_supported_traces()

    def supported_trace_records(self):
        return self._figure_ir.supported_trace_records()

    def figure_name(self):
        return self._figure_name


def attach_figure_context_service(manager, figure_context):
    figure_context_service = type(
        "FigureContextService",
        (),
        {"active_editable_figure": (lambda _self: figure_context)},
    )()
    manager.services["figure_context_service"] = figure_context_service
    manager.plugins["curve_fit_dialog"].services["figure_context_service"] = (
        figure_context_service
    )
    return figure_context_service


def make_figure_window(figure_ir):
    figure_window = FigureWindow(figure_number=7, services={})
    figure_window.widget_ir = FigureIR(
        figure_state=copy.deepcopy(figure_ir),
        figure_number=figure_window.figure_number,
    )
    return figure_window


def create_curve_fit_dialog(plugin, app, *, figure_context=None, figure_window=None):
    if figure_context is None and figure_window is not None:
        figure_context = EditableFigureContext(figure_window)
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


class AttachedFigureHarness:
    def __init__(
        self,
        x_values,
        y_values,
        *,
        y_label="signal",
        implicit_x=False,
    ):
        import matplotlib

        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as plt

        self._pyplot = plt
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
        self.figure_window = FigureWindow(figure_number=self.figure.number, services={})
        ATTACHED_FIGURE_HARNESSES.append(self)
        self.refresh_snapshot()

    def refresh_snapshot(self):
        imported_ir, import_warning = _import_first_class_figure_ir(self.figure)
        self.figure._hyde_ir = imported_ir
        self.figure._hyde_import_warning = import_warning
        self.figure_window.update_payload(
            {
                "figure_number": self.figure.number,
                "snapshot": figure_snapshot_payload(self.figure, self.figure.number),
            }
        )

    def close(self):
        if self in ATTACHED_FIGURE_HARNESSES:
            ATTACHED_FIGURE_HARNESSES.remove(self)
        self._pyplot.close(self.figure)


def create_configured_line_fit_dialog(
    *,
    include_weights=False,
    figure_context=None,
    figure_window=None,
):
    manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
    manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        manager.plugins["curve_fit_dialog"],
        app,
        figure_context=figure_context,
        figure_window=figure_window,
    )
    configure_line_fit_dialog(dialog)
    return manager, app, harness, dialog


class TestProcedureExecutionHarnessLeavesTheProcessUsable(unittest.TestCase):
    """The harness runs the product's real project bootstrap, which is designed
    to chdir into the project directory and put it on sys.path and to stay
    there, because that is how a running Hyde GUI resolves `procedures/`
    imports. The harness borrows that behaviour against a temporary directory
    it then deletes, so it -- not the product -- has to put the process back.

    Without this, every test module loaded afterwards in the same process dies
    at import with FileNotFoundError from `os.getcwd()`, and the leaked
    sys.path entries pile up one pair per test.
    """

    def test_harness_close_restores_cwd_and_sys_path(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
        plugin = manager.plugins["curve_fit_dialog"]

        original_cwd = os.getcwd()
        original_sys_path = list(sys.path)

        harness = ProcedureExecutionHarness(plugin)
        project_dir = harness.project_dir
        try:
            harness.reload_procedures()
            # The bootstrap really did move the process, or this test is vacuous.
            self.assertEqual(os.path.realpath(os.getcwd()), os.path.realpath(project_dir))
            self.assertIn(os.path.join(os.getcwd(), "procedures"), sys.path)
        finally:
            harness.close()

        self.assertEqual(os.getcwd(), original_cwd)
        self.assertEqual(sys.path, original_sys_path)
        self.assertFalse(os.path.exists(project_dir))

    def test_module_run_leaks_no_temporary_directories_onto_sys_path(self):
        # The blast radius check: whatever this module does internally, a later
        # module in the same process must still be able to import. Python keeps
        # its own absent entries on sys.path (the stdlib zip), so this looks
        # only for leaked temporary project directories.
        os.getcwd()
        temp_root = os.path.realpath(tempfile.gettempdir())
        leaked = [
            entry
            for entry in sys.path
            if entry
            and os.path.realpath(entry).startswith(temp_root)
            and not os.path.exists(entry)
        ]
        self.assertEqual([], leaked)


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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertEqual(
            [action.text() for action in app.ui.menuAnalysis.actions()],
            ["Curve Fit..."],
        )

    def test_curve_fit_action_with_no_active_figure_opens_unattached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
                dialog.ui.status_title_label.text(),
                "Status",
            )
            self.assertEqual(dialog.ok_button.text(), "OK")
            self.assertEqual(dialog.to_ipython_button.text(), "To IPython")
            self.assertFalse(dialog.to_ipython_button.isEnabled())
            self.assertTrue(dialog.to_ipython_button.isVisibleTo(dialog))
            self.assertEqual(dialog.copy_button.text(), "Copy")
            self.assertEqual(dialog.cancel_button.text(), "Cancel")
            show_output_options_tab(dialog)
            self.assertTrue(dialog.show_fit_checkbox.isVisible())
            self.assertFalse(dialog.show_fit_checkbox.isEnabled())
            self.assertTrue(dialog.show_residuals_checkbox.isVisible())
            self.assertFalse(dialog.show_residuals_checkbox.isEnabled())
            dialog.close()
        finally:
            harness.close()

    def test_project_activation_does_not_dispatch_fit_function_registry_refresh(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            plugin = manager.plugins["curve_fit_dialog"]
            execution_service = manager.services["python_execution_service"]
            execution_service.calls.clear()

            plugin.on_project_activated({"project_dir": harness.project_dir})

            self.assertEqual(execution_service.calls, [])
            self.assertIn(
                "line",
                [
                    entry["name"]
                    for entry in manager.services["curve_fit_catalog_service"].fit_functions()
                ],
            )
        finally:
            harness.close()

    def test_curve_fit_dialog_preserves_static_surface_after_ui_port(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            dialog = trigger_curve_fit_action_and_capture_dialog(manager)

            self.assertEqual(
                tab_titles(dialog),
                [
                    "Function and Data",
                    "Data Options",
                    "Coefficients",
                    "Output Options",
                ],
            )
            self.assertEqual(dialog.preview_mode_combo.currentText(), "Commands")
            self.assertEqual(dialog.status_label.text(), "Select Y data.")
            dialog.close()
        finally:
            harness.close()

    def test_curve_fit_action_with_active_figure_context_opens_attached_dialog(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        harness = configure_curve_fit_runtime(app, manager)

        try:
            figure_context = FakeEditableFigureContext(
                figure_ir=figure_ir_without_traces()
            )
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
            implicit_x=True,
        )

        try:
            dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit_dialog"],
                app,
                figure_window=attached_figure.figure_window,
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

                dialog.ok_button.click()
                QtWidgets.QApplication.processEvents()

                self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
                self.assertIn("signal_fit_result", harness.namespace)
                self.assertEqual(harness.execution_service.last_error_message, "")
            finally:
                dialog.close()
        finally:
            harness.close()
            attached_figure.close()

    def test_new_fit_function_button_scaffolds_reloads_and_selects_new_function(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

    def test_curve_fit_catalog_service_uses_reload_published_catalog_and_default_name(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
            self.assertEqual(execution_service.calls, [])
        finally:
            harness.close()

    def test_curve_fit_catalog_service_scaffolds_through_project_procedures_service(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
        app = make_plugin_host(manager)
        plugin = manager.plugins["curve_fit_dialog"]
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
                manager.plugins["curve_fit_dialog"],
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
                manager.plugins["curve_fit_dialog"],
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
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

    def test_curve_fit_copy_copies_canonical_lower_text(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
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

                dialog.copy_button.click()
                self.assertEqual(clipboard.text(), dialog.preview_string())
                self.assertNotEqual(
                    clipboard.text(),
                    dialog.lower_text_edit.toPlainText(),
                )
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_requires_usable_free_parameter_values_for_ok(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                self.assertEqual(dialog.coefficients_table.rowCount(), 2)
                self.assertFalse(dialog.ok_button.isEnabled())
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
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
                self.assertTrue(dialog.ok_button.isEnabled())
                self.assertEqual(dialog.status_label.text(), "")
            finally:
                dialog.close()
        finally:
            harness.close()

    def test_curve_fit_dialog_invalid_free_parameter_does_not_preview_executable_fit(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
            try:
                dialog.fit_function_combo.setCurrentIndex(
                    dialog.fit_function_combo.findText("line_fit")
                )
                QtWidgets.QApplication.processEvents()

                finish_line_edit(
                    coefficient_row_widgets(dialog, "slope")["expr"],
                    "2 * offset",
                )

                self.assertFalse(dialog.ok_button.isEnabled())
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

            self.assertFalse(dialog.ok_button.isEnabled())
            self.assertIn(
                "valid Python identifier",
                dialog.status_label.text(),
            )
            self.assertNotIn("bad-name =", dialog.lower_text_edit.toPlainText())
            self.assertNotIn(".fit(", dialog.lower_text_edit.toPlainText())

            dialog.copy_button.click()
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

            self.assertTrue(dialog.ok_button.isEnabled())
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

            self.assertFalse(dialog.to_ipython_button.isEnabled())
            self.assertTrue(dialog.to_ipython_button.isVisibleTo(dialog))
            self.assertIn(
                "signal_fit_result = signal_fit_model.fit(",
                dialog.lower_text_edit.toPlainText(),
            )

            dialog.copy_button.click()

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

    def test_curve_fit_equation_preview_keeps_to_ipython_disabled_but_ok_available(self):
        _, _, harness, dialog = create_configured_line_fit_dialog()
        try:
            clipboard = QtWidgets.QApplication.clipboard()
            dialog.preview_mode_combo.setCurrentText("Equation")
            QtWidgets.QApplication.processEvents()

            self.assertFalse(dialog.to_ipython_button.isEnabled())
            self.assertTrue(dialog.ok_button.isEnabled())
            self.assertIn("def line_fit(", dialog.lower_text_edit.toPlainText())

            dialog.copy_button.click()
            self.assertEqual(clipboard.text(), dialog.preview_string())
            self.assertIn("signal_fit_result = signal_fit_model.fit(", clipboard.text())
            self.assertNotEqual(clipboard.text(), dialog.lower_text_edit.toPlainText())
        finally:
            dialog.close()
            harness.close()

    def test_curve_fit_ir_expression_owned_coefficients_feed_preview_and_commit_lowering(
        self,
    ):
        array_metadata = {
            "python_type": "ndarray",
            "numpy_type": "Array",
            "ndim": 1,
            "numpy_kind": "f",
        }
        widget_ir = CurveFitIR()
        widget_ir.set_context(
            {
                "fit_functions": [
                    {
                        "name": "line_fit",
                        "callable_ref": "line_fit",
                        "independent_vars": ["x"],
                        "parameters": ["slope", "offset"],
                    }
                ],
                "namespace_view": {
                    "signal": array_metadata,
                    "time": array_metadata,
                },
                "trace_records": [],
            }
        )
        widget_ir.apply_action(
            {
                "type": "set",
                "path": ("settings", "fit_function_name"),
                "value": "line_fit",
            }
        )
        widget_ir.apply_action(
            {"type": "set", "path": ("settings", "y_name"), "value": "signal"}
        )
        widget_ir.set_x_name("x", "time")
        widget_ir.set_fit_result_name("signal_fit_result", locked=True)
        widget_ir.set_coefficient_field("slope", "expr", "2 * offset")
        widget_ir.set_coefficient_field("offset", "initial_value", "1.5")

        widget_ir.set_commit_command()
        commit_preview = widget_ir.python_source(log=False)
        widget_ir.set_preview_command(preview_target_name="_preview_fit")
        guessed_preview = widget_ir.python_source(log=False)

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

    def test_curve_fit_ir_python_source_selects_preview_commit_live_store_and_restore_commands(
        self,
    ):
        array_metadata = {
            "python_type": "ndarray",
            "numpy_type": "Array",
            "ndim": 1,
            "numpy_kind": "f",
        }
        widget_ir = CurveFitIR()
        widget_ir.set_context(
            {
                "fit_functions": [
                    {
                        "name": "line_fit",
                        "callable_ref": "line_fit",
                        "independent_vars": ["x"],
                        "parameters": ["slope", "offset"],
                    }
                ],
                "namespace_view": {
                    "signal": array_metadata,
                    "time": array_metadata,
                },
                "trace_records": [],
            }
        )
        widget_ir.apply_action(
            {
                "type": "set",
                "path": ("settings", "fit_function_name"),
                "value": "line_fit",
            }
        )
        widget_ir.apply_action(
            {"type": "set", "path": ("settings", "y_name"), "value": "signal"}
        )
        widget_ir.set_x_name("x", "time")
        widget_ir.set_fit_result_name("signal_fit_result", locked=True)
        widget_ir.set_coefficient_field("slope", "initial_value", "2.0")
        widget_ir.set_coefficient_field("offset", "initial_value", "1.0")

        widget_ir.set_preview_command(preview_target_name="_preview_fit")
        preview_source = widget_ir.python_source(log=False)

        widget_ir.set_commit_command()
        commit_source = widget_ir.python_source(log=False)

        widget_ir.set_live_command(
            previous_target_name="old_fit_result",
            restore_store_name="_restore_store",
            missing_sentinel_name="_missing",
        )
        live_source = widget_ir.python_source(log=False)

        widget_ir.set_store_target_command(
            "signal_fit_result",
            restore_store_name="_restore_store",
            missing_sentinel_name="_missing",
        )
        store_source = widget_ir.python_source(log=False)

        widget_ir.set_restore_target_command(
            "signal_fit_result",
            restore_store_name="_restore_store",
            missing_sentinel_name="_missing",
        )
        restore_source = widget_ir.python_source(log=False)

        self.assertIn(
            "_preview_fit.best_fit = line_fit(x=time, slope=2.0, offset=1.0)",
            preview_source,
        )
        self.assertIn(
            "signal_fit_result = signal_fit_model.fit(signal, params=signal_fit_params, x=time)",
            commit_source,
        )
        self.assertIn(
            "_restore_store = globals().setdefault('_restore_store', {})",
            live_source,
        )
        self.assertIn(
            "globals().pop('old_fit_result', None)",
            live_source,
        )
        self.assertIn(
            "if 'signal_fit_result' not in _restore_store:",
            store_source,
        )
        self.assertIn(
            "_hyde_lmfit_restore_target_state = _restore_store.pop(",
            restore_source,
        )

    def test_curve_fit_ir_python_source_uses_owned_context_snapshot(self):
        array_metadata = {
            "python_type": "ndarray",
            "numpy_type": "Array",
            "ndim": 1,
            "numpy_kind": "f",
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
            "namespace_view": {
                "signal": dict(array_metadata),
                "time": dict(array_metadata),
            },
            "trace_records": [],
        }
        widget_ir = CurveFitIR()
        widget_ir.set_context(context)
        widget_ir.apply_action(
            {
                "type": "set",
                "path": ("settings", "fit_function_name"),
                "value": "line_fit",
            }
        )
        widget_ir.apply_action(
            {"type": "set", "path": ("settings", "y_name"), "value": "signal"}
        )
        widget_ir.set_x_name("x", "time")
        widget_ir.set_fit_result_name("signal_fit_result", locked=True)
        widget_ir.set_coefficient_field("slope", "initial_value", "2.0")
        widget_ir.set_coefficient_field("offset", "initial_value", "1.0")
        widget_ir.set_preview_command(preview_target_name="_preview_fit")

        context["fit_functions"][0]["callable_ref"] = "mutated_fit"

        preview_source = widget_ir.python_source(log=False)

        self.assertIn(
            "_preview_fit = type('_HydeLmfitPreview', (), {})()",
            preview_source,
        )
        self.assertIn(
            "_preview_fit.best_fit = line_fit(x=time, slope=2.0, offset=1.0)",
            preview_source,
        )
        self.assertNotIn("mutated_fit", preview_source)

    def test_curve_fit_dialog_data_options_update_preview_and_execution_mode_without_running(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
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

    def test_curve_fit_dialog_suppressed_ok_runs_one_hidden_fit_and_creates_result_object(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
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

                dialog.ok_button.click()
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

    def test_curve_fit_dialog_suppressed_ok_recreates_existing_result_target_once(
        self,
    ):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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

            dialog = create_curve_fit_dialog(manager.plugins["curve_fit_dialog"], app)
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

                dialog.ok_button.click()
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

    def test_curve_fit_dialog_live_mode_reruns_immediately_and_ok_does_not_rerun(
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

            dialog.ok_button.click()
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

    def test_curve_fit_dialog_attached_display_works_with_direct_figure_ir_context(
        self,
    ):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        figure_ir = EditableFigureContext(attached_figure.figure_window).current_figure_ir()
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_context=FigureIROnlyContext(
                figure_ir,
                figure_name=attached_figure.figure_window.snapshot_state.default_macro_name(),
            )
        )
        try:
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            dialog.show_fit_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                harness.namespace["signal_fit_result"].best_fit,
            )

            dialog.cancel_button.click()
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertEqual(len(subplot["traces"]), 1)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 1)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_preview_and_send_to_ipython_use_same_patch_block(
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
            dialog.services["visible_terminal_service"] = harness.execution_service
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()
            harness.execution_service.calls.clear()
            dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            preview = dialog.lower_text_edit.toPlainText()
            self.assertIn("fig = hyde.get_figure('CurveFitAttachedFigure')", preview)
            self.assertIn("ax = fig.axes[0]", preview)
            self.assertIn("ax.plot(", preview)
            self.assertTrue(dialog.to_ipython_button.isEnabled())

            hidden_call_count = len(harness.execution_service.calls)
            dialog.to_ipython_button.click()

            self.assertEqual(harness.execution_service.visible_calls[-1], preview)
            self.assertEqual(len(harness.execution_service.calls), hidden_call_count)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_display_uses_hidden_python_patch_instead_of_figure_actions(
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
            harness.execution_service.calls.clear()

            dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            self.assertTrue(harness.execution_service.calls)
            command = harness.execution_service.calls[-1]["code"]
            self.assertIn("fig = hyde.get_figure('CurveFitAttachedFigure')", command)
            self.assertIn("ax.plot(", command)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 3)
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
                manager.plugins["curve_fit_dialog"],
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

            harness.execution_service.calls.clear()
            dialog.ok_button.click()
            QtWidgets.QApplication.processEvents()

            self.assertTrue(harness.execution_service.calls)
            self.assertIn(
                "fig = hyde.get_figure('CurveFitAttachedFigure')",
                harness.execution_service.calls[-1]["code"],
            )
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 2)
            np.testing.assert_allclose(
                attached_figure.figure.axes[0].lines[-1].get_ydata(),
                harness.namespace["signal_fit_result"].best_fit,
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
            manager.plugins["curve_fit_dialog"],
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
            hidden_calls_before_cancel = len(harness.execution_service.calls)

            dialog.reject()
            QtWidgets.QApplication.processEvents()

            subplot = attached_figure.figure_window.snapshot_state.figure_ir()["layout"][
                "subplots"
            ][0]
            self.assertEqual(len(subplot["traces"]), 1)
            self.assertFalse(subplot["legend"])
            self.assertEqual(len(attached_figure.figure.axes), 1)
            self.assertEqual(len(attached_figure.figure.axes[0].lines), 1)
            self.assertGreater(len(harness.execution_service.calls), hidden_calls_before_cancel)
            self.assertIn(
                "fig = hyde.get_figure('CurveFitAttachedFigure')",
                harness.execution_service.calls[-1]["code"],
            )
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_hidden_curve_fit_attached_patch_logs_through_transport_debug_channel(
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
            with self.assertLogs("hyde", level="DEBUG") as logs:
                dialog.show_residuals_checkbox.setChecked(True)
                QtWidgets.QApplication.processEvents()
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

        output = "\n".join(logs.output)
        self.assertIn("[Hyde state] TransportDispatchState", output)
        self.assertIn("'mode': 'hidden'", output)
        self.assertIn("python:", output)
        self.assertIn("fig = hyde.get_figure('CurveFitAttachedFigure')", output)
        self.assertIn(".residual = signal - ", output)

    def test_curve_fit_dialog_attached_preview_edit_uses_one_hidden_logged_command_block(
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
            harness.execution_service.calls.clear()

            with self.assertLogs("hyde", level="DEBUG") as logs:
                finish_line_edit(
                    coefficient_row_widgets(dialog, "offset")["initial"],
                    "0.5",
                )

            self.assertEqual(len(harness.execution_service.calls), 1)
            command = harness.execution_service.calls[-1]["code"]
            self.assertIn("fig = hyde.get_figure('CurveFitAttachedFigure')", command)
            self.assertIn(".best_fit = line_fit(", command)
            self.assertIn(".residual = signal - ", command)

            output = "\n".join(logs.output)
            self.assertIn("[Hyde state] TransportDispatchState", output)
            self.assertIn("'mode': 'hidden'", output)
            self.assertIn(".best_fit = line_fit(", output)
            self.assertIn("fig = hyde.get_figure('CurveFitAttachedFigure')", output)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_uses_shared_figure_dialog_state_contract(self):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            self.assertIsInstance(dialog.widget_ir, CurveFitIR)
            self.assertIsInstance(dialog.widget_ir.figure_dialog_ir, FigureDialogIR)
            opening_state = dialog.opening_effective_state()
            initial_applied_state = dialog.applied_effective_state()
            self.assertIsInstance(dialog.current_figure_ir, FigureIR)
            self.assertEqual(
                dialog.widget_ir.opening_figure_ir.default_macro_name(),
                "CurveFitAttachedFigure",
            )
            self.assertEqual(
                [record["label"] for record in dialog.supported_trace_records()],
                ["signal", "signal_fit_result"],
            )
            self.assertEqual(
                [record["display_name"] for record in dialog.supported_trace_records()],
                ["signal: signal vs time", "signal_fit_result"],
            )
            self.assertEqual(
                dialog.supported_trace_record("signal_fit_result")["label"],
                "signal_fit_result",
            )

            dialog.show_residuals_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            updated_applied_state = dialog.applied_effective_state()
            self.assertNotEqual(updated_applied_state, initial_applied_state)
            self.assertEqual(
                [record["label"] for record in dialog.supported_trace_records()],
                ["signal", "signal_fit_result", "signal_fit_result_residuals"],
            )
            self.assertEqual(
                [record["display_name"] for record in dialog.supported_trace_records()],
                [
                    "signal: signal vs time",
                    "signal_fit_result",
                    "signal_fit_result_residuals",
                ],
            )

            dialog.reject()
            QtWidgets.QApplication.processEvents()

            self.assertEqual(dialog.applied_effective_state(), opening_state)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_attached_live_update_uses_one_attached_display_command_block(
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
            harness.execution_service.calls.clear()

            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(dialog.execution_mode(), "live")
            self.assertEqual(len(harness.execution_service.calls), 2)
            self.assertNotIn(
                "fig = hyde.get_figure('CurveFitAttachedFigure')",
                harness.execution_service.calls[0]["code"],
            )
            self.assertIn(
                "fig = hyde.get_figure('CurveFitAttachedFigure')",
                harness.execution_service.calls[1]["code"],
            )
            self.assertIn(".best_fit = line_fit(", harness.execution_service.calls[1]["code"])
            self.assertIn(".residual = signal - ", harness.execution_service.calls[1]["code"])
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_dialog_live_update_and_reject_use_widget_ir_python_source(
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
            dialog.widget_ir.set_context(dialog._context())
            dialog.widget_ir.set_live_command(
                previous_target_name=None,
                restore_store_name=dialog._live_restore_store_name,
                missing_sentinel_name=dialog._live_missing_sentinel_name,
            )
            expected_live = dialog.widget_ir.python_source(log=False)

            harness.execution_service.calls.clear()
            dialog.suppress_screen_updates_checkbox.setChecked(False)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(
                harness.execution_service.calls[0]["code"],
                expected_live,
            )

            dialog.widget_ir.set_context(dialog._context())
            dialog.widget_ir.set_restore_target_command(
                "signal_fit_result",
                restore_store_name=dialog._live_restore_store_name,
                missing_sentinel_name=dialog._live_missing_sentinel_name,
            )
            expected_restore = dialog.widget_ir.python_source(log=False)
            call_count_before_reject = len(harness.execution_service.calls)

            dialog.reject()
            QtWidgets.QApplication.processEvents()

            self.assertIn(
                expected_restore,
                [
                    call["code"]
                    for call in harness.execution_service.calls[call_count_before_reject:]
                ],
            )
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
        manager.plugins = {"curve_fit_dialog": CurveFitPlugin({})}
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
            manager.plugins["curve_fit_dialog"],
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

    def test_curve_fit_ok_rolls_back_when_the_commit_raises_in_the_kernel(self):
        """The snapshot exists for a fit that runs and fails.

        Dispatching only says a command was sent, so before the reply was read
        the rollback fired for a command that could not be sent and never for
        the case it was written for.
        """
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            dialog.show_fit_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()
            execution = harness.execution_service

            dialog.ok_button.click()
            QtWidgets.QApplication.processEvents()
            self.assertTrue(execution.kernel_requests)
            execution.calls.clear()

            execution.answer_last(KernelRequest.RAISED, "ValueError: fit diverged")
            QtWidgets.QApplication.processEvents()

            restored = [
                call["code"]
                for call in execution.calls
                if dialog._live_restore_store_name in call["code"]
            ]
            self.assertTrue(restored, execution.calls)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

    def test_curve_fit_ok_does_not_roll_back_when_the_commit_runs(self):
        attached_figure = AttachedFigureHarness(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([1.0, 3.0, 5.0, 7.0]),
        )
        _, _, harness, dialog = create_configured_line_fit_dialog(
            figure_window=attached_figure.figure_window
        )
        try:
            dialog.show_fit_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()
            execution = harness.execution_service

            dialog.ok_button.click()
            QtWidgets.QApplication.processEvents()
            execution.calls.clear()

            execution.answer_last()
            QtWidgets.QApplication.processEvents()

            self.assertEqual([], execution.calls)
        finally:
            dialog.close()
            harness.close()
            attached_figure.close()

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
            dialog.ok_button.click()
            QtWidgets.QApplication.processEvents()

            reopening_dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit_dialog"],
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

    def test_curve_fit_dialog_reopen_after_hidden_command_legend_change_preserves_hidden_legend_state(
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

            self.assertTrue(
                harness.execution_service.execute_hidden(
                    "fig = hyde.get_figure('CurveFitAttachedFigure')\n"
                    "legend = fig.axes[0].get_legend()\n"
                    "if legend is not None:\n"
                    "    legend.set_visible(False)"
                )
            )
            hidden_legend_subplot = attached_figure.figure_window.snapshot_state.figure_ir()[
                "layout"
            ]["subplots"][0]
            self.assertFalse(hidden_legend_subplot["legend"])
            self.assertEqual(len(hidden_legend_subplot["traces"]), 2)

            reopening_dialog = create_curve_fit_dialog(
                manager.plugins["curve_fit_dialog"],
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

    def test_curve_fit_dialog_live_failure_retains_last_successful_result_and_blocks_ok_until_valid_again(
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
            self.assertFalse(dialog.ok_button.isEnabled())
            self.assertIn("Curve Fit execution failed:", dialog.status_label.text())
            self.assertIn(
                harness.execution_service.last_error_message.strip(),
                dialog.status_label.text(),
            )

            harness.execution_service.calls.clear()
            dialog.weighting_combo.setCurrentText("")
            QtWidgets.QApplication.processEvents()

            self.assertEqual(len(harness.execution_service.calls), 1)
            self.assertTrue(dialog.ok_button.isEnabled())
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
            self.assertFalse(dialog.ok_button.isEnabled())
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

            self.assertFalse(dialog.ok_button.isEnabled())
            self.assertIn("Curve Fit execution failed:", dialog.status_label.text())

            dialog.suppress_screen_updates_checkbox.setChecked(True)
            QtWidgets.QApplication.processEvents()

            self.assertEqual(dialog.execution_mode(), "suppressed")
            self.assertTrue(dialog.ok_button.isEnabled())
            self.assertEqual(dialog.status_label.text(), "")
        finally:
            dialog.close()
            harness.close()


if __name__ == "__main__":
    unittest.main()
