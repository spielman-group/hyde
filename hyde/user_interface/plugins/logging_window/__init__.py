from qtutils.qt.QtWidgets import QWidget, QVBoxLayout
from labscript_utils.qtwidgets.outputbox import OutputBox
from labscript_utils.plugins import BasePlugin
from hyde.user_interface.plugin_tools import capture_subwindow_state, restore_subwindow_state

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

    def closeEvent(self, event):
        # Instead of destroying, we just hide the entire MDI sub-window.
        # This allows the window to be toggled via the 'Windows' menu.
        if self.parentWidget():
            self.parentWidget().hide()
        else:
            self.hide()
        event.ignore()


class Plugin(BasePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})

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
