from qtutils.qt import QtWidgets

from hyde.user_interface.base_hyde_widgets import HydeInteractiveWidget
from hyde.features.example_features import ExampleCodec


class ExampleInteractiveWindow(HydeInteractiveWidget):
    def __init__(self, services=None, initial_window_name=None, parent=None):
        super().__init__(
            services=services,
            initial_window_name=initial_window_name,
            parent=parent,
        )
        self.codec = ExampleCodec()
        self.load_ui("example_interactive.ui", module_name=__name__)

    def saveable_default_macro_name(self):
        return "example_interactive"

    def saveable_decorator_name(self):
        return "interactive_window"

    def macro_definition_source(self, macro_name, *, handle):
        del macro_name
        return f"print({handle!r})"

    def session_restore_definition_source(self, handle):
        return f"print({handle!r})"

    def tracked_namespace_names(self):
        return ("example_data",)

    def on_stable_name_bound(self, stable_name):
        self.setWindowTitle(stable_name)
