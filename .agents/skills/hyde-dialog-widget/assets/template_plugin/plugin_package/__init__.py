from qtutils.qt import QtWidgets

from hyde.user_interface.plugins.plugin_tools import PluginFeature, add_menu_action

from .dialogs import ExampleDialog


class Plugin(PluginFeature):
    def on_plugin_available(self, name):
        if name != "app_ready":
            return
        add_menu_action(
            self,
            menu_location="analysis",
            action_name="Open Example Dialog",
            callback=self.open_dialog,
        )

    def open_dialog(self):
        dialog = ExampleDialog(services=self.services, parent=self.parent_widget())
        dialog.exec_()

    def parent_widget(self):
        mdi_area = self.service("mdi_area")
        return None if mdi_area is None else mdi_area
