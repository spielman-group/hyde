from qtutils.qt import QtWidgets

from hyde.user_interface.shared.plugin import HydePlugin

from .axis_edit_dialog import AxisEditDialog
from .trace_edit_dialog import TraceAppearanceDialog


class Plugin(HydePlugin):
    def get_menu_contributions(self):
        return [
            {
                "location": "figure",
                "group": "10_figure_controls",
                "order": 10,
                "name": "Modify Data Appearance...",
                "action": self.show_trace_appearance_dialog,
                "enabled": self.has_active_editable_figure,
            },
            {
                "location": "figure",
                "group": "10_figure_controls",
                "order": 20,
                "name": "Modify Axis...",
                "action": self.show_axis_edit_dialog,
                "enabled": self.has_active_editable_figure,
            }
        ]

    def show_trace_appearance_dialog(self, checked=False):
        del checked
        return self._show_dialog(
            TraceAppearanceDialog,
            lambda dialog: dialog.figure_context.has_supported_traces(),
        )

    def show_axis_edit_dialog(self, checked=False):
        del checked
        return self._show_dialog(
            AxisEditDialog,
            lambda dialog: dialog.has_supported_axes(),
        )



    def _show_dialog(self, dialog_class, support_check):
        figure_context = self.active_editable_figure()
        if figure_context is None:
            return False
        dialog = dialog_class(
            figure_context,
            services=self.services,
            parent=self.services.get("ui"),
        )
        if not support_check(dialog):
            dialog.deleteLater()
            return False
        return dialog.exec() == QtWidgets.QDialog.Accepted
