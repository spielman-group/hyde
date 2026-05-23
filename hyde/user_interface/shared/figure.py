import ast
import copy
import logging

from matplotlib import colors as mcolors
from matplotlib import rcParams
from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec, figure_patch_source
from hyde.user_interface.base_hyde_widgets import HydeDialogWidget
from hyde.user_interface.shared.core import log_hyde_state_debug

_COMMON_COLOR_NAMES = [
    "black",
    "red",
    "blue",
    "green",
    "white",
    "yellow",
    "orange",
    "purple",
    "cyan",
    "magenta",
    "gray",
    "brown",
    "pink",
    "olive",
    "navy",
    "teal",
    "maroon",
    "lime",
]


def rgba_from_matplotlib_color(value):
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("Color text is empty.")
        try:
            return mcolors.to_rgba(stripped)
        except ValueError:
            literal = ast.literal_eval(stripped)
            return mcolors.to_rgba(literal)
    return mcolors.to_rgba(value)


def normalize_matplotlib_color_text(value, *, allow_auto=False, allow_empty=True):
    text = "" if value is None else str(value).strip()
    if not text:
        return "" if allow_empty else None
    if allow_auto and text.lower() == "auto":
        return "auto"
    try:
        rgba = rgba_from_matplotlib_color(text)
    except Exception:
        return None
    keep_alpha = abs(float(rgba[3]) - 1.0) > 1e-9
    return mcolors.to_hex(rgba, keep_alpha=keep_alpha)


def qcolor_from_matplotlib_color_text(value, *, allow_auto=False):
    normalized = normalize_matplotlib_color_text(
        value,
        allow_auto=allow_auto,
        allow_empty=True,
    )
    if normalized in (None, "", "auto"):
        return None
    rgba = rgba_from_matplotlib_color(normalized)
    qcolor = QtGui.QColor()
    qcolor.setRgbF(*rgba)
    return qcolor if qcolor.isValid() else None


def color_text_from_qcolor(color):
    if color is None or not color.isValid():
        return ""
    rgba = (
        float(color.redF()),
        float(color.greenF()),
        float(color.blueF()),
        float(color.alphaF()),
    )
    keep_alpha = abs(rgba[3] - 1.0) > 1e-9
    return mcolors.to_hex(rgba, keep_alpha=keep_alpha)


def named_matplotlib_colors():
    names = dict(mcolors.CSS4_COLORS)
    ordered = []
    seen = set()
    for name in _COMMON_COLOR_NAMES:
        if name in names:
            ordered.append((name, names[name]))
            seen.add(name)
    for name in sorted(names, key=str.lower):
        if name in seen:
            continue
        ordered.append((name, names[name]))
    return ordered


