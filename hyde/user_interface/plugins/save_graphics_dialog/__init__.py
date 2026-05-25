from qtutils.qt import QtWidgets

from hyde.user_interface.shared.plugin import HydePlugin

from .dialogs import SaveGraphicsDialog


class Plugin(HydePlugin):
    def get_menu_contributions(self):
        return [
            {
                "location": "figure",
                "group": "figure_export",
                "group_order": 100,
                "order": 10,
                "name": "Save Graphics...",
                "action": self.show_save_graphics_dialog,
            }
        ]

    def show_save_graphics_dialog(self, checked=False):
        del checked
        figure_context = self._active_editable_figure()
        if figure_context is None:
            return False
        dialog = SaveGraphicsDialog(
            figure_context,
            services=self.services,
            parent=self.services.get("ui"),
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted

    def _active_editable_figure(self):
        figure_context_service = self.services.get("figure_context_service")
        if figure_context_service is None:
            return None
        return figure_context_service.active_editable_figure()
