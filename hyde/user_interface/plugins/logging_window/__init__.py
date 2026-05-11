from qtutils.qt.QtWidgets import QWidget, QVBoxLayout
from labscript_utils.qtwidgets.outputbox import OutputBox
from hyde.user_interface.plugin_tools import HydePlugin

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
        return self.plugin.ensure_mdi_widget("logging")

    def widget(self):
        return self.plugin.mdi_widget("logging")

    def subwindow(self):
        return self.plugin.mdi_subwindow("logging")

    def output_box(self):
        widget = self.ensure_widget()
        return widget.output_box

    def port(self):
        widget = self.ensure_widget()
        return widget.port


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.logging_window_service = LoggingWindowService(self)

    def setup(self, data=None):
        del data
        self.logging_window_service.ensure_widget()
        self.hide_mdi_subwindow("logging")

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

    def get_session_toml_data(self):
        return self.tool_window_save_data("logging")

    def on_project_loaded(self, data):
        self.restore_tool_window(data["session"], "logging")
