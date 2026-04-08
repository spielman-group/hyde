from __future__ import annotations

import ast
import base64
import html
import re
import sys
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import numpy as np
from qtutils import UiLoader
from qtutils.qt import QtCore, QtGui, QtWidgets


UI_DIR = Path(__file__).resolve().parent / "user_interface"


def load_ui(filename, instance=None):
    return UiLoader().load(str(UI_DIR / filename), instance)


def encode_qbytes(value):
    return base64.b64encode(bytes(value)).decode("ascii")


def decode_qbytes(value):
    if not value:
        return QtCore.QByteArray()
    return QtCore.QByteArray.fromBase64(value.encode("ascii"))


class TerminalWidget(QtWidgets.QWidget):
    command_submitted = QtCore.Signal(str)
    completion_requested = QtCore.Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = load_ui("terminal_panel.ui", self)
        self.output = self.ui.output
        self.input = self.ui.input
        self.history = []
        self.history_index = 0
        self.history_draft = ""
        self._completion_token = ""
        self._completion_cursor = 0
        self.completer = QtWidgets.QCompleter(self)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseSensitive)
        self.completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.completer.activated.connect(self._insert_completion)
        self.input.setCompleter(self.completer)
        self.input.installEventFilter(self)
        self.input.returnPressed.connect(self._submit)
        self.output.setAcceptRichText(True)
        self.output.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.input.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))

    def _submit(self):
        command = self.input.text().strip()
        if not command:
            return
        self._record_history(command)
        self.input.clear()
        self.command_submitted.emit(command)

    def append_command(self, command):
        self._append_html(f"<span style='color:#1f6feb;'>&gt;&gt;&gt; {html.escape(command)}</span>")

    def append_output(self, text):
        if text:
            self._append_html(self._ansi_to_html(text.rstrip("\n")))

    def insert_command(self, command):
        self.input.setText(command)
        self.input.setFocus(QtCore.Qt.OtherFocusReason)

    def set_history(self, history):
        self.history = list(history)
        self.history_index = len(self.history)
        self.history_draft = ""

    def apply_completion(self, token, cursor_pos, matches):
        self._completion_token = token
        self._completion_cursor = cursor_pos
        model = QtCore.QStringListModel(matches, self.completer)
        self.completer.setModel(model)
        if not matches:
            return
        if len(matches) == 1:
            self._insert_completion(matches[0])
            return
        rect = self.input.cursorRect()
        rect.setWidth(self.completer.popup().sizeHintForColumn(0) + 24)
        self.completer.complete(rect)

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Up:
                self._show_previous_history()
                return True
            if event.key() == QtCore.Qt.Key_Down:
                self._show_next_history()
                return True
            if event.key() == QtCore.Qt.Key_Tab:
                self.completion_requested.emit(self.input.text(), self.input.cursorPosition())
                return True
        return super().eventFilter(watched, event)

    def _record_history(self, command):
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        self.history_index = len(self.history)
        self.history_draft = ""

    def _show_previous_history(self):
        if not self.history:
            return
        if self.history_index == len(self.history):
            self.history_draft = self.input.text()
        if self.history_index > 0:
            self.history_index -= 1
        self.input.setText(self.history[self.history_index])

    def _show_next_history(self):
        if not self.history:
            return
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.input.setText(self.history[self.history_index])
            return
        self.history_index = len(self.history)
        self.input.setText(self.history_draft)

    def _insert_completion(self, completion):
        line = self.input.text()
        start = max(self._completion_cursor - len(self._completion_token), 0)
        self.input.setText(line[:start] + completion + line[self._completion_cursor :])
        self.input.setCursorPosition(start + len(completion))

    def _append_html(self, fragment):
        cursor = self.output.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertHtml(f"<div style='white-space: pre-wrap;'>{fragment}</div>")
        cursor.insertBlock()
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def _ansi_to_html(self, text):
        pattern = re.compile(r"\x1b\[([0-9;]*)m")
        html_parts = []
        open_span = False
        position = 0
        style = {"color": None, "font-weight": None}
        colors = {
            30: "#000000",
            31: "#cc0000",
            32: "#238636",
            33: "#9a6700",
            34: "#1f6feb",
            35: "#8250df",
            36: "#0a7ea4",
            37: "#6e7781",
            90: "#6e7781",
            91: "#ff7b72",
            92: "#3fb950",
            93: "#d29922",
            94: "#79c0ff",
            95: "#bc8cff",
            96: "#39c5cf",
            97: "#f0f6fc",
        }
        for match in pattern.finditer(text):
            html_parts.append(html.escape(text[position : match.start()]))
            position = match.end()
            codes = [int(part) for part in match.group(1).split(";") if part] or [0]
            for code in codes:
                if code == 0:
                    style = {"color": None, "font-weight": None}
                elif code == 1:
                    style["font-weight"] = "bold"
                elif code == 39:
                    style["color"] = None
                elif code in colors:
                    style["color"] = colors[code]
            if open_span:
                html_parts.append("</span>")
                open_span = False
            css = "; ".join(
                f"{key}: {value}" for key, value in style.items() if value is not None
            )
            if css:
                html_parts.append(f"<span style='{css}'>")
                open_span = True
        html_parts.append(html.escape(text[position:]))
        if open_span:
            html_parts.append("</span>")
        return "".join(html_parts)


