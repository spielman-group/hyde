from qtutils.qt.QtWidgets import QWidget, QVBoxLayout
from labscript_utils.qtwidgets.outputbox import OutputBox
from labscript_utils.plugins import BasePlugin
from hyde.user_interface.plugin_tools import (
    capture_subwindow_state,
    restore_subwindow_state,
)

class LoggingWindow(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Logging")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Initialize the OutputBox, which populates our layout
        self.output_box = OutputBox(self.layout)
    
    @property
    def port(self):
        return self.output_box.port


class LoggingWindowService:
    def __init__(self, plugin):
        self.plugin = plugin

    def ensure_widget(self):
        return self.plugin.services["mdi_context"].ensure_widget("logging")

    def widget(self):
        return self.plugin.services["mdi_context"].widget("logging")

    def subwindow(self):
        return self.plugin.services["mdi_context"].subwindow("logging")

    def output_box(self):
        widget = self.ensure_widget()
        return widget.output_box

    def port(self):
        widget = self.ensure_widget()
        return widget.port


class Plugin(BasePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}
        self.logging_window_service = LoggingWindowService(self)

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})
        self.logging_window_service.ensure_widget()
        subwindow = self.logging_window_service.subwindow()
        if subwindow is not None:
            subwindow.hide()

    def get_ui_contributions(self):
        return [
            {
                "context": "mdi",
                "key": "logging",
                "title": "Logging",
                "size": (800, 600),
                "factory": self.create_widget,
            }
        ]

    def get_menu_contributions(self):
        return [
            {
                "location": "window",
                "group": "tool_windows",
                "order": 40,
                "name": "Logging",
                "action": self.show_window,
            }
        ]

    def get_services(self):
        return {"runtime_output_service": self.logging_window_service}

    def create_widget(self, parent=None, data=None):
        del data
        return LoggingWindow(parent=parent)

    def show_window(self, checked=False):
        del checked
        self.services["show_window"]("logging")

    def get_event_handlers(self):
        return {
            "project_loaded": self.on_project_loaded,
        }

    def get_save_data(self):
        subwindow = self.services["mdi_context"].subwindow("logging")
        if subwindow is None:
            return {}
        return {
            "tool_windows": {
                "logging": capture_subwindow_state(subwindow),
            }
        }

    def on_project_loaded(self, data):
        info = data["session"].get("tool_windows", {}).get("logging", {})
        restore_subwindow_state(
            self.services["mdi_context"].subwindow("logging"),
            info,
        )
