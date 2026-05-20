from qtutils.qt import QtWidgets
from hyde.user_interface.hyde_interactive_widget import active_interactive_window
from hyde.user_interface.plugins.figure.window import FigureWindow
from hyde.user_interface.plugin_tools import HydePlugin

from .dialogs import CurveFitDialog


class Plugin(HydePlugin):
    def get_menu_contributions(self):
        return [
            {
                "location": "analysis",
                "group": "analysis_tools",
                "order": 10,
                "name": "Curve Fit...",
                "action": self.show_curve_fit_dialog,
            }
        ]

    def show_curve_fit_dialog(self, checked=False):
        del checked
        figure_window = active_interactive_window(self.services, FigureWindow)
        dialog = CurveFitDialog(
            figure_window=figure_window,
            parent=self.services.get("ui"),
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted
