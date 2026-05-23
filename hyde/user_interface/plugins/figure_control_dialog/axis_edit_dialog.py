from qtutils.qt import QtWidgets

from hyde.user_interface.shared.figure import (
    HydeFigureDialogWidget,
    MatplotlibColorLineEdit,
)

AXIS_TAB_TITLES = [
    "Axis",
    "Auto/Man Ticks",
    "Ticks and Grids",
    "Tick Options",
    "Axis Label",
    "Label Options",
    "Axis Range",
]

AXIS_SIDE_CHOICES = [
    ("Left", "left"),
    ("Bottom", "bottom"),
    ("Right", "right"),
    ("Top", "top"),
]

AXIS_MODE_CHOICES = [
    ("Linear", "linear"),
    ("Log", "log"),
    ("Log2", "log2"),
]

LOG_TICK_MODE_CHOICES = [
    ("Plain", "plain"),
    ("LogLin", "loglin"),
]

TICK_DIRECTION_CHOICES = [
    ("Outside", "outside"),
    ("Inside", "inside"),
    ("Both", "both"),
]

FORMATTER_STYLE_CHOICES = [
    ("Plain", "plain"),
    ("Scientific", "scientific"),
    ("Engineering", "engineering"),
]

GRID_WHICH_CHOICES = [
    ("Major", "major"),
    ("Minor", "minor"),
    ("Both", "both"),
]

LINE_STYLE_CHOICES = [
    ("Solid", "-"),
    ("Dashed", "--"),
    ("Dash-dot", "-."),
    ("Dotted", ":"),
]

LABEL_SIDE_CHOICES = [
    ("Primary", "primary"),
    ("Mirror", "mirror"),
]

LABEL_POSITION_MODE_CHOICES = [
    ("Auto", "auto"),
    ("Manual", "manual"),
]

AUTOSCALE_CHOICES = [
    ("Data", "data"),
    ("Tight", "tight"),
]

AXIS_DIALOG_COMBO_SPECS = (
    ("axis_selector", AXIS_SIDE_CHOICES),
    ("axis_mode_combo", AXIS_MODE_CHOICES),
    ("log_tick_mode_combo", LOG_TICK_MODE_CHOICES),
    ("major_tick_mode_combo", (("Auto", "auto"), ("Manual Step", "manual"))),
    ("formatter_style_combo", FORMATTER_STYLE_CHOICES),
    ("tick_direction_combo", TICK_DIRECTION_CHOICES),
    ("grid_which_combo", GRID_WHICH_CHOICES),
    ("grid_style_combo", LINE_STYLE_CHOICES),
    ("label_side_combo", LABEL_SIDE_CHOICES),
    ("label_position_mode_combo", LABEL_POSITION_MODE_CHOICES),
    ("autoscale_combo", AUTOSCALE_CHOICES),
    ("zero_line_style_combo", LINE_STYLE_CHOICES),
)

AXIS_DIALOG_COLOR_FIELD_SPECS = (
    ("side_color_container", "side_color_edit"),
    ("axis_label_color_container", "axis_label_color_edit"),
    ("tick_label_color_container", "tick_label_color_edit"),
    ("grid_color_container", "grid_color_edit"),
    ("zero_line_color_container", "zero_line_color_edit"),
)


def _format_optional_number(value):
    if value is None:
        return ""
    return str(float(value))


def _format_optional_text(value):
    if value in (None, ""):
        return ""
    return str(value)


def _format_float_list(values):
    if not values:
        return ""
    return ", ".join(str(float(value)) for value in values)


def _format_text_list(values):
    if not values:
        return ""
    return ", ".join(str(value) for value in values)


def _parse_optional_float(text, field_name):
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid number.") from exc


def _parse_float_list(text, field_name):
    stripped = str(text or "").strip()
    if not stripped:
        return None
    values = []
    for chunk in stripped.replace("\n", ",").split(","):
        item = chunk.strip()
        if not item:
            continue
        try:
            values.append(float(item))
        except ValueError as exc:
            raise ValueError(f"{field_name} must contain only numbers.") from exc
    return None if not values else values


