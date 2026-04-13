import os
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from qtconsole.client import QtKernelClient


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
        self.row_count = max([len(v) for v in self.data_cache.values()] + [0])
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return self.row_count

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.names) + 1  # +1 for Point column

    def headerData(self, section, orientation, role):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            if section == 0:
                return "Point"
            return self.names[section - 1]
        return None

    def data(self, index, role):
        if not index.isValid():
            return None
        
        row = index.row()
        col = index.column()

        if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.EditRole:
            if col == 0:
                return str(row)
            
            name = self.names[col - 1]
            vals = self.data_cache.get(name, [])
            if row < len(vals):
                return str(vals[row])
            return ""
        
        if role == QtCore.Qt.TextAlignmentRole:
            return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter

        return None

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        
        if index.column() == 0:
            return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEditable


class TableWidget(QtWidgets.QWidget):
    def __init__(self, handle, names, connection_file, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handle = handle
        self.names = list(names)
        self.connection_file = connection_file
        self.app = app
        self._external_kernel_busy = False
        self._refresh_in_flight = False
        self._closed = False

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "table.ui")
        self.ui = loader.load(ui_path, self)

        self.model = TableViewModel(self.names)
        self.ui.tableView.setModel(self.model)

        # Separate client for listening to execution state (iopub)
        self.kernel_client = QtKernelClient(connection_file=self.connection_file)
        self.kernel_client.load_connection_file()
        self.kernel_client.start_channels()

        self.kernel_client.iopub_channel.message_received.connect(self._handle_iopub_message)

        self.ui.tableView.selectionModel().currentChanged.connect(self._on_selection_changed)
        self.ui.valueEdit.returnPressed.connect(self._on_value_edited)
        
        # Initial data fetch
        QtCore.QTimer.singleShot(0, self.refresh_data)

    def append_columns(self, names):
        for name in names:
            if name not in self.names:
                self.names.append(name)
        self.model.names = self.names
        self.refresh_data()

    def refresh_data(self):
        """Request array data via the shared Hyde comm."""
        if self._closed or self._refresh_in_flight:
            return
        
        if self.app and self.app.hyde_comm:
            self._refresh_in_flight = True
            self.app.hyde_comm.request_table_data(
                self.names, 
                callback=self._on_data_received
            )

    @inmain_decorator()
    def _on_data_received(self, data):
        self._refresh_in_flight = False
        if not isinstance(data, dict):
            return
        self.model.update_data(data)
        self._update_selection_info()

    def _handle_iopub_message(self, msg):
        msg_type = msg["header"]["msg_type"]
        if msg_type == "status":
            state = msg["content"].get("execution_state")
            if state == "busy":
                if not self._refresh_in_flight:
                    self._external_kernel_busy = True
            elif state == "idle":
                if self._external_kernel_busy:
                    # External command finished, refresh viewports
                    self._external_kernel_busy = False
                    self.refresh_data()

    def _on_selection_changed(self, current, previous):
        self._update_selection_info()

    def _update_selection_info(self):
        idx = self.ui.tableView.currentIndex()
        if not idx.isValid():
            self.ui.cellInfoLabel.setText("Selection")
            self.ui.valueEdit.clear()
            return
        
        row = idx.row()
        col = idx.column()
        
        if col == 0:
            self.ui.cellInfoLabel.setText(f"Point {row}")
            self.ui.valueEdit.setText(str(row))
            self.ui.valueEdit.setReadOnly(True)
        else:
            name = self.names[col - 1]
            self.ui.cellInfoLabel.setText(f"{name}[{row}]")
            val = self.model.data(idx, QtCore.Qt.DisplayRole)
            self.ui.valueEdit.setText(val if val is not None else "")
            self.ui.valueEdit.setReadOnly(False)

    def _on_value_edited(self):
        idx = self.ui.tableView.currentIndex()
        if not idx.isValid() or idx.column() == 0:
            return
        
        row = idx.row()
        name = self.names[idx.column() - 1]
        val_text = self.ui.valueEdit.text()
        
        # Guard against non-numeric (scoped to numeric for now)
        try:
            float(val_text)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Only numeric values are supported.")
            return

        command = f"{name}[{row}] = {val_text}"
        if self.app:
            self.app.execute_command(command)

    def closeEvent(self, event):
        self._closed = True
        try:
            self.kernel_client.iopub_channel.message_received.disconnect(self._handle_iopub_message)
        except Exception:
            pass
        self.kernel_client.stop_channels()
        super().closeEvent(event)
