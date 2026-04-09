"""Figure window UI package."""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui


class FigureWindow(QtWidgets.QMdiSubWindow):
    close_requested = QtCore.Signal(str)

    def __init__(self, figure_id, parent=None):
        super().__init__(parent)
        self.figure_id = figure_id
        self._allow_close = False
        self.ui = load_ui("figure_window/figure_window.ui")
        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ui.figure_layout.addWidget(self.canvas)
        self.setWidget(self.ui)

    def apply_snapshot(self, snapshot):
        self.setWindowTitle(snapshot["title"])
        self.figure.clear()
        grid = self.figure.add_gridspec(1, 1)
        axes = self.figure.add_subplot(grid[0, 0])
        for trace in snapshot["traces"]:
            line, = axes.plot(
                trace["x_data"],
                trace["y_data"],
                label=trace["label"],
                linestyle=trace.get("style", "-"),
                color=trace.get("color") or None,
                marker=trace.get("marker") or None,
                markersize=trace.get("markersize") or None,
                linewidth=trace.get("linewidth") or None,
            )
            line.set_visible(trace.get("visible", True))
        axes_info = snapshot.get("axes", {})
        axes.set_xlabel(axes_info.get("xlabel", "x"))
        axes.set_ylabel(axes_info.get("ylabel", "y"))
        axes.set_title(snapshot["title"])
        if axes_info.get("xscale") and axes_info.get("xscale") != "linear":
            axes.set_xscale(axes_info["xscale"])
        if axes_info.get("yscale") and axes_info.get("yscale") != "linear":
            axes.set_yscale(axes_info["yscale"])
        if axes_info.get("xmin") is not None or axes_info.get("xmax") is not None:
            axes.set_xlim(left=axes_info.get("xmin"), right=axes_info.get("xmax"))
        if axes_info.get("ymin") is not None or axes_info.get("ymax") is not None:
            axes.set_ylim(bottom=axes_info.get("ymin"), top=axes_info.get("ymax"))
        if axes_info.get("xgrid"):
            axes.grid(True, axis="x")
        if axes_info.get("ygrid"):
            axes.grid(True, axis="y")
        if len(snapshot["traces"]) > 1:
            axes.legend()
        self.canvas.draw_idle()

    def close_from_sync(self):
        self._allow_close = True
        self.close()

    def closeEvent(self, event):
        if self._allow_close:
            return super().closeEvent(event)
        self.close_requested.emit(self.figure_id)
        event.ignore()


__all__ = ["FigureWindow"]