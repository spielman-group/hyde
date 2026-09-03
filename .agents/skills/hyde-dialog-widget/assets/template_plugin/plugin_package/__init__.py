from qtutils.qt import QtWidgets

from hyde.user_interface.shared.plugin import HydePlugin

from .dialogs import ExampleDialog


class Plugin(HydePlugin):
    """Dialog surface.

    Menu entries come from `get_menu_contributions()`. Valid `location` values
    are `file`, `window`, `analysis`, `table`, and `figure`. Separator groups
    within a location order by group name, so the name carries a leading
    ordinal.
    """

    def get_menu_contributions(self):
        return [
            {
                "location": "analysis",
                "group": "10_example",
                "order": 10,
                "name": "Example Dialog...",
                "action": self.show_example_dialog,
            }
        ]

    def show_example_dialog(self, checked=False):
        del checked
        dialog = ExampleDialog(
            services=self.services,
            parent=self.service("ui"),
        )
        return dialog.exec() == QtWidgets.QDialog.Accepted