class DataBrowserWidget(QtWidgets.QWidget):
    display_requested = QtCore.Signal(list)
    edit_requested = QtCore.Signal(list)
    table_requested = QtCore.Signal(list)
    append_graph_requested = QtCore.Signal(list)
    append_table_requested = QtCore.Signal(list)
    delete_requested = QtCore.Signal(list)
    where_used_requested = QtCore.Signal(list)
    fit_requested = QtCore.Signal(list)
    copy_path_requested = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = load_ui("data_browser.ui", self)
        self.filter_edit = self.ui.filter_edit
        self.current_folder_edit = self.ui.current_folder_edit
        self.tree = self.ui.tree
        self.summary = self.ui.summary
        self.details_text = self.ui.details_text
        self.waves_checkbox = self.ui.waves_checkbox
        self.variables_checkbox = self.ui.variables_checkbox
        self.strings_checkbox = self.ui.strings_checkbox
        self.info_checkbox = getattr(self.ui, "info_checkbox", None)
        self.plot_checkbox = getattr(self.ui, "plot_checkbox", None)
        self.display_button = self.ui.display_button
        self.edit_button = self.ui.edit_button
        self.append_graph_button = self.ui.append_graph_button
        self.append_table_button = self.ui.append_table_button
        self.delete_button = self.ui.delete_button
        self.where_used_button = getattr(self.ui, "where_used_button", None)
        self.fit_button = getattr(self.ui, "fit_button", None)
        self.entries_by_name = {}

        self.tree.setHeaderLabels(["Name", "Kind", "Type", "Shape", "Preview"])
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.tree.itemSelectionChanged.connect(self._update_summary)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.display_button.clicked.connect(self._emit_display)
        self.edit_button.clicked.connect(self._emit_edit)
        self.append_graph_button.clicked.connect(self._emit_append_graph)
        self.append_table_button.clicked.connect(self._emit_append_table)
        self.delete_button.clicked.connect(self._emit_delete)
        if self.where_used_button is not None:
            self.where_used_button.clicked.connect(self._emit_where_used)
        if self.fit_button is not None:
            self.fit_button.clicked.connect(self._emit_fit)
        self.waves_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        self.variables_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        self.strings_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        if self.info_checkbox is not None:
            self.info_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        if self.plot_checkbox is not None:
            self.plot_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))

    def set_objects(self, entries):
        self.entries_by_name = {entry["name"]: entry for entry in entries}
        self.tree.clear()
        for entry in entries:
            item = QtWidgets.QTreeWidgetItem(
                [
                    entry["name"],
                    entry["kind"],
                    entry["type_name"],
                    "x".join(str(value) for value in entry["shape"]),
                    entry["preview"],
                ]
            )
            item.setData(0, QtCore.Qt.UserRole, entry["name"])
            item.setData(0, QtCore.Qt.UserRole + 1, entry)
            self.tree.addTopLevelItem(item)
        self.current_folder_edit.setText("root:")
        self._apply_filter(self.filter_edit.text())
        self._update_summary()

    def selected_names(self):
        return [item.data(0, QtCore.Qt.UserRole) for item in self.tree.selectedItems()]

    def _apply_filter(self, text):
        text = text.strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            entry = item.data(0, QtCore.Qt.UserRole + 1)
            visible = self._matches_display_filter(entry)
            visible = visible and (
                not text or text in item.text(0).lower() or text in item.text(2).lower()
            )
            item.setHidden(not visible)

    def _update_summary(self):
        names = self.selected_names()
        if not names:
            self.summary.setText("No selection")
            self.details_text.clear()
        elif len(names) == 1:
            self.summary.setText(f"Selected: {names[0]}")
            self.details_text.setPlainText(self._entry_details(self.entries_by_name[names[0]]))
        else:
            self.summary.setText(f"Selected {len(names)} objects: {', '.join(names)}")
            self.details_text.setPlainText(
                "\n\n".join(self._entry_details(self.entries_by_name[name]) for name in names[:4])
            )

    def _emit_display(self):
        self.display_requested.emit(self.selected_names())

    def _emit_edit(self):
        self.edit_requested.emit(self.selected_names())

    def _emit_table(self):
        self.table_requested.emit(self.selected_names())

    def _emit_append_graph(self):
        self.append_graph_requested.emit(self.selected_names())

    def _emit_append_table(self):
        self.append_table_requested.emit(self.selected_names())

    def _emit_delete(self):
        self.delete_requested.emit(self.selected_names())

    def _emit_where_used(self):
        self.where_used_requested.emit(self.selected_names())

    def _emit_fit(self):
        self.fit_requested.emit(self.selected_names())

    def _emit_copy_path(self):
        self.copy_path_requested.emit(self.selected_names())

    def _matches_display_filter(self, entry):
        if entry["kind"] == "numpy":
            return self.waves_checkbox.isChecked()
        if entry["type_name"] == "str":
            return self.strings_checkbox.isChecked()
        if entry["kind"] == "plot":
            return self.plot_checkbox is None or self.plot_checkbox.isChecked()
        if entry["kind"] == "info":
            return self.info_checkbox is None or self.info_checkbox.isChecked()
        return self.variables_checkbox.isChecked()

    def _entry_details(self, entry):
        lines = [
            f"Name: {entry['name']}",
            f"Full Path: root:{entry['name']}",
            f"Kind: {entry['kind']}",
            f"Type: {entry['type_name']}",
        ]
        if entry["shape"]:
            lines.append(f"Shape: {tuple(entry['shape'])}")
        if entry.get("dtype"):
            lines.append(f"DType: {entry['dtype']}")
        lines.append(f"Preview: {entry['preview']}")
        return "\n".join(lines)

    def _show_context_menu(self, position):
        menu = QtWidgets.QMenu(self)
        names = self.selected_names()
        has_selection = bool(names)
        actions = [
            ("Display", self._emit_display),
            ("Edit", self._emit_edit),
            ("Append to Graph", self._emit_append_graph),
            ("Append to Table", self._emit_append_table),
            ("Copy Full Path", self._emit_copy_path),
            ("Delete Object", self._emit_delete),
            ("Show Where Object Is Used...", self._emit_where_used),
        ]
        for label, callback in actions:
            action = menu.addAction(label)
            action.setEnabled(has_selection)
            action.triggered.connect(callback)
        menu.exec(self.tree.viewport().mapToGlobal(position))


class ProcedureBrowserWidget(QtWidgets.QWidget):
    open_requested = QtCore.Signal(str)
    run_requested = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = load_ui("procedure_browser.ui", self)
        self.tree = self.ui.tree
        self.open_button = self.ui.open_button
        self.run_button = self.ui.run_button

        self.tree.setHeaderLabels(["Title", "Kind", "Path"])
        self.tree.itemDoubleClicked.connect(self._open_selected)
        self.open_button.clicked.connect(self._open_selected)
        self.run_button.clicked.connect(self._run_selected)

    def set_entries(self, entries):
        self.tree.clear()
        for entry in entries:
            item = QtWidgets.QTreeWidgetItem([entry.title, entry.kind, entry.path])
            item.setData(0, QtCore.Qt.UserRole, entry)
            self.tree.addTopLevelItem(item)

    def selected_entry(self):
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, QtCore.Qt.UserRole)

    def _open_selected(self, *_args):
        entry = self.selected_entry()
        if entry is not None:
            self.open_requested.emit(entry.path)

    def _run_selected(self):
        entry = self.selected_entry()
        if entry is not None:
            self.run_requested.emit(entry.path, entry.function_name)


class CombinedTableModel(QtCore.QAbstractTableModel):
    value_edited = QtCore.Signal(str, int, int, object, bool)

    def __init__(self, table_snapshot, parent=None):
        super().__init__(parent)
        self._apply_snapshot(table_snapshot)

    def _apply_snapshot(self, table_snapshot):
        self.table_snapshot = table_snapshot
        self.columns = [("Point", None, None)]
        self.data_by_name = {}
        self.object_column_counts = {}
        self.max_data_rows = 0
        for name, values in table_snapshot["data"].items():
            matrix = self._normalize(values)
            self.data_by_name[name] = matrix
            self.max_data_rows = max(self.max_data_rows, len(matrix))
            column_count = len(matrix[0]) if matrix else 1
            self.object_column_counts[name] = column_count
            for column in range(column_count):
                label = name if column_count == 1 else f"{name}[{column}]"
                self.columns.append((label, name, column))
        self.row_total = self.max_data_rows + 1

    def replace_snapshot(self, table_snapshot):
        self.beginResetModel()
        self._apply_snapshot(table_snapshot)
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else self.row_total

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            return self.columns[section][0]
        return str(section)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        if index.column() == 0:
            if role == QtCore.Qt.TextAlignmentRole:
                return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
                return "" if index.row() >= self.max_data_rows else index.row()
            return None
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        if role == QtCore.Qt.TextAlignmentRole:
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if role == QtCore.Qt.BackgroundRole and self._is_append_target(index):
            return QtGui.QBrush(QtGui.QColor("#c8c8c8"))
        if index.row() >= len(matrix) or subcolumn >= len(matrix[index.row()]):
            return "" if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole) else None
        value = matrix[index.row()][subcolumn]
        if role == QtCore.Qt.DisplayRole:
            return self._display_text(value)
        if role == QtCore.Qt.EditRole:
            return value
        return None

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if role != QtCore.Qt.EditRole or not index.isValid() or index.column() == 0:
            return False
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        if self._is_append_target(index):
            if isinstance(value, str):
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass
            self.beginResetModel()
            matrix.append([value])
            self.max_data_rows = max(len(rows) for rows in self.data_by_name.values())
            self.row_total = self.max_data_rows + 1
            self.endResetModel()
            self.value_edited.emit(object_name, index.row(), subcolumn, value, True)
            return True
        if index.row() >= len(matrix) or subcolumn >= len(matrix[index.row()]):
            return False
        if isinstance(value, str):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                pass
        matrix[index.row()][subcolumn] = value
        self.dataChanged.emit(index, index, [role, QtCore.Qt.DisplayRole])
        self.value_edited.emit(object_name, index.row(), subcolumn, value, False)
        return True

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
        if index.column() != 0 and (self._has_value(index) or self._is_append_target(index)):
            flags |= QtCore.Qt.ItemIsEditable
        return flags

    def full_precision_text(self, index):
        if not index.isValid():
            return ""
        if index.column() == 0:
            return ""
        value = self.data(index, QtCore.Qt.EditRole)
        if value in (None, ""):
            return ""
        if isinstance(value, (float, np.floating)):
            return np.format_float_positional(float(value), precision=15, trim="-")
        return repr(value)

    def _normalize(self, values):
        if not values:
            return []
        if isinstance(values[0], list):
            return [list(row) for row in values]
        return [[value] for value in values]

    def _display_text(self, value):
        if isinstance(value, (float, np.floating)):
            return np.format_float_positional(float(value), precision=8, trim="-")
        return repr(value)

    def _has_value(self, index):
        if index.column() == 0:
            return False
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        return index.row() < len(matrix) and subcolumn < len(matrix[index.row()])

    def _is_append_target(self, index):
        if index.column() == 0:
            return False
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        return (
            self.object_column_counts.get(object_name, 1) == 1
            and subcolumn == 0
            and index.row() == len(matrix)
        )


class PanelWindow(QtWidgets.QMdiSubWindow):
    visibility_changed = QtCore.Signal(bool)

    def __init__(self, layout_key, title, widget, parent=None):
        super().__init__(parent)
        self.layout_key = layout_key
        self.setWidget(widget)
        self.setWindowTitle(title)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def show_and_raise(self):
        self.show()
        self.raise_()
        mdi = self.mdiArea()
        if mdi is not None:
            mdi.setActiveSubWindow(self)


