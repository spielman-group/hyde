import logging
import os
import uuid

from qtutils import inmain_decorator
from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.hyde_ir import TableIR, TableIRDiff
from hyde.user_interface.base_hyde_widgets import HydeInteractiveWidget


LOGGER = logging.getLogger("hyde")


class TableViewModel(QtCore.QAbstractTableModel):
    """
    Mirror of kernel data for 1D numeric arrays.
    Column 0: Point (index)
    Column 1+: Data arrays
    """

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.names = names
        self.data_cache = {name: [] for name in names}
        self.row_count = 0

    def set_names(self, names):
        self.beginResetModel()
        self.names = list(names)
        self.data_cache = {
            name: self.data_cache.get(name, [])
            for name in self.names
        }
        longest = max([len(v) for v in self.data_cache.values()] + [0])
        self.row_count = max(longest + 1, 1)
        self.endResetModel()

    def update_data(self, new_data):
        self.beginResetModel()
        incoming = dict(new_data or {})
        self.data_cache = {
            name: incoming.get(name, self.data_cache.get(name, []))
            for name in self.names
        }
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

class TableWidget(HydeInteractiveWidget):
    # The kernel runs one request at a time, so a refresh issued while the
    # user's own cell is running waits its turn -- and waiting is not failing.
    # This bounds only the gap between the kernel saying the push ran and its
    # data arriving on the parent-message channel.
    REFRESH_PAYLOAD_TIMEOUT_MS = 2000
    ui_filename = os.path.join("plugins", "table_interactive", "table.ui")

    def __init__(
        self,
        handle,
        names,
        services=None,
        geometry=None,
        column_widths=None,
        *args,
        **kwargs,
    ):
        parent = kwargs.pop("parent", None)
        flags = kwargs.pop("flags", kwargs.pop("f", None))
        if len(args) > 2:
            raise TypeError("TableWidget accepts at most parent and flags QWidget arguments")
        if args:
            if len(args) == 2:
                positional_parent, positional_flags = args
            elif isinstance(args[0], QtWidgets.QWidget) or args[0] is None:
                positional_parent, positional_flags = args[0], None
            else:
                positional_parent, positional_flags = None, args[0]
            if positional_parent is not None:
                if parent is not None:
                    raise TypeError("parent specified both positionally and by keyword")
                parent = positional_parent
            if positional_flags is not None:
                if flags is not None:
                    raise TypeError("flags specified both positionally and by keyword")
                flags = positional_flags
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments for TableWidget: {unexpected}")
        super().__init__(
            services=services,
            initial_window_name=str(handle),
            parent=parent,
        )
        if flags is not None:
            self.setWindowFlags(flags)
        self.widget_ir = TableIR(
            names=tuple(names or ()),
            name=handle,
            geometry=geometry,
            column_widths=column_widths,
        )
        self._current_request_id = None
        self._refresh_request = None
        self._refresh_in_flight = False
        self._refresh_requested = False
        self._refresh_payload_timer = QtCore.QTimer(self)
        self._refresh_payload_timer.setSingleShot(True)
        self._refresh_payload_timer.timeout.connect(self._on_refresh_payload_timeout)
        self._selected_cell = None
        self._value_edit_dirty = False
        self._initial_size_applied = False
        self._closed = False
        self._restore_layout_requested = bool(geometry or column_widths)
        self._pending_created_columns = []
        self._pending_column_requests = {}
        self._tracked_namespace_state = self.current_tracked_namespace_state()

        self.model = TableViewModel(self.widget_ir.names)
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

        python_variables_service = self.services.get("namespace_view_service")
        if python_variables_service is not None:
            python_variables_service.connect_namespace_view_updated(
                self._on_namespace_view_updated
            )

        QtCore.QTimer.singleShot(0, self.refresh_data)

    def append_columns(self, names, refresh=True):
        current_names = list(self.widget_ir.names)
        for name in names:
            if name not in current_names:
                current_names.append(name)
        self.widget_ir = self.widget_ir.with_names(current_names)
        self.model.set_names(self.widget_ir.names)
        if refresh:
            self.refresh_data()

    def remove_columns(self, names, refresh=True):
        current_names = list(self.widget_ir.names)
        removed = [name for name in names if name in current_names]
        if not removed:
            return
        remaining_names = [name for name in current_names if name not in removed]
        self.widget_ir = self.widget_ir.with_names(remaining_names)
        self.model.set_names(self.widget_ir.names)
        self._update_selection_info()
        if refresh and self.widget_ir.names:
            self.refresh_data()

    def on_stable_name_bound(self, stable_name):
        self.widget_ir = self.widget_ir.with_name(stable_name)

    def bind_subwindow(self, subwindow, stable_name=None):
        super().bind_subwindow(subwindow, stable_name=stable_name)
        geometry = self.widget_ir.geometry
        if geometry is not None:
            subwindow.setGeometry(QtCore.QRect(*geometry))
        self._remember_subwindow_geometry()
        self.capture_layout_state()

    def tracked_namespace_names(self):
        return tuple(self.widget_ir.names) + tuple(self._pending_created_columns)

    def _queue_refresh(self, prefix_commands=None):
        if self._closed:
            return False
        prefix = [command for command in (prefix_commands or []) if command]
        request_id = str(uuid.uuid4())
        self._current_request_id = request_id
        self._refresh_in_flight = True
        self._refresh_requested = False
        refresh_command = self.widget_ir.with_push_table_data(request_id).python_source()
        for command in prefix:
            # Correlated rather than dispatched: Hyde's commands are silent, so
            # a mutation that raises does not abort the refresh queued behind
            # it. Uncorrelated, the refresh would return unchanged data and the
            # failed edit would look like it simply had no effect.
            if self.request_command(command, self._on_table_command_finished) is None:
                self._clear_refresh_in_flight()
                return False
        self._refresh_request = self.request_command(
            refresh_command, self._on_refresh_finished
        )
        if self._refresh_request is not None:
            return True
        self._clear_refresh_in_flight()
        return False

    def refresh_data(self):
        if self._closed:
            return
        if self._refresh_in_flight:
            self._refresh_requested = True
            return
        self._queue_refresh()

    @inmain_decorator()
    def on_data_received(self, data, request_id):
        if request_id != self._current_request_id:
            return

        selected_index = self.ui.tableView.currentIndex()
        selected_row = selected_index.row() if selected_index.isValid() else None
        selected_col = selected_index.column() if selected_index.isValid() else None

        self._clear_refresh_in_flight()
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
        if self._refresh_requested and not self._closed:
            self._refresh_requested = False
            self.refresh_data()

    def _report_command_failure(self, kernel_request):
        """A table command the user asked for did not run. Say so."""
        if not self.report_failed_command(kernel_request):
            return False
        LOGGER.warning(
            "Table %s command failed: %s",
            self.window_handle(),
            kernel_request.error,
        )
        return True

    @inmain_decorator()
    def _on_table_command_finished(self, kernel_request):
        if self._closed:
            return
        # The refresh behind this still runs. Showing the unchanged data is
        # what tells the user the edit did not take.
        self._report_command_failure(kernel_request)

    @inmain_decorator()
    def _on_create_column_finished(self, kernel_request):
        pending_new_name = self._pending_column_requests.pop(
            kernel_request.msg_id, None
        )
        if self._closed or not self._report_command_failure(kernel_request):
            return
        if pending_new_name in self._pending_created_columns:
            # The column was never created, so stop waiting for a name that
            # does not exist in the kernel.
            self._pending_created_columns.remove(pending_new_name)

    def _clear_refresh_in_flight(self):
        self._refresh_payload_timer.stop()
        self._refresh_in_flight = False
        self._current_request_id = None
        self._refresh_request = None

    @inmain_decorator()
    def _on_refresh_finished(self, kernel_request):
        """The kernel answered the push command. Its data is separate."""
        if self._closed or kernel_request is not self._refresh_request:
            return
        if kernel_request.ran():
            self._refresh_payload_timer.start(self.REFRESH_PAYLOAD_TIMEOUT_MS)
            return
        self._abandon_refresh()

    @inmain_decorator()
    def _on_refresh_payload_timeout(self):
        if self._closed or not self._refresh_in_flight:
            return
        self._abandon_refresh()

    def _abandon_refresh(self):
        self._clear_refresh_in_flight()
        if self._refresh_requested and not self._closed:
            self._refresh_requested = False
            self.refresh_data()

    @inmain_decorator()
    def _on_namespace_view_updated(self, view):
        if self._closed:
            return
        view = dict(view or {})
        confirmed_columns = [
            name
            for name in self._pending_created_columns
            if dict(view.get(name, {}) or {})
        ]
        if confirmed_columns:
            self.append_columns(confirmed_columns, refresh=False)
            self._pending_created_columns = [
                name
                for name in self._pending_created_columns
                if name not in confirmed_columns
            ]
        removed_columns = [name for name in self.widget_ir.names if name not in view]
        if removed_columns:
            self.remove_columns(removed_columns, refresh=False)
        if not self.update_tracked_namespace_state(view):
            return
        if self.widget_ir.names:
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
        self.activate_popup_menu(
            "table",
            self.ui.tableView.viewport().mapToGlobal(position),
        )

    def _schedule_value_editor_activation(self, index):
        if not (self.model.flags(index) & QtCore.Qt.ItemIsEditable):
            return
        QtCore.QTimer.singleShot(0, self._activate_value_editor)

    def eventFilter(self, watched, event):
        subwindow = getattr(self, "_subwindow", None)
        ui = getattr(self, "ui", None)
        table_view = getattr(ui, "tableView", None)
        value_edit = getattr(ui, "valueEdit", None)
        if watched is subwindow and event.type() in (
            QtCore.QEvent.Move,
            QtCore.QEvent.Resize,
        ):
            self.capture_layout_state()
        if (
            table_view is not None
            and watched is table_view.viewport()
            and event.type() == QtCore.QEvent.MouseButtonRelease
            and event.button() == QtCore.Qt.LeftButton
        ):
            index = table_view.indexAt(event.pos())
            if index.isValid():
                if event.modifiers() == QtCore.Qt.NoModifier:
                    table_view.setCurrentIndex(index)
                    self._update_selection_info()
                    self._schedule_value_editor_activation(index)
                else:
                    QtCore.QTimer.singleShot(0, self._update_selection_info)
        elif (
            value_edit is not None
            and watched is value_edit
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
        widths = self.widget_ir.column_widths
        if not widths:
            return
        for column, name in enumerate(self.widget_ir.names, start=1):
            width = widths.get(name)
            if width is not None:
                self.ui.tableView.setColumnWidth(column, width)

    def _on_section_resized(self, section, old_size, new_size):
        del old_size
        if section <= 0 or section >= self.model.active_column_count():
            return
        name = self.widget_ir.names[section - 1]
        self.widget_ir = self.widget_ir.with_column_width(name, new_size)

    def capture_layout_state(self):
        widget_ir = self.widget_ir
        if self._subwindow is not None:
            widget_ir = widget_ir.with_name(self.window_handle())
            if not self._subwindow.isMinimized():
                self._remember_subwindow_geometry()
            if self._last_normal_geometry is not None:
                widget_ir = widget_ir.with_geometry(self._last_normal_geometry)
        widths = {}
        for column, name in enumerate(widget_ir.names, start=1):
            widths[name] = self.ui.tableView.columnWidth(column)
        self.widget_ir = widget_ir.with_column_widths(widths)

    def saveable_default_macro_name(self):
        return self.widget_ir.default_macro_name()

    def saveable_decorator_name(self):
        return "@hyde.table"

    def macro_definition_source(self, macro_name, *, handle):
        return self.widget_ir.recreation_function_source(
            macro_name,
            name=handle,
        )

    def session_restore_definition_source(self, handle):
        return self.widget_ir.recreation_function_source(
            handle,
            name=handle,
        )

    def session_restore_arguments(self):
        return self.widget_ir.names

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
            name = self.widget_ir.names[col - 1]
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
            name = self.widget_ir.names[col - 1]
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

        commands = []
        for name, rows in sorted(rows_by_name.items()):
            mutation_ir = self.widget_ir.with_delete_indices(name, rows)
            commands.append(
                TableIRDiff.from_irs(self.widget_ir, mutation_ir).python_source()
            )
        if commands and not self._queue_refresh(commands):
            return
        self._value_edit_dirty = False

    def request_delete_selected_data(self):
        rows_by_name = self._selected_data_rows_by_name()
        if not rows_by_name:
            return False
        self._delete_selected_data(rows_by_name)
        return True

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
            base_ir = self.widget_ir
            if idx.column() == self.model.columnCount() - 1:
                if row != 0:
                    return False
                namespace_names = set(base_ir.names)
                python_variables_service = self.services.get("namespace_view_service")
                if python_variables_service is not None:
                    namespace_names.update(
                        python_variables_service.namespace_view().keys()
                    )
                mutation_ir = base_ir.with_create_array(
                    val_text,
                    namespace_names,
                )
                command = TableIRDiff.from_irs(base_ir, mutation_ir).python_source()
                pending_new_name = mutation_ir.var_name
            else:
                name = base_ir.names[idx.column() - 1]
                column_length = len(self.model.data_cache.get(name, []))
                pending_new_name = None
                if row < column_length:
                    mutation_ir = base_ir.with_edit_value(
                        name,
                        row,
                        val_text,
                    )
                elif row == column_length:
                    mutation_ir = base_ir.with_append_value(
                        name,
                        val_text,
                    )
                else:
                    return False
                command = TableIRDiff.from_irs(base_ir, mutation_ir).python_source()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", str(exc))
            return False

        if pending_new_name is not None:
            kernel_request = self.request_command(
                command, self._on_create_column_finished
            )
            if kernel_request is None:
                return False
            self._pending_column_requests[kernel_request.msg_id] = pending_new_name
            self._pending_created_columns.append(pending_new_name)
            self._tracked_namespace_state = self.current_tracked_namespace_state()
        else:
            if not self._queue_refresh([command]):
                return False
        self._value_edit_dirty = False
        return True

    def is_close_complete(self):
        return self._closed

    def finalize_interactive_close(self, event):
        self.shutdown_client()
        self.complete_interactive_close(event)

    def shutdown_client(self):
        if self._closed:
            return
        self._closed = True
        self._refresh_payload_timer.stop()
        try:
            python_variables_service = self.services.get("namespace_view_service")
            if python_variables_service is not None:
                python_variables_service.disconnect_namespace_view_updated(
                    self._on_namespace_view_updated
                )
        except Exception:
            pass
