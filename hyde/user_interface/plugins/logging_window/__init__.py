from labscript_utils.qtwidgets.outputbox import OutputBox
from hyde.user_interface.base_hyde_widgets import HydeToolWidget
from hyde.user_interface.shared.plugin import HydeToolWindowPlugin, HydeToolWindowService

class LoggingWindow(HydeToolWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Logging")
        self.output_box = OutputBox(self.ui.content_layout)


class LoggingWindowService(HydeToolWindowService):
    def write(self, text, color=None):
        widget = self.ensure_widget()
        widget.output_box.write(text, color=color)

    def port(self):
        widget = self.ensure_widget()
        return widget.output_box.port


class Plugin(HydeToolWindowPlugin):
    session_key = "logging"
    window_title = "Logging"
    menu_name = "Logging"
    window_size = (800, 600)
    menu_order = 40
    creation_policy = "eager"
    restore_on_project_loaded = True

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.logging_window_service = LoggingWindowService(self)

    def get_services(self):
        return {"runtime_output_service": self.logging_window_service}

    def create_tool_window_widget(self, parent=None):
        return LoggingWindow(
            parent=parent,
            services=self.services,
            session_key=self.session_key,
        )
