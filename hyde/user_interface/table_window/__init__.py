"""Table window UI package."""

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui

from .table_model import CombinedTableModel


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
        self.ui = load_ui("table_window/table_window.ui")
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


__all__ = ["PanelWindow", "TableWindow", "CombinedTableModel"]