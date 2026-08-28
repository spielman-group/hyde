import copy
from dataclasses import replace as dataclass_replace

from hyde.features.matplotlib_ir import FigureIR


class EditableFigureContext:
    def __init__(self, figure_window):
        from .window import FigureWindow

        if not isinstance(figure_window, FigureWindow):
            raise TypeError("EditableFigureContext requires a FigureWindow.")
        self.figure_number = int(figure_window.figure_number)
        self._figure_window = figure_window

    def figure_name(self):
        figure_ir = self.current_figure_ir()
        if figure_ir is None:
            return f"Figure{self.figure_number}"
        return str(figure_ir.default_macro_name())

    def current_figure_ir(self):
        figure_ir = getattr(self._figure_window, "widget_ir", None)
        if figure_ir is None:
            return None
        if not isinstance(figure_ir, FigureIR):
            raise TypeError("FigureWindow.widget_ir must be a FigureIR.")
        return dataclass_replace(
            copy.deepcopy(figure_ir),
            figure_number=self.figure_number,
        )

    def current_size_inches(self):
        figure_ir = self.current_figure_ir()
        if figure_ir is None:
            return None
        size = figure_ir.figure_size()
        if size in (None, ""):
            return None
        return (float(size[0]), float(size[1]))

    def has_supported_traces(self):
        figure_ir = self.current_figure_ir()
        return bool(figure_ir is not None and figure_ir.has_supported_traces())

    def supported_trace_records(self):
        figure_ir = self.current_figure_ir()
        if figure_ir is None:
            return ()
        return tuple(copy.deepcopy(figure_ir.supported_trace_records()))
