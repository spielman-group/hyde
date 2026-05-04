import copy
import os
import uuid

from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui

from hyde.features.hyde_features import TableCodec
from hyde.user_interface.base import HydeGuiState, MutationState
from hyde.user_interface.save_window_dialog import SaveWindowDialog
from hyde.user_interface.window_macro_store import (
    MacroStoreError,
    inspect_macro_conflict,
    write_macro_source,
)


class TableState(HydeGuiState):
    codec = TableCodec

    def configure_defaults(self):
        self.set_command("open")

    def _temporary_state(self, command=None, **settings):
        state = copy.deepcopy(self.normalized_state())
        if command is not None:
            state["settings"]["command"] = command
        state["settings"].update(settings)
        return state

    def set_command(self, command):
        self.apply_action({"type": "set_command", "command": command})

    def set_items(self, names):
        self.apply_action({"type": "replace_items", "items": list(names)})

    def set_title(self, title):
        if title:
            self.apply_action(
                {"type": "set", "path": ("settings", "title"), "value": title}
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "title")})

    def set_target(self, target):
        if target:
            self.apply_action(
                {"type": "set", "path": ("settings", "target"), "value": target}
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "target")})

    def set_geometry(self, geometry):
        if geometry:
            self.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "geometry"),
                    "value": list(geometry),
                }
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "geometry")})

    def set_column_widths(self, column_widths):
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "column_widths"),
                "value": dict(column_widths or {}),
            }
        )

    def set_column_width(self, name, width):
        self.apply_action({"type": "set_column_width", "name": name, "width": width})

    def set_request_id(self, request_id):
        if request_id:
            self.apply_action(
                {"type": "set", "path": ("settings", "request_id"), "value": request_id}
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "request_id")})

    def source_for_command(self, command, **settings):
        return self.codec.state_to_python(
            self._temporary_state(command=command, **settings)
        )

    def default_macro_name(self):
        settings = self.normalized_state()["settings"]
        return settings["title"] or settings["target"] or "Table"


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
        return len(self.names) + 2

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
            return (
                base | QtCore.Qt.ItemIsEditable
                if row == 0
                else QtCore.Qt.NoItemFlags
            )

        vals = self._column_values(col)
        return (
            base | QtCore.Qt.ItemIsEditable
            if row <= len(vals)
            else QtCore.Qt.NoItemFlags
        )


class TableWidget(QtWidgets.QWidget):
    def __init__(
        self,
        handle,
        names,
        services=None,
        visible_title=None,
        geometry=None,
        column_widths=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.handle = handle
        self.names = list(names)
        self.services = dict(services or {})
        self.table_state = TableState()
        self.table_state.set_items(self.names)
        self.table_state.set_title(visible_title or handle)
        self.table_state.set_geometry(geometry)
        self.table_state.set_column_widths(column_widths or {})
        self.mutation_state = MutationState()
        self._current_request_id = None
        self._refresh_in_flight = False
        self._selected_cell = None
        self._value_edit_dirty = False
        self._initial_size_applied = False
        self._closed = False
        self._restore_layout_requested = bool(geometry or column_widths)
        self._subwindow = None
        self._tracked_namespace_state = self._current_tracked_namespace_state()

        loader = UiLoader()
        ui_path = os.path.join(
            os.path.dirname(__file__),
            "plugins",
            "table",
            "table.ui",
        )
        self.ui = loader.load(ui_path, self)

        self.model = TableViewModel(self.names)
        self.ui.tableView.setModel(self.model)
        self.ui.tableView.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.ui.tableView.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.tableView.viewport().installEventFilter(self)
        self.ui.valueEdit.installEventFilter(self)
        self.ui.tableView.horizontalHeader().sectionResized.connect(
            self._on_section_resized
        )

        self.ui.tableView.selectionModel().currentChanged.connect(
            self._on_selection_changed
        )
        self.ui.tableView.customContextMenuRequested.connect(self._show_context_menu)
        self.ui.valueEdit.textEdited.connect(self._on_value_text_edited)

        connect_namespace_view_updated = self.services.get(
            "connect_namespace_view_updated"
        )
        if connect_namespace_view_updated is not None:
            connect_namespace_view_updated(self._on_namespace_view_updated)

        QtCore.QTimer.singleShot(0, self.refresh_data)

    def append_columns(self, names, refresh=True):
        for name in names:
            if name not in self.names:
                self.names.append(name)
        self.model.names = self.names
        self.table_state.set_items(self.names)
        if refresh:
            self.refresh_data()

    def bind_subwindow(self, subwindow):
        self._subwindow = subwindow
        subwindow.installEventFilter(self)
        geometry = self.table_state.normalized_state()["settings"]["geometry"]
        if geometry is not None:
            subwindow.setGeometry(QtCore.QRect(*geometry))
        self.capture_layout_state()

    def refresh_data(self):
        if self._closed or self._refresh_in_flight:
            return

        self._current_request_id = str(uuid.uuid4())
        self._refresh_in_flight = True
        queue_background_command = self.services.get("queue_background_command")
        if queue_background_command is None:
            return
        code = self.table_state.source_for_command(
            "push_table_data",
            request_id=self._current_request_id,
        )
        queue_background_command(code, silent=True)

    @inmain_decorator()
    def on_data_received(self, data, request_id):
        if request_id != self._current_request_id:
            return

        selected_index = self.ui.tableView.currentIndex()
        selected_row = selected_index.row() if selected_index.isValid() else None
        selected_col = selected_index.column() if selected_index.isValid() else None

        self._refresh_in_flight = False
        self.model.update_data(data)
        self._apply_saved_column_widths()

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
            if self._restore_layout_requested:
                self.capture_layout_state()
            else:
                QtCore.QTimer.singleShot(0, self._fit_subwindow_to_contents)

    def _current_tracked_namespace_state(self):
        get_namespace_view = self.services.get("get_namespace_view")
        if get_namespace_view is None:
            return ()
        return self._tracked_namespace_state_from_view(get_namespace_view())

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
        subwindow = getattr(self, "_subwindow", None)
        ui = getattr(self, "ui", None)
        if watched is subwindow and event.type() in (
            QtCore.QEvent.Move,
            QtCore.QEvent.Resize,
        ):
            self.capture_layout_state()
        if (
            ui is not None
            and watched is ui.tableView.viewport()
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
        elif (
            ui is not None
            and watched is ui.valueEdit
            and event.type() == QtCore.QEvent.KeyPress
        ):
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
        self.capture_layout_state()

    def _apply_saved_column_widths(self):
        widths = self.table_state.normalized_state()["settings"]["column_widths"]
        if not widths:
            return
        for column, name in enumerate(self.names, start=1):
            width = widths.get(name)
            if width is not None:
                self.ui.tableView.setColumnWidth(column, width)

    def _on_section_resized(self, section, old_size, new_size):
        del old_size
        if section <= 0 or section >= self.model.active_column_count():
            return
        name = self.names[section - 1]
        self.table_state.set_column_width(name, new_size)

    def capture_layout_state(self):
        if self._subwindow is not None:
            geometry = self._subwindow.geometry()
            self.table_state.set_geometry(
                [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
            )
        widths = {}
        for column, name in enumerate(self.names, start=1):
            widths[name] = self.ui.tableView.columnWidth(column)
        self.table_state.set_column_widths(widths)

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
            self.mutation_state.set_delete_indices(name, rows)
            command = self.mutation_state.python_source()
            execute_command = self.services.get("execute_command")
            if execute_command is not None:
                execute_command(command, visible=False)
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

        while (
            0 <= next_row < self.model.rowCount()
            and 0 <= next_col < self.model.columnCount()
        ):
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
                get_namespace_view = self.services.get("get_namespace_view")
                if get_namespace_view is not None:
                    namespace_names.update(get_namespace_view().keys())
                new_name = self.mutation_state.set_create_array(
                    val_text, namespace_names
                )
                command = self.mutation_state.python_source()
                pending_new_name = new_name
            else:
                name = self.names[idx.column() - 1]
                column_length = len(self.model.data_cache.get(name, []))
                pending_new_name = None
                if row < column_length:
                    self.mutation_state.set_edit_value(name, row, val_text)
                    command = self.mutation_state.python_source()
                elif row == column_length:
                    self.mutation_state.set_append_value(name, val_text)
                    command = self.mutation_state.python_source()
                else:
                    return False
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", str(exc))
            return False

        execute_command = self.services.get("execute_command")
        if execute_command is not None:
            execute_command(command, visible=False)
            if pending_new_name is not None:
                self.append_columns([pending_new_name], refresh=False)
                self._tracked_namespace_state = self._current_tracked_namespace_state()
        self._value_edit_dirty = False
        return True

    def closeEvent(self, event):
        if self._closed:
            super().closeEvent(event)
            return

        get_shutting_down = self.services.get("get_shutting_down")
        if get_shutting_down is not None and get_shutting_down():
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

        request_save_table_macro = self.services.get("request_save_table_macro")
        if request_save_table_macro is not None:
            self.capture_layout_state()
            if not request_save_table_macro(self.table_state):
                event.ignore()
                return

        self.shutdown_client()
        super().closeEvent(event)

    def shutdown_client(self):
        if self._closed:
            return
        self._closed = True
        try:
            disconnect_namespace_view_updated = self.services.get(
                "disconnect_namespace_view_updated"
            )
            if disconnect_namespace_view_updated is not None:
                disconnect_namespace_view_updated(self._on_namespace_view_updated)
        except Exception:
            pass


def prompt_to_save_table_macro(table_state, parent, procedures_init, reload_procedures):
    while True:
        dialog = SaveWindowDialog(table_state=table_state, parent=parent)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return False
        if dialog.choice == SaveWindowDialog.NO_SAVE:
            return True
        if dialog.choice != SaveWindowDialog.SAVE:
            return False

        macro_name = dialog.macro_name()
        try:
            macro_source = dialog.macro_source()
        except MacroStoreError as exc:
            QtWidgets.QMessageBox.warning(parent, "Invalid Macro Name", str(exc))
            continue

        conflict = inspect_macro_conflict(procedures_init, macro_name)
        if conflict is not None:
            response = QtWidgets.QMessageBox.question(
                parent,
                "Overwrite Recreation Macro",
                f"A function named {macro_name} already exists in procedures/__init__.py.\n\n"
                "Overwrite that function?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if response != QtWidgets.QMessageBox.Yes:
                continue

        write_macro_source(procedures_init, macro_name, macro_source)
        reload_procedures()
        return True
