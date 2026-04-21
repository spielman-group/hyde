import os
import uuid
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from hyde.features.hyde_features import (
    format_cell_append_command,
    format_cell_edit_command,
    format_delete_indices_command,
    format_new_array_command,
    format_push_table_data_command,
    format_table_macro_source,
    suggest_new_array_name,
)
from hyde.user_interface.window_macro_store import MacroStoreError, validate_macro_name


class TableViewModel(QtCore.QAbstractTableModel):
    """
    Mirror of kernel data for 1D numeric waves.
    Column 0: Point (index)
    Column 1+: Data waves
    """
    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.names = names
        self.data_cache = {name: [] for name in names}
        self.row_count = 0

    def update_data(self, new_data):
        self.beginResetModel()
        self.data_cache.update(new_data)
        longest = max([len(v) for v in self.data_cache.values()] + [0])
        self.row_count = max(longest + 1, 1)
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return self.row_count

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.names) + 2  # +1 for Point column, +1 inactive column

    def active_column_count(self):
        return len(self.names) + 1

    def headerData(self, section, orientation, role):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            if section == 0:
                return "Point"
            if section == self.columnCount() - 1:
                return ""
            return self.names[section - 1]
        return None

    def _column_values(self, col):
        if col <= 0 or col > len(self.names):
            return []
        return self.data_cache.get(self.names[col - 1], [])

    def data(self, index, role):
        if not index.isValid():
            return None
        
        row = index.row()
        col = index.column()

        if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.EditRole:
            if col == 0:
                return str(row) if row < self.row_count - 1 else ""
            if col >= self.active_column_count():
                return ""

            vals = self._column_values(col)
            if row < len(vals):
                return str(vals[row])
            return ""
        
        if role == QtCore.Qt.TextAlignmentRole:
            return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter

        if role == QtCore.Qt.BackgroundRole:
            if 0 < col < self.active_column_count():
                vals = self._column_values(col)
                if row == len(vals):
                    return QtGui.QBrush(QtGui.QColor(210, 210, 210))

        return None

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        
        row = index.row()
        col = index.column()
        base = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

        if col == 0:
            return base

        if col == self.columnCount() - 1:
            return base | QtCore.Qt.ItemIsEditable if row == 0 else QtCore.Qt.NoItemFlags

        vals = self._column_values(col)
        return base | QtCore.Qt.ItemIsEditable if row <= len(vals) else QtCore.Qt.NoItemFlags


