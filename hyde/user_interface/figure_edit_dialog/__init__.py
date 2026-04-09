"""Figure edit dialog UI package."""

from __future__ import annotations

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui


class FigureEditDialog(QtWidgets.QDialog):
    command_changed = QtCore.Signal(str)

    def __init__(self, figure_id, snapshot, parent=None):
        super().__init__(parent)
        self.ui = load_ui("figure_edit_dialog/figure_edit_dialog.ui", self)
        self.figure_id = figure_id
        self.snapshot = snapshot
        self._loading = False

        self.axis_combo = self.ui.axis_combo
        self.title_edit = self.ui.title_edit
        self.title_bold_button = self.ui.title_bold_button
        self.title_italic_button = self.ui.title_italic_button
        self.linear_radio = self.ui.linear_radio
        self.log_radio = self.ui.log_radio
        self.log2_radio = self.ui.log2_radio
        self.date_time_radio = self.ui.date_time_radio
        self.axis_label_edit = self.ui.axis_label_edit
        self.label_bold_button = self.ui.label_bold_button
        self.label_italic_button = self.ui.label_italic_button
        self.major_ticks_checkbox = self.ui.major_ticks_checkbox
        self.minor_ticks_checkbox = self.ui.minor_ticks_checkbox
        self.tick_labels_checkbox = self.ui.tick_labels_checkbox
        self.ticks_both_sides_checkbox = self.ui.ticks_both_sides_checkbox
        self.major_grid_checkbox = self.ui.major_grid_checkbox
        self.minor_grid_checkbox = self.ui.minor_grid_checkbox
        self.auto_range_checkbox = self.ui.auto_range_checkbox
        self.minimum_edit = self.ui.minimum_edit
        self.maximum_edit = self.ui.maximum_edit
        self.reverse_axis_checkbox = self.ui.reverse_axis_checkbox
        self.font_combo = self.ui.font_combo
        self.font_size_spin = self.ui.font_size_spin
        self.font_bold_button = self.ui.font_bold_button
        self.font_italic_button = self.ui.font_italic_button
        self.line_color_combo = self.ui.line_color_combo
        self.line_style_combo = self.ui.line_style_combo
        self.line_width_spin = self.ui.line_width_spin
        self.marker_style_combo = self.ui.marker_style_combo
        self.marker_size_spin = self.ui.marker_size_spin
        self.marker_fill_combo = self.ui.marker_fill_combo
        self.fill_enabled_checkbox = self.ui.fill_enabled_checkbox
        self.fill_style_combo = self.ui.fill_style_combo
        self.fill_color_combo = self.ui.fill_color_combo
        self.fill_opacity_slider = self.ui.fill_opacity_slider
        self.error_bars_checkbox = self.ui.error_bars_checkbox
        self.error_style_combo = self.ui.error_style_combo
        self.error_color_combo = self.ui.error_color_combo
        self.show_trendline_checkbox = self.ui.show_trendline_checkbox
        self.trend_type_combo = self.ui.trend_type_combo
        self.polynomial_order_spin = self.ui.polynomial_order_spin
        self.show_equation_checkbox = self.ui.show_equation_checkbox
        self.show_r_squared_checkbox = self.ui.show_r_squared_checkbox
        self.show_mean_checkbox = self.ui.show_mean_checkbox
        self.show_std_dev_checkbox = self.ui.show_std_dev_checkbox
        self.show_min_max_checkbox = self.ui.show_min_max_checkbox
        self.show_sum_checkbox = self.ui.show_sum_checkbox
        self.show_n_checkbox = self.ui.show_n_checkbox
        self.show_confidence_checkbox = self.ui.show_confidence_checkbox
        self.show_prediction_checkbox = self.ui.show_prediction_checkbox
        self.error_level_combo = self.ui.error_level_combo
        self.sync_with_combo = self.ui.sync_with_combo
        self.sync_axis_combo = self.ui.sync_axis_combo
        self.link_x_axis_checkbox = self.ui.link_x_axis_checkbox
        self.link_y_axis_checkbox = self.ui.link_y_axis_checkbox
        self.events_enabled_checkbox = self.ui.events_enabled_checkbox
        self.axes_table = self.ui.axes_table
        self.add_axis_button = self.ui.add_axis_button
        self.remove_axis_button = self.ui.remove_axis_button
        self.live_update_checkbox = self.ui.live_update_checkbox
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button

        self.title_edit.setText(snapshot.get("title", ""))
        self.axis_combo.currentIndexChanged.connect(self._load_axis)
        self.cancel_button.clicked.connect(self.reject)
        self.help_button.clicked.connect(self._show_help)

        self._connect_all_signals()

        self._load_axis()

    def _connect_all_signals(self):
        signals = [
            (self.axis_combo, "currentIndexChanged"),
            (self.title_edit, "textChanged"),
            (self.axis_label_edit, "textChanged"),
            (self.minimum_edit, "textChanged"),
            (self.maximum_edit, "textChanged"),
            (self.linear_radio, "toggled"),
            (self.log_radio, "toggled"),
            (self.major_grid_checkbox, "toggled"),
            (self.minor_grid_checkbox, "toggled"),
            (self.auto_range_checkbox, "toggled"),
            (self.reverse_axis_checkbox, "toggled"),
            (self.line_color_combo, "currentTextChanged"),
            (self.line_style_combo, "currentTextChanged"),
            (self.line_width_spin, "valueChanged"),
            (self.marker_style_combo, "currentTextChanged"),
            (self.marker_size_spin, "valueChanged"),
            (self.marker_fill_combo, "currentTextChanged"),
            (self.fill_enabled_checkbox, "toggled"),
            (self.fill_style_combo, "currentTextChanged"),
            (self.fill_color_combo, "currentTextChanged"),
            (self.fill_opacity_slider, "valueChanged"),
            (self.error_bars_checkbox, "toggled"),
            (self.show_trendline_checkbox, "toggled"),
            (self.trend_type_combo, "currentTextChanged"),
            (self.polynomial_order_spin, "valueChanged"),
            (self.show_equation_checkbox, "toggled"),
            (self.show_r_squared_checkbox, "toggled"),
            (self.show_mean_checkbox, "toggled"),
            (self.show_std_dev_checkbox, "toggled"),
            (self.show_min_max_checkbox, "toggled"),
            (self.show_sum_checkbox, "toggled"),
            (self.show_n_checkbox, "toggled"),
            (self.show_confidence_checkbox, "toggled"),
            (self.show_prediction_checkbox, "toggled"),
            (self.sync_with_combo, "currentTextChanged"),
            (self.sync_axis_combo, "currentTextChanged"),
            (self.link_x_axis_checkbox, "toggled"),
            (self.link_y_axis_checkbox, "toggled"),
            (self.events_enabled_checkbox, "toggled"),
        ]
        for widget, signal_name in signals:
            getattr(widget, signal_name).connect(self._emit_command)

    def command(self):
        axis = self.axis_combo.currentText()
        axis_label = self.axis_label_edit.text().strip()
        title = self.title_edit.text().strip()

        if self.linear_radio.isChecked():
            scale = "linear"
        elif self.log_radio.isChecked():
            scale = "log"
        elif self.log2_radio.isChecked():
            scale = "log2"
        else:
            scale = "linear"

        updates = [f"title={title!r}"]
        if axis == "bottom":
            updates.extend([
                f"xlabel={axis_label!r}",
                f"xscale={scale!r}",
                f"xgrid={self.major_grid_checkbox.isChecked()!r}",
                f"xmin={self._limit_value(self.minimum_edit.text())!r}",
                f"xmax={self._limit_value(self.maximum_edit.text())!r}",
            ])
        else:
            updates.extend([
                f"ylabel={axis_label!r}",
                f"yscale={scale!r}",
                f"ygrid={self.major_grid_checkbox.isChecked()!r}",
                f"ymin={self._limit_value(self.minimum_edit.text())!r}",
                f"ymax={self._limit_value(self.maximum_edit.text())!r}",
            ])
        return f"edit_figure({self.figure_id!r}, {', '.join(updates)})"

    def revert_command(self):
        axes = self.snapshot.get("axes", {})
        return (
            f"edit_figure({self.figure_id!r}, title={self.snapshot.get('title', '')!r}, "
            f"xlabel={axes.get('xlabel', '')!r}, ylabel={axes.get('ylabel', '')!r}, "
            f"xscale={axes.get('xscale', 'linear')!r}, yscale={axes.get('yscale', 'linear')!r}, "
            f"xgrid={axes.get('xgrid', False)!r}, ygrid={axes.get('ygrid', False)!r}, "
            f"xmin={axes.get('xmin')!r}, xmax={axes.get('xmax')!r}, "
            f"ymin={axes.get('ymin')!r}, ymax={axes.get('ymax')!r})"
        )

    def _load_axis(self):
        axes = self.snapshot.get("axes", {})
        self._loading = True
        axis = self.axis_combo.currentText()

        if axis == "bottom":
            self.axis_label_edit.setText(axes.get("xlabel", ""))
            scale = axes.get("xscale", "linear")
            self.minimum_edit.setText("" if axes.get("xmin") is None else repr(axes["xmin"]))
            self.maximum_edit.setText("" if axes.get("xmax") is None else repr(axes["xmax"]))
        else:
            self.axis_label_edit.setText(axes.get("ylabel", ""))
            scale = axes.get("yscale", "linear")
            self.minimum_edit.setText("" if axes.get("ymin") is None else repr(axes["ymin"]))
            self.maximum_edit.setText("" if axes.get("ymax") is None else repr(axes["ymax"]))

        if scale == "linear":
            self.linear_radio.setChecked(True)
        elif scale == "log":
            self.log_radio.setChecked(True)
        elif scale == "log2":
            self.log2_radio.setChecked(True)
        else:
            self.linear_radio.setChecked(True)

        self.major_grid_checkbox.setChecked(axes.get("xgrid" if axis == "bottom" else "ygrid", False))
        self._loading = False
        self._emit_command()

    def _emit_command(self, *_args):
        if not self._loading:
            self.command_changed.emit(self.command())

    def _limit_value(self, text):
        text = text.strip()
        return None if not text else float(text)

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Modify Axis",
            "Adjust axis settings including title, label, scale, grid, and limits. "
            "With Live Update enabled, edits are applied to the active figure immediately. "
            "The Graph, Analysis, and Advanced tabs contain additional styling and analysis options.",
        )


__all__ = ["FigureEditDialog"]
