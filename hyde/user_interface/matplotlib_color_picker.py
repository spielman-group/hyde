import ast

from matplotlib import colors as mcolors
from qtutils.qt import QtCore, QtGui, QtWidgets

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


def _rgba_from_matplotlib_color(value):
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
        rgba = _rgba_from_matplotlib_color(text)
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
    rgba = _rgba_from_matplotlib_color(normalized)
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


def _named_matplotlib_colors():
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

        for name, value in _named_matplotlib_colors():
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
            while left_layout.count():
                item = left_layout.takeAt(0)
                widget = item.widget()
                child_layout = item.layout()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                elif child_layout is not None:
                    child_layout.setParent(None)
            left_layout.addWidget(self._named_colors_label)
            left_layout.addWidget(self._named_colors_list, 1)

        if right_layout is not None:
            right_layout.addWidget(self._html_container)

        if sample_frame is not None:
            sample_frame.setFixedWidth(max(sample_frame.width(), 78))

        if self._html_edit is not None:
            self._html_edit.setMaxLength(256)
            self._html_edit.editingFinished.connect(self._on_html_editing_finished)

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
        dialog = MatplotlibColorDialog(
            self,
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