class MatplotlibColorDialog(QtWidgets.QColorDialog):
    def __init__(
        self,
        parent=None,
        *,
        initial_text="",
        preview_text=None,
        allow_empty=True,
        allow_auto=False,
    ):
        super().__init__(parent)
        self._allow_empty = bool(allow_empty)
        self._allow_auto = bool(allow_auto)
        self._selected_text = ""
        self._syncing_html = False
        self._html_edit = None
        self._html_label = None
        self._html_container = None
        self._named_colors_list = None
        self._named_colors_label = None
        self.setOption(QtWidgets.QColorDialog.ShowAlphaChannel, True)
        self.setOption(QtWidgets.QColorDialog.DontUseNativeDialog, True)
        self._patch_dialog_ui()
        self._apply_initial_text(initial_text, preview_text)
        self.currentColorChanged.connect(self._on_current_color_changed)

    def _find_label(self, needle):
        normalized = needle.replace("&", "").replace(":", "").strip().lower()
        for label in self.findChildren(QtWidgets.QLabel):
            text = label.text().replace("&", "").replace(":", "").strip().lower()
            if text == normalized:
                return label
        return None

    def _patch_dialog_ui(self):
        top_layout = self.layout()
        top_content_layout = None
        left_layout = None
        right_layout = None
        if top_layout is not None and top_layout.count():
            top_item = top_layout.itemAt(0)
            if top_item is not None and top_item.layout() is not None:
                top_content_layout = top_item.layout()
        if (
            top_content_layout is not None
            and top_content_layout.count()
            and top_content_layout.itemAt(0).layout() is not None
        ):
            left_layout = top_content_layout.itemAt(0).layout()
        if (
            top_content_layout is not None
            and top_content_layout.count() > 1
            and top_content_layout.itemAt(1).layout() is not None
        ):
            right_layout = top_content_layout.itemAt(1).layout()

        html_label = self._find_label("HTML")
        html_edit = None
        sample_frame = None
        for frame in self.findChildren(QtWidgets.QFrame):
            parent_layout = None if frame.parentWidget() is None else frame.parentWidget().layout()
            if isinstance(parent_layout, QtWidgets.QGridLayout):
                sample_frame = frame
                break
        if html_label is not None:
            html_edit = html_label.buddy()
            html_label.hide()
            if html_edit is not None:
                html_edit.hide()

        self._html_container = QtWidgets.QWidget(self)
        self._html_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        html_layout = QtWidgets.QHBoxLayout(self._html_container)
        html_layout.setContentsMargins(0, 0, 0, 0)
        html_layout.setSpacing(6)
        self._html_label = QtWidgets.QLabel("Matplotlib color:", self._html_container)
        self._html_label.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Fixed,
        )
        html_layout.addWidget(self._html_label)
        if html_edit is None:
            self._html_edit = QtWidgets.QLineEdit(self._html_container)
        else:
            self._html_edit = html_edit
            html_layout.addWidget(self._html_edit)
            self._html_edit.show()
        if html_edit is None:
            html_layout.addWidget(self._html_edit, 1)
        else:
            html_layout.setStretch(html_layout.indexOf(self._html_edit), 1)
        self._html_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        self._html_label.setBuddy(self._html_edit)

        self._named_colors_label = QtWidgets.QLabel("Matplotlib colors", self)
        self._named_colors_list = QtWidgets.QListWidget(self)
        self._named_colors_list.setViewMode(QtWidgets.QListView.ListMode)
        self._named_colors_list.setFlow(QtWidgets.QListView.TopToBottom)
        self._named_colors_list.setMovement(QtWidgets.QListView.Static)
        self._named_colors_list.setWrapping(False)
        self._named_colors_list.setWordWrap(False)
        self._named_colors_list.setUniformItemSizes(True)
        self._named_colors_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        self._named_colors_list.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollPerPixel
        )
        self._named_colors_list.setSpacing(1)
        self._named_colors_list.itemClicked.connect(self._on_named_color_clicked)
        self._named_colors_list.itemDoubleClicked.connect(
            lambda _item: self.accept()
        )
        self._named_colors_label.setBuddy(self._named_colors_list)

        for name, value in named_matplotlib_colors():
            qcolor = qcolor_from_matplotlib_color_text(value)
            if qcolor is None:
                continue
            item = QtWidgets.QListWidgetItem(name)
            item.setData(QtCore.Qt.UserRole, color_text_from_qcolor(qcolor))
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            item.setBackground(QtGui.QBrush(qcolor))
            luminance = (
                0.2126 * qcolor.redF()
                + 0.7152 * qcolor.greenF()
                + 0.0722 * qcolor.blueF()
            )
            foreground = QtGui.QColor("black" if luminance > 0.55 else "white")
            item.setForeground(QtGui.QBrush(foreground))
            item.setToolTip(f"{name}: {item.data(QtCore.Qt.UserRole)}")
            item.setSizeHint(QtCore.QSize(0, 22))
            self._named_colors_list.addItem(item)

        if left_layout is not None:
            self._hide_layout_widgets(left_layout)
            left_layout.addWidget(self._named_colors_label)
            left_layout.addWidget(self._named_colors_list, 1)

        if right_layout is not None:
            right_layout.addWidget(self._html_container)

        if sample_frame is not None:
            sample_frame.setFixedWidth(max(sample_frame.width(), 78))

        if self._html_edit is not None:
            self._html_edit.setMaxLength(256)
            self._html_edit.editingFinished.connect(self._on_html_editing_finished)

    def _hide_layout_widgets(self, layout):
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.hide()
            elif child_layout is not None:
                self._hide_layout_widgets(child_layout)

    def _apply_initial_text(self, initial_text, preview_text):
        text = "" if initial_text is None else str(initial_text).strip()
        if self._html_edit is not None:
            self._html_edit.setText(text)
        normalized = normalize_matplotlib_color_text(
            text,
            allow_auto=self._allow_auto,
            allow_empty=self._allow_empty,
        )
        if normalized not in (None, "", "auto"):
            self.setCurrentColor(qcolor_from_matplotlib_color_text(normalized))
            if self._html_edit is not None:
                self._html_edit.setText(normalized)
            return
        preview_color = qcolor_from_matplotlib_color_text(preview_text)
        if preview_color is not None:
            self.setCurrentColor(preview_color)

    def _on_html_editing_finished(self):
        if self._html_edit is None or self._syncing_html:
            return
        normalized = normalize_matplotlib_color_text(
            self._html_edit.text(),
            allow_auto=self._allow_auto,
            allow_empty=self._allow_empty,
        )
        if normalized is None:
            return
        if normalized in ("", "auto"):
            self._html_edit.setText(normalized)
            return
        self._syncing_html = True
        try:
            self.setCurrentColor(qcolor_from_matplotlib_color_text(normalized))
            self._html_edit.setText(normalized)
        finally:
            self._syncing_html = False

    def _on_current_color_changed(self, color):
        if self._html_edit is None or self._syncing_html or color is None:
            return
        self._syncing_html = True
        try:
            self._html_edit.setText(color_text_from_qcolor(color))
        finally:
            self._syncing_html = False

    def _on_named_color_clicked(self, item):
        color_text = str(item.data(QtCore.Qt.UserRole) or "")
        qcolor = qcolor_from_matplotlib_color_text(color_text)
        if qcolor is None:
            return
        self.setCurrentColor(qcolor)
        if self._html_edit is not None:
            self._html_edit.setText(color_text)

    def accept(self):
        text = ""
        if self._html_edit is not None:
            text = self._html_edit.text()
        normalized = normalize_matplotlib_color_text(
            text,
            allow_auto=self._allow_auto,
            allow_empty=self._allow_empty,
        )
        if normalized is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid color",
                "Enter a valid matplotlib color name, tuple, or hex value.",
            )
            if self._html_edit is not None:
                self._html_edit.setFocus()
                self._html_edit.selectAll()
            return
        if normalized in ("", "auto"):
            self._selected_text = normalized
        else:
            qcolor = qcolor_from_matplotlib_color_text(normalized)
            if qcolor is not None:
                self.setCurrentColor(qcolor)
            self._selected_text = normalized
        super().accept()

    def selected_color_text(self):
        return self._selected_text


class MatplotlibColorLineEdit(QtWidgets.QLineEdit):
    def __init__(self, parent=None, *, allow_empty=True, allow_auto=False):
        super().__init__(parent)
        self._allow_empty = bool(allow_empty)
        self._allow_auto = bool(allow_auto)
        self._committed_text = ""
        self._swatch_preview_text = None
        self._swatch_button = QtWidgets.QToolButton(self)
        self._swatch_button.setCursor(QtCore.Qt.PointingHandCursor)
        self._swatch_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self._swatch_button.clicked.connect(self._open_color_dialog)
        self.textChanged.connect(self._update_swatch)
        self.editingFinished.connect(self._commit_current_text)
        self._update_text_margins()
        self._update_swatch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        side = max(18, self.height() - 8)
        x = self.width() - side - 4
        y = max(2, (self.height() - side) // 2)
        self._swatch_button.setGeometry(x, y, side, side)
        self._update_text_margins()

    def _update_text_margins(self):
        side = max(18, self.height() - 8)
        self.setTextMargins(0, 0, side + 8, 0)

    def set_committed_text(self, text):
        normalized = normalize_matplotlib_color_text(
            text,
            allow_auto=self._allow_auto,
            allow_empty=self._allow_empty,
        )
        committed = (
            ("" if text is None else str(text).strip())
            if normalized is None
            else normalized
        )
        self._committed_text = committed
        super().setText(committed)
        self._update_swatch()

    def set_swatch_preview_text(self, text):
        self._swatch_preview_text = text
        self._update_swatch()

    def swatch_color_text(self):
        display_text = self.text().strip()
        normalized = normalize_matplotlib_color_text(
            display_text,
            allow_auto=self._allow_auto,
            allow_empty=True,
        )
        if normalized == "auto":
            return normalize_matplotlib_color_text(
                self._swatch_preview_text,
                allow_auto=False,
                allow_empty=True,
            )
        if normalized not in (None, ""):
            return normalized
        return None

    def _open_color_dialog(self):
        dialog_parent = self.window()
        if not isinstance(dialog_parent, QtWidgets.QWidget):
            dialog_parent = self
        dialog = MatplotlibColorDialog(
            dialog_parent,
            initial_text=self.text(),
            preview_text=self._swatch_preview_text,
            allow_empty=self._allow_empty,
            allow_auto=self._allow_auto,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        self.set_committed_text(dialog.selected_color_text())
        self.editingFinished.emit()

    def _commit_current_text(self):
        normalized = normalize_matplotlib_color_text(
            self.text(),
            allow_auto=self._allow_auto,
            allow_empty=self._allow_empty,
        )
        if normalized is None:
            super().setText(self._committed_text)
            self._update_swatch()
            return
        self._committed_text = normalized
        if self.text() != normalized:
            super().setText(normalized)
        self._update_swatch()

    def _update_swatch(self):
        display_color = qcolor_from_matplotlib_color_text(self.swatch_color_text())
        current_text = self.text().strip()
        is_invalid = bool(current_text) and normalize_matplotlib_color_text(
            current_text,
            allow_auto=self._allow_auto,
            allow_empty=self._allow_empty,
        ) is None
        swatch_text = ""
        tooltip = current_text or "Select color"
        if current_text.lower() == "auto" and self._allow_auto:
            swatch_text = "A"
            tooltip = (
                "auto"
                if display_color is None
                else f"auto -> {color_text_from_qcolor(display_color)}"
            )
        border = "#b00020" if is_invalid else "#666666"
        if display_color is None:
            background = "transparent"
        else:
            background = (
                f"rgba({display_color.red()}, {display_color.green()}, "
                f"{display_color.blue()}, {display_color.alpha()})"
            )
        self._swatch_button.setText(swatch_text)
        self._swatch_button.setToolTip(tooltip)
        self._swatch_button.setStyleSheet(
            "QToolButton {"
            f"background-color: {background};"
            f"border: 1px solid {border};"
            "border-radius: 2px;"
            "padding: 0px;"
            "}"
        )

    def getAllowAuto(self):
        return bool(self._allow_auto)

    def setAllowAuto(self, allow_auto):
        self._allow_auto = bool(allow_auto)
        self._commit_current_text()

    def getAllowEmpty(self):
        return bool(self._allow_empty)

    def setAllowEmpty(self, allow_empty):
        self._allow_empty = bool(allow_empty)
        self._commit_current_text()

    allowAuto = QtCore.pyqtProperty(bool, fget=getAllowAuto, fset=setAllowAuto)
    allowEmpty = QtCore.pyqtProperty(bool, fget=getAllowEmpty, fset=setAllowEmpty)


COMM_TARGET = "hyde_figure"
LOGGER = logging.getLogger("hyde")


def register_auxiliary_figure_comm_sink(kernel_client, label):
    comm_manager = getattr(kernel_client, "comm_manager", None)
    if comm_manager is None:
        return False

    def _on_open(comm, msg):
        payload = msg.get("content", {}).get("data", {})
        LOGGER.debug(
            "Auxiliary kernel client %s absorbed figure comm %s for figure %s.",
            label,
            getattr(comm, "comm_id", None),
            payload.get("figure_number"),
        )
        comm.on_msg(lambda _message: None)
        comm.on_close(
            lambda _message, current_comm=comm: LOGGER.debug(
                "Auxiliary kernel client %s observed figure comm %s close.",
                label,
                getattr(current_comm, "comm_id", None),
            )
        )

    comm_manager.register_target(COMM_TARGET, _on_open)
    return True

def normalize_empty_choice(value):
    if value in (None, "", "none", "None", " "):
        return "None"
    return str(value)


SUPPORTED_TRACE_STYLE_DEFAULTS = {
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

TRACE_STYLE_ACTION_KEYS = (
    "alpha",
    "color",
    "drawstyle",
    "label",
    "linestyle",
    "linewidth",
    "marker",
    "markeredgecolor",
    "markeredgewidth",
    "markerfacecolor",
    "markersize",
    "visible",
)


def default_trace_color(index):
    colors = rcParams["axes.prop_cycle"].by_key().get("color", ["#1f77b4"])
    return str(colors[index % len(colors)])


def normalize_trace_style_color(value, fallback):
    if value in (None, ""):
        return fallback
    normalized = normalize_matplotlib_color_text(value, allow_auto=True)
    return fallback if normalized in (None, "") else normalized


def apply_trace_style_values(style, values):
    if not isinstance(values, dict):
        return style
    for key in ("color",) + TRACE_STYLE_ACTION_KEYS:
        if key not in values:
            continue
        value = values[key]
        if key == "color":
            style[key] = normalize_trace_style_color(value, style[key])
        elif key in {"markerfacecolor", "markeredgecolor"}:
            style[key] = normalize_trace_style_color(value, style[key])
        elif key in {"linestyle", "marker"}:
            style[key] = normalize_empty_choice(value)
        elif key == "visible":
            style[key] = bool(value)
        elif key in {"linewidth", "alpha", "markersize", "markeredgewidth"}:
            style[key] = float(value)
        else:
            style[key] = value
    return style


def trace_style_defaults_by_subplot(figure_defaults):
    defaults = dict(figure_defaults or {})
    default_ir = defaults.get("figure_ir")
    if default_ir is None and ("layout" in defaults or "settings" in defaults):
        default_ir = defaults
    trace_defaults_by_subplot = {}
    if isinstance(default_ir, dict):
        for subplot in default_ir.get("layout", {}).get("subplots", []):
            subplot_id = str(subplot.get("id"))
            trace_defaults_by_subplot[subplot_id] = {
                str(trace.get("id")): dict(trace or {})
                for trace in subplot.get("traces", [])
            }
    for subplot_id, trace_defaults in dict(defaults.get("trace_styles", {}) or {}).items():
        subplot_defaults = trace_defaults_by_subplot.setdefault(str(subplot_id), {})
        for trace_id, style in dict(trace_defaults or {}).items():
            subplot_defaults.setdefault(
                str(trace_id),
                {"kwargs": dict(style or {})},
            )
    return trace_defaults_by_subplot


def supported_trace_style_state(
    trace,
    *,
    index,
    default_trace=None,
    live_style=None,
):
    style = dict(SUPPORTED_TRACE_STYLE_DEFAULTS)
    style["color"] = default_trace_color(index)
    if isinstance(default_trace, dict):
        apply_trace_style_values(style, default_trace.get("kwargs", {}))
    apply_trace_style_values(style, dict(trace.get("kwargs", {}) or {}))
    apply_trace_style_values(style, live_style)
    return style


def trace_source_name(source):
    if not isinstance(source, dict):
        return None
    if source.get("kind") != "name":
        return None
    value = str(source.get("value") or "").strip()
    return value or None


def trace_display_name(trace):
    label = trace.get("kwargs", {}).get("label")
    if label not in (None, "", "_nolegend_"):
        return str(label)
    y_name = trace_source_name(trace.get("y_source"))
    if y_name:
        return y_name
    return str(trace.get("id", "trace"))


def supported_trace_records_from_figure_ir(figure_ir):
    figure_ir = dict(figure_ir or {})
    subplots = figure_ir.get("layout", {}).get("subplots", [])
    if not subplots:
        return ()
    subplot = subplots[0]
    records = []
    for trace in subplot.get("traces", []):
        if trace.get("kind") != "line":
            continue
        records.append(
            {
                "subplot_id": str(subplot.get("id")),
                "trace_id": str(trace.get("id")),
                "label": trace_display_name(trace),
                "x_name": trace_source_name(trace.get("x_source")),
                "y_name": trace_source_name(trace.get("y_source")),
                "trace": dict(trace),
            }
        )
    return tuple(records)


def default_subplot_layout_state():
    return FigureIRCodec.validate_state({"layout": {"subplots": [{}]}})["layout"][
        "subplots"
    ][0]


def merge_defaulted_value(current, default, baseline):
    if isinstance(baseline, dict) and isinstance(current, dict):
        merged = {}
        keys = set(baseline) | set(current) | set(default or {})
        for key in keys:
            merged[key] = merge_defaulted_value(
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


def figure_ir_with_defaults(figure_ir, figure_defaults):
    if figure_ir is None:
        return None
    if not isinstance(figure_defaults, dict):
        return FigureIRCodec.validate_state(figure_ir)
    merged = FigureIRCodec.validate_state(figure_ir)
    defaults = FigureIRCodec.validate_state(figure_defaults)
    baseline_subplot = default_subplot_layout_state()
    default_subplots = {
        subplot["id"]: subplot for subplot in defaults.get("layout", {}).get("subplots", [])
    }
    for subplot in merged.get("layout", {}).get("subplots", []):
        default_subplot = default_subplots.get(subplot["id"])
        if default_subplot is None:
            continue
        for axis_name in ("x", "y"):
            subplot["axes"][axis_name] = merge_defaulted_value(
                subplot["axes"][axis_name],
                default_subplot["axes"][axis_name],
                baseline_subplot["axes"][axis_name],
            )
        for side in ("bottom", "top", "left", "right"):
            subplot["axis_sides"][side] = merge_defaulted_value(
                subplot["axis_sides"][side],
                default_subplot["axis_sides"][side],
                baseline_subplot["axis_sides"][side],
            )
        subplot["margins"] = merge_defaulted_value(
            subplot.get("margins", {}),
            default_subplot.get("margins", {}),
            baseline_subplot.get("margins", {}),
        )
    return merged


class EditableFigureContext:
    def __init__(self, figure_window):
        self.figure_number = int(figure_window.figure_number)
        self._figure_window = figure_window

    def figure_name(self):
        return str(self._figure_window.snapshot_state.default_macro_name())

    def open_session(self):
        return self._figure_window.open_edit_session()

    def has_supported_traces(self):
        return self.open_session().has_supported_traces()


class HydeFigureDialogWidget(HydeDialogWidget):
    figure_patch_command_name = "figure_edit"

    def __init__(self, *args, figure_context=None, services=None, **kwargs):
        self.figure_context = figure_context
        self._session = None
        self._opening_effective_state = None
        self._applied_effective_state = None
        self._supported_trace_rows = ()
        self._supported_trace_rows_by_id = {}
        super().__init__(*args, services=dict(services or {}), **kwargs)
        if self.figure_context is None:
            return
        self._session = self.figure_context.open_session()
        self._opening_effective_state = self._session.opening_effective_state()
        self._applied_effective_state = copy.deepcopy(self._opening_effective_state)
        self._reload_supported_trace_rows()

    def figure_session(self):
        return self._session

    def opening_effective_state(self):
        if self._opening_effective_state is None:
            return None
        return copy.deepcopy(self._opening_effective_state)

    def applied_effective_state(self):
        if self._applied_effective_state is None:
            return None
        return copy.deepcopy(self._applied_effective_state)

    def current_effective_state(self):
        if self._session is None:
            return None
        return self._session.current_effective_state()

    def figure_patch_source(self, source_state, target_state, *, refresh_trace_ids=()):
        if self.figure_context is None:
            return ""
        return figure_patch_source(
            source_state,
            target_state,
            figure_name=self.figure_context.figure_name(),
            refresh_trace_ids=refresh_trace_ids,
        )

    def refresh_figure_preview(self, error_message=""):
        message = str(error_message or "")
        if message:
            self.set_preview_message(message)
            self.refresh_shell()
            return self.preview_display_text()
        target_state = self.current_effective_state()
        if self._applied_effective_state is None or target_state is None:
            self.set_preview_string("")
            self.refresh_shell()
            return self.preview_string()
        try:
            self.set_preview_string(
                self.figure_patch_source(
                    self._applied_effective_state,
                    target_state,
                )
            )
        except Exception as exc:
            self.set_preview_message(str(exc))
        self.refresh_shell()
        return self.preview_string()

    def execute_figure_patch(self, code, *, mode):
        if not str(code or "").strip():
            return True
        if self.figure_context is not None:
            log_hyde_state_debug(
                "FigurePatchState",
                {
                    "feature": "figure_patch",
                    "command": self.figure_patch_command_name,
                    "mode": str(mode),
                    "figure_number": int(self.figure_context.figure_number),
                    "figure_name": self.figure_context.figure_name(),
                },
                code,
            )
        return self.execute_hidden_command(code)

    def apply_figure_patch_command(
        self,
        code,
        *,
        mode,
        target_state=None,
        refresh_preview=True,
    ):
        if not str(code or "").strip():
            return True
        if not self.execute_figure_patch(code, mode=mode):
            return False
        if target_state is not None:
            self._applied_effective_state = copy.deepcopy(target_state)
            self._reload_supported_trace_rows(target_state)
        if refresh_preview:
            self.refresh_figure_preview()
        return True

    def apply_figure_patch(self, target_state, *, mode, refresh_preview=True):
        if self._applied_effective_state is None or target_state is None:
            return False
        code = self.figure_patch_source(self._applied_effective_state, target_state)
        return self.apply_figure_patch_command(
            code,
            mode=mode,
            target_state=target_state,
            refresh_preview=refresh_preview,
        )

    def apply_current_figure_patch(self, *, mode, refresh_preview=True):
        return self.apply_figure_patch(
            self.current_effective_state(),
            mode=mode,
            refresh_preview=refresh_preview,
        )

    def commit_current_figure_patch(self, *, mode="do_it"):
        target_state = self.current_effective_state()
        if self.dispatch_do_it_payload(
            executor=lambda code: self.execute_figure_patch(code, mode=mode),
            accept_on_success=False,
        ):
            if target_state is not None:
                self._applied_effective_state = copy.deepcopy(target_state)
                self._reload_supported_trace_rows(target_state)
            self.accept()
            return True
        return False

    def handle_do_it(self):
        self.commit_current_figure_patch()

    def rollback_figure_patch(self):
        if (
            self._opening_effective_state is None
            or self._applied_effective_state is None
        ):
            return True
        rollback_state = copy.deepcopy(self._opening_effective_state)
        if not self.apply_figure_patch(
            rollback_state,
            mode="cancel",
            refresh_preview=False,
        ):
            return False
        self.refresh_figure_preview()
        return True

    def reject(self):
        self.rollback_figure_patch()
        super().reject()

    def supported_trace_records(self):
        return copy.deepcopy(self._supported_trace_rows)

    def supported_trace_record(self, trace_id):
        record = self._supported_trace_rows_by_id.get(str(trace_id))
        return None if record is None else copy.deepcopy(record)

    def refresh_supported_trace_list(
        self,
        list_widget,
        *,
        rows=None,
        selected_trace_ids=(),
        current_trace_id=None,
    ):
        rendered_rows = self.supported_trace_records() if rows is None else tuple(
            copy.deepcopy(rows)
        )
        normalized_selected = {str(trace_id) for trace_id in selected_trace_ids}
        normalized_current = (
            None if current_trace_id is None else str(current_trace_id)
        )
        blocker = QtCore.QSignalBlocker(list_widget)
        try:
            list_widget.clear()
            for row in rendered_rows:
                item = QtWidgets.QListWidgetItem(row["row_text"])
                item.setData(QtCore.Qt.UserRole, row["trace_id"])
                list_widget.addItem(item)
                if row["trace_id"] in normalized_selected:
                    item.setSelected(True)
                if row["trace_id"] == normalized_current:
                    list_widget.setCurrentItem(item)
            if normalized_current is None and not normalized_selected:
                list_widget.setCurrentRow(-1)
        finally:
            del blocker
        return rendered_rows

    def current_supported_trace_id(self, list_widget):
        item = list_widget.currentItem()
        if item is None:
            return None
        trace_id = item.data(QtCore.Qt.UserRole)
        return None if trace_id is None else str(trace_id)

    def selected_supported_trace_ids(self, list_widget):
        trace_ids = []
        for item in list_widget.selectedItems():
            trace_id = item.data(QtCore.Qt.UserRole)
            if trace_id is None:
                continue
            trace_ids.append(str(trace_id))
        return tuple(trace_ids)

    def _reload_supported_trace_rows(self, effective_state=None):
        if self._session is None and effective_state is None:
            self._supported_trace_rows = ()
            self._supported_trace_rows_by_id = {}
            return self._supported_trace_rows
        rows = []
        rows_by_id = {}
        trace_records = (
            self._session.supported_trace_records()
            if effective_state is None
            else supported_trace_records_from_figure_ir(effective_state)
        )
        for index, record in enumerate(trace_records):
            row = dict(record)
            row["trace_index"] = index
            row["trace_id"] = str(row["trace_id"])
            row["subplot_id"] = str(row["subplot_id"])
            row["row_text"] = self._canonical_supported_trace_row_text(row)
            rows.append(row)
            rows_by_id[row["trace_id"]] = dict(row)
        self._supported_trace_rows = tuple(rows)
        self._supported_trace_rows_by_id = rows_by_id
        return self.supported_trace_records()

    def _canonical_supported_trace_row_text(self, record):
        text = str(record.get("label") or "").strip()
        if not text:
            text = str(record.get("trace_id") or "").strip()
        y_name = str(record.get("y_name") or "").strip()
        x_name = str(record.get("x_name") or "").strip()
        if y_name and x_name:
            return f"{text} | {y_name} vs {x_name}"
        if y_name:
            return f"{text} | {y_name}"
        if x_name:
            return f"{text} | {x_name}"
        return text


class FigureEditSession:
    def __init__(
        self,
        *,
        figure_number,
        figure_ir,
        figure_defaults=None,
        trace_styles=None,
        resolved_axis_limits=None,
    ):
        self.figure_number = int(figure_number)
        self._figure_defaults = copy.deepcopy(figure_defaults)
        self._trace_styles = copy.deepcopy(trace_styles) or {}
        self._trace_style_defaults = trace_style_defaults_by_subplot(self._figure_defaults)
        self._resolved_axis_limits = copy.deepcopy(resolved_axis_limits) or {}
        self._opening_state = FigureIRCodec.validate_state(figure_ir)
        self._current_state = copy.deepcopy(self._opening_state)
        self._opening_trace_style_states = self._initial_trace_style_states(
            self._opening_state
        )
        self._current_trace_style_states = copy.deepcopy(
            self._opening_trace_style_states
        )

    def figure_title(self):
        return self._current_state["settings"]["title"]

    def figure_size(self):
        return copy.deepcopy(self._current_state["settings"]["figsize"])

    def subplot_ids(self):
        return tuple(
            subplot["id"] for subplot in self._current_state["layout"]["subplots"]
        )

    def subplot_title(self, subplot_id=None):
        return self._subplot(subplot_id)["title"]

    def legend_visible(self, subplot_id=None):
        return bool(self._subplot(subplot_id)["legend"])

    def axis_label(self, axis, subplot_id=None):
        return self.axis_value(axis, "label", "text", subplot_id=subplot_id)

    def axis_limits(self, axis, subplot_id=None):
        return self.axis_value(axis, "range", "limits", subplot_id=subplot_id)

    def axis_limit_mode(self, axis, subplot_id=None):
        return self.axis_value(axis, "range", "limit_mode", subplot_id=subplot_id)

    def axis_scale(self, axis, subplot_id=None):
        return self.axis_value(axis, "scale_mode", subplot_id=subplot_id)

    def axis_value(self, axis, *path, subplot_id=None, default=None):
        value = self._value_from_path(
            self._effective_axis_state(axis, subplot_id),
            path,
            default=default,
        )
        return copy.deepcopy(value)

    def axis_side_value(self, side, *path, subplot_id=None, default=None):
        value = self._value_from_path(
            self._effective_axis_side_state(side, subplot_id),
            path,
            default=default,
        )
        return copy.deepcopy(value)

    def subplot_margin(self, side, *, subplot_id=None, default=None):
        subplot = self._effective_subplot(subplot_id)
        return copy.deepcopy(subplot.get("margins", {}).get(str(side), default))

    def resolved_axis_limits(self, axis, subplot_id=None):
        subplot_id = self._resolve_subplot_id(subplot_id)
        return copy.deepcopy(
            self._resolved_axis_limits.get(subplot_id, {}).get(
                self._normalize_axis_name(axis)
            )
        )

    def trace_ids(self, subplot_id=None):
        return tuple(trace["id"] for trace in self._subplot(subplot_id)["traces"])

    def trace(self, trace_id, subplot_id=None):
        return copy.deepcopy(self._trace(trace_id, subplot_id))

    def trace_style(self, trace_id, name, subplot_id=None, default=None):
        trace_key = self._trace_style_key(trace_id, subplot_id)
        if trace_key in self._current_trace_style_states:
            return copy.deepcopy(
                self._current_trace_style_states[trace_key].get(str(name), default)
            )
        trace = self._trace(trace_id, subplot_id)
        return copy.deepcopy(trace["kwargs"].get(str(name), default))

    def supported_trace_records(self):
        return supported_trace_records_from_figure_ir(self._current_state)

    def has_supported_traces(self):
        return bool(self.supported_trace_records())

    def is_dirty(self):
        return (
            self._current_state != self._opening_state
            or self._current_trace_style_states != self._opening_trace_style_states
        )

    def preview_source(self):
        return FigureIRCodec.state_to_python(
            self._dispatch_state(self._current_state, self._current_trace_style_states),
            context={"figure_defaults": self._figure_defaults},
        )

    def python_source(self):
        return self.preview_source()

    def opening_effective_state(self):
        return figure_ir_with_defaults(
            self._dispatch_state(
                self._opening_state,
                self._opening_trace_style_states,
            ),
            self._figure_defaults,
        )

    def current_effective_state(self):
        return figure_ir_with_defaults(
            self._dispatch_state(
                self._current_state,
                self._current_trace_style_states,
            ),
            self._figure_defaults,
        )

    def reset_current_state(self):
        self._current_state = copy.deepcopy(self._opening_state)
        self._current_trace_style_states = copy.deepcopy(
            self._opening_trace_style_states
        )
        return copy.deepcopy(self._current_state)

    def set_figure_title(self, title, *, subplot_id=None):
        return self._update_current_state(
            {
                "type": "set_figure_title",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "title": title,
            }
        )

    def set_subplot_title(self, title, *, subplot_id=None):
        return self._update_current_state(
            {
                "type": "set_subplot_title",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "title": title,
            }
        )

    def set_legend_visible(self, visible, *, subplot_id=None):
        return self._update_current_state(
            {
                "type": "set_legend_visible",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "visible": bool(visible),
            }
        )

    def set_axis_label(self, axis, label, *, subplot_id=None):
        return self._update_current_state(
            {
                "type": "set_axis_label",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "axis": self._normalize_axis_name(axis),
                "label": label,
            }
        )

    def set_axis_limits(self, axis, minimum, maximum, *, subplot_id=None):
        return self._update_current_state(
            {
                "type": "set_axis_limits",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "axis": self._normalize_axis_name(axis),
                "min": minimum,
                "max": maximum,
            }
        )

    def set_xlim(self, left, right, *, subplot_id=None):
        return self.set_axis_limits("x", left, right, subplot_id=subplot_id)

    def set_ylim(self, bottom, top, *, subplot_id=None):
        return self.set_axis_limits("y", bottom, top, subplot_id=subplot_id)

    def set_axis_state(self, axis, state, *, subplot_id=None, replace=False):
        return self._update_current_state(
            {
                "type": "set_axis_state",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "axis": self._normalize_axis_name(axis),
                "state": copy.deepcopy(state),
                "replace": bool(replace),
            }
        )

    def set_axis_side_state(self, side, state, *, subplot_id=None, replace=False):
        return self._update_current_state(
            {
                "type": "set_axis_side_state",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "side": self._normalize_side_name(side),
                "state": copy.deepcopy(state),
                "replace": bool(replace),
            }
        )

    def set_subplot_margins(self, *, subplot_id=None, replace=False, **state):
        return self._update_current_state(
            {
                "type": "set_subplot_margins",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "state": copy.deepcopy(state),
                "replace": bool(replace),
            }
        )

    def subplots_adjust(
        self,
        *,
        left=None,
        bottom=None,
        right=None,
        top=None,
        subplot_id=None,
        replace=False,
    ):
        state = {
            key: value
            for key, value in (
                ("left", left),
                ("bottom", bottom),
                ("right", right),
                ("top", top),
            )
            if value is not None
        }
        return self.set_subplot_margins(
            subplot_id=subplot_id,
            replace=replace,
            **state,
        )

    def set_trace_style(
        self,
        trace_id,
        *,
        subplot_id=None,
        replace=False,
        style=None,
        **kwargs,
    ):
        merged_style = dict(style or {})
        merged_style.update(kwargs)
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        updated_state = self._update_current_state(
            {
                "type": "set_trace_style",
                "subplot_id": resolved_subplot_id,
                "trace_id": str(trace_id),
                "style": merged_style,
                "replace": bool(replace),
            }
        )
        self._update_trace_style_state(
            trace_id,
            subplot_id=resolved_subplot_id,
            style=merged_style,
            replace=replace,
        )
        return updated_state

    def set_trace(self, trace_id, trace=None, *, subplot_id=None):
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        updated_state = self._update_current_state(
            {
                "type": "set_trace",
                "subplot_id": resolved_subplot_id,
                "trace_id": str(trace_id),
                "trace": copy.deepcopy(trace),
            }
        )
        self._sync_current_trace_style_state(
            trace_id,
            subplot_id=resolved_subplot_id,
        )
        return updated_state

    def remove_trace(self, trace_id, *, subplot_id=None):
        return self.set_trace(trace_id, None, subplot_id=subplot_id)

    def remove_traces(self, trace_ids, *, subplot_id=None):
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        normalized_ids = {
            str(trace_id)
            for trace_id in tuple(trace_ids or ())
            if str(trace_id or "").strip()
        }
        for trace_id in tuple(self.trace_ids(resolved_subplot_id)):
            if trace_id not in normalized_ids:
                continue
            self.remove_trace(trace_id, subplot_id=resolved_subplot_id)
        return copy.deepcopy(self._current_state)

    def attribute_path_trace(
        self,
        component,
        *,
        subplot_id=None,
        trace_id=None,
        id_suffix="",
        root_names=(),
    ):
        entry = self._find_attribute_path_trace(
            component,
            subplot_id=subplot_id,
            trace_id=trace_id,
            id_suffix=id_suffix,
            root_names=root_names,
        )
        return copy.deepcopy(entry)

    def set_attribute_path_lines(
        self,
        display_name=None,
        *,
        components=(),
        root_name=None,
        x_name=None,
        subplot_id=None,
        owner_root_names=(),
    ):
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        normalized_display_name = self._normalize_optional_text(display_name)
        normalized_root_name = (
            self._normalize_optional_text(root_name) or normalized_display_name
        )
        normalized_owner_roots = self._normalized_root_names(
            owner_root_names,
            normalized_display_name,
            normalized_root_name,
        )
        for component_spec in self._normalized_attribute_path_components(components):
            current_entry = self._find_attribute_path_trace(
                component_spec["path"],
                subplot_id=resolved_subplot_id,
                id_suffix=component_spec["id_suffix"],
                root_names=normalized_owner_roots,
            )
            if not component_spec["visible"] or normalized_display_name is None:
                if current_entry is not None:
                    self.set_trace(
                        current_entry["trace_id"],
                        None,
                        subplot_id=resolved_subplot_id,
                    )
                continue
            desired_trace_id = f"{normalized_display_name}{component_spec['id_suffix']}"
            if (
                current_entry is not None
                and current_entry["trace_id"] != desired_trace_id
            ):
                self.set_trace(
                    current_entry["trace_id"],
                    None,
                    subplot_id=resolved_subplot_id,
                )
            self.set_trace(
                desired_trace_id,
                self._attribute_path_line_trace(
                    trace_id=desired_trace_id,
                    root_name=normalized_root_name,
                    path=component_spec["path"],
                    x_name=x_name,
                    label=component_spec["label"],
                    style=component_spec["style"],
                ),
                subplot_id=resolved_subplot_id,
            )
        return copy.deepcopy(self._current_state)

    def _update_current_state(self, action):
        self._current_state = FigureIRCodec.update_state(self._current_state, action)
        return copy.deepcopy(self._current_state)

    def _dispatch_state(self, state, trace_style_states):
        dispatch_state = copy.deepcopy(state)
        for (subplot_id, trace_id), style in trace_style_states.items():
            dispatch_state = FigureIRCodec.update_state(
                dispatch_state,
                {
                    "type": "set_trace_style",
                    "subplot_id": subplot_id,
                    "trace_id": trace_id,
                    "style": copy.deepcopy(style),
                    "replace": True,
                },
            )
        return dispatch_state

    def _subplot(self, subplot_id=None):
        resolved_id = self._resolve_subplot_id(subplot_id)
        for subplot in self._current_state["layout"]["subplots"]:
            if subplot["id"] == resolved_id:
                return subplot
        raise ValueError(f"Unknown figure subplot id: {resolved_id!r}.")

    def _effective_state(self):
        return figure_ir_with_defaults(self._current_state, self._figure_defaults)

    def _effective_subplot(self, subplot_id=None):
        resolved_id = self._resolve_subplot_id(subplot_id)
        for subplot in self._effective_state()["layout"]["subplots"]:
            if subplot["id"] == resolved_id:
                return subplot
        raise ValueError(f"Unknown figure subplot id: {resolved_id!r}.")

    def _axis_state(self, axis, subplot_id=None):
        return self._subplot(subplot_id)["axes"][self._normalize_axis_name(axis)]

    def _effective_axis_state(self, axis, subplot_id=None):
        return self._effective_subplot(subplot_id)["axes"][self._normalize_axis_name(axis)]

    def _effective_axis_side_state(self, side, subplot_id=None):
        return self._effective_subplot(subplot_id)["axis_sides"][
            self._normalize_side_name(side)
        ]

    def _trace(self, trace_id, subplot_id=None):
        for trace in self._subplot(subplot_id)["traces"]:
            if trace["id"] == str(trace_id):
                return trace
        raise ValueError(f"Unknown figure trace id: {trace_id!r}.")

    def _trace_from_state(self, state, trace_id, *, subplot_id=None):
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        for subplot in state["layout"]["subplots"]:
            if subplot["id"] != resolved_subplot_id:
                continue
            for trace in subplot.get("traces", []):
                if trace["id"] == str(trace_id):
                    return copy.deepcopy(trace)
            return None
        return None

    def _trace_style_key(self, trace_id, subplot_id=None):
        return (self._resolve_subplot_id(subplot_id), str(trace_id))

    def _sync_current_trace_style_state(self, trace_id, *, subplot_id=None):
        trace_key = self._trace_style_key(trace_id, subplot_id)
        self._current_trace_style_states.pop(trace_key, None)
        for index, record in enumerate(supported_trace_records_from_figure_ir(self._current_state)):
            if record["subplot_id"] != trace_key[0]:
                continue
            if record["trace_id"] != trace_key[1]:
                continue
            default_trace = self._trace_style_defaults.get(record["subplot_id"], {}).get(
                record["trace_id"]
            )
            live_style = self._trace_styles.get(record["subplot_id"], {}).get(
                record["trace_id"]
            )
            self._current_trace_style_states[trace_key] = supported_trace_style_state(
                record["trace"],
                index=index,
                default_trace=default_trace,
                live_style=live_style,
            )
            return self._current_trace_style_states[trace_key]
        return None

    def _find_attribute_path_trace(
        self,
        component,
        *,
        subplot_id=None,
        trace_id=None,
        id_suffix="",
        root_names=(),
    ):
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        normalized_path = self._normalize_attribute_path(component)
        normalized_suffix = str(id_suffix or "")
        normalized_roots = self._normalized_root_names(root_names)
        subplot = self._subplot(resolved_subplot_id)

        def matches(candidate_trace_id):
            candidate_trace = None
            for trace in subplot["traces"]:
                if trace["id"] == str(candidate_trace_id):
                    candidate_trace = trace
                    break
            if not isinstance(candidate_trace, dict):
                return None
            y_source = dict(candidate_trace.get("y_source") or {})
            if y_source.get("kind") != "attribute_path":
                return None
            path = tuple(str(value) for value in y_source.get("path", ()))
            if path != normalized_path:
                return None
            root = dict(y_source.get("root") or {})
            if root.get("kind") != "name":
                return None
            display_name = self._attribute_path_display_name(
                candidate_trace_id,
                normalized_suffix,
            )
            if display_name is None:
                return None
            root_name = self._normalize_optional_text(root.get("value"))
            if (
                normalized_roots
                and root_name not in normalized_roots
                and display_name not in normalized_roots
            ):
                return None
            return {
                "trace_id": str(candidate_trace_id),
                "trace": copy.deepcopy(candidate_trace),
                "display_name": display_name,
                "root_name": root_name,
            }

        if trace_id:
            matched = matches(trace_id)
            if matched is not None:
                return matched
        for trace in subplot["traces"]:
            matched = matches(trace["id"])
            if matched is not None:
                return matched
        return None

    def _normalized_attribute_path_components(self, components):
        normalized = []
        for component in tuple(components or ()):
            component_state = dict(component or {})
            normalized.append(
                {
                    "path": self._normalize_attribute_path(
                        component_state.get("path", component_state.get("component"))
                    ),
                    "visible": bool(component_state.get("visible", True)),
                    "id_suffix": str(component_state.get("id_suffix") or ""),
                    "label": component_state.get("label"),
                    "style": copy.deepcopy(component_state.get("style") or {}),
                }
            )
        return normalized

    def _normalize_attribute_path(self, component):
        if isinstance(component, (tuple, list)):
            path = tuple(
                str(value) for value in component if str(value or "").strip()
            )
        else:
            normalized = self._normalize_optional_text(component)
            path = () if normalized is None else (normalized,)
        if not path:
            raise ValueError("Attribute-path trace component path cannot be empty.")
        return path

    def _attribute_path_display_name(self, trace_id, id_suffix):
        normalized_trace_id = self._normalize_optional_text(trace_id)
        if normalized_trace_id is None:
            return None
        normalized_suffix = str(id_suffix or "")
        if normalized_suffix:
            if not normalized_trace_id.endswith(normalized_suffix):
                return None
            display_name = normalized_trace_id[: -len(normalized_suffix)]
            return display_name or None
        return normalized_trace_id

    def _normalized_root_names(self, root_names, *extra_root_names):
        normalized = set()
        for root_name in tuple(root_names or ()) + tuple(extra_root_names):
            normalized_root = self._normalize_optional_text(root_name)
            if normalized_root is not None:
                normalized.add(normalized_root)
        return normalized

    def _normalize_optional_text(self, value):
        text = str(value or "").strip()
        return text or None

    def _attribute_path_line_trace(
        self,
        *,
        trace_id,
        root_name,
        path,
        x_name,
        label,
        style,
    ):
        trace_kwargs = dict(style or {})
        normalized_label = self._normalize_optional_text(label)
        if normalized_label is not None:
            trace_kwargs["label"] = normalized_label
        normalized_x_name = self._normalize_optional_text(x_name)
        return {
            "id": str(trace_id),
            "kind": "line",
            "x_source": (
                None
                if normalized_x_name is None
                else {"kind": "name", "value": normalized_x_name}
            ),
            "y_source": {
                "kind": "attribute_path",
                "root": {"kind": "name", "value": str(root_name)},
                "path": [str(value) for value in path],
            },
            "kwargs": trace_kwargs,
        }

    def _initial_trace_style_states(self, state):
        trace_style_states = {}
        for index, record in enumerate(supported_trace_records_from_figure_ir(state)):
            trace_key = (record["subplot_id"], record["trace_id"])
            default_trace = self._trace_style_defaults.get(record["subplot_id"], {}).get(
                record["trace_id"]
            )
            live_style = self._trace_styles.get(record["subplot_id"], {}).get(
                record["trace_id"]
            )
            trace_style_states[trace_key] = supported_trace_style_state(
                record["trace"],
                index=index,
                default_trace=default_trace,
                live_style=live_style,
            )
        return trace_style_states

    def _update_trace_style_state(
        self,
        trace_id,
        *,
        subplot_id=None,
        style=None,
        replace=False,
    ):
        trace_key = self._trace_style_key(trace_id, subplot_id)
        current_style = self._current_trace_style_states.get(trace_key)
        if current_style is None:
            return None
        if replace:
            replacement = dict(
                self._opening_trace_style_states.get(trace_key, current_style)
            )
            apply_trace_style_values(replacement, dict(style or {}))
            self._current_trace_style_states[trace_key] = replacement
            return replacement
        apply_trace_style_values(current_style, dict(style or {}))
        return current_style

    def _resolve_subplot_id(self, subplot_id):
        if subplot_id not in (None, ""):
            return str(subplot_id)
        subplot_ids = self.subplot_ids()
        if not subplot_ids:
            raise ValueError("Figure edit session does not contain any subplots.")
        return subplot_ids[0]

    def _normalize_axis_name(self, axis):
        axis_name = str(axis or "")
        if axis_name not in {"x", "y"}:
            raise ValueError("Figure edit session axis must be 'x' or 'y'.")
        return axis_name

    def _normalize_side_name(self, side):
        side_name = str(side or "")
        if side_name not in {"bottom", "top", "left", "right"}:
            raise ValueError(f"Unsupported axis side: {side_name!r}.")
        return side_name

    def _value_from_path(self, value, path, *, default=None):
        if not path:
            return copy.deepcopy(value)
        current = value
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return copy.deepcopy(default)
            current = current[key]
        return current
