from qtutils.qt import QtWidgets

from hyde.user_interface.plugins.figure.window import FigureWindow
from hyde.user_interface.plugin_tools import HydePlugin

from .axis_edit_dialog import AxisEditDialog
from .trace_edit_dialog import TraceAppearanceDialog


def _active_figure_window(services):
    mdi_area = services.get("mdi_area")
    if mdi_area is None:
        return None
    subwindow = mdi_area.activeSubWindow()
    widget = None if subwindow is None else subwindow.widget()
    if not isinstance(widget, FigureWindow):
        return None
    if widget.snapshot_state.figure_ir() is None:
        return None
    if widget.services.get("send_figure_action") is None:
        return None
    return widget


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
        return self._show_dialog(TraceAppearanceDialog, "has_supported_traces")

    def show_axis_edit_dialog(self, checked=False):
        del checked
        return self._show_dialog(AxisEditDialog, "has_supported_axes")

    def _show_dialog(self, dialog_class, support_method_name):
        figure_window = _active_figure_window(self.services)
        if figure_window is None:
            return False
        dialog = dialog_class(
            figure_window,
            parent=self.services.get("ui"),
        )
        if not getattr(dialog, support_method_name)():
            dialog.deleteLater()
            return False
        return dialog.exec_() == QtWidgets.QDialog.Accepted
