"""Save graphics dialog UI package."""

from __future__ import annotations

from pathlib import Path

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui


class SaveGraphicsDialog(QtWidgets.QDialog):
    command_changed = QtCore.Signal(str)

    FORMATS = [
        ("Quartz PDF", "pdf", True),
        ("PNG File", "png", True),
        ("SVG File", "svg", True),
        ("EPS File", "eps", False),
    ]

    def __init__(self, figure_id, default_path, size_inches=(6.4, 4.8), parent=None):
        super().__init__(parent)
        self.ui = load_ui("save_graphics_dialog/save_graphics_dialog.ui", self)
        self.figure_id = figure_id
        self._loading = False
        self._previous_suffix = Path(default_path).suffix.lower()
        self.same_size_radio = self.ui.same_size_radio
        self.custom_size_radio = self.ui.custom_size_radio
        self.width_spin = self.ui.width_spin
        self.height_spin = self.ui.height_spin
        self.units_combo = self.ui.units_combo
        self.recommended_formats_checkbox = self.ui.recommended_formats_checkbox
        self.format_list = self.ui.format_list
        self.color_checkbox = self.ui.color_checkbox
        self.path_edit = self.ui.path_edit
        self.browse_button = self.ui.browse_button
        self.overwrite_checkbox = self.ui.overwrite_checkbox
        self.command_preview = self.ui.command_preview
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button
        self.units_combo.addItems(["inches", "cm"])
        self.width_spin.setValue(float(size_inches[0]))
        self.height_spin.setValue(float(size_inches[1]))
        self.path_edit.setText(default_path)
        self.cancel_button.clicked.connect(self.reject)
        self.help_button.clicked.connect(self._show_help)
        self.browse_button.clicked.connect(self._browse_for_path)
        self.same_size_radio.toggled.connect(self._refresh_state)
        self.custom_size_radio.toggled.connect(self._refresh_state)
        self.recommended_formats_checkbox.toggled.connect(self._populate_formats)
        for widget, signal_name in (
            (self.width_spin, "valueChanged"),
            (self.height_spin, "valueChanged"),
            (self.units_combo, "currentTextChanged"),
            (self.color_checkbox, "toggled"),
            (self.path_edit, "textChanged"),
            (self.overwrite_checkbox, "toggled"),
        ):
            getattr(widget, signal_name).connect(self._emit_command)
        self.format_list.currentRowChanged.connect(self._format_changed)
        self._populate_formats()
        self._refresh_state()

    def command(self):
        path = self.path_edit.text().strip()
        if not path:
            return ""
        kwargs = [repr(self.figure_id), repr(path), f"format={self.selected_format()!r}"]
        if self.custom_size_radio.isChecked():
            kwargs.append(f"size={self.selected_size_inches()!r}")
            kwargs.append("units='inches'")
        if not self.color_checkbox.isChecked():
            kwargs.append("color=False")
        if self.overwrite_checkbox.isChecked():
            kwargs.append("overwrite=True")
        return f"save_graphics({', '.join(kwargs)})"

    def selected_format(self):
        item = self.format_list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item is not None else "pdf"

    def selected_size_inches(self):
        width = self.width_spin.value()
        height = self.height_spin.value()
        if self.units_combo.currentText() == "cm":
            return (round(width / 2.54, 6), round(height / 2.54, 6))
        return (width, height)

    def _populate_formats(self):
        current = self.selected_format() if self.format_list.count() else "pdf"
        self._loading = True
        self.format_list.clear()
        for label, extension, recommended in self.FORMATS:
            if self.recommended_formats_checkbox.isChecked() and not recommended:
                continue
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, extension)
            self.format_list.addItem(item)
            if extension == current:
                self.format_list.setCurrentItem(item)
        if self.format_list.currentRow() < 0 and self.format_list.count():
            self.format_list.setCurrentRow(0)
        self._loading = False
        self._format_changed()

    def _refresh_state(self):
        custom = self.custom_size_radio.isChecked()
        self.width_spin.setEnabled(custom)
        self.height_spin.setEnabled(custom)
        self.units_combo.setEnabled(custom)
        self._emit_command()

    def _format_changed(self, *_args):
        if self._loading:
            return
        path = self.path_edit.text().strip()
        if path:
            new_suffix = f".{self.selected_format()}"
            current = Path(path)
            if current.suffix.lower() == self._previous_suffix or not current.suffix:
                current = current.with_suffix(new_suffix)
                self.path_edit.setText(str(current))
            self._previous_suffix = new_suffix
        self._emit_command()

    def _browse_for_path(self):
        selected_format = self.selected_format()
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Graphics File",
            self.path_edit.text().strip(),
            f"{selected_format.upper()} Files (*.{selected_format});;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _emit_command(self, *_args):
        command = self.command()
        self.command_preview.setPlainText(command)
        self.command_changed.emit(command)

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Save Graphics",
            "Choose an output path and format, then save the active figure as a replayable Hyde command.",
        )


__all__ = ["SaveGraphicsDialog"]
