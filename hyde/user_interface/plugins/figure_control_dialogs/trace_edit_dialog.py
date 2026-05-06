from matplotlib import colors as mcolors
from matplotlib import rcParams
from qtutils.qt import QtCore, QtWidgets

SUPPORTED_STYLE_DEFAULTS = {
    "visible": True,
    "linestyle": "-",
    "linewidth": 1.5,
    "alpha": 1.0,
    "drawstyle": "default",
    "marker": "None",
    "markersize": 6.0,
    "markerfacecolor": "auto",
    "markeredgecolor": "auto",
    "markeredgewidth": 1.0,
}

LINE_STYLE_CHOICES = [
    ("Solid", "-"),
    ("Dashed", "--"),
    ("Dash-dot", "-."),
    ("Dotted", ":"),
    ("None", "None"),
]

MODE_CHOICES = [
    ("Lines", "lines"),
    ("Markers", "markers"),
    ("Lines + Markers", "lines+markers"),
]

DRAW_STYLE_CHOICES = [
    ("Default", "default"),
    ("Steps Pre", "steps-pre"),
    ("Steps Mid", "steps-mid"),
    ("Steps Post", "steps-post"),
]

MARKER_CHOICES = [
    ("None", "None"),
    ("Circle", "o"),
    ("Square", "s"),
    ("Triangle", "^"),
    ("Diamond", "d"),
    ("Plus", "+"),
    ("Cross", "x"),
    ("Star", "*"),
]


def _default_trace_color(index):
    colors = rcParams["axes.prop_cycle"].by_key().get("color", ["#1f77b4"])
    return str(colors[index % len(colors)])


def _normalize_linestyle(value):
    if value in (None, "", "none", "None", " ", ""):
        return "None"
    return str(value)


def _normalize_marker(value):
    if value in (None, "", "none", "None", " ", ""):
        return "None"
    return str(value)


def _normalize_color(value, fallback):
    if value in (None, ""):
        return fallback
    if str(value).lower() == "auto":
        return "auto"
    try:
        return mcolors.to_hex(value)
    except Exception:
        return str(value)


def _parse_color_input(text, *, fallback, allow_auto=False):
    if text in (None, ""):
        return None
    if allow_auto and str(text).lower() == "auto":
        return "auto"
    try:
        return mcolors.to_hex(text)
    except Exception:
        return None


def _trace_display_name(trace):
    label = trace.get("kwargs", {}).get("label")
    if label not in (None, "", "_nolegend_"):
        return str(label)
    y_source = trace.get("y_source", {})
    if y_source.get("kind") == "name" and y_source.get("value"):
        return str(y_source["value"])
    return str(trace.get("id", "trace"))


def _apply_style_values(style, values):
    if not isinstance(values, dict):
        return
    for key in style:
        if key not in values:
            continue
        value = values[key]
        if key == "color":
            style[key] = _normalize_color(value, style[key])
        elif key in {"markerfacecolor", "markeredgecolor"}:
            style[key] = _normalize_color(value, style[key])
        elif key == "linestyle":
            style[key] = _normalize_linestyle(value)
        elif key == "marker":
            style[key] = _normalize_marker(value)
        elif key == "visible":
            style[key] = bool(value)
        elif key in {"linewidth", "alpha", "markersize", "markeredgewidth"}:
            style[key] = float(value)
        else:
            style[key] = value


class TraceAppearanceDialog(QtWidgets.QDialog):
    def __init__(self, figure_window, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Modify Data Appearance")
        self.figure_window = figure_window
        self._loading_controls = False
        self._trace_records = []
        self._trace_records_by_id = {}
        self._original_styles = {}
        self._current_styles = {}
        self._touched_trace_ids = set()
        self._build_ui()
        self._load_traces()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        content_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(content_layout)

        self.trace_list = QtWidgets.QListWidget(self)
        self.trace_list.currentRowChanged.connect(self._on_trace_changed)
        content_layout.addWidget(self.trace_list, 1)

        form_container = QtWidgets.QWidget(self)
        form_layout = QtWidgets.QFormLayout(form_container)
        content_layout.addWidget(form_container, 2)

        self.hide_trace_checkbox = QtWidgets.QCheckBox("Hide trace", self)
        self.hide_trace_checkbox.toggled.connect(self._on_hide_trace_toggled)
        form_layout.addRow("Visibility", self.hide_trace_checkbox)

        self.mode_combo = QtWidgets.QComboBox(self)
        for label, value in MODE_CHOICES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form_layout.addRow("Mode", self.mode_combo)

        self.line_color_edit = QtWidgets.QLineEdit(self)
        self.line_color_edit.editingFinished.connect(self._on_line_color_changed)
        form_layout.addRow("Line color", self.line_color_edit)

        self.line_style_combo = QtWidgets.QComboBox(self)
        for label, value in LINE_STYLE_CHOICES:
            self.line_style_combo.addItem(label, value)
        self.line_style_combo.currentIndexChanged.connect(self._on_line_style_changed)
        form_layout.addRow("Line style", self.line_style_combo)

        self.line_width_spin = QtWidgets.QDoubleSpinBox(self)
        self.line_width_spin.setRange(0.0, 99.0)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.valueChanged.connect(self._on_line_width_changed)
        form_layout.addRow("Line width", self.line_width_spin)

        self.opacity_spin = QtWidgets.QDoubleSpinBox(self)
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.valueChanged.connect(self._on_opacity_changed)
        form_layout.addRow("Opacity", self.opacity_spin)

        self.draw_style_combo = QtWidgets.QComboBox(self)
        for label, value in DRAW_STYLE_CHOICES:
            self.draw_style_combo.addItem(label, value)
        self.draw_style_combo.currentIndexChanged.connect(self._on_draw_style_changed)
        form_layout.addRow("Draw style", self.draw_style_combo)

        self.marker_combo = QtWidgets.QComboBox(self)
        for label, value in MARKER_CHOICES:
            self.marker_combo.addItem(label, value)
        self.marker_combo.currentIndexChanged.connect(self._on_marker_changed)
        form_layout.addRow("Marker", self.marker_combo)

        self.marker_size_spin = QtWidgets.QDoubleSpinBox(self)
        self.marker_size_spin.setRange(0.0, 99.0)
        self.marker_size_spin.setSingleStep(0.5)
        self.marker_size_spin.valueChanged.connect(self._on_marker_size_changed)
        form_layout.addRow("Marker size", self.marker_size_spin)

        self.marker_face_color_edit = QtWidgets.QLineEdit(self)
        self.marker_face_color_edit.editingFinished.connect(
            self._on_marker_face_color_changed
        )
        form_layout.addRow("Marker face", self.marker_face_color_edit)

        self.marker_edge_color_edit = QtWidgets.QLineEdit(self)
        self.marker_edge_color_edit.editingFinished.connect(
            self._on_marker_edge_color_changed
        )
        form_layout.addRow("Marker edge", self.marker_edge_color_edit)

        self.marker_edge_width_spin = QtWidgets.QDoubleSpinBox(self)
        self.marker_edge_width_spin.setRange(0.0, 99.0)
        self.marker_edge_width_spin.setSingleStep(0.1)
        self.marker_edge_width_spin.valueChanged.connect(
            self._on_marker_edge_width_changed
        )
        form_layout.addRow("Marker edge width", self.marker_edge_width_spin)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        self.button_box.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.accept
        )
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _load_traces(self):
        figure_ir = self.figure_window.snapshot_state.figure_ir() or {}
        trace_styles = self.figure_window.snapshot_state.trace_styles()
        figure_defaults = self.figure_window.snapshot_state.figure_defaults() or {}
        default_traces_by_subplot = {}
        for subplot in figure_defaults.get("layout", {}).get("subplots", []):
            subplot_id = str(subplot.get("id"))
            default_traces_by_subplot[subplot_id] = {
                str(trace.get("id")): dict(trace or {})
                for trace in subplot.get("traces", [])
            }
        for subplot_id, trace_defaults in dict(
            figure_defaults.get("trace_styles", {}) or {}
        ).items():
            subplot_defaults = default_traces_by_subplot.setdefault(str(subplot_id), {})
            for trace_id, style in dict(trace_defaults or {}).items():
                subplot_defaults.setdefault(
                    str(trace_id),
                    {"kwargs": dict(style or {})},
                )
        subplots = figure_ir.get("layout", {}).get("subplots", [])
        if not subplots:
            return
        subplot = subplots[0]
        for index, trace in enumerate(subplot.get("traces", [])):
            if trace.get("kind") != "line":
                continue
            trace_id = str(trace.get("id"))
            style = self._style_from_trace(
                trace,
                index,
                default_trace=default_traces_by_subplot.get(subplot["id"], {}).get(
                    trace_id
                ),
                live_style=trace_styles.get(subplot["id"], {}).get(trace_id),
            )
            record = {
                "subplot_id": subplot["id"],
                "trace_id": trace_id,
                "label": _trace_display_name(trace),
            }
            self._trace_records.append(record)
            self._trace_records_by_id[trace_id] = dict(record)
            self._original_styles[trace_id] = dict(style)
            self._current_styles[trace_id] = dict(style)
            self.trace_list.addItem(record["label"])
        if self.trace_list.count():
            self.trace_list.setCurrentRow(0)

    def _style_from_trace(self, trace, index, default_trace=None, live_style=None):
        style = dict(SUPPORTED_STYLE_DEFAULTS)
        style["color"] = _default_trace_color(index)
        if isinstance(default_trace, dict):
            _apply_style_values(style, default_trace.get("kwargs", {}))
        _apply_style_values(style, trace.get("kwargs", {}))
        _apply_style_values(style, live_style)
        return style

    def has_supported_traces(self):
        return bool(self._trace_records)

    def _current_record(self):
        row = self.trace_list.currentRow()
        if row < 0 or row >= len(self._trace_records):
            return None
        return self._trace_records[row]

    def _current_trace_id(self):
        record = self._current_record()
        return None if record is None else record["trace_id"]

    def _load_controls_for_trace(self, trace_id):
        style = self._current_styles[trace_id]
        self._loading_controls = True
        try:
            self.hide_trace_checkbox.setChecked(not style["visible"])
            self.mode_combo.setCurrentIndex(
                self.mode_combo.findData(self._mode_from_style(style))
            )
            self.line_color_edit.setText(style["color"])
            self.line_style_combo.setCurrentIndex(
                self.line_style_combo.findData(style["linestyle"])
            )
            self.line_width_spin.setValue(style["linewidth"])
            self.opacity_spin.setValue(style["alpha"])
            self.draw_style_combo.setCurrentIndex(
                self.draw_style_combo.findData(style["drawstyle"])
            )
            self.marker_combo.setCurrentIndex(
                self.marker_combo.findData(style["marker"])
            )
            self.marker_size_spin.setValue(style["markersize"])
            self.marker_face_color_edit.setText(style["markerfacecolor"])
            self.marker_edge_color_edit.setText(style["markeredgecolor"])
            self.marker_edge_width_spin.setValue(style["markeredgewidth"])
        finally:
            self._loading_controls = False

    def _mode_from_style(self, style):
        has_line = style["linestyle"] != "None"
        has_marker = style["marker"] != "None"
        if has_line and has_marker:
            return "lines+markers"
        if has_marker:
            return "markers"
        return "lines"

    def _record_for_trace(self, trace_id):
        record = self._trace_records_by_id.get(str(trace_id))
        return None if record is None else dict(record)

    def _send_style_update(self, trace_id, patch, replace=False, reload_controls=False):
        trace_id = str(trace_id)
        if not patch:
            return False
        record = self._record_for_trace(trace_id)
        if record is None:
            return False
        action = {
            "type": "set_trace_style",
            "subplot_id": record["subplot_id"],
            "trace_id": record["trace_id"],
            "style": dict(patch),
        }
        if replace:
            action["replace"] = True
        if not self.figure_window.request_figure_action(action):
            return False
        if replace:
            self._current_styles[trace_id] = dict(patch)
        else:
            self._current_styles[trace_id].update(patch)
        if self._current_styles[trace_id] == self._original_styles[trace_id]:
            self._touched_trace_ids.discard(trace_id)
        else:
            self._touched_trace_ids.add(trace_id)
        if reload_controls and trace_id == self._current_trace_id():
            self._load_controls_for_trace(trace_id)
        return True

    def _on_trace_changed(self, row):
        if row < 0 or row >= len(self._trace_records):
            return
        self._load_controls_for_trace(self._trace_records[row]["trace_id"])

    def _on_hide_trace_toggled(self, checked):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(trace_id, {"visible": not checked})

    def _on_mode_changed(self, index):
        if self._loading_controls or index < 0:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        style = self._current_styles[trace_id]
        current_marker = style["marker"]
        current_linestyle = style["linestyle"]
        mode = self.mode_combo.itemData(index)
        marker = current_marker if current_marker != "None" else "o"
        linestyle = current_linestyle if current_linestyle != "None" else "-"
        if mode == "lines":
            patch = {"marker": "None", "linestyle": linestyle}
        elif mode == "markers":
            patch = {"marker": marker, "linestyle": "None"}
        else:
            patch = {"marker": marker, "linestyle": linestyle}
        self._send_style_update(trace_id, patch, reload_controls=True)

    def _on_line_color_changed(self):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        text = self.line_color_edit.text().strip()
        color = _parse_color_input(
            text,
            fallback=self._current_styles[trace_id]["color"],
        )
        if color is None:
            self.line_color_edit.setText(
                self._current_styles[trace_id]["color"]
            )
            return
        self._send_style_update(trace_id, {"color": color})

    def _on_line_style_changed(self, index):
        if self._loading_controls or index < 0:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(
            trace_id,
            {"linestyle": self.line_style_combo.itemData(index)},
            reload_controls=True,
        )

    def _on_line_width_changed(self, value):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(trace_id, {"linewidth": float(value)})

    def _on_opacity_changed(self, value):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(trace_id, {"alpha": float(value)})

    def _on_draw_style_changed(self, index):
        if self._loading_controls or index < 0:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(
            trace_id,
            {"drawstyle": self.draw_style_combo.itemData(index)},
        )

    def _on_marker_changed(self, index):
        if self._loading_controls or index < 0:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(
            trace_id,
            {"marker": self.marker_combo.itemData(index)},
            reload_controls=True,
        )

    def _on_marker_size_changed(self, value):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(trace_id, {"markersize": float(value)})

    def _on_marker_face_color_changed(self):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        text = self.marker_face_color_edit.text().strip()
        color = _parse_color_input(
            text,
            fallback=self._current_styles[trace_id]["markerfacecolor"],
            allow_auto=True,
        )
        if color is None:
            self.marker_face_color_edit.setText(
                self._current_styles[trace_id]["markerfacecolor"]
            )
            return
        self._send_style_update(trace_id, {"markerfacecolor": color})

    def _on_marker_edge_color_changed(self):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        text = self.marker_edge_color_edit.text().strip()
        color = _parse_color_input(
            text,
            fallback=self._current_styles[trace_id]["markeredgecolor"],
            allow_auto=True,
        )
        if color is None:
            self.marker_edge_color_edit.setText(
                self._current_styles[trace_id]["markeredgecolor"]
            )
            return
        self._send_style_update(trace_id, {"markeredgecolor": color})

    def _on_marker_edge_width_changed(self, value):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(trace_id, {"markeredgewidth": float(value)})

    def reject(self):
        for trace_id in sorted(self._touched_trace_ids):
            self._send_style_update(
                trace_id,
                self._original_styles[trace_id],
                replace=True,
            )
        self._touched_trace_ids.clear()
        super().reject()
