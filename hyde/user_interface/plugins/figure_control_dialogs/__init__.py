from qtutils.qt import QtWidgets

from hyde.user_interface.plugin_tools import HydePlugin
from hyde.user_interface.plugins.figure.window import FigureWindow

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
            }
        ]

    def _active_figure_window(self):
        mdi_area = self.services.get("mdi_area")
        if mdi_area is None:
            return None
        subwindow = mdi_area.activeSubWindow()
        widget = None if subwindow is None else subwindow.widget()
        if isinstance(widget, FigureWindow):
            return widget
        return None

    def show_trace_appearance_dialog(self, checked=False):
        del checked
        figure_window = self._active_figure_window()
        if figure_window is None:
            return False
        dialog = TraceAppearanceDialog(
            figure_window,
            parent=self.services.get("ui"),
        )
        if not dialog.has_supported_traces():
            dialog.deleteLater()
            return False
        return dialog.exec_() == QtWidgets.QDialog.Accepted
