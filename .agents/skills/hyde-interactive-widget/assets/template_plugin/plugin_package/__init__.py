from hyde.user_interface.plugins.plugin_tools import PluginFeature

from .window import ExampleInteractiveWindow


class Plugin(PluginFeature):
    def descriptors(self):
        return {
            "example_interactive": {
                "context": "mdi",
                "key": "example_interactive",
                "title": "Example Interactive",
                "factory": lambda parent=None, data=None: ExampleInteractiveWindow(
                    parent=parent,
                    services=self.services,
                    initial_window_name="ExampleInteractive0",
                ),
            }
        }
