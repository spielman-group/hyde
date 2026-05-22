import copy

from qtutils.qt import QtCore, QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec
from hyde.user_interface.shared.figure import MatplotlibColorLineEdit
from hyde.user_interface.base_hyde_widgets import HydeDialogWidget
from hyde.user_interface.shared.figure import (
    FigureControlDraftTracker,
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


def _default_subplot_state():
    return FigureIRCodec.validate_state({"layout": {"subplots": [{}]}})["layout"][
        "subplots"
    ][0]


def _merge_defaulted_value(current, default, baseline):
    if isinstance(baseline, dict) and isinstance(current, dict):
        merged = {}
        keys = set(baseline) | set(current) | set(default or {})
        for key in keys:
            merged[key] = _merge_defaulted_value(
                current.get(key),
                None if not isinstance(default, dict) else default.get(key),
                baseline.get(key),
            )
        return merged
    if current != baseline:
        return copy.deepcopy(current)
    if default is not None:
        return copy.deepcopy(default)
    return copy.deepcopy(current)


def _merge_figure_ir_with_defaults(figure_ir, figure_defaults):
    if figure_ir is None:
        return None
    if not isinstance(figure_defaults, dict):
        return copy.deepcopy(figure_ir)
    merged = FigureIRCodec.validate_state(figure_ir)
    defaults = FigureIRCodec.validate_state(figure_defaults)
    baseline_subplot = _default_subplot_state()
    default_subplots = {
        subplot["id"]: subplot for subplot in defaults.get("layout", {}).get("subplots", [])
    }
    for subplot in merged.get("layout", {}).get("subplots", []):
        default_subplot = default_subplots.get(subplot["id"])
        if default_subplot is None:
            continue
        for axis_name in ("x", "y"):
            subplot["axes"][axis_name] = _merge_defaulted_value(
                subplot["axes"][axis_name],
                default_subplot["axes"][axis_name],
                baseline_subplot["axes"][axis_name],
            )
        for side in ("bottom", "top", "left", "right"):
            subplot["axis_sides"][side] = _merge_defaulted_value(
                subplot["axis_sides"][side],
                default_subplot["axis_sides"][side],
                baseline_subplot["axis_sides"][side],
            )
    return merged


class AxisEditDialog(HydeDialogWidget):
    def __init__(self, figure_context, services=None, parent=None):
        self.figure_context = figure_context
        self._preview_error_message = ""
        self._draft_figure_ir = None
        super().__init__(parent=parent, services=dict(services or {}))
        self.setWindowTitle("Modify Axis")
        self._loading_controls = False
        self._live_updates_sent = False
        self._original_figure_ir = self.figure_context.figure_ir()
        self._draft_tracker = FigureControlDraftTracker()
        self._draft_figure_ir = self._draft_tracker.seed(
            "figure",
            _merge_figure_ir_with_defaults(
                self._original_figure_ir,
                self.figure_context.figure_defaults(),
            ),
            revert_state=self._original_figure_ir,
        )
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
        return self._current_subplot() is not None

    def _load_initial_axis(self):
        if not self.has_supported_axes():
            self._update_preview()
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
        if self._draft_figure_ir is None:
            return None
        subplots = self._draft_figure_ir.get("layout", {}).get("subplots", [])
        return None if not subplots else subplots[0]

    def _selected_context(self):
        subplot = self._current_subplot()
        if subplot is None:
            return None
        side = self.ui.axis_selector.currentData()
        if side not in {"left", "bottom", "right", "top"}:
            return None
        axis_name = _axis_name_for_side(side)
        return {
            "subplot": subplot,
            "subplot_id": subplot["id"],
            "side": side,
            "axis_name": axis_name,
            "axis_state": subplot["axes"][axis_name],
            "side_state": subplot["axis_sides"][side],
        }

    def _load_selected_side(self):
        context = self._selected_context()
        if context is None:
            self._update_preview()
            return
        axis_state = context["axis_state"]
        side_state = context["side_state"]
        label_state = dict(axis_state.get("label", {}) or {})
        range_state = dict(axis_state.get("range", {}) or {})
        tick_state = dict(axis_state.get("ticks", {}) or {})
        major_ticks = dict(tick_state.get("major", {}) or {})
        formatter_state = dict(tick_state.get("formatter", {}) or {})
        grid_state = dict(axis_state.get("grid", {}) or {})
        zero_line_state = dict(axis_state.get("zero_line", {}) or {})
        limits = range_state.get("limits") or (None, None)
        display_range = tick_state.get("display_range") or (None, None)
        limit_mode = dict(range_state.get("limit_mode", {}) or {})
        margins = dict(context["subplot"].get("margins", {}) or {})

        self._loading_controls = True
        try:
            self._set_combo_data(self.ui.axis_mode_combo, axis_state.get("scale_mode"))
            self._set_combo_data(
                self.ui.log_tick_mode_combo,
                axis_state.get("log_tick_mode", "plain"),
            )
            self.ui.axis_label_edit.setText(_format_optional_text(label_state.get("text")))
            self.ui.axis_label_preview.setText(_format_optional_text(label_state.get("text")))
            self.ui.label_visible_checkbox.setChecked(bool(label_state.get("visible")))
            self._set_combo_data(
                self.ui.label_side_combo,
                _label_choice_for_side(label_state.get("side"), context["axis_name"]),
            )
            self._set_combo_data(
                self.ui.label_position_mode_combo,
                label_state.get("position_mode", "auto"),
            )
            self.ui.label_position_spin.setValue(float(label_state.get("position") or 0.0))
            self.ui.label_offset_spin.setValue(float(label_state.get("offset") or 0.0))
            self.ui.label_rotation_spin.setValue(float(label_state.get("rotation") or 0.0))
            self.ui.line_spacing_spin.setValue(float(label_state.get("line_spacing") or 1.2))
            self.ui.axis_label_color_edit.set_committed_text(
                _format_optional_text(label_state.get("color"))
            )
            self._set_combo_data(
                self.ui.autoscale_combo,
                range_state.get("autoscale", "data"),
            )
            self.ui.minimum_auto_checkbox.setChecked(limit_mode.get("min", "auto") == "auto")
            self.ui.minimum_edit.setText(_format_optional_number(limits[0]))
            self.ui.maximum_auto_checkbox.setChecked(limit_mode.get("max", "auto") == "auto")
            self.ui.maximum_edit.setText(_format_optional_number(limits[1]))
            self.ui.reverse_axis_checkbox.setChecked(bool(range_state.get("reverse")))
            self.ui.side_visible_checkbox.setChecked(bool(side_state.get("spine_visible")))
            self.ui.side_ticks_checkbox.setChecked(bool(side_state.get("ticks_visible")))
            self.ui.side_tick_labels_checkbox.setChecked(
                bool(side_state.get("tick_labels_visible"))
            )
            self.ui.side_line_width_spin.setValue(
                float(side_state.get("spine_width") or 0.0)
            )
            self.ui.side_offset_spin.setValue(float(margins.get(context["side"]) or 0.0))
            self.ui.spine_offset_spin.setValue(float(side_state.get("offset") or 0.0))
            self.ui.draw_on_top_checkbox.setChecked(bool(side_state.get("draw_on_top")))
            self.ui.side_color_edit.set_committed_text(
                _format_optional_text(side_state.get("spine_color"))
            )
            self.ui.tick_label_color_edit.set_committed_text(
                _format_optional_text(side_state.get("tick_label_color"))
            )
            self.ui.tick_label_rotation_spin.setValue(
                float(side_state.get("tick_label_rotation") or 0.0)
            )
            self.ui.tick_label_offset_spin.setValue(
                float(side_state.get("tick_label_offset") or 0.0)
            )
            self.ui.major_tick_count_spin.setValue(int(major_ticks.get("count") or 0))
            self.ui.major_tick_step_spin.setValue(float(major_ticks.get("step") or 0.0))
            self.ui.major_tick_positions_edit.setText(
                _format_float_list(major_ticks.get("positions"))
            )
            self.ui.major_tick_labels_edit.setText(
                _format_text_list(major_ticks.get("labels"))
            )
            self._set_combo_data(
                self.ui.major_tick_mode_combo,
                major_ticks.get("mode", "auto"),
            )
            self.ui.minor_ticks_checkbox.setChecked(
                bool(dict(tick_state.get("minor", {}) or {}).get("visible"))
            )
            self._set_combo_data(
                self.ui.tick_direction_combo,
                tick_state.get("direction", "outside"),
            )
            self._set_combo_data(
                self.ui.formatter_style_combo,
                formatter_state.get("style", "plain"),
            )
            self.ui.low_trip_spin.setValue(float(formatter_state.get("low_trip") or 0.0))
            self.ui.high_trip_spin.setValue(float(formatter_state.get("high_trip") or 0.0))
            self.ui.exponent_prescale_spin.setValue(
                int(formatter_state.get("exponent_prescale") or 0)
            )
            self.ui.display_range_min_edit.setText(_format_optional_number(display_range[0]))
            self.ui.display_range_max_edit.setText(_format_optional_number(display_range[1]))
            self.ui.suppressed_values_edit.setText(
                _format_float_list(tick_state.get("suppressed_values"))
            )
            self.ui.max_log_cycles_minor_spin.setValue(
                float(tick_state.get("max_log_cycles_minor") or 0.0)
            )
            self.ui.max_log_cycles_minor_labels_spin.setValue(
                float(tick_state.get("max_log_cycles_minor_labels") or 0.0)
            )
            self.ui.use_thousands_separator_checkbox.setChecked(
                bool(formatter_state.get("use_thousands_separator"))
            )
            self.ui.zero_as_zero_checkbox.setChecked(
                bool(formatter_state.get("zero_as_zero", True))
            )
            self.ui.trim_trailing_zeros_checkbox.setChecked(
                bool(formatter_state.get("trim_trailing_zeros"))
            )
            self.ui.trim_leading_zero_checkbox.setChecked(
                bool(formatter_state.get("trim_leading_zero"))
            )
            self.ui.prefer_exponent_checkbox.setChecked(
                bool(formatter_state.get("prefer_exponent"))
            )
            self.ui.grid_visible_checkbox.setChecked(bool(grid_state.get("visible")))
            self._set_combo_data(self.ui.grid_which_combo, grid_state.get("which", "major"))
            self._set_combo_data(
                self.ui.grid_style_combo,
                grid_state.get("linestyle", "-"),
            )
            self.ui.grid_width_spin.setValue(float(grid_state.get("linewidth") or 0.0))
            self.ui.grid_color_edit.set_committed_text(
                _format_optional_text(grid_state.get("color"))
            )
            self.ui.zero_line_visible_checkbox.setChecked(bool(zero_line_state.get("visible")))
            self._set_combo_data(
                self.ui.zero_line_style_combo,
                zero_line_state.get("linestyle", "-"),
            )
            self.ui.zero_line_width_spin.setValue(
                float(zero_line_state.get("linewidth") or 0.0)
            )
            self.ui.zero_line_color_edit.set_committed_text(
                _format_optional_text(zero_line_state.get("color"))
            )
        finally:
            self._loading_controls = False
        self._update_preview()

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

    def _apply_current_controls_to_draft(self):
        context = self._selected_context()
        if context is None:
            return {"valid": False, "message": "No active axis selection."}

        axis_state = context["axis_state"]
        side_state = context["side_state"]
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
            context["axis_name"],
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
        context["subplot"]["margins"][context["side"]] = float(self.ui.side_offset_spin.value())
        side_state["offset"] = float(self.ui.spine_offset_spin.value())
        side_state["draw_on_top"] = bool(self.ui.draw_on_top_checkbox.isChecked())
        side_color = self.ui.side_color_edit.text().strip()
        side_state["spine_color"] = None if not side_color else side_color
        tick_color = self.ui.tick_label_color_edit.text().strip()
        side_state["tick_label_color"] = None if not tick_color else tick_color
        side_state["tick_label_rotation"] = float(self.ui.tick_label_rotation_spin.value())
        side_state["tick_label_offset"] = float(self.ui.tick_label_offset_spin.value())

        try:
            self._draft_figure_ir = self._draft_tracker.replace(
                "figure",
                FigureIRCodec.validate_state(self._draft_figure_ir),
            )
        except ValueError as exc:
            return {"valid": False, "message": str(exc)}
        return {"valid": True, "message": ""}

    def _dispatch_selected_state(self):
        context = self._selected_context()
        if context is None:
            return False
        sent = False
        axis_action = {
            "type": "set_axis_state",
            "subplot_id": context["subplot_id"],
            "axis": context["axis_name"],
            "state": dict(context["axis_state"]),
            "replace": True,
        }
        sent = self.figure_context.request_figure_action(axis_action) or sent
        side_action = {
            "type": "set_axis_side_state",
            "subplot_id": context["subplot_id"],
            "side": context["side"],
            "state": dict(context["side_state"]),
            "replace": True,
        }
        sent = self.figure_context.request_figure_action(side_action) or sent
        layout_action = {
            "type": "set_subplot_margins",
            "subplot_id": context["subplot_id"],
            "state": dict(context["subplot"].get("margins", {}) or {}),
            "replace": True,
        }
        sent = self.figure_context.request_figure_action(layout_action) or sent
        if sent:
            self._live_updates_sent = True
        return sent

    def _dispatch_all_state(self, figure_ir):
        if figure_ir is None:
            return False
        subplots = figure_ir.get("layout", {}).get("subplots", [])
        if not subplots:
            return False
        subplot = subplots[0]
        sent = False
        for axis_name in ("x", "y"):
            action = {
                "type": "set_axis_state",
                "subplot_id": subplot["id"],
                "axis": axis_name,
                "state": dict(subplot["axes"][axis_name]),
                "replace": True,
            }
            sent = self.figure_context.request_figure_action(action) or sent
        for side in ("bottom", "top", "left", "right"):
            action = {
                "type": "set_axis_side_state",
                "subplot_id": subplot["id"],
                "side": side,
                "state": dict(subplot["axis_sides"][side]),
                "replace": True,
            }
            sent = self.figure_context.request_figure_action(action) or sent
        action = {
            "type": "set_subplot_margins",
            "subplot_id": subplot["id"],
            "state": dict(subplot.get("margins", {}) or {}),
            "replace": True,
        }
        sent = self.figure_context.request_figure_action(action) or sent
        if sent:
            self._live_updates_sent = True
        return sent

    def _update_preview(self, error_message=""):
        self._preview_error_message = str(error_message or "")
        self.refresh_shell()

    def canonical_text_payload(self):
        if self._preview_error_message:
            return self._preview_error_message
        if self._draft_figure_ir is None:
            return ""
        try:
            return FigureIRCodec.state_to_python(
                self._draft_figure_ir,
                context={"figure_defaults": self.figure_context.figure_defaults()},
            )
        except Exception as exc:
            return str(exc)

    def _on_controls_changed(self, *args):
        del args
        if self._loading_controls:
            return
        self.ui.axis_label_preview.setText(self.ui.axis_label_edit.text())
        result = self._apply_current_controls_to_draft()
        self._update_preview(result["message"])
        if not result["valid"]:
            return
        if self.ui.live_update_checkbox.isChecked():
            self._dispatch_selected_state()

    def _on_live_update_toggled(self, checked):
        if self._loading_controls or not checked:
            return
        result = self._apply_current_controls_to_draft()
        self._update_preview(result["message"])
        if result["valid"]:
            self._dispatch_all_state(self._draft_figure_ir)

    def handle_do_it(self):
        result = self._apply_current_controls_to_draft()
        self._update_preview(result["message"])
        if not result["valid"]:
            return
        if not self.ui.live_update_checkbox.isChecked():
            self._dispatch_all_state(self._draft_figure_ir)
        self.accept()

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
        resolved_limits = (
            self.figure_context.resolved_axis_limits()
            .get(context["subplot_id"], {})
            .get(context["axis_name"])
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

    def reject(self):
        if self._live_updates_sent and self._draft_tracker.changed_keys():
            self._dispatch_all_state(self._draft_tracker.revert_state("figure"))
        super().reject()