def _parse_text_list(text):
    stripped = str(text or "").strip()
    if not stripped:
        return None
    values = [item.strip() for item in stripped.replace("\n", ",").split(",")]
    values = [value for value in values if value]
    return None if not values else values


def _axis_name_for_side(side):
    return "x" if side in {"bottom", "top"} else "y"


def _primary_side_for_axis(axis_name):
    return "bottom" if axis_name == "x" else "left"


def _mirror_side_for_axis(axis_name):
    return "top" if axis_name == "x" else "right"


def _label_choice_for_side(side, axis_name):
    return "primary" if side == _primary_side_for_axis(axis_name) else "mirror"


def _side_for_label_choice(choice, axis_name):
    return (
        _primary_side_for_axis(axis_name)
        if choice == "primary"
        else _mirror_side_for_axis(axis_name)
    )


class AxisEditDialog(HydeFigureDialogWidget):
    figure_patch_command_name = "axis_edit"

    def __init__(self, figure_context, services=None, parent=None):
        super().__init__(
            figure_context=figure_context,
            parent=parent,
            services=services,
        )
        self.setWindowTitle("Modify Axis")
        self._loading_controls = False
        self.load_ui("axis_edit_dialog.ui", module_name=__name__)
        self._install_color_fields()
        self._populate_choice_controls()
        self._wire_signals()
        self._apply_initial_dialog_size()
        self._load_initial_axis()

    def _install_color_fields(self):
        for container_name, attr_name in AXIS_DIALOG_COLOR_FIELD_SPECS:
            container = getattr(self.ui, container_name)
            widget = MatplotlibColorLineEdit(container)
            layout = container.layout()
            if layout is None:
                layout = QtWidgets.QHBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(widget)
            setattr(self.ui, attr_name, widget)

    def _populate_choice_controls(self):
        for name, choices in AXIS_DIALOG_COMBO_SPECS:
            combo = getattr(self.ui, name)
            combo.clear()
            for label, value in choices:
                combo.addItem(label, value)

    def _wire_signals(self):
        self.ui.axis_selector.currentIndexChanged.connect(self._on_axis_side_changed)
        self.ui.live_update_checkbox.toggled.connect(self._on_live_update_toggled)

        for name in (
            "axis_mode_combo",
            "log_tick_mode_combo",
            "major_tick_mode_combo",
            "formatter_style_combo",
            "tick_direction_combo",
            "grid_which_combo",
            "grid_style_combo",
            "label_side_combo",
            "label_position_mode_combo",
            "autoscale_combo",
            "zero_line_style_combo",
        ):
            getattr(self.ui, name).currentIndexChanged.connect(self._on_controls_changed)

        for name in (
            "side_visible_checkbox",
            "side_ticks_checkbox",
            "side_tick_labels_checkbox",
            "draw_on_top_checkbox",
            "minor_ticks_checkbox",
            "grid_visible_checkbox",
            "zero_line_visible_checkbox",
            "use_thousands_separator_checkbox",
            "zero_as_zero_checkbox",
            "trim_trailing_zeros_checkbox",
            "trim_leading_zero_checkbox",
            "prefer_exponent_checkbox",
            "label_visible_checkbox",
            "minimum_auto_checkbox",
            "maximum_auto_checkbox",
            "reverse_axis_checkbox",
        ):
            getattr(self.ui, name).toggled.connect(self._on_controls_changed)

        for name in (
            "side_line_width_spin",
            "side_offset_spin",
            "spine_offset_spin",
            "major_tick_count_spin",
            "major_tick_step_spin",
            "low_trip_spin",
            "high_trip_spin",
            "exponent_prescale_spin",
            "grid_width_spin",
            "zero_line_width_spin",
            "max_log_cycles_minor_spin",
            "max_log_cycles_minor_labels_spin",
            "line_spacing_spin",
            "label_rotation_spin",
            "label_position_spin",
            "label_offset_spin",
            "tick_label_rotation_spin",
            "tick_label_offset_spin",
        ):
            getattr(self.ui, name).valueChanged.connect(self._on_controls_changed)

        for name in (
            "major_tick_positions_edit",
            "major_tick_labels_edit",
            "display_range_min_edit",
            "display_range_max_edit",
            "suppressed_values_edit",
            "axis_label_edit",
            "minimum_edit",
            "maximum_edit",
        ):
            getattr(self.ui, name).editingFinished.connect(self._on_controls_changed)

        for name in (
            "side_color_edit",
            "axis_label_color_edit",
            "tick_label_color_edit",
            "grid_color_edit",
            "zero_line_color_edit",
        ):
            getattr(self.ui, name).editingFinished.connect(self._on_controls_changed)

        self.ui.set_auto_ticks_button.clicked.connect(self._set_auto_tick_values)
        self.ui.expand_range_button.clicked.connect(self._expand_range)
        self.ui.swap_range_button.clicked.connect(self._swap_range)
        self.ui.set_autoscale_values_button.clicked.connect(self._set_autoscale_values)

    def _apply_initial_dialog_size(self):
        tab_bar_width = self.ui.tab_widget.tabBar().sizeHint().width()
        target_width = max(self.sizeHint().width(), tab_bar_width + 48)
        self.setMinimumWidth(target_width)
        self.resize(target_width, max(self.height(), self.sizeHint().height()))

    def has_supported_axes(self):
        return bool(self._session.subplot_ids())

    def _load_initial_axis(self):
        if not self.has_supported_axes():
            self.refresh_figure_preview()
            return
        index = self.ui.axis_selector.findData("bottom")
        if index >= 0:
            self.ui.axis_selector.setCurrentIndex(index)
        self._load_selected_side()

    def _on_axis_side_changed(self, index):
        if index < 0:
            return
        self._load_selected_side()

    def _current_subplot(self):
        subplot_ids = self._session.subplot_ids()
        return None if not subplot_ids else subplot_ids[0]

    def _selected_context(self):
        subplot_id = self._current_subplot()
        if subplot_id is None:
            return None
        side = self.ui.axis_selector.currentData()
        if side not in {"left", "bottom", "right", "top"}:
            return None
        axis_name = _axis_name_for_side(side)
        return {
            "subplot_id": subplot_id,
            "side": side,
            "axis_name": axis_name,
        }

    def _load_selected_side(self):
        context = self._selected_context()
        if context is None:
            self.refresh_figure_preview()
            return
        subplot_id = context["subplot_id"]
        axis_name = context["axis_name"]
        side = context["side"]
        limits = self._session.axis_limits(axis_name, subplot_id=subplot_id) or (
            None,
            None,
        )
        display_range = self._session.axis_value(
            axis_name,
            "ticks",
            "display_range",
            subplot_id=subplot_id,
        ) or (None, None)
        limit_mode = self._session.axis_limit_mode(
            axis_name,
            subplot_id=subplot_id,
        ) or {}

        self._loading_controls = True
        try:
            self._set_combo_data(
                self.ui.axis_mode_combo,
                self._session.axis_scale(axis_name, subplot_id=subplot_id),
            )
            self._set_combo_data(
                self.ui.log_tick_mode_combo,
                self._session.axis_value(
                    axis_name,
                    "log_tick_mode",
                    subplot_id=subplot_id,
                    default="plain",
                ),
            )
            self.ui.axis_label_edit.setText(
                _format_optional_text(
                    self._session.axis_label(axis_name, subplot_id=subplot_id)
                )
            )
            self.ui.axis_label_preview.setText(self.ui.axis_label_edit.text())
            self.ui.label_visible_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "label",
                        "visible",
                        subplot_id=subplot_id,
                    )
                )
            )
            self._set_combo_data(
                self.ui.label_side_combo,
                _label_choice_for_side(
                    self._session.axis_value(
                        axis_name,
                        "label",
                        "side",
                        subplot_id=subplot_id,
                    ),
                    axis_name,
                ),
            )
            self._set_combo_data(
                self.ui.label_position_mode_combo,
                self._session.axis_value(
                    axis_name,
                    "label",
                    "position_mode",
                    subplot_id=subplot_id,
                    default="auto",
                ),
            )
            self.ui.label_position_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "label",
                        "position",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.label_offset_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "label",
                        "offset",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.label_rotation_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "label",
                        "rotation",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.line_spacing_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "label",
                        "line_spacing",
                        subplot_id=subplot_id,
                    )
                    or 1.2
                )
            )
            self.ui.axis_label_color_edit.set_committed_text(
                _format_optional_text(
                    self._session.axis_value(
                        axis_name,
                        "label",
                        "color",
                        subplot_id=subplot_id,
                    )
                )
            )
            self._set_combo_data(
                self.ui.autoscale_combo,
                self._session.axis_value(
                    axis_name,
                    "range",
                    "autoscale",
                    subplot_id=subplot_id,
                    default="data",
                ),
            )
            self.ui.minimum_auto_checkbox.setChecked(limit_mode.get("min", "auto") == "auto")
            self.ui.minimum_edit.setText(_format_optional_number(limits[0]))
            self.ui.maximum_auto_checkbox.setChecked(limit_mode.get("max", "auto") == "auto")
            self.ui.maximum_edit.setText(_format_optional_number(limits[1]))
            self.ui.reverse_axis_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "range",
                        "reverse",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.side_visible_checkbox.setChecked(
                bool(
                    self._session.axis_side_value(
                        side,
                        "spine_visible",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.side_ticks_checkbox.setChecked(
                bool(
                    self._session.axis_side_value(
                        side,
                        "ticks_visible",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.side_tick_labels_checkbox.setChecked(
                bool(
                    self._session.axis_side_value(
                        side,
                        "tick_labels_visible",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.side_line_width_spin.setValue(
                float(
                    self._session.axis_side_value(
                        side,
                        "spine_width",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.side_offset_spin.setValue(
                float(self._session.subplot_margin(side, subplot_id=subplot_id) or 0.0)
            )
            self.ui.spine_offset_spin.setValue(
                float(
                    self._session.axis_side_value(
                        side,
                        "offset",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.draw_on_top_checkbox.setChecked(
                bool(
                    self._session.axis_side_value(
                        side,
                        "draw_on_top",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.side_color_edit.set_committed_text(
                _format_optional_text(
                    self._session.axis_side_value(
                        side,
                        "spine_color",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.tick_label_color_edit.set_committed_text(
                _format_optional_text(
                    self._session.axis_side_value(
                        side,
                        "tick_label_color",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.tick_label_rotation_spin.setValue(
                float(
                    self._session.axis_side_value(
                        side,
                        "tick_label_rotation",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.tick_label_offset_spin.setValue(
                float(
                    self._session.axis_side_value(
                        side,
                        "tick_label_offset",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.major_tick_count_spin.setValue(
                int(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "major",
                        "count",
                        subplot_id=subplot_id,
                    )
                    or 0
                )
            )
            self.ui.major_tick_step_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "major",
                        "step",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.major_tick_positions_edit.setText(
                _format_float_list(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "major",
                        "positions",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.major_tick_labels_edit.setText(
                _format_text_list(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "major",
                        "labels",
                        subplot_id=subplot_id,
                    )
                )
            )
            self._set_combo_data(
                self.ui.major_tick_mode_combo,
                self._session.axis_value(
                    axis_name,
                    "ticks",
                    "major",
                    "mode",
                    subplot_id=subplot_id,
                    default="auto",
                ),
            )
            self.ui.minor_ticks_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "minor",
                        "visible",
                        subplot_id=subplot_id,
                    )
                )
            )
            self._set_combo_data(
                self.ui.tick_direction_combo,
                self._session.axis_value(
                    axis_name,
                    "ticks",
                    "direction",
                    subplot_id=subplot_id,
                    default="outside",
                ),
            )
            self._set_combo_data(
                self.ui.formatter_style_combo,
                self._session.axis_value(
                    axis_name,
                    "ticks",
                    "formatter",
                    "style",
                    subplot_id=subplot_id,
                    default="plain",
                ),
            )
            self.ui.low_trip_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "low_trip",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.high_trip_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "high_trip",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.exponent_prescale_spin.setValue(
                int(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "exponent_prescale",
                        subplot_id=subplot_id,
                    )
                    or 0
                )
            )
            self.ui.display_range_min_edit.setText(_format_optional_number(display_range[0]))
            self.ui.display_range_max_edit.setText(_format_optional_number(display_range[1]))
            self.ui.suppressed_values_edit.setText(
                _format_float_list(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "suppressed_values",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.max_log_cycles_minor_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "max_log_cycles_minor",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.max_log_cycles_minor_labels_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "max_log_cycles_minor_labels",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.use_thousands_separator_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "use_thousands_separator",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.zero_as_zero_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "zero_as_zero",
                        subplot_id=subplot_id,
                        default=True,
                    )
                )
            )
            self.ui.trim_trailing_zeros_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "trim_trailing_zeros",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.trim_leading_zero_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "trim_leading_zero",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.prefer_exponent_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "ticks",
                        "formatter",
                        "prefer_exponent",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.grid_visible_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "grid",
                        "visible",
                        subplot_id=subplot_id,
                    )
                )
            )
            self._set_combo_data(
                self.ui.grid_which_combo,
                self._session.axis_value(
                    axis_name,
                    "grid",
                    "which",
                    subplot_id=subplot_id,
                    default="major",
                ),
            )
            self._set_combo_data(
                self.ui.grid_style_combo,
                self._session.axis_value(
                    axis_name,
                    "grid",
                    "linestyle",
                    subplot_id=subplot_id,
                    default="-",
                ),
            )
            self.ui.grid_width_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "grid",
                        "linewidth",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.grid_color_edit.set_committed_text(
                _format_optional_text(
                    self._session.axis_value(
                        axis_name,
                        "grid",
                        "color",
                        subplot_id=subplot_id,
                    )
                )
            )
            self.ui.zero_line_visible_checkbox.setChecked(
                bool(
                    self._session.axis_value(
                        axis_name,
                        "zero_line",
                        "visible",
                        subplot_id=subplot_id,
                    )
                )
            )
            self._set_combo_data(
                self.ui.zero_line_style_combo,
                self._session.axis_value(
                    axis_name,
                    "zero_line",
                    "linestyle",
                    subplot_id=subplot_id,
                    default="-",
                ),
            )
            self.ui.zero_line_width_spin.setValue(
                float(
                    self._session.axis_value(
                        axis_name,
                        "zero_line",
                        "linewidth",
                        subplot_id=subplot_id,
                    )
                    or 0.0
                )
            )
            self.ui.zero_line_color_edit.set_committed_text(
                _format_optional_text(
                    self._session.axis_value(
                        axis_name,
                        "zero_line",
                        "color",
                        subplot_id=subplot_id,
                    )
                )
            )
        finally:
            self._loading_controls = False
        self.refresh_figure_preview()

    def _set_combo_data(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _validate_range_inputs(self):
        minimum_auto = bool(self.ui.minimum_auto_checkbox.isChecked())
        maximum_auto = bool(self.ui.maximum_auto_checkbox.isChecked())
        try:
            minimum = None if minimum_auto else _parse_optional_float(self.ui.minimum_edit.text(), "Minimum")
            maximum = None if maximum_auto else _parse_optional_float(self.ui.maximum_edit.text(), "Maximum")
        except ValueError as exc:
            return {"limits": None, "valid": False, "message": str(exc)}
        if not minimum_auto and minimum is None:
            return {"limits": None, "valid": False, "message": "Minimum is required when auto minimum is off."}
        if not maximum_auto and maximum is None:
            return {"limits": None, "valid": False, "message": "Maximum is required when auto maximum is off."}
        if minimum is None and maximum is None:
            return {"limits": None, "valid": True, "message": ""}
        if minimum is not None and maximum is not None and minimum >= maximum:
            return {
                "limits": None,
                "valid": False,
                "message": "Minimum must be smaller than maximum.",
            }
        return {
            "limits": (minimum, maximum),
            "valid": True,
            "message": "",
            "limit_mode": {
                "min": "auto" if minimum_auto else "manual",
                "max": "auto" if maximum_auto else "manual",
            },
        }

    def _validate_display_range_inputs(self):
        minimum_text = self.ui.display_range_min_edit.text().strip()
        maximum_text = self.ui.display_range_max_edit.text().strip()
        if not minimum_text and not maximum_text:
            return {"display_range": None, "valid": True, "message": ""}
        try:
            minimum = _parse_optional_float(minimum_text, "Display-range minimum")
            maximum = _parse_optional_float(maximum_text, "Display-range maximum")
        except ValueError as exc:
            return {"display_range": None, "valid": False, "message": str(exc)}
        if minimum is None or maximum is None:
            return {
                "display_range": None,
                "valid": False,
                "message": "Display range requires both minimum and maximum.",
            }
        if minimum >= maximum:
            return {
                "display_range": None,
                "valid": False,
                "message": "Display-range minimum must be smaller than the maximum.",
            }
        return {"display_range": (minimum, maximum), "valid": True, "message": ""}

    def _apply_current_controls_to_session(self):
        context = self._selected_context()
        if context is None:
            return {"valid": False, "message": "No active axis selection."}

        subplot_id = context["subplot_id"]
        axis_name = context["axis_name"]
        side = context["side"]
        axis_state = self._session.axis_value(axis_name, subplot_id=subplot_id)
        side_state = self._session.axis_side_value(side, subplot_id=subplot_id)
        margins = {
            margin_side: self._session.subplot_margin(
                margin_side,
                subplot_id=subplot_id,
            )
            for margin_side in ("left", "bottom", "right", "top")
        }
        range_validation = self._validate_range_inputs()
        if not range_validation["valid"]:
            return range_validation
        display_range_validation = self._validate_display_range_inputs()
        if not display_range_validation["valid"]:
            return display_range_validation
        try:
            manual_positions = _parse_float_list(
                self.ui.major_tick_positions_edit.text(),
                "Manual positions",
            )
            manual_labels = _parse_text_list(self.ui.major_tick_labels_edit.text())
            suppressed_values = _parse_float_list(
                self.ui.suppressed_values_edit.text(),
                "Suppress values",
            )
        except ValueError as exc:
            return {"valid": False, "message": str(exc)}
        if manual_labels is not None and manual_positions is None:
            return {
                "valid": False,
                "message": "Manual labels require manual positions.",
            }
        if (
            manual_labels is not None
            and manual_positions is not None
            and len(manual_labels) != len(manual_positions)
        ):
            return {
                "valid": False,
                "message": "Manual labels must match the number of manual positions.",
            }

        axis_state["scale_mode"] = str(self.ui.axis_mode_combo.currentData() or "linear")
        axis_state["log_tick_mode"] = str(
            self.ui.log_tick_mode_combo.currentData() or "plain"
        )
        label_text = self.ui.axis_label_edit.text().strip()
        axis_state["label"]["text"] = None if not label_text else label_text
        axis_state["label"]["visible"] = bool(self.ui.label_visible_checkbox.isChecked())
        axis_state["label"]["side"] = _side_for_label_choice(
            self.ui.label_side_combo.currentData() or "primary",
            axis_name,
        )
        axis_state["label"]["position_mode"] = str(
            self.ui.label_position_mode_combo.currentData() or "auto"
        )
        label_position = float(self.ui.label_position_spin.value())
        axis_state["label"]["position"] = (
            None
            if axis_state["label"]["position_mode"] == "auto"
            else label_position
        )
        axis_state["label"]["offset"] = float(self.ui.label_offset_spin.value())
        axis_state["label"]["rotation"] = float(self.ui.label_rotation_spin.value())
        axis_state["label"]["line_spacing"] = float(self.ui.line_spacing_spin.value())
        label_color = self.ui.axis_label_color_edit.text().strip()
        axis_state["label"]["color"] = None if not label_color else label_color
        axis_state["range"]["limits"] = range_validation["limits"]
        axis_state["range"]["limit_mode"] = dict(range_validation.get("limit_mode", {}))
        axis_state["range"]["autoscale"] = str(
            self.ui.autoscale_combo.currentData() or "data"
        )
        axis_state["range"]["reverse"] = bool(self.ui.reverse_axis_checkbox.isChecked())
        axis_state["ticks"]["major"]["mode"] = str(
            self.ui.major_tick_mode_combo.currentData() or "auto"
        )
        count = int(self.ui.major_tick_count_spin.value())
        axis_state["ticks"]["major"]["count"] = None if count <= 0 else count
        step = float(self.ui.major_tick_step_spin.value())
        axis_state["ticks"]["major"]["step"] = None if step <= 0 else step
        axis_state["ticks"]["major"]["positions"] = manual_positions
        axis_state["ticks"]["major"]["labels"] = manual_labels
        axis_state["ticks"]["minor"]["visible"] = bool(
            self.ui.minor_ticks_checkbox.isChecked()
        )
        axis_state["ticks"]["direction"] = str(
            self.ui.tick_direction_combo.currentData() or "outside"
        )
        axis_state["ticks"]["formatter"]["style"] = str(
            self.ui.formatter_style_combo.currentData() or "plain"
        )
        axis_state["ticks"]["formatter"]["low_trip"] = (
            None if self.ui.low_trip_spin.value() == 0.0 else float(self.ui.low_trip_spin.value())
        )
        axis_state["ticks"]["formatter"]["high_trip"] = (
            None if self.ui.high_trip_spin.value() == 0.0 else float(self.ui.high_trip_spin.value())
        )
        axis_state["ticks"]["formatter"]["exponent_prescale"] = (
            None
            if self.ui.exponent_prescale_spin.value() == 0
            else float(self.ui.exponent_prescale_spin.value())
        )
        axis_state["ticks"]["formatter"]["use_thousands_separator"] = bool(
            self.ui.use_thousands_separator_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["zero_as_zero"] = bool(
            self.ui.zero_as_zero_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["trim_trailing_zeros"] = bool(
            self.ui.trim_trailing_zeros_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["trim_leading_zero"] = bool(
            self.ui.trim_leading_zero_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["prefer_exponent"] = bool(
            self.ui.prefer_exponent_checkbox.isChecked()
        )
        axis_state["ticks"]["suppressed_values"] = suppressed_values or []
        axis_state["ticks"]["display_range"] = display_range_validation["display_range"]
        axis_state["ticks"]["max_log_cycles_minor"] = (
            None
            if self.ui.max_log_cycles_minor_spin.value() <= 0
            else float(self.ui.max_log_cycles_minor_spin.value())
        )
        axis_state["ticks"]["max_log_cycles_minor_labels"] = (
            None
            if self.ui.max_log_cycles_minor_labels_spin.value() <= 0
            else float(self.ui.max_log_cycles_minor_labels_spin.value())
        )
        axis_state["grid"]["visible"] = bool(self.ui.grid_visible_checkbox.isChecked())
        axis_state["grid"]["which"] = str(self.ui.grid_which_combo.currentData() or "major")
        axis_state["grid"]["linestyle"] = str(self.ui.grid_style_combo.currentData() or "-")
        grid_width = float(self.ui.grid_width_spin.value())
        axis_state["grid"]["linewidth"] = None if grid_width <= 0 else grid_width
        grid_color = self.ui.grid_color_edit.text().strip()
        axis_state["grid"]["color"] = None if not grid_color else grid_color
        axis_state["zero_line"]["visible"] = bool(
            self.ui.zero_line_visible_checkbox.isChecked()
        )
        axis_state["zero_line"]["linestyle"] = str(
            self.ui.zero_line_style_combo.currentData() or "-"
        )
        zero_width = float(self.ui.zero_line_width_spin.value())
        axis_state["zero_line"]["linewidth"] = None if zero_width <= 0 else zero_width
        zero_color = self.ui.zero_line_color_edit.text().strip()
        axis_state["zero_line"]["color"] = None if not zero_color else zero_color

        side_state["spine_visible"] = bool(self.ui.side_visible_checkbox.isChecked())
        side_state["ticks_visible"] = bool(self.ui.side_ticks_checkbox.isChecked())
        side_state["tick_labels_visible"] = bool(
            self.ui.side_tick_labels_checkbox.isChecked()
        )
        width = float(self.ui.side_line_width_spin.value())
        side_state["spine_width"] = None if width <= 0 else width
        margins[side] = float(self.ui.side_offset_spin.value())
        side_state["offset"] = float(self.ui.spine_offset_spin.value())
        side_state["draw_on_top"] = bool(self.ui.draw_on_top_checkbox.isChecked())
        side_color = self.ui.side_color_edit.text().strip()
        side_state["spine_color"] = None if not side_color else side_color
        tick_color = self.ui.tick_label_color_edit.text().strip()
        side_state["tick_label_color"] = None if not tick_color else tick_color
        side_state["tick_label_rotation"] = float(self.ui.tick_label_rotation_spin.value())
        side_state["tick_label_offset"] = float(self.ui.tick_label_offset_spin.value())

        try:
            self._session.set_axis_state(
                axis_name,
                axis_state,
                subplot_id=subplot_id,
                replace=True,
            )
            self._session.set_axis_side_state(
                side,
                side_state,
                subplot_id=subplot_id,
                replace=True,
            )
            self._session.set_subplot_margins(
                subplot_id=subplot_id,
                replace=True,
                **margins,
            )
        except ValueError as exc:
            return {"valid": False, "message": str(exc)}
        return {"valid": True, "message": ""}

    def _on_controls_changed(self, *args):
        del args
        if self._loading_controls:
            return
        self.ui.axis_label_preview.setText(self.ui.axis_label_edit.text())
        result = self._apply_current_controls_to_session()
        self.refresh_figure_preview(result["message"])
        if not result["valid"]:
            return
        if self.ui.live_update_checkbox.isChecked():
            self.apply_current_figure_patch(mode="live_update")

    def _on_live_update_toggled(self, checked):
        if self._loading_controls or not checked:
            return
        result = self._apply_current_controls_to_session()
        self.refresh_figure_preview(result["message"])
        if result["valid"]:
            self.apply_current_figure_patch(mode="live_update_enable")

    def _set_auto_tick_values(self):
        self.ui.major_tick_mode_combo.setCurrentIndex(self.ui.major_tick_mode_combo.findData("auto"))
        self.ui.major_tick_count_spin.setValue(0)
        self.ui.major_tick_step_spin.setValue(0.0)
        self.ui.major_tick_positions_edit.clear()
        self.ui.major_tick_labels_edit.clear()

    def _swap_range(self):
        minimum = self.ui.minimum_edit.text()
        maximum = self.ui.maximum_edit.text()
        self.ui.minimum_edit.setText(maximum)
        self.ui.maximum_edit.setText(minimum)
        self._on_controls_changed()

    def _expand_range(self):
        validation = self._validate_range_inputs()
        limits = validation.get("limits")
        if not validation.get("valid") or not limits or limits[0] is None or limits[1] is None:
            return
        span = limits[1] - limits[0]
        if span <= 0:
            return
        delta = span * 0.05
        self.ui.minimum_edit.setText(str(limits[0] - delta))
        self.ui.maximum_edit.setText(str(limits[1] + delta))
        self._on_controls_changed()

    def _set_autoscale_values(self):
        context = self._selected_context()
        if context is None:
            return
        resolved_limits = self._session.resolved_axis_limits(
            context["axis_name"],
            subplot_id=context["subplot_id"],
        )
        if not isinstance(resolved_limits, (list, tuple)) or len(resolved_limits) != 2:
            return
        self._loading_controls = True
        try:
            self.ui.minimum_edit.setText(_format_optional_number(resolved_limits[0]))
            self.ui.maximum_edit.setText(_format_optional_number(resolved_limits[1]))
            self.ui.minimum_auto_checkbox.setChecked(False)
            self.ui.maximum_auto_checkbox.setChecked(False)
        finally:
            self._loading_controls = False
        self._on_controls_changed()
