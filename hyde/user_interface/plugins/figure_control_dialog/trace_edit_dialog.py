from qtutils.qt import QtWidgets

from hyde.user_interface.base_hyde_widgets import HydeDialogWidget
from hyde.user_interface.shared.figure import (
    MatplotlibColorLineEdit,
    default_trace_color,
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
class TraceAppearanceDialog(HydeDialogWidget):
    def __init__(self, figure_context, services=None, parent=None):
        self.figure_context = figure_context
        self._session = self.figure_context.open_session()
        self._loading_controls = False
        self._trace_records = []
        self._trace_records_by_id = {}
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
        for supported_trace in self._session.supported_trace_records():
            trace_id = supported_trace["trace_id"]
            record = {
                "trace_index": len(self._trace_records),
                "subplot_id": supported_trace["subplot_id"],
                "trace_id": trace_id,
                "label": supported_trace["label"],
            }
            self._trace_records.append(record)
            self._trace_records_by_id[trace_id] = dict(record)
            self.ui.trace_list.addItem(record["label"])
        if self.ui.trace_list.count():
            self.ui.trace_list.setCurrentRow(0)
        self.refresh_shell()

    def _current_record(self):
        row = self.ui.trace_list.currentRow()
        if row < 0 or row >= len(self._trace_records):
            return None
        return self._trace_records[row]

    def _current_trace_id(self):
        record = self._current_record()
        return None if record is None else record["trace_id"]

    def _style_for_trace(self, trace_id, subplot_id=None):
        record = self._record_for_trace(trace_id)
        index = 0 if record is None else int(record.get("trace_index", 0))
        style = {
            "color": self._session.trace_style(
                trace_id,
                "color",
                subplot_id=subplot_id,
                default=default_trace_color(index),
            )
        }
        style.update(
            {
            name: self._session.trace_style(
                trace_id,
                name,
                subplot_id=subplot_id,
                default=default,
            )
            for name, default in SUPPORTED_STYLE_DEFAULTS.items()
        }
        )
        return style

    def _load_controls_for_trace(self, trace_id):
        record = self._record_for_trace(trace_id)
        if record is None:
            return
        style = self._style_for_trace(trace_id, subplot_id=record["subplot_id"])
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
        record = self._record_for_trace(trace_id)
        if record is None:
            return
        style = self._style_for_trace(trace_id, subplot_id=record["subplot_id"])
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
        self._session.set_trace_style(
            record["trace_id"],
            subplot_id=record["subplot_id"],
            replace=replace,
            style=dict(patch),
        )
        if not self._session.apply_live():
            return False
        if trace_id == self._current_trace_id():
            self._update_color_field_previews(trace_id)
        if reload_controls and trace_id == self._current_trace_id():
            self._load_controls_for_trace(trace_id)
        self.refresh_shell()
        return True

    def canonical_text_payload(self):
        return self._session.preview_source()

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
        record = self._record_for_trace(trace_id)
        if record is None:
            return
        style = self._style_for_trace(trace_id, subplot_id=record["subplot_id"])
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
        record = self._record_for_trace(trace_id)
        if record is None:
            return
        if color == self._style_for_trace(trace_id, subplot_id=record["subplot_id"])["color"]:
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
        record = self._record_for_trace(trace_id)
        if record is None:
            return
        if (
            color
            == self._style_for_trace(trace_id, subplot_id=record["subplot_id"])[
                "markerfacecolor"
            ]
        ):
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
        record = self._record_for_trace(trace_id)
        if record is None:
            return
        if (
            color
            == self._style_for_trace(trace_id, subplot_id=record["subplot_id"])[
                "markeredgecolor"
            ]
        ):
            return
        self._send_style_update(
            trace_id,
            {"markeredgecolor": color},
        )

    def handle_do_it(self):
        if self._session.commit():
            self.accept()

    def _on_marker_edge_width_changed(self, value):
        if self._loading_controls:
            return
        trace_id = self._current_trace_id()
        if trace_id is None:
            return
        self._send_style_update(trace_id, {"markeredgewidth": float(value)})

    def reject(self):
        self._session.revert()
        super().reject()
