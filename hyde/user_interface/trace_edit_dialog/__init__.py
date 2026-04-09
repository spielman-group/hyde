"""Trace edit dialog UI package."""

from __future__ import annotations

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui


class TraceEditDialog(QtWidgets.QDialog):
    command_changed = QtCore.Signal(str)

    def __init__(self, figure_id, snapshot, parent=None):
        super().__init__(parent)
        self.ui = load_ui("trace_edit_dialog/trace_edit_dialog.ui", self)
        self.figure_id = figure_id
        self.snapshot = snapshot
        self._loading = False
        self.trace_combo = self.ui.trace_combo
        self.trace_filter_edit = self.ui.trace_filter_edit
        self.label_edit = self.ui.label_edit
        self.color_combo = self.ui.color_combo
        self.visible_checkbox = self.ui.visible_checkbox
        self.mode_combo = self.ui.mode_combo
        self.marker_combo = self.ui.marker_combo
        self.marker_size_spin = self.ui.marker_size_spin
        self.line_width_spin = self.ui.line_width_spin
        self.gaps_checkbox = self.ui.gaps_checkbox
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.cancel_button = self.ui.cancel_button
        self.color_combo.addItems(["", "black", "red", "blue", "green", "magenta"])
        self.mode_combo.addItems(["Lines", "Markers", "Lines+Markers"])
        self.marker_combo.addItems(["", "o", "s", "^", "x", "+"])
        self.marker_size_spin.setRange(0.0, 100.0)
        self.line_width_spin.setRange(0.0, 20.0)
        for index, trace in enumerate(snapshot["traces"]):
            self.trace_combo.addItem(f"{index}: {trace['label']}", index)
        self.trace_combo.currentIndexChanged.connect(self._load_selected_trace)
        self.trace_filter_edit.textChanged.connect(self._apply_filter)
        self.cancel_button.clicked.connect(self.reject)
        for widget, signal_name in (
            (self.trace_combo, "currentIndexChanged"),
            (self.label_edit, "textChanged"),
            (self.color_combo, "currentTextChanged"),
            (self.visible_checkbox, "toggled"),
            (self.mode_combo, "currentTextChanged"),
            (self.marker_combo, "currentTextChanged"),
            (self.marker_size_spin, "valueChanged"),
            (self.line_width_spin, "valueChanged"),
            (self.gaps_checkbox, "toggled"),
        ):
            getattr(widget, signal_name).connect(self._emit_command)
        self._load_selected_trace()

    def command(self):
        index = self.trace_combo.currentData()
        if index is None:
            return ""
        mode = self.mode_combo.currentText()
        marker = self.marker_combo.currentText() or None
        style = "None" if mode == "Markers" else "-"
        if mode == "Lines" and not marker:
            marker = None
        linewidth = 0.0 if mode == "Markers" else self.line_width_spin.value()
        return (
            f"edit_trace({self.figure_id!r}, {index!r}, label={self.label_edit.text()!r}, "
            f"style={style!r}, color={self.color_combo.currentText()!r}, "
            f"visible={not self.visible_checkbox.isChecked()!r}, marker={marker!r}, "
            f"markersize={self.marker_size_spin.value()!r}, linewidth={linewidth!r}, "
            f"gaps={self.gaps_checkbox.isChecked()!r})"
        )

    def revert_command(self):
        index = self.trace_combo.currentData()
        trace = self.snapshot["traces"][index]
        return (
            f"edit_trace({self.figure_id!r}, {index!r}, label={trace.get('label', '')!r}, "
            f"style={trace.get('style', '-')!r}, color={trace.get('color', '')!r}, "
            f"visible={trace.get('visible', True)!r}, marker={trace.get('marker')!r}, "
            f"markersize={trace.get('markersize', 6.0)!r}, linewidth={trace.get('linewidth', 1.5)!r}, "
            f"gaps={trace.get('gaps', False)!r})"
        )

    def _load_selected_trace(self):
        index = self.trace_combo.currentData()
        if index is None:
            return
        self._load_trace(self.snapshot["traces"][index])

    def _load_trace(self, trace):
        self._loading = True
        self.label_edit.setText(trace["label"])
        self.color_combo.setCurrentText(trace.get("color", ""))
        self.visible_checkbox.setChecked(not trace.get("visible", True))
        marker = trace.get("marker") or ""
        self.marker_combo.setCurrentText(marker)
        self.marker_size_spin.setValue(float(trace.get("markersize", 6.0)))
        self.line_width_spin.setValue(float(trace.get("linewidth", 1.5)))
        self.gaps_checkbox.setChecked(trace.get("gaps", False))
        style = trace.get("style", "-")
        if style == "None":
            self.mode_combo.setCurrentText("Markers")
        elif marker:
            self.mode_combo.setCurrentText("Lines+Markers")
        else:
            self.mode_combo.setCurrentText("Lines")
        self._loading = False
        self._emit_command()

    def _apply_filter(self, text):
        text = text.strip().lower()
        for index in range(self.trace_combo.count()):
            visible = not text or text in self.trace_combo.itemText(index).lower()
            self.trace_combo.view().setRowHidden(index, not visible)

    def _emit_command(self, *_args):
        if not self._loading:
            self.command_changed.emit(self.command())


__all__ = ["TraceEditDialog"]
