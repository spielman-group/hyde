from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.hyde_interactive_widget import active_interactive_window
from hyde.user_interface.plugin_tools import HydePlugin
from hyde.user_interface.plugins.figure.window import FigureWindow
from hyde.user_interface.window_naming import resolve_requested_name

from .dialogs import CurveFitDialog
from .fit_function_scaffolding import (
    CurveFitCatalogError,
    validate_fit_function_name,
    write_fit_function_scaffold,
)


class CurveFitCatalogService(QtCore.QObject):
    catalog_changed = QtCore.Signal()

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self._fit_functions = []
        self._rejected_fit_functions = []

    def fit_functions(self):
        return tuple(dict(entry) for entry in self._fit_functions)

    def rejected_fit_functions(self):
        return tuple(dict(entry) for entry in self._rejected_fit_functions)

    def refresh(self):
        python_execution_service = self.plugin.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        python_execution_service.execute_hidden(
            "hyde.recreation_registry.publish_registry('fit_function')"
        )
        return True

    def default_new_fit_function_name(self):
        existing_names = [
            entry["name"] for entry in self._fit_functions
        ] + [
            entry["name"] for entry in self._rejected_fit_functions
        ]
        return resolve_requested_name("FitFunction", existing_names)

    def scaffold_new_fit_function(self, function_name):
        validated_name = validate_fit_function_name(function_name)
        procedures_service = self.plugin.services.get("project_procedures_service")
        if procedures_service is None:
            raise CurveFitCatalogError(
                "Curve Fit requires an active project procedures/__init__.py path."
            )
        procedures_init = procedures_service.procedures_init()
        if not procedures_init:
            raise CurveFitCatalogError(
                "Curve Fit requires an active project procedures/__init__.py path."
            )
        write_fit_function_scaffold(procedures_init, validated_name)
        procedures_service.reload_procedures()
        self.refresh()
        return validated_name

    def replace_catalog(self, fit_functions, rejected_fit_functions):
        next_fit_functions = [dict(entry) for entry in fit_functions]
        next_rejected = [dict(entry) for entry in rejected_fit_functions]
        if (
            next_fit_functions == self._fit_functions
            and next_rejected == self._rejected_fit_functions
        ):
            return
        self._fit_functions = next_fit_functions
        self._rejected_fit_functions = next_rejected
        self.catalog_changed.emit()


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.catalog_service = CurveFitCatalogService(self)

    def get_services(self):
        return {"curve_fit_catalog_service": self.catalog_service}

    def get_menu_contributions(self):
        return [
            {
                "location": "analysis",
                "group": "analysis_tools",
                "order": 10,
                "name": "Curve Fit...",
                "action": self.show_curve_fit_dialog,
            }
        ]

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "kernel_message": self.on_kernel_message,
            "project_activated": self.on_project_activated,
        }

    def on_enter_no_project_state(self, data):
        del data
        self.catalog_service.replace_catalog([], [])

    def on_project_activated(self, data):
        del data
        self.catalog_service.refresh()

    def on_kernel_message(self, payload):
        if payload.get("task") != "FIT_FUNCTIONS_RESPONSE":
            return
        data = payload.get("data", {})
        self.catalog_service.replace_catalog(
            data.get("entries", []),
            data.get("rejected", []),
        )

    def _active_curve_fit_figure_window(self):
        figure_window = active_interactive_window(self.services, FigureWindow)
        if figure_window is None:
            return None
        snapshot_state = getattr(figure_window, "snapshot_state", None)
        if snapshot_state is None or snapshot_state.figure_ir() is None:
            return None
        if figure_window.services.get("send_figure_action") is None:
            return None
        return figure_window

    def show_curve_fit_dialog(self, checked=False):
        del checked
        figure_window = self._active_curve_fit_figure_window()
        dialog = CurveFitDialog(
            figure_window=figure_window,
            services=self.services,
            parent=self.services.get("ui"),
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted
