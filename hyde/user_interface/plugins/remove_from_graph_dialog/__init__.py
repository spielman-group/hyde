from qtutils.qt import QtWidgets

from hyde.user_interface.shared.plugin import HydePlugin

from .dialogs import RemoveFromGraphDialog


class Plugin(HydePlugin):
    def get_menu_contributions(self):
        return [
            {
                "location": "figure",
                "group": "figure_controls",
                "order": 0,
                "name": "Remove from Graph...",
                "action": self.show_remove_from_graph_dialog,
            }
        ]

    def show_remove_from_graph_dialog(self, checked=False):
        del checked
        figure_context = self._active_editable_figure()
        if figure_context is None:
            return False
        dialog = RemoveFromGraphDialog(
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
