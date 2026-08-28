from hyde.user_interface.shared.plugin import HydeToolWindowPlugin

from .window import ExampleTool


class Plugin(HydeToolWindowPlugin):
    """Persistent tool window.

    `HydeToolWindowPlugin` already contributes the Window-menu action, the MDI
    window descriptor, and the show/hide lifecycle. Declare the class
    attributes and build the widget; do not re-register the menu action.
    """

    session_key = "example_tool"
    window_title = "Example Tool"
    menu_name = "Example Tool"
    window_size = (600, 400)
    menu_order = 50
    creation_policy = "lazy"

    def create_tool_window_widget(self, parent=None):
        return ExampleTool(
            parent=parent,
            services=self.services,
            window_identifier=self.session_key,
        )
