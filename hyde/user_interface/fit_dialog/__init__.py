"""Fit dialog UI package."""

from __future__ import annotations

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui


class FitDialog(QtWidgets.QDialog):
    def __init__(self, fit_entries, selected_names, project_path, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.ui = load_ui("fit_dialog/fit_dialog.ui", self)
        self.tabs = self.ui.tabs
        self.function_combo = self.ui.function_combo
        self.y_combo = self.ui.y_combo
        self.x_combo = self.ui.x_combo
        self.lower_edit = self.ui.lower_edit
        self.upper_edit = self.ui.upper_edit
        self.coefficients_table = self.ui.coefficients_table
        self.destination_combo = self.ui.destination_combo
        self.residual_combo = self.ui.residual_combo
        self.coefficient_wave_combo = self.ui.coefficient_wave_combo
        self.auto_guess_combo = self.ui.auto_guess_combo
        self.constraints_combo = self.ui.constraints_combo
        self.weighting_combo = self.ui.weighting_combo
        self.mask_combo = self.ui.mask_combo
        self.from_target_checkbox = self.ui.from_target_checkbox
        self.show_commands_radio = self.ui.show_commands_radio
        self.show_equation_radio = self.ui.show_equation_radio
        self.preview_stack = self.ui.preview_stack
        self.commands_preview = self.ui.commands_preview
        self.equation_preview = self.ui.equation_preview
        self.status_label = self.ui.status_label
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.graph_now_button = self.ui.graph_now_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button

        for entry in fit_entries:
            self.function_combo.addItem(entry.title, entry)
        self.x_combo.addItem("_calculated_", None)
        for name in selected_names:
            self.y_combo.addItem(name, name)
            self.x_combo.addItem(name, name)
            self.destination_combo.addItem(f"{name}_fit", f"{name}_fit")
            self.residual_combo.addItem(f"{name}_residuals", f"{name}_residuals")
            self.coefficient_wave_combo.addItem(f"{name}_coef", f"{name}_coef")
            self.mask_combo.addItem(name, name)
        self.destination_combo.insertItem(0, "_auto_", "_auto_")
        self.residual_combo.insertItem(0, "_none_", "_none_")
        self.coefficient_wave_combo.insertItem(0, "_auto_", "_auto_")
        self.auto_guess_combo.addItems(["Auto Guess", "Use Defaults"])
        self.constraints_combo.addItems(["None"])
        self.weighting_combo.addItems(["None", "Std Dev", "1/Std Dev"])
        self.destination_combo.setEditable(True)

        self.coefficients_table.setColumnCount(3)
        self.coefficients_table.setHorizontalHeaderLabels(["Name", "Initial", "Hold"])
        self.function_combo.currentIndexChanged.connect(self._populate_parameters)
        self.function_combo.currentIndexChanged.connect(self._update_preview)
        self.y_combo.currentIndexChanged.connect(self._update_preview)
        self.x_combo.currentIndexChanged.connect(self._update_preview)
        self.lower_edit.textChanged.connect(self._update_preview)
        self.upper_edit.textChanged.connect(self._update_preview)
        self.destination_combo.currentTextChanged.connect(self._update_preview)
        self.residual_combo.currentTextChanged.connect(self._update_preview)
        self.show_commands_radio.toggled.connect(self._update_preview_mode)
        self.help_button.clicked.connect(self._show_help)
        self.cancel_button.clicked.connect(self.reject)
        self.to_clip_button.clicked.connect(self._copy_command)
        self._populate_parameters()
        self._update_preview_mode()
        self._update_preview()

    def command(self, graph_override=None, graph_target=None, preview=False):
        entry = self.function_combo.currentData()
        x_name = self.x_combo.currentData()
        range_expr = []
        for edit in (self.lower_edit, self.upper_edit):
            text = edit.text().strip()
            range_expr.append(None if not text else float(text))
        params = {}
        for row in range(self.coefficients_table.rowCount()):
            name_item = self.coefficients_table.item(row, 0)
            initial_item = self.coefficients_table.item(row, 1)
            if name_item is None or initial_item is None:
                continue
            name = name_item.text()
            try:
                initial = float(initial_item.text())
            except ValueError:
                continue
            hold_item = self.coefficients_table.item(row, 2)
            hold = hold_item.checkState() == QtCore.Qt.Checked if hold_item else False
            params[name] = {"value": initial, "vary": not hold}
        result_name = self._result_name()
        graph_value = bool(graph_override)
        residual_name = self.residual_combo.currentData()
        kwargs = [
            f"function_path={str(entry.path)!r}",
            f"function_name={entry.function_name!r}",
            f"y={self.y_combo.currentText()!r}",
            f"x={x_name!r}",
            f"result_name={result_name!r}",
            f"params={params!r}",
            f"x_range={tuple(range_expr)!r}",
            f"store_residuals={(False if preview else residual_name not in (None, '_none_'))!r}",
            f"graph={graph_value!r}",
        ]
        if graph_target is not None:
            kwargs.append(f"graph_target={graph_target!r}")
        if preview:
            kwargs.append("preview=True")
        return f"do_fit({', '.join(kwargs)})"

    def _populate_parameters(self):
        entry = self.function_combo.currentData()
        if entry is None:
            self.coefficients_table.setRowCount(0)
            return
        self.coefficients_table.setRowCount(len(entry.parameters))
        for row, name in enumerate(entry.parameters):
            self.coefficients_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
            self.coefficients_table.setItem(row, 1, QtWidgets.QTableWidgetItem("1.0"))
            hold_item = QtWidgets.QTableWidgetItem()
            hold_item.setCheckState(QtCore.Qt.Unchecked)
            self.coefficients_table.setItem(row, 2, hold_item)
        self._update_preview()

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Curve Fit",
            "Hyde v1 builds fits with lmfit. Generate a replayable Python command with To Cmd Line or execute it directly with Do It.",
        )

    def _copy_command(self):
        QtWidgets.QApplication.clipboard().setText(self.command())

    def _result_name(self):
        destination = self.destination_combo.currentText().strip()
        if destination in {"", "_auto_"}:
            return f"fit_{self.y_combo.currentText()}"
        return destination

    def _update_preview_mode(self):
        self.preview_stack.setCurrentIndex(0 if self.show_commands_radio.isChecked() else 1)

    def _update_preview(self, *_args):
        entry = self.function_combo.currentData()
        if entry is None:
            self.commands_preview.setPlainText("")
            self.equation_preview.setText("")
            self.status_label.setText("No fit function selected")
            return
        self.commands_preview.setPlainText(self.command())
        params = " + ".join(entry.parameters) if entry.parameters else "..."
        self.equation_preview.setText(f"{entry.function_name}(x, {', '.join(entry.parameters)})")
        self.status_label.setText("No Error")


__all__ = ["FitDialog"]