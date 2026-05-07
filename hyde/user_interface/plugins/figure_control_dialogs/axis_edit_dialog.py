import copy

from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec
from hyde.user_interface.matplotlib_color_picker import MatplotlibColorLineEdit

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


class AxisEditDialog(QtWidgets.QDialog):
    def __init__(self, figure_window, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Modify Axis")
        self.figure_window = figure_window
        self._loading_controls = False
        self._live_updates_sent = False
        self._original_figure_ir = self.figure_window.snapshot_state.figure_ir()
        self._draft_figure_ir = _merge_figure_ir_with_defaults(
            self._original_figure_ir,
            self.figure_window.snapshot_state.figure_defaults(),
        )
        self._build_ui()
        self._load_initial_axis()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        header_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(header_layout)

        header_layout.addWidget(QtWidgets.QLabel("Axis", self))
        self.axis_selector = QtWidgets.QComboBox(self)
        for label, value in AXIS_SIDE_CHOICES:
            self.axis_selector.addItem(label, value)
        self.axis_selector.currentIndexChanged.connect(self._on_axis_side_changed)
        header_layout.addWidget(self.axis_selector)

        header_layout.addStretch(1)
        self.live_update_checkbox = QtWidgets.QCheckBox("Live Update", self)
        self.live_update_checkbox.setChecked(True)
        self.live_update_checkbox.toggled.connect(self._on_live_update_toggled)
        header_layout.addWidget(self.live_update_checkbox)

        self.tab_widget = QtWidgets.QTabWidget(self)
        layout.addWidget(self.tab_widget, 1)

        self._build_axis_tab()
        self._build_auto_ticks_tab()
        self._build_ticks_grids_tab()
        self._build_tick_options_tab()
        self._build_axis_label_tab()
        self._build_label_options_tab()
        self._build_range_tab()

        self.preview_pane = QtWidgets.QTextEdit(self)
        self.preview_pane.setReadOnly(True)
        self.preview_pane.setMinimumHeight(140)
        layout.addWidget(self.preview_pane)

        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.addStretch(1)

        self.do_it_button = QtWidgets.QPushButton("Do It", self)
        self.do_it_button.clicked.connect(self._on_do_it_clicked)
        footer_layout.addWidget(self.do_it_button)

        self.to_clip_button = QtWidgets.QPushButton("To Clip", self)
        self.to_clip_button.clicked.connect(self._copy_preview_to_clipboard)
        footer_layout.addWidget(self.to_clip_button)

        self.help_button = QtWidgets.QPushButton("Help", self)
        self.help_button.setEnabled(False)
        footer_layout.addWidget(self.help_button)

        self.cancel_button = QtWidgets.QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self.reject)
        footer_layout.addWidget(self.cancel_button)

        layout.addLayout(footer_layout)

    def _build_axis_tab(self):
        axis_tab = QtWidgets.QWidget(self)
        form = QtWidgets.QFormLayout(axis_tab)

        self.axis_mode_combo = QtWidgets.QComboBox(axis_tab)
        for label, value in AXIS_MODE_CHOICES:
            self.axis_mode_combo.addItem(label, value)
        self.axis_mode_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Axis mode", self.axis_mode_combo)

        self.log_tick_mode_combo = QtWidgets.QComboBox(axis_tab)
        for label, value in LOG_TICK_MODE_CHOICES:
            self.log_tick_mode_combo.addItem(label, value)
        self.log_tick_mode_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Log ticks", self.log_tick_mode_combo)

        self.side_visible_checkbox = QtWidgets.QCheckBox("Show axis line", axis_tab)
        self.side_visible_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Axis line", self.side_visible_checkbox)

        self.side_ticks_checkbox = QtWidgets.QCheckBox("Show ticks", axis_tab)
        self.side_ticks_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Ticks", self.side_ticks_checkbox)

        self.side_tick_labels_checkbox = QtWidgets.QCheckBox(
            "Show tick labels",
            axis_tab,
        )
        self.side_tick_labels_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Tick labels", self.side_tick_labels_checkbox)

        self.side_line_width_spin = QtWidgets.QDoubleSpinBox(axis_tab)
        self.side_line_width_spin.setRange(0.0, 99.0)
        self.side_line_width_spin.setSingleStep(0.1)
        self.side_line_width_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Line width", self.side_line_width_spin)

        self.side_offset_spin = QtWidgets.QDoubleSpinBox(axis_tab)
        self.side_offset_spin.setRange(-999.0, 999.0)
        self.side_offset_spin.setSingleStep(1.0)
        self.side_offset_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Offset", self.side_offset_spin)

        draw_between_widget = QtWidgets.QWidget(axis_tab)
        draw_between_layout = QtWidgets.QHBoxLayout(draw_between_widget)
        draw_between_layout.setContentsMargins(0, 0, 0, 0)
        self.draw_between_min_spin = QtWidgets.QDoubleSpinBox(draw_between_widget)
        self.draw_between_min_spin.setRange(0.0, 100.0)
        self.draw_between_min_spin.setSingleStep(1.0)
        self.draw_between_min_spin.valueChanged.connect(self._on_controls_changed)
        draw_between_layout.addWidget(self.draw_between_min_spin)
        draw_between_layout.addWidget(QtWidgets.QLabel("to", draw_between_widget))
        self.draw_between_max_spin = QtWidgets.QDoubleSpinBox(draw_between_widget)
        self.draw_between_max_spin.setRange(0.0, 100.0)
        self.draw_between_max_spin.setSingleStep(1.0)
        self.draw_between_max_spin.valueChanged.connect(self._on_controls_changed)
        draw_between_layout.addWidget(self.draw_between_max_spin)
        draw_between_layout.addWidget(QtWidgets.QLabel("%", draw_between_widget))
        form.addRow("Draw between", draw_between_widget)

        self.draw_on_top_checkbox = QtWidgets.QCheckBox(
            "Draw on top of traces",
            axis_tab,
        )
        self.draw_on_top_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Z order", self.draw_on_top_checkbox)

        self.side_color_edit = MatplotlibColorLineEdit(axis_tab)
        self.side_color_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Axis color", self.side_color_edit)

        self.axis_label_color_edit = MatplotlibColorLineEdit(axis_tab)
        self.axis_label_color_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Label color", self.axis_label_color_edit)

        self.tick_label_color_edit = MatplotlibColorLineEdit(axis_tab)
        self.tick_label_color_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Tick label color", self.tick_label_color_edit)

        self.tab_widget.addTab(axis_tab, AXIS_TAB_TITLES[0])

    def _build_auto_ticks_tab(self):
        auto_ticks_tab = QtWidgets.QWidget(self)
        form = QtWidgets.QFormLayout(auto_ticks_tab)

        self.major_tick_mode_combo = QtWidgets.QComboBox(auto_ticks_tab)
        self.major_tick_mode_combo.addItem("Auto", "auto")
        self.major_tick_mode_combo.addItem("Manual Step", "manual")
        self.major_tick_mode_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Major ticks", self.major_tick_mode_combo)

        self.major_tick_count_spin = QtWidgets.QSpinBox(auto_ticks_tab)
        self.major_tick_count_spin.setRange(0, 50)
        self.major_tick_count_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Approx. count", self.major_tick_count_spin)

        self.major_tick_step_spin = QtWidgets.QDoubleSpinBox(auto_ticks_tab)
        self.major_tick_step_spin.setRange(0.0, 999999.0)
        self.major_tick_step_spin.setSingleStep(0.1)
        self.major_tick_step_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Manual step", self.major_tick_step_spin)

        self.minor_ticks_checkbox = QtWidgets.QCheckBox("Show minor ticks", auto_ticks_tab)
        self.minor_ticks_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Minor ticks", self.minor_ticks_checkbox)

        self.major_tick_positions_edit = QtWidgets.QLineEdit(auto_ticks_tab)
        self.major_tick_positions_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Manual positions", self.major_tick_positions_edit)

        self.major_tick_labels_edit = QtWidgets.QLineEdit(auto_ticks_tab)
        self.major_tick_labels_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Manual labels", self.major_tick_labels_edit)

        self.set_auto_ticks_button = QtWidgets.QPushButton("Set to Auto Values", auto_ticks_tab)
        self.set_auto_ticks_button.clicked.connect(self._set_auto_tick_values)
        form.addRow("", self.set_auto_ticks_button)

        self.tab_widget.addTab(auto_ticks_tab, AXIS_TAB_TITLES[1])

    def _build_ticks_grids_tab(self):
        ticks_grid_tab = QtWidgets.QWidget(self)
        form = QtWidgets.QFormLayout(ticks_grid_tab)

        self.formatter_style_combo = QtWidgets.QComboBox(ticks_grid_tab)
        for label, value in FORMATTER_STYLE_CHOICES:
            self.formatter_style_combo.addItem(label, value)
        self.formatter_style_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Number style", self.formatter_style_combo)

        self.low_trip_spin = QtWidgets.QDoubleSpinBox(ticks_grid_tab)
        self.low_trip_spin.setRange(-99.0, 99.0)
        self.low_trip_spin.setSpecialValueText("")
        self.low_trip_spin.setValue(0.0)
        self.low_trip_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Low trip", self.low_trip_spin)

        self.high_trip_spin = QtWidgets.QDoubleSpinBox(ticks_grid_tab)
        self.high_trip_spin.setRange(-99.0, 99.0)
        self.high_trip_spin.setSpecialValueText("")
        self.high_trip_spin.setValue(0.0)
        self.high_trip_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("High trip", self.high_trip_spin)

        self.exponent_prescale_spin = QtWidgets.QSpinBox(ticks_grid_tab)
        self.exponent_prescale_spin.setRange(-99, 99)
        self.exponent_prescale_spin.setSpecialValueText("")
        self.exponent_prescale_spin.setValue(0)
        self.exponent_prescale_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Exponent prescale", self.exponent_prescale_spin)

        self.tick_direction_combo = QtWidgets.QComboBox(ticks_grid_tab)
        for label, value in TICK_DIRECTION_CHOICES:
            self.tick_direction_combo.addItem(label, value)
        self.tick_direction_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Tick direction", self.tick_direction_combo)

        self.grid_visible_checkbox = QtWidgets.QCheckBox("Show grid", ticks_grid_tab)
        self.grid_visible_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Grid", self.grid_visible_checkbox)

        self.grid_which_combo = QtWidgets.QComboBox(ticks_grid_tab)
        for label, value in GRID_WHICH_CHOICES:
            self.grid_which_combo.addItem(label, value)
        self.grid_which_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Grid which", self.grid_which_combo)

        self.grid_style_combo = QtWidgets.QComboBox(ticks_grid_tab)
        for label, value in LINE_STYLE_CHOICES:
            self.grid_style_combo.addItem(label, value)
        self.grid_style_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Grid style", self.grid_style_combo)

        self.grid_width_spin = QtWidgets.QDoubleSpinBox(ticks_grid_tab)
        self.grid_width_spin.setRange(0.0, 99.0)
        self.grid_width_spin.setSingleStep(0.1)
        self.grid_width_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Grid width", self.grid_width_spin)

        self.grid_color_edit = MatplotlibColorLineEdit(ticks_grid_tab)
        self.grid_color_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Grid color", self.grid_color_edit)

        self.zero_line_visible_checkbox = QtWidgets.QCheckBox(
            "Show zero line",
            ticks_grid_tab,
        )
        self.zero_line_visible_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Zero line", self.zero_line_visible_checkbox)

        self.zero_line_style_combo = QtWidgets.QComboBox(ticks_grid_tab)
        for label, value in LINE_STYLE_CHOICES:
            self.zero_line_style_combo.addItem(label, value)
        self.zero_line_style_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Zero style", self.zero_line_style_combo)

        self.zero_line_width_spin = QtWidgets.QDoubleSpinBox(ticks_grid_tab)
        self.zero_line_width_spin.setRange(0.0, 99.0)
        self.zero_line_width_spin.setSingleStep(0.1)
        self.zero_line_width_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Zero width", self.zero_line_width_spin)

        self.zero_line_color_edit = MatplotlibColorLineEdit(ticks_grid_tab)
        self.zero_line_color_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Zero color", self.zero_line_color_edit)

        self.tab_widget.addTab(ticks_grid_tab, AXIS_TAB_TITLES[2])

    def _build_tick_options_tab(self):
        tick_options_tab = QtWidgets.QWidget(self)
        form = QtWidgets.QFormLayout(tick_options_tab)

        display_range_widget = QtWidgets.QWidget(tick_options_tab)
        display_range_layout = QtWidgets.QHBoxLayout(display_range_widget)
        display_range_layout.setContentsMargins(0, 0, 0, 0)
        self.display_range_min_edit = QtWidgets.QLineEdit(display_range_widget)
        self.display_range_min_edit.editingFinished.connect(self._on_controls_changed)
        display_range_layout.addWidget(self.display_range_min_edit)
        display_range_layout.addWidget(QtWidgets.QLabel("to", display_range_widget))
        self.display_range_max_edit = QtWidgets.QLineEdit(display_range_widget)
        self.display_range_max_edit.editingFinished.connect(self._on_controls_changed)
        display_range_layout.addWidget(self.display_range_max_edit)
        form.addRow("Display range", display_range_widget)

        self.suppressed_values_edit = QtWidgets.QLineEdit(tick_options_tab)
        self.suppressed_values_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Suppress values", self.suppressed_values_edit)

        self.max_log_cycles_minor_spin = QtWidgets.QDoubleSpinBox(tick_options_tab)
        self.max_log_cycles_minor_spin.setRange(0.0, 99.0)
        self.max_log_cycles_minor_spin.setSingleStep(0.5)
        self.max_log_cycles_minor_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Max minor cycles", self.max_log_cycles_minor_spin)

        self.max_log_cycles_minor_labels_spin = QtWidgets.QDoubleSpinBox(tick_options_tab)
        self.max_log_cycles_minor_labels_spin.setRange(0.0, 99.0)
        self.max_log_cycles_minor_labels_spin.setSingleStep(0.5)
        self.max_log_cycles_minor_labels_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Max minor-label cycles", self.max_log_cycles_minor_labels_spin)

        self.use_thousands_separator_checkbox = QtWidgets.QCheckBox(
            "Use thousands separator",
            tick_options_tab,
        )
        self.use_thousands_separator_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Thousands", self.use_thousands_separator_checkbox)

        self.zero_as_zero_checkbox = QtWidgets.QCheckBox("Format zero as 0", tick_options_tab)
        self.zero_as_zero_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Zero format", self.zero_as_zero_checkbox)

        self.trim_trailing_zeros_checkbox = QtWidgets.QCheckBox(
            "Trim trailing zeros",
            tick_options_tab,
        )
        self.trim_trailing_zeros_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Trailing zeros", self.trim_trailing_zeros_checkbox)

        self.trim_leading_zero_checkbox = QtWidgets.QCheckBox(
            "Trim leading zero",
            tick_options_tab,
        )
        self.trim_leading_zero_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Leading zero", self.trim_leading_zero_checkbox)

        self.prefer_exponent_checkbox = QtWidgets.QCheckBox(
            "Prefer exponent",
            tick_options_tab,
        )
        self.prefer_exponent_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Exponent style", self.prefer_exponent_checkbox)

        self.tab_widget.addTab(tick_options_tab, AXIS_TAB_TITLES[3])

    def _build_axis_label_tab(self):
        axis_label_tab = QtWidgets.QWidget(self)
        form = QtWidgets.QFormLayout(axis_label_tab)

        self.axis_label_edit = QtWidgets.QLineEdit(axis_label_tab)
        self.axis_label_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Axis label", self.axis_label_edit)

        self.axis_label_preview = QtWidgets.QLabel(axis_label_tab)
        self.axis_label_preview.setFrameShape(QtWidgets.QFrame.StyledPanel)
        form.addRow("Preview", self.axis_label_preview)

        self.line_spacing_spin = QtWidgets.QDoubleSpinBox(axis_label_tab)
        self.line_spacing_spin.setRange(0.1, 9.0)
        self.line_spacing_spin.setSingleStep(0.1)
        self.line_spacing_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Line spacing", self.line_spacing_spin)

        self.label_rotation_spin = QtWidgets.QDoubleSpinBox(axis_label_tab)
        self.label_rotation_spin.setRange(-360.0, 360.0)
        self.label_rotation_spin.setSingleStep(1.0)
        self.label_rotation_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Label rotation", self.label_rotation_spin)

        self.tab_widget.addTab(axis_label_tab, AXIS_TAB_TITLES[4])

    def _build_label_options_tab(self):
        label_options_tab = QtWidgets.QWidget(self)
        form = QtWidgets.QFormLayout(label_options_tab)

        self.label_side_combo = QtWidgets.QComboBox(label_options_tab)
        for label, value in LABEL_SIDE_CHOICES:
            self.label_side_combo.addItem(label, value)
        self.label_side_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Label side", self.label_side_combo)

        self.label_visible_checkbox = QtWidgets.QCheckBox("Show label", label_options_tab)
        self.label_visible_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Visibility", self.label_visible_checkbox)

        self.label_position_mode_combo = QtWidgets.QComboBox(label_options_tab)
        for label, value in LABEL_POSITION_MODE_CHOICES:
            self.label_position_mode_combo.addItem(label, value)
        self.label_position_mode_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Position mode", self.label_position_mode_combo)

        self.label_position_spin = QtWidgets.QDoubleSpinBox(label_options_tab)
        self.label_position_spin.setRange(-999.0, 999.0)
        self.label_position_spin.setSingleStep(0.05)
        self.label_position_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Label position", self.label_position_spin)

        self.label_offset_spin = QtWidgets.QDoubleSpinBox(label_options_tab)
        self.label_offset_spin.setRange(-999.0, 999.0)
        self.label_offset_spin.setSingleStep(0.5)
        self.label_offset_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Label margin", self.label_offset_spin)

        self.tick_label_rotation_spin = QtWidgets.QDoubleSpinBox(label_options_tab)
        self.tick_label_rotation_spin.setRange(-360.0, 360.0)
        self.tick_label_rotation_spin.setSingleStep(1.0)
        self.tick_label_rotation_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Tick label rotation", self.tick_label_rotation_spin)

        self.tick_label_offset_spin = QtWidgets.QDoubleSpinBox(label_options_tab)
        self.tick_label_offset_spin.setRange(-999.0, 999.0)
        self.tick_label_offset_spin.setSingleStep(0.5)
        self.tick_label_offset_spin.valueChanged.connect(self._on_controls_changed)
        form.addRow("Tick label offset", self.tick_label_offset_spin)

        self.tab_widget.addTab(label_options_tab, AXIS_TAB_TITLES[5])

    def _build_range_tab(self):
        range_tab = QtWidgets.QWidget(self)
        form = QtWidgets.QFormLayout(range_tab)

        self.autoscale_combo = QtWidgets.QComboBox(range_tab)
        for label, value in AUTOSCALE_CHOICES:
            self.autoscale_combo.addItem(label, value)
        self.autoscale_combo.currentIndexChanged.connect(self._on_controls_changed)
        form.addRow("Autoscale", self.autoscale_combo)

        self.minimum_auto_checkbox = QtWidgets.QCheckBox("Auto minimum", range_tab)
        self.minimum_auto_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Minimum mode", self.minimum_auto_checkbox)

        self.minimum_edit = QtWidgets.QLineEdit(range_tab)
        self.minimum_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Minimum", self.minimum_edit)

        self.maximum_auto_checkbox = QtWidgets.QCheckBox("Auto maximum", range_tab)
        self.maximum_auto_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Maximum mode", self.maximum_auto_checkbox)

        self.maximum_edit = QtWidgets.QLineEdit(range_tab)
        self.maximum_edit.editingFinished.connect(self._on_controls_changed)
        form.addRow("Maximum", self.maximum_edit)

        self.reverse_axis_checkbox = QtWidgets.QCheckBox("Reverse axis", range_tab)
        self.reverse_axis_checkbox.toggled.connect(self._on_controls_changed)
        form.addRow("Direction", self.reverse_axis_checkbox)

        range_actions = QtWidgets.QWidget(range_tab)
        range_actions_layout = QtWidgets.QHBoxLayout(range_actions)
        range_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.expand_range_button = QtWidgets.QPushButton("Expand 5%", range_actions)
        self.expand_range_button.clicked.connect(self._expand_range)
        range_actions_layout.addWidget(self.expand_range_button)
        self.swap_range_button = QtWidgets.QPushButton("Swap", range_actions)
        self.swap_range_button.clicked.connect(self._swap_range)
        range_actions_layout.addWidget(self.swap_range_button)
        self.set_autoscale_values_button = QtWidgets.QPushButton(
            "Set to Autoscale Values",
            range_actions,
        )
        self.set_autoscale_values_button.clicked.connect(self._set_autoscale_values)
        range_actions_layout.addWidget(self.set_autoscale_values_button)
        form.addRow("", range_actions)

        self.tab_widget.addTab(range_tab, AXIS_TAB_TITLES[6])

    def has_supported_axes(self):
        return (
            self.figure_window.services.get("send_figure_action") is not None
            and self._current_subplot() is not None
        )

    def _load_initial_axis(self):
        if not self.has_supported_axes():
            self._update_preview()
            return
        index = self.axis_selector.findData("bottom")
        if index >= 0:
            self.axis_selector.setCurrentIndex(index)
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
        side = self.axis_selector.currentData()
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
        draw_between = side_state.get("draw_between") or (0.0, 1.0)
        display_range = tick_state.get("display_range") or (None, None)
        limit_mode = dict(range_state.get("limit_mode", {}) or {})

        self._loading_controls = True
        try:
            self._set_combo_data(self.axis_mode_combo, axis_state.get("scale_mode"))
            self._set_combo_data(
                self.log_tick_mode_combo,
                axis_state.get("log_tick_mode", "plain"),
            )
            self.axis_label_edit.setText(_format_optional_text(label_state.get("text")))
            self.axis_label_preview.setText(_format_optional_text(label_state.get("text")))
            self.label_visible_checkbox.setChecked(bool(label_state.get("visible")))
            self._set_combo_data(
                self.label_side_combo,
                _label_choice_for_side(label_state.get("side"), context["axis_name"]),
            )
            self._set_combo_data(
                self.label_position_mode_combo,
                label_state.get("position_mode", "auto"),
            )
            self.label_position_spin.setValue(float(label_state.get("position") or 0.0))
            self.label_offset_spin.setValue(float(label_state.get("offset") or 0.0))
            self.label_rotation_spin.setValue(float(label_state.get("rotation") or 0.0))
            self.line_spacing_spin.setValue(float(label_state.get("line_spacing") or 1.2))
            self.axis_label_color_edit.set_committed_text(
                _format_optional_text(label_state.get("color"))
            )
            self._set_combo_data(
                self.autoscale_combo,
                range_state.get("autoscale", "data"),
            )
            self.minimum_auto_checkbox.setChecked(limit_mode.get("min", "auto") == "auto")
            self.minimum_edit.setText(_format_optional_number(limits[0]))
            self.maximum_auto_checkbox.setChecked(limit_mode.get("max", "auto") == "auto")
            self.maximum_edit.setText(_format_optional_number(limits[1]))
            self.reverse_axis_checkbox.setChecked(bool(range_state.get("reverse")))
            self.side_visible_checkbox.setChecked(bool(side_state.get("spine_visible")))
            self.side_ticks_checkbox.setChecked(bool(side_state.get("ticks_visible")))
            self.side_tick_labels_checkbox.setChecked(
                bool(side_state.get("tick_labels_visible"))
            )
            self.side_line_width_spin.setValue(
                float(side_state.get("spine_width") or 0.0)
            )
            self.side_offset_spin.setValue(float(side_state.get("offset") or 0.0))
            self.draw_between_min_spin.setValue(float(draw_between[0]) * 100.0)
            self.draw_between_max_spin.setValue(float(draw_between[1]) * 100.0)
            self.draw_on_top_checkbox.setChecked(bool(side_state.get("draw_on_top")))
            self.side_color_edit.set_committed_text(
                _format_optional_text(side_state.get("spine_color"))
            )
            self.tick_label_color_edit.set_committed_text(
                _format_optional_text(side_state.get("tick_label_color"))
            )
            self.tick_label_rotation_spin.setValue(
                float(side_state.get("tick_label_rotation") or 0.0)
            )
            self.tick_label_offset_spin.setValue(
                float(side_state.get("tick_label_offset") or 0.0)
            )
            self.major_tick_count_spin.setValue(int(major_ticks.get("count") or 0))
            self.major_tick_step_spin.setValue(float(major_ticks.get("step") or 0.0))
            self.major_tick_positions_edit.setText(
                _format_float_list(major_ticks.get("positions"))
            )
            self.major_tick_labels_edit.setText(
                _format_text_list(major_ticks.get("labels"))
            )
            self._set_combo_data(
                self.major_tick_mode_combo,
                major_ticks.get("mode", "auto"),
            )
            self.minor_ticks_checkbox.setChecked(
                bool(dict(tick_state.get("minor", {}) or {}).get("visible"))
            )
            self._set_combo_data(
                self.tick_direction_combo,
                tick_state.get("direction", "outside"),
            )
            self._set_combo_data(
                self.formatter_style_combo,
                formatter_state.get("style", "plain"),
            )
            self.low_trip_spin.setValue(float(formatter_state.get("low_trip") or 0.0))
            self.high_trip_spin.setValue(float(formatter_state.get("high_trip") or 0.0))
            self.exponent_prescale_spin.setValue(
                int(formatter_state.get("exponent_prescale") or 0)
            )
            self.display_range_min_edit.setText(_format_optional_number(display_range[0]))
            self.display_range_max_edit.setText(_format_optional_number(display_range[1]))
            self.suppressed_values_edit.setText(
                _format_float_list(tick_state.get("suppressed_values"))
            )
            self.max_log_cycles_minor_spin.setValue(
                float(tick_state.get("max_log_cycles_minor") or 0.0)
            )
            self.max_log_cycles_minor_labels_spin.setValue(
                float(tick_state.get("max_log_cycles_minor_labels") or 0.0)
            )
            self.use_thousands_separator_checkbox.setChecked(
                bool(formatter_state.get("use_thousands_separator"))
            )
            self.zero_as_zero_checkbox.setChecked(
                bool(formatter_state.get("zero_as_zero", True))
            )
            self.trim_trailing_zeros_checkbox.setChecked(
                bool(formatter_state.get("trim_trailing_zeros"))
            )
            self.trim_leading_zero_checkbox.setChecked(
                bool(formatter_state.get("trim_leading_zero"))
            )
            self.prefer_exponent_checkbox.setChecked(
                bool(formatter_state.get("prefer_exponent"))
            )
            self.grid_visible_checkbox.setChecked(bool(grid_state.get("visible")))
            self._set_combo_data(self.grid_which_combo, grid_state.get("which", "major"))
            self._set_combo_data(
                self.grid_style_combo,
                grid_state.get("linestyle", "-"),
            )
            self.grid_width_spin.setValue(float(grid_state.get("linewidth") or 0.0))
            self.grid_color_edit.set_committed_text(
                _format_optional_text(grid_state.get("color"))
            )
            self.zero_line_visible_checkbox.setChecked(bool(zero_line_state.get("visible")))
            self._set_combo_data(
                self.zero_line_style_combo,
                zero_line_state.get("linestyle", "-"),
            )
            self.zero_line_width_spin.setValue(
                float(zero_line_state.get("linewidth") or 0.0)
            )
            self.zero_line_color_edit.set_committed_text(
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
        minimum_auto = bool(self.minimum_auto_checkbox.isChecked())
        maximum_auto = bool(self.maximum_auto_checkbox.isChecked())
        try:
            minimum = None if minimum_auto else _parse_optional_float(self.minimum_edit.text(), "Minimum")
            maximum = None if maximum_auto else _parse_optional_float(self.maximum_edit.text(), "Maximum")
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
        minimum_text = self.display_range_min_edit.text().strip()
        maximum_text = self.display_range_max_edit.text().strip()
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
                self.major_tick_positions_edit.text(),
                "Manual positions",
            )
            manual_labels = _parse_text_list(self.major_tick_labels_edit.text())
            suppressed_values = _parse_float_list(
                self.suppressed_values_edit.text(),
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

        axis_state["scale_mode"] = str(self.axis_mode_combo.currentData() or "linear")
        axis_state["log_tick_mode"] = str(
            self.log_tick_mode_combo.currentData() or "plain"
        )
        label_text = self.axis_label_edit.text().strip()
        axis_state["label"]["text"] = None if not label_text else label_text
        axis_state["label"]["visible"] = bool(self.label_visible_checkbox.isChecked())
        axis_state["label"]["side"] = _side_for_label_choice(
            self.label_side_combo.currentData() or "primary",
            context["axis_name"],
        )
        axis_state["label"]["position_mode"] = str(
            self.label_position_mode_combo.currentData() or "auto"
        )
        label_position = float(self.label_position_spin.value())
        axis_state["label"]["position"] = (
            None
            if axis_state["label"]["position_mode"] == "auto"
            else label_position
        )
        axis_state["label"]["offset"] = float(self.label_offset_spin.value())
        axis_state["label"]["rotation"] = float(self.label_rotation_spin.value())
        axis_state["label"]["line_spacing"] = float(self.line_spacing_spin.value())
        label_color = self.axis_label_color_edit.text().strip()
        axis_state["label"]["color"] = None if not label_color else label_color
        axis_state["range"]["limits"] = range_validation["limits"]
        axis_state["range"]["limit_mode"] = dict(range_validation.get("limit_mode", {}))
        axis_state["range"]["autoscale"] = str(
            self.autoscale_combo.currentData() or "data"
        )
        axis_state["range"]["reverse"] = bool(self.reverse_axis_checkbox.isChecked())
        axis_state["ticks"]["major"]["mode"] = str(
            self.major_tick_mode_combo.currentData() or "auto"
        )
        count = int(self.major_tick_count_spin.value())
        axis_state["ticks"]["major"]["count"] = None if count <= 0 else count
        step = float(self.major_tick_step_spin.value())
        axis_state["ticks"]["major"]["step"] = None if step <= 0 else step
        axis_state["ticks"]["major"]["positions"] = manual_positions
        axis_state["ticks"]["major"]["labels"] = manual_labels
        axis_state["ticks"]["minor"]["visible"] = bool(
            self.minor_ticks_checkbox.isChecked()
        )
        axis_state["ticks"]["direction"] = str(
            self.tick_direction_combo.currentData() or "outside"
        )
        axis_state["ticks"]["formatter"]["style"] = str(
            self.formatter_style_combo.currentData() or "plain"
        )
        axis_state["ticks"]["formatter"]["low_trip"] = (
            None if self.low_trip_spin.value() == 0.0 else float(self.low_trip_spin.value())
        )
        axis_state["ticks"]["formatter"]["high_trip"] = (
            None if self.high_trip_spin.value() == 0.0 else float(self.high_trip_spin.value())
        )
        axis_state["ticks"]["formatter"]["exponent_prescale"] = (
            None
            if self.exponent_prescale_spin.value() == 0
            else float(self.exponent_prescale_spin.value())
        )
        axis_state["ticks"]["formatter"]["use_thousands_separator"] = bool(
            self.use_thousands_separator_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["zero_as_zero"] = bool(
            self.zero_as_zero_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["trim_trailing_zeros"] = bool(
            self.trim_trailing_zeros_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["trim_leading_zero"] = bool(
            self.trim_leading_zero_checkbox.isChecked()
        )
        axis_state["ticks"]["formatter"]["prefer_exponent"] = bool(
            self.prefer_exponent_checkbox.isChecked()
        )
        axis_state["ticks"]["suppressed_values"] = suppressed_values or []
        axis_state["ticks"]["display_range"] = display_range_validation["display_range"]
        axis_state["ticks"]["max_log_cycles_minor"] = (
            None
            if self.max_log_cycles_minor_spin.value() <= 0
            else float(self.max_log_cycles_minor_spin.value())
        )
        axis_state["ticks"]["max_log_cycles_minor_labels"] = (
            None
            if self.max_log_cycles_minor_labels_spin.value() <= 0
            else float(self.max_log_cycles_minor_labels_spin.value())
        )
        axis_state["grid"]["visible"] = bool(self.grid_visible_checkbox.isChecked())
        axis_state["grid"]["which"] = str(self.grid_which_combo.currentData() or "major")
        axis_state["grid"]["linestyle"] = str(self.grid_style_combo.currentData() or "-")
        grid_width = float(self.grid_width_spin.value())
        axis_state["grid"]["linewidth"] = None if grid_width <= 0 else grid_width
        grid_color = self.grid_color_edit.text().strip()
        axis_state["grid"]["color"] = None if not grid_color else grid_color
        axis_state["zero_line"]["visible"] = bool(
            self.zero_line_visible_checkbox.isChecked()
        )
        axis_state["zero_line"]["linestyle"] = str(
            self.zero_line_style_combo.currentData() or "-"
        )
        zero_width = float(self.zero_line_width_spin.value())
        axis_state["zero_line"]["linewidth"] = None if zero_width <= 0 else zero_width
        zero_color = self.zero_line_color_edit.text().strip()
        axis_state["zero_line"]["color"] = None if not zero_color else zero_color

        side_state["spine_visible"] = bool(self.side_visible_checkbox.isChecked())
        side_state["ticks_visible"] = bool(self.side_ticks_checkbox.isChecked())
        side_state["tick_labels_visible"] = bool(
            self.side_tick_labels_checkbox.isChecked()
        )
        width = float(self.side_line_width_spin.value())
        side_state["spine_width"] = None if width <= 0 else width
        side_state["offset"] = float(self.side_offset_spin.value())
        draw_between = (
            float(self.draw_between_min_spin.value()) / 100.0,
            float(self.draw_between_max_spin.value()) / 100.0,
        )
        if draw_between[0] > draw_between[1]:
            return {
                "valid": False,
                "message": "Draw-between start must not exceed the end.",
            }
        side_state["draw_between"] = draw_between
        side_state["draw_on_top"] = bool(self.draw_on_top_checkbox.isChecked())
        side_color = self.side_color_edit.text().strip()
        side_state["spine_color"] = None if not side_color else side_color
        tick_color = self.tick_label_color_edit.text().strip()
        side_state["tick_label_color"] = None if not tick_color else tick_color
        side_state["tick_label_rotation"] = float(self.tick_label_rotation_spin.value())
        side_state["tick_label_offset"] = float(self.tick_label_offset_spin.value())

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
        sent = self.figure_window.request_figure_action(axis_action) or sent
        side_action = {
            "type": "set_axis_side_state",
            "subplot_id": context["subplot_id"],
            "side": context["side"],
            "state": dict(context["side_state"]),
            "replace": True,
        }
        sent = self.figure_window.request_figure_action(side_action) or sent
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
            sent = self.figure_window.request_figure_action(action) or sent
        for side in ("bottom", "top", "left", "right"):
            action = {
                "type": "set_axis_side_state",
                "subplot_id": subplot["id"],
                "side": side,
                "state": dict(subplot["axis_sides"][side]),
                "replace": True,
            }
            sent = self.figure_window.request_figure_action(action) or sent
        if sent:
            self._live_updates_sent = True
        return sent

    def _update_preview(self, error_message=""):
        if error_message:
            self.preview_pane.setPlainText(error_message)
            return
        if self._draft_figure_ir is None:
            self.preview_pane.clear()
            return
        try:
            self.preview_pane.setPlainText(
                FigureIRCodec.state_to_python(
                    self._draft_figure_ir,
                    context={
                        "figure_defaults": self.figure_window.snapshot_state.figure_defaults()
                    },
                )
            )
        except Exception as exc:
            self.preview_pane.setPlainText(str(exc))

    def _on_controls_changed(self, *args):
        del args
        if self._loading_controls:
            return
        self.axis_label_preview.setText(self.axis_label_edit.text())
        result = self._apply_current_controls_to_draft()
        self._update_preview(result["message"])
        if not result["valid"]:
            return
        if self.live_update_checkbox.isChecked():
            self._dispatch_selected_state()

    def _on_live_update_toggled(self, checked):
        if self._loading_controls or not checked:
            return
        result = self._apply_current_controls_to_draft()
        self._update_preview(result["message"])
        if result["valid"]:
            self._dispatch_all_state(self._draft_figure_ir)

    def _copy_preview_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self.preview_pane.toPlainText(), QtGui.QClipboard.Clipboard)

    def _on_do_it_clicked(self):
        result = self._apply_current_controls_to_draft()
        self._update_preview(result["message"])
        if not result["valid"]:
            return
        if not self.live_update_checkbox.isChecked():
            self._dispatch_all_state(self._draft_figure_ir)
        self.accept()

    def _set_auto_tick_values(self):
        self.major_tick_mode_combo.setCurrentIndex(self.major_tick_mode_combo.findData("auto"))
        self.major_tick_count_spin.setValue(0)
        self.major_tick_step_spin.setValue(0.0)
        self.major_tick_positions_edit.clear()
        self.major_tick_labels_edit.clear()

    def _swap_range(self):
        minimum = self.minimum_edit.text()
        maximum = self.maximum_edit.text()
        self.minimum_edit.setText(maximum)
        self.maximum_edit.setText(minimum)
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
        self.minimum_edit.setText(str(limits[0] - delta))
        self.maximum_edit.setText(str(limits[1] + delta))
        self._on_controls_changed()

    def _set_autoscale_values(self):
        context = self._selected_context()
        if context is None:
            return
        resolved_limits = (
            self.figure_window.snapshot_state.resolved_axis_limits()
            .get(context["subplot_id"], {})
            .get(context["axis_name"])
        )
        if not isinstance(resolved_limits, (list, tuple)) or len(resolved_limits) != 2:
            return
        self._loading_controls = True
        try:
            self.minimum_edit.setText(_format_optional_number(resolved_limits[0]))
            self.maximum_edit.setText(_format_optional_number(resolved_limits[1]))
            self.minimum_auto_checkbox.setChecked(False)
            self.maximum_auto_checkbox.setChecked(False)
        finally:
            self._loading_controls = False
        self._on_controls_changed()

    def reject(self):
        if self._live_updates_sent:
            self._dispatch_all_state(self._original_figure_ir)
        super().reject()
