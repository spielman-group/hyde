from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.hyde_interactive_widget import active_interactive_window
from hyde.user_interface.plugin_tools import HydePlugin
from hyde.user_interface.plugins.figure.window import FigureWindow
from hyde.user_interface.window_macro_store import (
    MacroStoreError,
    inspect_fit_function_conflict,
    validate_macro_name,
    write_fit_function_source,
)
from hyde.user_interface.window_naming import resolve_requested_name

from .dialogs import CurveFitDialog


class CurveFitCatalogService(QtCore.QObject):
    catalog_changed = QtCore.Signal()

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.command_state = RuntimeCommandState()

    def fit_functions(self):
        return tuple(dict(entry) for entry in self.plugin.fit_functions)

    def rejected_fit_functions(self):
        return tuple(dict(entry) for entry in self.plugin.rejected_fit_functions)

    def refresh(self):
        python_execution_service = self.plugin.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        self.command_state.set_callable_invocation(
            "hyde.recreation_registry.publish_fit_function_registry",
            [],
        )
        python_execution_service.execute_hidden(self.command_state.python_source())
        return True

    def default_new_fit_function_name(self):
        existing_names = [
            entry["name"] for entry in self.plugin.fit_functions
        ] + [
            entry["name"] for entry in self.plugin.rejected_fit_functions
        ]
        return resolve_requested_name("FitFunction", existing_names)

    def scaffold_new_fit_function(self, function_name):
        validated_name = validate_macro_name(function_name)
        procedures_init_getter = self.plugin.services.get("get_procedures_init")
        reload_procedures = self.plugin.services.get("reload_procedures")
        if procedures_init_getter is None or reload_procedures is None:
            raise MacroStoreError(
                "Curve Fit requires an active project procedures/__init__.py path."
            )
        procedures_init = procedures_init_getter()
        if not procedures_init:
            raise MacroStoreError(
                "Curve Fit requires an active project procedures/__init__.py path."
            )
        if inspect_fit_function_conflict(procedures_init, validated_name) is not None:
            raise MacroStoreError(
                f"{validated_name} already exists in procedures/__init__.py."
            )
        write_fit_function_source(
            procedures_init,
            validated_name,
            (
                '@hyde.fit_function(independent_vars=("x",))\n'
                f"def {validated_name}(x, c0):\n"
                "    return c0 * x\n"
            ),
        )
        reload_procedures()
        self.refresh()
        return validated_name

    def replace_catalog(self, fit_functions, rejected_fit_functions):
        next_fit_functions = [dict(entry) for entry in fit_functions]
        next_rejected = [dict(entry) for entry in rejected_fit_functions]
        if (
            next_fit_functions == self.plugin.fit_functions
            and next_rejected == self.plugin.rejected_fit_functions
        ):
            return
        self.plugin.fit_functions = next_fit_functions
        self.plugin.rejected_fit_functions = next_rejected
        self.catalog_changed.emit()


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.fit_functions = []
        self.rejected_fit_functions = []
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

    def show_curve_fit_dialog(self, checked=False):
        del checked
        figure_window = active_interactive_window(self.services, FigureWindow)
        dialog = CurveFitDialog(
            figure_window=figure_window,
            services=self.services,
            parent=self.services.get("ui"),
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted
