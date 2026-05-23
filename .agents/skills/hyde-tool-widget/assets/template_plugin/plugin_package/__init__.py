from hyde.user_interface.plugins.plugin_tools import PluginFeature

from .window import ExampleTool


class Plugin(PluginFeature):
    def open_tool(self):
        mdi_context = self.service("mdi_context")
        if mdi_context is None:
            return None
        return mdi_context.show("example_tool")

    def descriptors(self):
        return {
            "example_tool": {
                "context": "mdi",
                "key": "example_tool",
                "title": "Example Tool",
                "factory": lambda parent=None, data=None: ExampleTool(
                    parent=parent,
                    services=self.services,
                    window_identifier="example_tool",
                ),
            }
        }