class TableWindow(QtWidgets.QMdiSubWindow):
    close_requested = QtCore.Signal(str)

    def __init__(self, table_snapshot, edit_callback, delete_callback, parent=None):
        super().__init__(parent)
        self.table_id = table_snapshot["id"]
        self._allow_close = False
        self.ui = load_ui("table_window.ui")
        self.selection_label = self.ui.selection_label
        self.edit_bar = self.ui.edit_bar
        self.options_button = self.ui.options_button
        self.table = QtWidgets.QTableView(self.ui)
        self.ui.table_frame_layout.addWidget(self.table)
        self.model = CombinedTableModel(table_snapshot, self)
        self.model.value_edited.connect(edit_callback)
        self.delete_callback = delete_callback
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._sync_selection_state)
        self.table.selectionModel().currentChanged.connect(self._sync_current_editor)
        self.table.clicked.connect(self._normalize_current_index)
        self.edit_bar.returnPressed.connect(self._apply_edit_bar)
        self.options_button.clicked.connect(
            lambda: self._show_context_menu(QtCore.QPoint(self.table.width() - 8, 8))
        )
        self.setWidget(self.ui)
        self.apply_snapshot(table_snapshot)

    def apply_snapshot(self, table_snapshot):
        self.table_id = table_snapshot["id"]
        self.setWindowTitle(table_snapshot["title"])
        self.model.replace_snapshot(table_snapshot)
        self._sync_selection_state()
        self._sync_current_editor()

    def _normalize_current_index(self, index):
        if index.column() == 0 and self.model.columnCount() > 1:
            self.table.setCurrentIndex(self.model.index(index.row(), 1))

    def _sync_selection_state(self, *_args):
        selected_rows = self._selected_rows()
        data_columns = max(self.model.columnCount() - 1, 0)
        if selected_rows and data_columns:
            self.selection_label.setText(f"{len(selected_rows)}R X {data_columns}C")
        else:
            self.selection_label.setText("0R X 0C")

    def _sync_current_editor(self, *_args):
        index = self.table.currentIndex()
        if index.column() == 0 and self.model.columnCount() > 1 and index.isValid():
            index = self.model.index(index.row(), 1)
            self.table.setCurrentIndex(index)
        self.edit_bar.setText(self.model.full_precision_text(index))

    def _apply_edit_bar(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return
        self.model.setData(index, self.edit_bar.text(), QtCore.Qt.EditRole)

    def _show_context_menu(self, position):
        menu = QtWidgets.QMenu(self)
        delete_action = menu.addAction("Delete Selected Elements")
        delete_action.setEnabled(bool(self._selected_rows()))
        delete_action.triggered.connect(self._delete_selection)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _delete_selection(self):
        rows = self._selected_rows()
        if not rows:
            return
        for object_name in self._selected_object_names():
            self.delete_callback(object_name, rows)

    def _selected_rows(self):
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _selected_object_names(self):
        names = []
        for index in self.table.selectionModel().selectedIndexes():
            if index.column() == 0:
                continue
            _label, object_name, _subcolumn = self.model.columns[index.column()]
            if object_name not in names:
                names.append(object_name)
        return names

    def close_from_sync(self):
        self._allow_close = True
        self.close()

    def closeEvent(self, event):
        if self._allow_close:
            return super().closeEvent(event)
        self.close_requested.emit(self.table_id)
        event.ignore()


class FigureWindow(QtWidgets.QMdiSubWindow):
    close_requested = QtCore.Signal(str)

    def __init__(self, figure_id, parent=None):
        super().__init__(parent)
        self.figure_id = figure_id
        self._allow_close = False
        self.ui = load_ui("figure_window.ui")
        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ui.figure_layout.addWidget(self.canvas)
        self.setWidget(self.ui)

    def apply_snapshot(self, snapshot):
        self.setWindowTitle(snapshot["title"])
        self.figure.clear()
        grid = self.figure.add_gridspec(1, 1)
        axes = self.figure.add_subplot(grid[0, 0])
        for trace in snapshot["traces"]:
            line, = axes.plot(
                trace["x_data"],
                trace["y_data"],
                label=trace["label"],
                linestyle=trace.get("style", "-"),
                color=trace.get("color") or None,
                marker=trace.get("marker") or None,
                markersize=trace.get("markersize") or None,
                linewidth=trace.get("linewidth") or None,
            )
            line.set_visible(trace.get("visible", True))
        axes_info = snapshot.get("axes", {})
        axes.set_xlabel(axes_info.get("xlabel", "x"))
        axes.set_ylabel(axes_info.get("ylabel", "y"))
        axes.set_title(snapshot["title"])
        if axes_info.get("xscale") and axes_info.get("xscale") != "linear":
            axes.set_xscale(axes_info["xscale"])
        if axes_info.get("yscale") and axes_info.get("yscale") != "linear":
            axes.set_yscale(axes_info["yscale"])
        if axes_info.get("xmin") is not None or axes_info.get("xmax") is not None:
            axes.set_xlim(left=axes_info.get("xmin"), right=axes_info.get("xmax"))
        if axes_info.get("ymin") is not None or axes_info.get("ymax") is not None:
            axes.set_ylim(bottom=axes_info.get("ymin"), top=axes_info.get("ymax"))
        if axes_info.get("xgrid"):
            axes.grid(True, axis="x")
        if axes_info.get("ygrid"):
            axes.grid(True, axis="y")
        if len(snapshot["traces"]) > 1:
            axes.legend()
        self.canvas.draw_idle()

    def close_from_sync(self):
        self._allow_close = True
        self.close()

    def closeEvent(self, event):
        if self._allow_close:
            return super().closeEvent(event)
        self.close_requested.emit(self.figure_id)
        event.ignore()


class FigureEditDialog(QtWidgets.QDialog):
    command_changed = QtCore.Signal(str)

    def __init__(self, figure_id, snapshot, parent=None):
        super().__init__(parent)
        self.ui = load_ui("figure_edit_dialog.ui", self)
        self.figure_id = figure_id
        self.snapshot = snapshot
        self._loading = False
        self.scale_combo = self.ui.scale_combo
        self.grid_checkbox = self.ui.grid_checkbox
        self.axis_combo = self.ui.axis_combo
        self.title_edit = self.ui.title_edit
        self.axis_label_edit = self.ui.axis_label_edit
        self.minimum_edit = self.ui.minimum_edit
        self.maximum_edit = self.ui.maximum_edit
        self.live_update_checkbox = self.ui.live_update_checkbox
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button
        self.scale_combo.addItems(["linear", "log"])
        self.axis_combo.addItems(["bottom", "left"])
        self.title_edit.setText(snapshot["title"])
        self.axis_combo.currentIndexChanged.connect(self._load_axis)
        self.cancel_button.clicked.connect(self.reject)
        self.help_button.clicked.connect(self._show_help)
        for widget, signal_name in (
            (self.axis_combo, "currentIndexChanged"),
            (self.title_edit, "textChanged"),
            (self.axis_label_edit, "textChanged"),
            (self.minimum_edit, "textChanged"),
            (self.maximum_edit, "textChanged"),
            (self.scale_combo, "currentTextChanged"),
            (self.grid_checkbox, "toggled"),
        ):
            getattr(widget, signal_name).connect(self._emit_command)
        self._load_axis()

    def command(self):
        axis = self.axis_combo.currentText()
        axis_label = self.axis_label_edit.text().strip()
        updates = [f"title={self.title_edit.text()!r}"]
        if axis == "bottom":
            updates.extend(
                [
                    f"xlabel={axis_label!r}",
                    f"xscale={self.scale_combo.currentText()!r}",
                    f"xgrid={self.grid_checkbox.isChecked()!r}",
                    f"xmin={self._limit_value(self.minimum_edit.text())!r}",
                    f"xmax={self._limit_value(self.maximum_edit.text())!r}",
                ]
            )
        else:
            updates.extend(
                [
                    f"ylabel={axis_label!r}",
                    f"yscale={self.scale_combo.currentText()!r}",
                    f"ygrid={self.grid_checkbox.isChecked()!r}",
                    f"ymin={self._limit_value(self.minimum_edit.text())!r}",
                    f"ymax={self._limit_value(self.maximum_edit.text())!r}",
                ]
            )
        return f"edit_figure({self.figure_id!r}, {', '.join(updates)})"

    def revert_command(self):
        axes = self.snapshot.get("axes", {})
        return (
            f"edit_figure({self.figure_id!r}, title={self.snapshot['title']!r}, "
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
            self.scale_combo.setCurrentText(axes.get("xscale", "linear"))
            self.grid_checkbox.setChecked(axes.get("xgrid", False))
            self.minimum_edit.setText("" if axes.get("xmin") is None else repr(axes["xmin"]))
            self.maximum_edit.setText("" if axes.get("xmax") is None else repr(axes["xmax"]))
        else:
            self.axis_label_edit.setText(axes.get("ylabel", ""))
            self.scale_combo.setCurrentText(axes.get("yscale", "linear"))
            self.grid_checkbox.setChecked(axes.get("ygrid", False))
            self.minimum_edit.setText("" if axes.get("ymin") is None else repr(axes["ymin"]))
            self.maximum_edit.setText("" if axes.get("ymax") is None else repr(axes["ymax"]))
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
            "Adjust the current axis label, scale, grid, and limits. With Live Update enabled, edits are applied to the active figure immediately.",
        )


class NewGraphDialog(QtWidgets.QDialog):
    def __init__(self, object_names, selected_names=None, parent=None):
        super().__init__(parent)
        self.ui = load_ui("new_graph_dialog.ui", self)
        self.figure_name = f"figure_{QtCore.QUuid.createUuid().toString(QtCore.QUuid.Id128)[:8]}"
        self.y_list = self.ui.y_list
        self.x_list = self.ui.x_list
        self.title_edit = self.ui.title_edit
        self.style_combo = self.ui.style_combo
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button
        self.more_choices_button = self.ui.more_choices_button
        self.swap_axes_checkbox = self.ui.swap_axes_checkbox
        self.y_axis_combo = self.ui.y_axis_combo
        self.x_axis_combo = self.ui.x_axis_combo
        self.y_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.x_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.style_combo.addItems(["_none_", "Lines", "Markers", "Lines+Markers", "Dashed"])
        self.y_axis_combo.addItems(["left"])
        self.x_axis_combo.addItems(["bottom"])
        for name in object_names:
            self.y_list.addItem(name)
            self.x_list.addItem(name)
        selected_names = selected_names or []
        self._select_items(self.y_list, selected_names[:1])
        if len(selected_names) > 1:
            self._select_items(self.x_list, [selected_names[1]])
        self.cancel_button.clicked.connect(self.reject)
        self.help_button.clicked.connect(self._show_help)
        self.more_choices_button.clicked.connect(self._show_help)

    def command(self):
        y_names = self.selected_y_names()
        if not y_names:
            return ""
        x_name = self.selected_x_name()
        if self.swap_axes_checkbox.isChecked():
            x_name, y_names = y_names[0], ([x_name] if x_name else [])
            if not y_names:
                return ""
        title = self.title_edit.text().strip() or None
        first_y = y_names[0]
        kwargs = [f"{first_y!r}"]
        if x_name is not None:
            kwargs.append(f"x={x_name!r}")
        if title is not None:
            kwargs.append(f"title={title!r}")
        kwargs.append(f"figure_name={self.figure_name!r}")
        kwargs.extend(self._style_kwargs())
        commands = [f"display({', '.join(kwargs)})"]
        for index, name in enumerate(y_names[1:], start=1):
            append_args = [repr(name)]
            if x_name is not None:
                append_args.append(f"x={x_name!r}")
            append_args.extend(self._style_kwargs())
            commands.append(f"append_to_graph({self.figure_name!r}, {', '.join(append_args)})")
        return "\n".join(commands)

    def selected_y_names(self):
        return [item.text() for item in self.y_list.selectedItems()]

    def selected_x_name(self):
        items = self.x_list.selectedItems()
        return items[0].text() if items else None

    def _select_items(self, widget, names):
        lookup = set(names)
        for index in range(widget.count()):
            item = widget.item(index)
            item.setSelected(item.text() in lookup)

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "New Graph",
            "Choose one or more Y arrays, optionally choose an X array, then generate or execute the replayable Python command.",
        )

    def _style_kwargs(self):
        style = self.style_combo.currentText()
        if style in {"", "_none_", "Lines"}:
            return []
        if style == "Markers":
            return ["style='None'", "marker='o'", "linewidth=0.0"]
        if style == "Lines+Markers":
            return ["style='-'", "marker='o'"]
        if style == "Dashed":
            return ["style='--'"]
        return []


class TraceEditDialog(QtWidgets.QDialog):
    command_changed = QtCore.Signal(str)

    def __init__(self, figure_id, snapshot, parent=None):
        super().__init__(parent)
        self.ui = load_ui("trace_edit_dialog.ui", self)
        self.figure_id = figure_id
        self.snapshot = snapshot
        self._loading = False
        self.trace_combo = self.ui.trace_combo
        self.trace_filter_edit = self.ui.trace_filter_edit
        self.label_edit = self.ui.label_edit
        self.color_combo = self.ui.color_combo
        self.visible_checkbox = self.ui.visible_checkbox
        self.mode_combo = self.ui.mode_combo
        self.marker_combo = self.ui.marker_combo
        self.marker_size_spin = self.ui.marker_size_spin
        self.line_width_spin = self.ui.line_width_spin
        self.gaps_checkbox = self.ui.gaps_checkbox
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.cancel_button = self.ui.cancel_button
        self.color_combo.addItems(["", "black", "red", "blue", "green", "magenta"])
        self.mode_combo.addItems(["Lines", "Markers", "Lines+Markers"])
        self.marker_combo.addItems(["", "o", "s", "^", "x", "+"])
        self.marker_size_spin.setRange(0.0, 100.0)
        self.line_width_spin.setRange(0.0, 20.0)
        for index, trace in enumerate(snapshot["traces"]):
            self.trace_combo.addItem(f"{index}: {trace['label']}", index)
        self.trace_combo.currentIndexChanged.connect(self._load_selected_trace)
        self.trace_filter_edit.textChanged.connect(self._apply_filter)
        self.cancel_button.clicked.connect(self.reject)
        for widget, signal_name in (
            (self.trace_combo, "currentIndexChanged"),
            (self.label_edit, "textChanged"),
            (self.color_combo, "currentTextChanged"),
            (self.visible_checkbox, "toggled"),
            (self.mode_combo, "currentTextChanged"),
            (self.marker_combo, "currentTextChanged"),
            (self.marker_size_spin, "valueChanged"),
            (self.line_width_spin, "valueChanged"),
            (self.gaps_checkbox, "toggled"),
        ):
            getattr(widget, signal_name).connect(self._emit_command)
        self._load_selected_trace()

    def command(self):
        index = self.trace_combo.currentData()
        if index is None:
            return ""
        mode = self.mode_combo.currentText()
        marker = self.marker_combo.currentText() or None
        style = "None" if mode == "Markers" else "-"
        if mode == "Lines" and not marker:
            marker = None
        linewidth = 0.0 if mode == "Markers" else self.line_width_spin.value()
        return (
            f"edit_trace({self.figure_id!r}, {index!r}, label={self.label_edit.text()!r}, "
            f"style={style!r}, color={self.color_combo.currentText()!r}, "
            f"visible={not self.visible_checkbox.isChecked()!r}, marker={marker!r}, "
            f"markersize={self.marker_size_spin.value()!r}, linewidth={linewidth!r}, "
            f"gaps={self.gaps_checkbox.isChecked()!r})"
        )

    def revert_command(self):
        index = self.trace_combo.currentData()
        trace = self.snapshot["traces"][index]
        return (
            f"edit_trace({self.figure_id!r}, {index!r}, label={trace.get('label', '')!r}, "
            f"style={trace.get('style', '-')!r}, color={trace.get('color', '')!r}, "
            f"visible={trace.get('visible', True)!r}, marker={trace.get('marker')!r}, "
            f"markersize={trace.get('markersize', 6.0)!r}, linewidth={trace.get('linewidth', 1.5)!r}, "
            f"gaps={trace.get('gaps', False)!r})"
        )

    def _load_selected_trace(self):
        index = self.trace_combo.currentData()
        if index is None:
            return
        self._load_trace(self.snapshot["traces"][index])

    def _load_trace(self, trace):
        self._loading = True
        self.label_edit.setText(trace["label"])
        self.color_combo.setCurrentText(trace.get("color", ""))
        self.visible_checkbox.setChecked(not trace.get("visible", True))
        marker = trace.get("marker") or ""
        self.marker_combo.setCurrentText(marker)
        self.marker_size_spin.setValue(float(trace.get("markersize", 6.0)))
        self.line_width_spin.setValue(float(trace.get("linewidth", 1.5)))
        self.gaps_checkbox.setChecked(trace.get("gaps", False))
        style = trace.get("style", "-")
        if style == "None":
            self.mode_combo.setCurrentText("Markers")
        elif marker:
            self.mode_combo.setCurrentText("Lines+Markers")
        else:
            self.mode_combo.setCurrentText("Lines")
        self._loading = False
        self._emit_command()

    def _apply_filter(self, text):
        text = text.strip().lower()
        for index in range(self.trace_combo.count()):
            visible = not text or text in self.trace_combo.itemText(index).lower()
            self.trace_combo.view().setRowHidden(index, not visible)

    def _emit_command(self, *_args):
        if not self._loading:
            self.command_changed.emit(self.command())


class CloseFigureDialog(QtWidgets.QDialog):
    save_selected = QtCore.Signal(str)
    discard_selected = QtCore.Signal()

    def __init__(self, suggested_name, parent=None):
        super().__init__(parent)
        self.ui = load_ui("close_figure_dialog.ui", self)
        self.name_edit = self.ui.name_edit
        self.save_button = self.ui.save_button
        self.no_save_button = self.ui.no_save_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button
        self.name_edit.setText(suggested_name)
        self.save_button.clicked.connect(self._emit_save)
        self.no_save_button.clicked.connect(self._emit_discard)
        self.help_button.clicked.connect(self._show_help)
        self.cancel_button.clicked.connect(self.reject)

    def _emit_save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        self.save_selected.emit(name)
        self.accept()

    def _emit_discard(self):
        self.discard_selected.emit()
        self.accept()

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Close Window",
            "Save stores a replayable Hyde function in procedures/master.py. No Save closes the window without writing a function.",
        )


class SaveGraphicsDialog(QtWidgets.QDialog):
    command_changed = QtCore.Signal(str)

    FORMATS = [
        ("Quartz PDF", "pdf", True),
        ("PNG File", "png", True),
        ("SVG File", "svg", True),
        ("EPS File", "eps", False),
    ]

    def __init__(self, figure_id, default_path, size_inches=(6.4, 4.8), parent=None):
        super().__init__(parent)
        self.ui = load_ui("save_graphics_dialog.ui", self)
        self.figure_id = figure_id
        self._loading = False
        self._previous_suffix = Path(default_path).suffix.lower()
        self.same_size_radio = self.ui.same_size_radio
        self.custom_size_radio = self.ui.custom_size_radio
        self.width_spin = self.ui.width_spin
        self.height_spin = self.ui.height_spin
        self.units_combo = self.ui.units_combo
        self.recommended_formats_checkbox = self.ui.recommended_formats_checkbox
        self.format_list = self.ui.format_list
        self.color_checkbox = self.ui.color_checkbox
        self.path_edit = self.ui.path_edit
        self.browse_button = self.ui.browse_button
        self.overwrite_checkbox = self.ui.overwrite_checkbox
        self.command_preview = self.ui.command_preview
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button
        self.units_combo.addItems(["inches", "cm"])
        self.width_spin.setValue(float(size_inches[0]))
        self.height_spin.setValue(float(size_inches[1]))
        self.path_edit.setText(default_path)
        self.cancel_button.clicked.connect(self.reject)
        self.help_button.clicked.connect(self._show_help)
        self.browse_button.clicked.connect(self._browse_for_path)
        self.same_size_radio.toggled.connect(self._refresh_state)
        self.custom_size_radio.toggled.connect(self._refresh_state)
        self.recommended_formats_checkbox.toggled.connect(self._populate_formats)
        for widget, signal_name in (
            (self.width_spin, "valueChanged"),
            (self.height_spin, "valueChanged"),
            (self.units_combo, "currentTextChanged"),
            (self.color_checkbox, "toggled"),
            (self.path_edit, "textChanged"),
            (self.overwrite_checkbox, "toggled"),
        ):
            getattr(widget, signal_name).connect(self._emit_command)
        self.format_list.currentRowChanged.connect(self._format_changed)
        self._populate_formats()
        self._refresh_state()

    def command(self):
        path = self.path_edit.text().strip()
        if not path:
            return ""
        kwargs = [repr(self.figure_id), repr(path), f"format={self.selected_format()!r}"]
        if self.custom_size_radio.isChecked():
            kwargs.append(f"size={self.selected_size_inches()!r}")
            kwargs.append("units='inches'")
        if not self.color_checkbox.isChecked():
            kwargs.append("color=False")
        if self.overwrite_checkbox.isChecked():
            kwargs.append("overwrite=True")
        return f"save_graphics({', '.join(kwargs)})"

    def selected_format(self):
        item = self.format_list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item is not None else "pdf"

    def selected_size_inches(self):
        width = self.width_spin.value()
        height = self.height_spin.value()
        if self.units_combo.currentText() == "cm":
            return (round(width / 2.54, 6), round(height / 2.54, 6))
        return (width, height)

    def _populate_formats(self):
        current = self.selected_format() if self.format_list.count() else "pdf"
        self._loading = True
        self.format_list.clear()
        for label, extension, recommended in self.FORMATS:
            if self.recommended_formats_checkbox.isChecked() and not recommended:
                continue
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, extension)
            self.format_list.addItem(item)
            if extension == current:
                self.format_list.setCurrentItem(item)
        if self.format_list.currentRow() < 0 and self.format_list.count():
            self.format_list.setCurrentRow(0)
        self._loading = False
        self._format_changed()

    def _refresh_state(self):
        custom = self.custom_size_radio.isChecked()
        self.width_spin.setEnabled(custom)
        self.height_spin.setEnabled(custom)
        self.units_combo.setEnabled(custom)
        self._emit_command()

    def _format_changed(self, *_args):
        if self._loading:
            return
        path = self.path_edit.text().strip()
        if path:
            new_suffix = f".{self.selected_format()}"
            current = Path(path)
            if current.suffix.lower() == self._previous_suffix or not current.suffix:
                current = current.with_suffix(new_suffix)
                self.path_edit.setText(str(current))
            self._previous_suffix = new_suffix
        self._emit_command()

    def _browse_for_path(self):
        selected_format = self.selected_format()
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Graphics File",
            self.path_edit.text().strip(),
            f"{selected_format.upper()} Files (*.{selected_format});;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _emit_command(self, *_args):
        command = self.command()
        self.command_preview.setPlainText(command)
        self.command_changed.emit(command)

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Save Graphics",
            "Choose an output path and format, then save the active figure as a replayable Hyde command.",
        )


class FitDialog(QtWidgets.QDialog):
    def __init__(self, fit_entries, selected_names, project_path, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.ui = load_ui("fit_dialog.ui", self)
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
            name = self.coefficients_table.item(row, 0).text()
            initial = float(self.coefficients_table.item(row, 1).text())
            hold = self.coefficients_table.item(row, 2).checkState() == QtCore.Qt.Checked
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


class HydeMainWindow(QtWidgets.QMainWindow):
    PANEL_KEYS = ("command", "data_browser", "script_browser")

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.ui = load_ui("main.ui", self)
        self.mdi = self.ui.mdiArea
        self.mdi.setOption(QtWidgets.QMdiArea.DontMaximizeSubWindowOnActivation, True)
        self.mdi.setViewMode(QtWidgets.QMdiArea.SubWindowView)
        self.figure_windows = {}
        self.table_windows = {}
        self.panel_windows = {}
        self._saved_subwindow_layouts = {}

        self.terminal = TerminalWidget()
        self.terminal.command_submitted.connect(self.app.execute_command)
        self.terminal.completion_requested.connect(self.app.request_terminal_completion)
        self.data_browser = DataBrowserWidget()
        self.data_browser.display_requested.connect(self.app.display_selection)
        self.data_browser.edit_requested.connect(self.app.table_selection)
        self.data_browser.table_requested.connect(self.app.table_selection)
        self.data_browser.append_graph_requested.connect(self.app.append_to_graph_selection)
        self.data_browser.append_table_requested.connect(self.app.append_to_table_selection)
        self.data_browser.delete_requested.connect(self.app.delete_selection)
        self.data_browser.where_used_requested.connect(self.app.where_used_selection)
        self.data_browser.fit_requested.connect(self.app.fit_selection)
        self.data_browser.copy_path_requested.connect(self.app.copy_object_paths)
        self.procedure_browser = ProcedureBrowserWidget()
        self.procedure_browser.open_requested.connect(self.app.open_external_editor)
        self.procedure_browser.run_requested.connect(self.app.run_script_entry)

        self._create_panel_windows()
        self._connect_actions()

    def _create_panel_windows(self):
        self.command_window = self._add_panel_window("command", "Command window", self.terminal)
        self.data_window = self._add_panel_window("data_browser", "Data Browser", self.data_browser)
        self.script_window = self._add_panel_window("script_browser", "Script browser", self.procedure_browser)

        self.command_window.setGeometry(20, 560, 1080, 260)
        self.data_window.setGeometry(20, 20, 420, 500)
        self.script_window.setGeometry(460, 20, 420, 500)

        self.command_window.show()
        self.data_window.show()
        self.script_window.show()

    def _add_panel_window(self, key, title, widget):
        window = PanelWindow(key, title, widget, self)
        self.panel_windows[key] = window
        self.mdi.addSubWindow(window)
        return window

    def _connect_actions(self):
        self.actionNewProject.triggered.connect(self.app.new_project)
        self.actionOpenProject.triggered.connect(self.app.open_project)
        self.actionSaveProject.triggered.connect(self.app.save_project)
        self.actionSaveProjectAs.triggered.connect(self.app.save_project_as)
        self.actionSaveGraphics.triggered.connect(self.app.save_graphics)
        self.actionExportArchive.triggered.connect(self.app.export_archive)
        self.actionQuit.triggered.connect(self.close)
        self.actionEditAxes.triggered.connect(self.app.edit_active_figure)
        self.actionEditTraces.triggered.connect(self.app.edit_active_trace)
        self.actionCurveFit.triggered.connect(self.app.open_fit_dialog)
        self.actionNewGraph.triggered.connect(self.app.new_graph)
        self.actionNewTable.triggered.connect(self.app.new_table)
        self.actionNewPythonScript.triggered.connect(self.app.new_python_script)

        command_shortcut = "Meta+J" if sys.platform == "darwin" else "Ctrl+J"
        self.actionCommandWindow.setShortcut(QtGui.QKeySequence(command_shortcut))
        self.actionCommandWindow.setShortcutContext(QtCore.Qt.ApplicationShortcut)

        self._bind_window_actions(self.command_window, self.actionCommandWindow)
        self._bind_window_actions(
            self.data_window,
            self.actionDataBrowser,
        )
        self._bind_window_actions(self.script_window, self.actionScriptBrowser)

        self.scripts_menu = self.menuScripts
        self.graph_macros_menu = self.menuGraphMacros
        self.table_macros_menu = self.menuTableMacros

    def _bind_window_actions(self, window, *actions):
        def set_visible(checked):
            if checked:
                window.show_and_raise()
            else:
                window.close()

        def sync(visible):
            for action in actions:
                was_blocked = action.blockSignals(True)
                action.setChecked(visible)
                action.blockSignals(was_blocked)

        for action in actions:
            action.setCheckable(True)
            action.toggled.connect(set_visible)
        window.visibility_changed.connect(sync)
        sync(window.isVisible())

    def apply_snapshot(self, snapshot, script_entries):
        self.data_browser.set_objects(snapshot.get("namespace_summary", []))
        self.procedure_browser.set_entries(script_entries)
        self._rebuild_scripts_menu(script_entries)
        self._sync_figures(snapshot.get("figures", []))
        self._sync_tables(snapshot.get("tables", []))

    def closeEvent(self, event):
        if self.app.shutdown_requested():
            return super().closeEvent(event)
        event.ignore()

    def _rebuild_scripts_menu(self, entries):
        self.scripts_menu.clear()
        self.graph_macros_menu.clear()
        self.table_macros_menu.clear()
        for entry in entries:
            if entry.kind == "figure":
                menu = self.graph_macros_menu
            elif entry.kind == "table":
                menu = self.table_macros_menu
            else:
                menu = self.scripts_menu
            action = menu.addAction(entry.title)
            action.triggered.connect(
                lambda checked=False, e=entry: self.app.run_script_entry(e.path, e.function_name)
            )

    def _sync_figures(self, figures):
        active_ids = set()
        for figure in figures:
            figure_id = figure["id"]
            active_ids.add(figure_id)
            if figure_id not in self.figure_windows:
                window = FigureWindow(figure_id)
                window.close_requested.connect(self.app.close_figure_requested)
                self.figure_windows[figure_id] = window
                self.mdi.addSubWindow(window)
                self._restore_subwindow_geometry(f"figure:{figure_id}", window)
                window.show()
            self.figure_windows[figure_id].apply_snapshot(figure)
        for figure_id in list(self.figure_windows):
            if figure_id not in active_ids:
                window = self.figure_windows.pop(figure_id)
                window.close_from_sync()

    def _sync_tables(self, tables):
        active_ids = set()
        for table in tables:
            table_id = table["id"]
            active_ids.add(table_id)
            if table_id not in self.table_windows:
                window = TableWindow(
                    table,
                    self.app.edit_table_value,
                    self.app.delete_table_values,
                )
                window.close_requested.connect(self.app.close_table_requested)
                self.table_windows[table_id] = window
                self.mdi.addSubWindow(window)
                self._restore_subwindow_geometry(f"table:{table_id}", window)
                window.show()
            self.table_windows[table_id].apply_snapshot(table)
        for table_id in list(self.table_windows):
            if table_id not in active_ids:
                window = self.table_windows.pop(table_id)
                window.close_from_sync()

    def current_figure_id(self):
        active = self.mdi.activeSubWindow()
        if isinstance(active, FigureWindow):
            return active.figure_id
        return None

    def current_figure_size_inches(self):
        active = self.mdi.activeSubWindow()
        if isinstance(active, FigureWindow):
            width, height = active.figure.get_size_inches()
            return (float(width), float(height))
        return None

    def current_table_id(self):
        active = self.mdi.activeSubWindow()
        if isinstance(active, TableWindow):
            return active.table_id
        return None

    def save_window_layout(self):
        subwindows = {
            f"panel:{key}": self._serialize_subwindow(window)
            for key, window in self.panel_windows.items()
        }
        subwindows.update(
            {
                f"figure:{figure_id}": self._serialize_subwindow(window)
                for figure_id, window in self.figure_windows.items()
            }
        )
        subwindows.update(
            {
                f"table:{table_id}": self._serialize_subwindow(window)
                for table_id, window in self.table_windows.items()
            }
        )
        return {
            "geometry": encode_qbytes(self.saveGeometry()),
            "subwindows": subwindows,
        }

    def restore_window_layout(self, layout):
        geometry = decode_qbytes(layout.get("geometry", ""))
        if not geometry.isEmpty():
            self.restoreGeometry(geometry)
        self._saved_subwindow_layouts = dict(layout.get("subwindows", {}))
        for key, window in self.panel_windows.items():
            self._restore_subwindow_geometry(f"panel:{key}", window)

    def _serialize_subwindow(self, window):
        return {
            "geometry": encode_qbytes(window.saveGeometry()),
            "visible": window.isVisible(),
        }

    def _restore_subwindow_geometry(self, key, window):
        layout = self._saved_subwindow_layouts.get(key)
        if not layout:
            return
        geometry = decode_qbytes(layout.get("geometry", ""))
        if not geometry.isEmpty():
            window.restoreGeometry(geometry)
        if not layout.get("visible", True):
            window.hide()
