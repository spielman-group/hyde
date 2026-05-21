from qtutils.qt import QtWidgets

from hyde.user_interface.hyde_interactive_widget import (
    active_interactive_window,
    has_supported_traces,
)
from hyde.user_interface.plugins.figure.window import FigureWindow
from hyde.user_interface.plugin_tools import HydePlugin

from .axis_edit_dialog import AxisEditDialog
from .trace_edit_dialog import TraceAppearanceDialog


class Plugin(HydePlugin):
    def get_menu_contributions(self):
        return [
            {
                "location": "figure",
                "group": "figure_controls",
                "order": 10,
                "name": "Modify Data Appearance...",
                "action": self.show_trace_appearance_dialog,
            },
            {
                "location": "figure",
                "group": "figure_controls",
                "order": 20,
                "name": "Modify Axis...",
                "action": self.show_axis_edit_dialog,
            }
        ]

    def show_trace_appearance_dialog(self, checked=False):
        del checked
        return self._show_dialog(
            TraceAppearanceDialog,
            lambda dialog: has_supported_traces(dialog.figure_window),
        )

    def show_axis_edit_dialog(self, checked=False):
        del checked
        return self._show_dialog(AxisEditDialog, lambda dialog: dialog.has_supported_axes())

    def _active_editable_figure_window(self):
        figure_window = active_interactive_window(self.services, FigureWindow)
        if figure_window is None:
            return None
        snapshot_state = getattr(figure_window, "snapshot_state", None)
        if snapshot_state is None or snapshot_state.figure_ir() is None:
            return None
        if figure_window.services.get("send_figure_action") is None:
            return None
        return figure_window

    def _show_dialog(self, dialog_class, support_check):
        figure_window = self._active_editable_figure_window()
        if figure_window is None:
            return False
        dialog = dialog_class(
            figure_window,
            parent=self.services.get("ui"),
        )
        if not support_check(dialog):
            dialog.deleteLater()
            return False
        return dialog.exec_() == QtWidgets.QDialog.Accepted