class TableWidget(QtWidgets.QWidget):
    def __init__(self, handle, names, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handle = handle
        self.names = list(names)
        self.app = app
        self._default_macro_name = handle
        self._current_request_id = None
        self._refresh_in_flight = False
        self._selected_cell = None
        self._value_edit_dirty = False
        self._initial_size_applied = False
        self._closed = False
        self._tracked_namespace_state = self._current_tracked_namespace_state()

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "table.ui")
        self.ui = loader.load(ui_path, self)

        self.model = TableViewModel(self.names)
        self.ui.tableView.setModel(self.model)
        self.ui.tableView.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.ui.tableView.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.tableView.viewport().installEventFilter(self)
        self.ui.valueEdit.installEventFilter(self)

        self.ui.tableView.selectionModel().currentChanged.connect(self._on_selection_changed)
        self.ui.tableView.customContextMenuRequested.connect(self._show_context_menu)
        self.ui.valueEdit.textEdited.connect(self._on_value_text_edited)

        if self.app and hasattr(self.app, "data_browser"):
            self.app.data_browser.namespace_view_updated.connect(
                self._on_namespace_view_updated
            )
        
        # Initial data fetch
        QtCore.QTimer.singleShot(0, self.refresh_data)

    def append_columns(self, names, refresh=True):
        for name in names:
            if name not in self.names:
                self.names.append(name)
        self.model.names = self.names
        if refresh:
            self.refresh_data()

    def refresh_data(self):
        """Request array data via Hyde's background runtime helper."""
        if self._closed or self._refresh_in_flight:
            return
        
        self._current_request_id = str(uuid.uuid4())
        self._refresh_in_flight = True
        if self.app:
            code = format_push_table_data_command(self.names, self._current_request_id)
            self.app.queue_background_command(code, silent=True)

    @inmain_decorator()
    def on_data_received(self, data, request_id):
        """Callback from HydeApp relay for structured table-data responses."""
        if request_id != self._current_request_id:
            return

        selected_index = self.ui.tableView.currentIndex()
        selected_row = selected_index.row() if selected_index.isValid() else None
        selected_col = selected_index.column() if selected_index.isValid() else None

        self._refresh_in_flight = False
        self.model.update_data(data)

        if (
            selected_row is not None
            and selected_col is not None
            and selected_row < self.model.rowCount()
            and selected_col < self.model.columnCount()
        ):
            restored_index = self.model.index(selected_row, selected_col)
            self.ui.tableView.setCurrentIndex(restored_index)

        self._update_selection_info()
        if not self._initial_size_applied:
            self._initial_size_applied = True
            QtCore.QTimer.singleShot(0, self._fit_subwindow_to_contents)

    def _current_tracked_namespace_state(self):
        if not self.app or not hasattr(self.app, "data_browser"):
            return ()
        return self._tracked_namespace_state_from_view(
            self.app.data_browser.namespace_view()
        )

    def _tracked_namespace_state_from_view(self, view):
        tracked = []
        for name in self.names:
            metadata = dict(view.get(name, {}) or {})
            tracked.append((name, tuple(sorted(metadata.items()))))
        return tuple(tracked)

    @inmain_decorator()
    def _on_namespace_view_updated(self, view):
        if self._closed:
            return
        new_state = self._tracked_namespace_state_from_view(view or {})
        if new_state == self._tracked_namespace_state:
            return
        self._tracked_namespace_state = new_state
        self.refresh_data()

    def _activate_value_editor(self):
        if self.ui.valueEdit.isReadOnly():
            return
        self.ui.valueEdit.setFocus(QtCore.Qt.OtherFocusReason)
        self.ui.valueEdit.selectAll()

    def _on_selection_changed(self, *args):
        self._update_selection_info()

    def _show_context_menu(self, position):
        index = self.ui.tableView.indexAt(position)
        if index.isValid():
            selection_model = self.ui.tableView.selectionModel()
            if not selection_model.isSelected(index):
                self.ui.tableView.setCurrentIndex(index)
                selection_model.select(
                    index,
                    QtCore.QItemSelectionModel.ClearAndSelect,
                )

        rows_by_name = self._selected_data_rows_by_name()

        menu = QtWidgets.QMenu(self)
        delete_action = menu.addAction("Delete Selected Data")
        delete_action.setEnabled(bool(rows_by_name))

        chosen = menu.exec_(self.ui.tableView.viewport().mapToGlobal(position))
        if chosen == delete_action:
            self._delete_selected_data(rows_by_name)

    def _schedule_value_editor_activation(self, index):
        if not (self.model.flags(index) & QtCore.Qt.ItemIsEditable):
            return
        QtCore.QTimer.singleShot(0, self._activate_value_editor)

    def eventFilter(self, watched, event):
        if (
            watched is self.ui.tableView.viewport()
            and event.type() == QtCore.QEvent.MouseButtonRelease
            and event.button() == QtCore.Qt.LeftButton
        ):
            index = self.ui.tableView.indexAt(event.pos())
            if index.isValid():
                if event.modifiers() == QtCore.Qt.NoModifier:
                    self.ui.tableView.setCurrentIndex(index)
                    self._update_selection_info()
                    self._schedule_value_editor_activation(index)
                else:
                    QtCore.QTimer.singleShot(0, self._update_selection_info)
        elif watched is self.ui.valueEdit and event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self._submit_and_move_selection(row_step=1, col_step=0)
                return True
            if event.key() == QtCore.Qt.Key_Tab:
                self._submit_and_move_selection(row_step=0, col_step=1)
                return True
            if event.key() == QtCore.Qt.Key_Backtab:
                self._submit_and_move_selection(row_step=0, col_step=-1)
                return True
        return super().eventFilter(watched, event)

    def _fit_subwindow_to_contents(self):
        subwindow = self.parentWidget()
        if not isinstance(subwindow, QtWidgets.QMdiSubWindow):
            return

        table_view = self.ui.tableView
        table_view.resizeColumnsToContents()
        table_view.resizeRowsToContents()

        frame = table_view.frameWidth() * 2
        vertical_header = table_view.verticalHeader()
        horizontal_header = table_view.horizontalHeader()

        width = frame + vertical_header.width()
        for column in range(self.model.columnCount()):
            width += table_view.columnWidth(column)
        if table_view.verticalScrollBar().isVisible():
            width += table_view.verticalScrollBar().sizeHint().width()

        top_bar_width = (
            self.ui.cellInfoLabel.sizeHint().width()
            + self.ui.valueEdit.sizeHint().width()
            + self.ui.gearButton.sizeHint().width()
            + self.layout().contentsMargins().left()
            + self.layout().contentsMargins().right()
            + 32
        )

        height = frame + horizontal_header.height()
        visible_rows = min(max(self.model.rowCount(), 1), 12)
        for row in range(visible_rows):
            height += table_view.rowHeight(row)
        if self.model.rowCount() > visible_rows:
            height += table_view.horizontalScrollBar().sizeHint().height()
        height += self.ui.cellInfoLabel.sizeHint().height() + 48

        target_width = max(width, top_bar_width)
        target_height = height

        mdi_area = subwindow.mdiArea()
        if mdi_area is not None:
            max_size = mdi_area.viewport().size()
            target_width = min(target_width, max_size.width())
            target_height = min(target_height, max_size.height())

        subwindow.resize(target_width, target_height)

    def _on_value_text_edited(self, text):
        del text
        if not self.ui.valueEdit.isReadOnly():
            self._value_edit_dirty = True

    def _update_selection_info(self):
        idx = self.ui.tableView.currentIndex()
        if not idx.isValid():
            self.ui.cellInfoLabel.setText("Selection")
            if not self._value_edit_dirty:
                self.ui.valueEdit.clear()
            self.ui.valueEdit.setReadOnly(True)
            self._selected_cell = None
            return
        
        row = idx.row()
        col = idx.column()
        current_cell = (row, col)
        same_cell = current_cell == self._selected_cell
        if not same_cell:
            self._value_edit_dirty = False
        self._selected_cell = current_cell
        
        if col == 0:
            self.ui.cellInfoLabel.setText(f"Point {row}")
            self.ui.valueEdit.setText(str(row))
            self.ui.valueEdit.setReadOnly(True)
            self._value_edit_dirty = False
        elif col == self.model.columnCount() - 1:
            self.ui.cellInfoLabel.setText("Unused")
            self.ui.valueEdit.setReadOnly(row != 0)
            if not self._value_edit_dirty:
                self.ui.valueEdit.clear()
        else:
            name = self.names[col - 1]
            column_length = len(self.model.data_cache.get(name, []))
            self.ui.cellInfoLabel.setText(f"{name}[{row}]")
            self.ui.valueEdit.setReadOnly(row > column_length)
            if not self._value_edit_dirty:
                val = self.model.data(idx, QtCore.Qt.DisplayRole)
                self.ui.valueEdit.setText(val if val is not None else "")

    def _selected_data_rows_by_name(self):
        selection_model = self.ui.tableView.selectionModel()
        selected = selection_model.selectedIndexes()
        if not selected:
            idx = self.ui.tableView.currentIndex()
            selected = [idx] if idx.isValid() else []

        rows_by_name = {}
        for idx in selected:
            col = idx.column()
            if col <= 0 or col >= self.model.active_column_count():
                continue
            name = self.names[col - 1]
            values = self.model.data_cache.get(name, [])
            if idx.row() >= len(values):
                continue
            rows_by_name.setdefault(name, set()).add(idx.row())
        return rows_by_name

    def _delete_selected_data(self, rows_by_name):
        if not rows_by_name:
            return

        label = ", ".join(
            f"{name}[{', '.join(map(str, sorted(rows)))}]"
            for name, rows in sorted(rows_by_name.items())
        )
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete selected data from the live namespace?\n\n{label}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        for name, rows in sorted(rows_by_name.items()):
            command = format_delete_indices_command(name, rows)
            if self.app:
                self.app.execute_command(command, visible=False)
        self._value_edit_dirty = False

    def _editable_index_at(self, row, col):
        if row < 0 or col < 0:
            return QtCore.QModelIndex()
        if row >= self.model.rowCount() or col >= self.model.columnCount():
            return QtCore.QModelIndex()
        index = self.model.index(row, col)
        if not index.isValid():
            return QtCore.QModelIndex()
        if not (self.model.flags(index) & QtCore.Qt.ItemIsEditable):
            return QtCore.QModelIndex()
        return index

    def _move_current_index(self, row_step, col_step):
        current = self.ui.tableView.currentIndex()
        if not current.isValid():
            return

        if row_step == 0 and col_step == 0:
            return

        row = current.row()
        col = current.column()
        next_row = row + row_step
        next_col = col + col_step

        while 0 <= next_row < self.model.rowCount() and 0 <= next_col < self.model.columnCount():
            next_index = self._editable_index_at(next_row, next_col)
            if next_index.isValid():
                self.ui.tableView.setCurrentIndex(next_index)
                self._update_selection_info()
                self._schedule_value_editor_activation(next_index)
                return
            next_row += row_step
            next_col += col_step

    def _submit_and_move_selection(self, row_step, col_step):
        if self._submit_value_edit():
            self._move_current_index(row_step, col_step)

    def _submit_value_edit(self):
        idx = self.ui.tableView.currentIndex()
        if not idx.isValid() or idx.column() == 0:
            return False
        
        row = idx.row()
        val_text = self.ui.valueEdit.text()

        try:
            if idx.column() == self.model.columnCount() - 1:
                if row != 0:
                    return False
                namespace_names = set(self.names)
                if self.app and hasattr(self.app, "data_browser"):
                    namespace_names.update(self.app.data_browser.namespace_view().keys())
                new_name = suggest_new_array_name(namespace_names, val_text)
                command = format_new_array_command(new_name, val_text)
                pending_new_name = new_name
            else:
                name = self.names[idx.column() - 1]
                column_length = len(self.model.data_cache.get(name, []))
                pending_new_name = None
                if row < column_length:
                    command = format_cell_edit_command(name, row, val_text)
                elif row == column_length:
                    command = format_cell_append_command(name, val_text)
                else:
                    return False
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", str(exc))
            return False
        
        if self.app:
            # Table edits use muted execution policy
            self.app.execute_command(command, visible=False)
            if pending_new_name is not None:
                self.append_columns([pending_new_name], refresh=False)
                self._tracked_namespace_state = self._current_tracked_namespace_state()
        self._value_edit_dirty = False
        return True

    def closeEvent(self, event):
        if self._closed:
            super().closeEvent(event)
            return

        if self.app and getattr(self.app, "shutting_down", False):
            self.shutdown_client()
            super().closeEvent(event)
            return

        if QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier:
            parent = self.parentWidget()
            if parent is not None:
                parent.hide()
            else:
                self.hide()
            event.ignore()
            return

        if self.app and hasattr(self.app, "request_save_table_macro"):
            if not self.app.request_save_table_macro(self):
                event.ignore()
                return

        self.shutdown_client()
        super().closeEvent(event)

    def default_macro_name(self):
        return self._default_macro_name

    def set_default_macro_name(self, name):
        try:
            self._default_macro_name = validate_macro_name(name)
        except MacroStoreError:
            self._default_macro_name = self.handle

    def recreation_function_source(self, macro_name):
        title = macro_name
        return format_table_macro_source(macro_name, self.names, title=title)

    def shutdown_client(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.app and hasattr(self.app, "data_browser"):
                self.app.data_browser.namespace_view_updated.disconnect(
                    self._on_namespace_view_updated
                )
        except Exception:
            pass
