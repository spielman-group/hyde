from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.shared.core import RuntimeCommandState
from hyde.user_interface.shared.plugin import HydePlugin
from hyde.user_interface.shared.project import resolve_requested_name

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
        state = RuntimeCommandState()
        state.set_callable_invocation(
            "hyde.recreation_registry.publish_registry",
            [repr("fit_function")],
        )
        python_execution_service.execute_hidden(state.python_source())
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

    def _active_curve_fit_figure_context(self):
        figure_context_service = self.services.get("figure_context_service")
        if figure_context_service is None:
            return None
        return figure_context_service.active_editable_figure()

    def show_curve_fit_dialog(self, checked=False):
        del checked
        figure_context = self._active_curve_fit_figure_context()
        dialog = CurveFitDialog(
            figure_context=figure_context,
            services=self.services,
            parent=self.services.get("ui"),
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted
