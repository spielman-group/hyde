from matplotlib import rcParams
from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec
from hyde.user_interface.base_hyde_widgets import HydeDialogWidget
from hyde.user_interface.shared.figure import (
    MatplotlibColorLineEdit,
    normalize_matplotlib_color_text,
)
from hyde.user_interface.shared.figure import (
    FigureControlDraftTracker,
    normalize_empty_choice,
)

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


def _normalize_color(value, fallback):
    if value in (None, ""):
        return fallback
    normalized = normalize_matplotlib_color_text(value, allow_auto=True)
    return fallback if normalized in (None, "") else normalized


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
            style[key] = normalize_empty_choice(value)
        elif key == "marker":
            style[key] = normalize_empty_choice(value)
        elif key == "visible":
            style[key] = bool(value)
        elif key in {"linewidth", "alpha", "markersize", "markeredgewidth"}:
            style[key] = float(value)
        else:
            style[key] = value


class TraceAppearanceDialog(HydeDialogWidget):
    def __init__(self, figure_context, services=None, parent=None):
        self.figure_context = figure_context
        self._loading_controls = False
        self._trace_records = []
        self._trace_records_by_id = {}
        self._draft_tracker = FigureControlDraftTracker()
        self._current_styles = self._draft_tracker.current_states
        super().__init__(parent=parent, services=dict(services or {}))
        self.setWindowTitle("Modify Data Appearance")
        self._build_ui()
        self._load_traces()

    def _build_ui(self):
        self.load_ui("trace_edit_dialog.ui", module_name=__name__)
        self.ui.trace_list.currentRowChanged.connect(self._on_trace_changed)
        self.ui.hide_trace_checkbox.toggled.connect(self._on_hide_trace_toggled)
        self.ui.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.ui.line_color_edit.editingFinished.connect(self._on_line_color_changed)
        self.ui.line_style_combo.currentIndexChanged.connect(self._on_line_style_changed)
        self.ui.line_width_spin.valueChanged.connect(self._on_line_width_changed)
        self.ui.opacity_spin.valueChanged.connect(self._on_opacity_changed)
        self.ui.draw_style_combo.currentIndexChanged.connect(self._on_draw_style_changed)
        self.ui.marker_combo.currentIndexChanged.connect(self._on_marker_changed)
        self.ui.marker_size_spin.valueChanged.connect(self._on_marker_size_changed)
        self.ui.marker_face_color_edit.editingFinished.connect(
            self._on_marker_face_color_changed
        )
        self.ui.marker_edge_color_edit.editingFinished.connect(
            self._on_marker_edge_color_changed
        )
        self.ui.marker_edge_width_spin.valueChanged.connect(
            self._on_marker_edge_width_changed
        )

        for label, value in MODE_CHOICES:
            self.ui.mode_combo.addItem(label, value)
        for label, value in LINE_STYLE_CHOICES:
            self.ui.line_style_combo.addItem(label, value)
        for label, value in DRAW_STYLE_CHOICES:
            self.ui.draw_style_combo.addItem(label, value)
        for label, value in MARKER_CHOICES:
            self.ui.marker_combo.addItem(label, value)

    def _load_traces(self):
        figure_ir = self.figure_context.figure_ir() or {}
        trace_styles = self.figure_context.trace_styles() or {}
        figure_defaults = self.figure_context.figure_defaults() or {}
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
        for index, supported_trace in enumerate(
            self.figure_context.supported_trace_records()
        ):
            trace = supported_trace["trace"]
            trace_id = supported_trace["trace_id"]
            style = self._style_from_trace(
                trace,
                index,
                default_trace=default_traces_by_subplot.get(subplot["id"], {}).get(
                    trace_id
                ),
                live_style=trace_styles.get(subplot["id"], {}).get(trace_id),
            )
            record = {
                "subplot_id": supported_trace["subplot_id"],
                "trace_id": trace_id,
                "label": supported_trace["label"],
            }
            self._trace_records.append(record)
            self._trace_records_by_id[trace_id] = dict(record)
            self._draft_tracker.seed(trace_id, style)
            self.ui.trace_list.addItem(record["label"])
        if self.ui.trace_list.count():
            self.ui.trace_list.setCurrentRow(0)
        self.refresh_shell()

    def _style_from_trace(self, trace, index, default_trace=None, live_style=None):
        style = dict(SUPPORTED_STYLE_DEFAULTS)
        style["color"] = _default_trace_color(index)
        if isinstance(default_trace, dict):
            _apply_style_values(style, default_trace.get("kwargs", {}))
        _apply_style_values(style, trace.get("kwargs", {}))
        _apply_style_values(style, live_style)
        return style

    def _current_record(self):
        row = self.ui.trace_list.currentRow()
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
            self.ui.hide_trace_checkbox.setChecked(not style["visible"])
            self.ui.mode_combo.setCurrentIndex(
                self.ui.mode_combo.findData(self._mode_from_style(style))
            )
            self.ui.line_color_edit.set_committed_text(style["color"])
            self.ui.line_style_combo.setCurrentIndex(
                self.ui.line_style_combo.findData(style["linestyle"])
            )
            self.ui.line_width_spin.setValue(style["linewidth"])
            self.ui.opacity_spin.setValue(style["alpha"])
            self.ui.draw_style_combo.setCurrentIndex(
                self.ui.draw_style_combo.findData(style["drawstyle"])
            )
            self.ui.marker_combo.setCurrentIndex(
                self.ui.marker_combo.findData(style["marker"])
            )
            self.ui.marker_size_spin.setValue(style["markersize"])
            self.ui.marker_face_color_edit.set_committed_text(style["markerfacecolor"])
            self.ui.marker_edge_color_edit.set_committed_text(style["markeredgecolor"])
            self.ui.marker_edge_width_spin.setValue(style["markeredgewidth"])
            self._update_color_field_previews(trace_id)
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

    def _update_color_field_previews(self, trace_id):
        style = self._current_styles[str(trace_id)]
        line_color = style["color"]
        self.ui.marker_face_color_edit.set_swatch_preview_text(line_color)
        self.ui.marker_edge_color_edit.set_swatch_preview_text(line_color)

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
        if not self.figure_context.request_figure_action(action):
            return False
        if replace:
            self._draft_tracker.replace(trace_id, patch)
        else:
            self._draft_tracker.update(trace_id, patch)
        if trace_id == self._current_trace_id():
            self._update_color_field_previews(trace_id)
        if reload_controls and trace_id == self._current_trace_id():
            self._load_controls_for_trace(trace_id)
        self.refresh_shell()
        return True

    def _draft_figure_ir(self):
        figure_ir = self.figure_context.figure_ir()
        if figure_ir is None:
            return None
        draft = figure_ir
        for trace_id in self._draft_tracker.current_states:
            record = self._record_for_trace(trace_id)
            if record is None:
                continue
            draft = FigureIRCodec.update_state(
                draft,
                {
                    "type": "set_trace_style",
                    "subplot_id": record["subplot_id"],
                    "trace_id": record["trace_id"],
                    "style": self._current_styles[trace_id],
                    "replace": True,
                },
            )
        return draft

    def canonical_text_payload(self):
        draft = self._draft_figure_ir()
        if draft is None:
            return ""
        return FigureIRCodec.state_to_python(
            draft,
            context={"figure_defaults": self.figure_context.figure_defaults()},
        )

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
        mode = self.ui.mode_combo.itemData(index)
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
        color = self.ui.line_color_edit.text().strip()
        if color == self._current_styles[trace_id]["color"]:
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
            {"linestyle": self.ui.line_style_combo.itemData(index)},
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
            {"drawstyle": self.ui.draw_style_combo.itemData(index)},
        )

    def _on_marker_changed(self, index):
        if self._loading_controls or index < 0:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(
            trace_id,
            {"marker": self.ui.marker_combo.itemData(index)},
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
        color = self.ui.marker_face_color_edit.text().strip()
        if color == self._current_styles[trace_id]["markerfacecolor"]:
            return
        self._send_style_update(
            trace_id,
            {"markerfacecolor": color},
        )

    def _on_marker_edge_color_changed(self):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        color = self.ui.marker_edge_color_edit.text().strip()
        if color == self._current_styles[trace_id]["markeredgecolor"]:
            return
        self._send_style_update(
            trace_id,
            {"markeredgecolor": color},
        )

    def _on_marker_edge_width_changed(self, value):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(trace_id, {"markeredgewidth": float(value)})

    def reject(self):
        for trace_id in self._draft_tracker.changed_keys():
            self._send_style_update(
                trace_id,
                self._draft_tracker.revert_state(trace_id),
                replace=True,
            )
        super().reject()
