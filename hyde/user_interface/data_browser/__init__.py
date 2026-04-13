import os
import time

from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from qtconsole.client import QtKernelClient
from spyder_kernels.comms.commbase import CommBase, CommError


NAMESPACE_VIEW_SETTINGS = {
    "check_all": False,
    "exclude_private": True,
    "exclude_uppercase": False,
    "exclude_capitalized": False,
    "exclude_unsupported": True,
    "excluded_names": ["project_root", "name"],
    "minmax": False,
    "show_callable_attributes": False,
    "show_special_attributes": False,
    "exclude_callables_and_modules": True,
    "filter_on": True,
}


class SpyderFrontendComm(CommBase):
    """Minimal frontend wrapper for Spyder's `spyder_api` remote-call protocol."""

    def __init__(self, kernel_client):
        super().__init__()
        self.kernel_client = kernel_client
        self.comm = None
        self._is_ready = False
        self.register_call_handler("_comm_ready", self._comm_ready)
        self.register_call_handler("_async_error", self._async_error)

    def open(self):
        if self.comm is not None:
            return
        self.comm = self.kernel_client.comm_manager.new_comm(self._comm_name)
        self._register_comm(self.comm)

    def close(self):
        super().close()
        self.comm = None
        self._is_ready = False

    def wait_until_ready(self, timeout=5):
        deadline = time.time() + timeout
        while not self._is_ready and time.time() < deadline:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.01)
        if not self._is_ready:
            raise TimeoutError("Timed out waiting for Spyder comm readiness.")

    def request_namespace_view(self, callback):
        if self.comm is None:
            return
        self.remote_call(
            comm_id=self.comm.comm_id,
            callback=callback,
        ).get_namespace_view()

    def configure_namespace_view(self, settings):
        if self.comm is None:
            raise CommError("The comm is not connected.")
        self.remote_call(
            comm_id=self.comm.comm_id,
            blocking=True,
        ).set_configuration({"namespace_view_settings": settings})

    def _comm_ready(self):
        self._is_ready = True
        return None

    def _wait_reply(self, comm_id, call_id, call_name, timeout):
        deadline = time.time() + timeout
        while call_id not in self._reply_inbox and time.time() < deadline:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.01)
        if call_id not in self._reply_inbox:
            raise TimeoutError(f"Timeout while waiting for '{call_name}' reply.")

    def _async_error(self, error_wrapper):
        # Let unexpected kernel-side comm errors surface in stderr for now.
        print(error_wrapper)


from hyde.user_interface.new_table_dialog import NewTableDialog


class DataBrowser(QtWidgets.QWidget):
    def __init__(self, connection_file, app=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection_file = connection_file
        self.app = app
        self._external_kernel_busy = False
        self._refresh_in_flight = False
        self._closed = False

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "data_browser.ui")
        self.ui = loader.load(ui_path, self)

        self.model = QtGui.QStandardItemModel(0, 3)
        self.model.setHorizontalHeaderLabels(["Name", "Type", "Value"])
        self.proxy_model = NamespaceFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.ui.treeView.setModel(self.proxy_model)
        self.ui.treeView.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.treeView.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        self.kernel_client = QtKernelClient(connection_file=self.connection_file)
        self.kernel_client.load_connection_file()
        self.kernel_client.start_channels()
        self.spyder_comm = SpyderFrontendComm(self.kernel_client)

        self.kernel_client.iopub_channel.message_received.connect(self._handle_iopub_message)

        self.ui.wavesCheckBox.toggled.connect(self._on_filter_changed)
        self.ui.variablesCheckBox.toggled.connect(self._on_filter_changed)
        self.ui.stringsCheckBox.toggled.connect(self._on_filter_changed)
        self.ui.infoCheckBox.toggled.connect(self._toggle_info_pane)
        self.ui.deleteButton.clicked.connect(self._delete_selected)
        self.ui.treeView.customContextMenuRequested.connect(self._show_context_menu)
        self.ui.treeView.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.ui.plotCheckBox.setEnabled(False)

        self._toggle_info_pane(self.ui.infoCheckBox.isChecked())
        QtCore.QTimer.singleShot(0, self._initialize_namespace_sync)

    def _initialize_namespace_sync(self):
        self.spyder_comm.open()
        self.spyder_comm.wait_until_ready()
        self.spyder_comm.configure_namespace_view(NAMESPACE_VIEW_SETTINGS)
        self.refresh_namespace()

    def refresh_namespace(self):
        if self._closed:
            return
        self._refresh_in_flight = True
        self.spyder_comm.request_namespace_view(self._on_namespace_view)

    def _handle_iopub_message(self, msg):
        msg_type = msg["header"]["msg_type"]
        if msg_type == "status":
            state = msg["content"].get("execution_state")
            if state == "busy":
                if not self._refresh_in_flight:
                    self._external_kernel_busy = True
            elif state == "idle" and self._refresh_in_flight:
                self._refresh_in_flight = False
            elif state == "idle" and self._external_kernel_busy:
                self._external_kernel_busy = False
                self.refresh_namespace()

    def _on_namespace_view(self, view):
        self._last_view = view  # Cache for dialogs
        self._update_ui(view or {})

    def namespace_view(self):
        """Return the latest cached namespace metadata snapshot."""
        return dict(getattr(self, "_last_view", {}) or {})

    @inmain_decorator()
    def _update_ui(self, view):
        self.model.removeRows(0, self.model.rowCount())
        for name, metadata in sorted(view.items()):
            name_item = QtGui.QStandardItem(name)
            type_item = QtGui.QStandardItem(metadata.get("type", ""))
            value_item = QtGui.QStandardItem(metadata.get("view", ""))
            name_item.setData({"name": name, **metadata}, QtCore.Qt.UserRole)
            self.model.appendRow([name_item, type_item, value_item])
        self._on_filter_changed()

    def _on_filter_changed(self):
        self.proxy_model.update_filters(
            waves=self.ui.wavesCheckBox.isChecked(),
            variables=self.ui.variablesCheckBox.isChecked(),
            strings=self.ui.stringsCheckBox.isChecked(),
        )

    def _toggle_info_pane(self, checked):
        self.ui.infoPane.setVisible(checked)

    def _on_selection_changed(self, selected, deselected):
        del selected, deselected
        metadata = self._primary_selected_metadata()
        if not metadata:
            self.ui.infoText.clear()
            return
        lines = [f"{key}: {value}" for key, value in metadata.items()]
        self.ui.infoText.setText("\n".join(lines))

    def _primary_selected_metadata(self):
        selection_model = self.ui.treeView.selectionModel()
        candidate_indexes = selection_model.selectedRows()
        if not candidate_indexes:
            candidate_indexes = selection_model.selectedIndexes()
        if not candidate_indexes and self.ui.treeView.currentIndex().isValid():
            candidate_indexes = [self.ui.treeView.currentIndex()]
        if not candidate_indexes:
            return {}
        idx = self.proxy_model.mapToSource(candidate_indexes[0])
        return self.model.itemFromIndex(idx).data(QtCore.Qt.UserRole) or {}

    def _selected_names(self):
        selection_model = self.ui.treeView.selectionModel()
        candidate_indexes = selection_model.selectedRows()
        if not candidate_indexes:
            candidate_indexes = selection_model.selectedIndexes()
        if not candidate_indexes and self.ui.treeView.currentIndex().isValid():
            candidate_indexes = [self.ui.treeView.currentIndex()]

        names = []
        seen = set()
        for index in candidate_indexes:
            idx = self.proxy_model.mapToSource(index)
            metadata = self.model.itemFromIndex(idx).data(QtCore.Qt.UserRole) or {}
            name = metadata.get("name")
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def _copy_selected_expression(self):
        names = self._selected_names()
        if not names:
            return
        QtWidgets.QApplication.clipboard().setText(names[0])

    def _delete_selected(self):
        names = self._selected_names()
        if not names:
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete {', '.join(names)} from the live namespace?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        for name in names:
            self.kernel_client.execute(f"del {name}", silent=True)
        QtCore.QTimer.singleShot(250, self.refresh_namespace)

    def _show_context_menu(self, position):
        menu = QtWidgets.QMenu(self)
        copy_action = menu.addAction("Copy Python Expression")
        delete_action = menu.addAction("Delete Object")
        menu.addSeparator()
        edit_action = menu.addAction("Edit")
        append_action = menu.addAction("Append to Table")

        names = self._selected_names()
        enabled = bool(names)
        copy_action.setEnabled(enabled)
        delete_action.setEnabled(enabled)
        
        # Table actions are only for eligible types (1D numeric arrays initially)
        can_table = False
        if enabled:
            metadata = self._primary_selected_metadata()
            from hyde.features.hyde_features import is_eligible_for_table
            can_table = is_eligible_for_table(metadata)
        
        edit_action.setEnabled(can_table)
        
        has_active_table = self.app and self.app.active_table_handle is not None
        append_action.setEnabled(can_table and has_active_table)

        chosen = menu.exec_(self.ui.treeView.viewport().mapToGlobal(position))
        if chosen == copy_action:
            self._copy_selected_expression()
        elif chosen == delete_action:
            self._delete_selected()
        elif chosen == edit_action:
            self._edit_selected()
        elif chosen == append_action:
            self._append_to_table_selected()

    def _edit_selected(self):
        names = self._selected_names()
        if not names:
            return
        
        dialog = NewTableDialog(self._last_view, preselection=names, parent=self)
        if dialog.exec_():
            command = dialog.get_command()
            if command and self.app:
                self.app.execute_command(command, visible=True)

    def _append_to_table_selected(self):
        names = self._selected_names()
        if not names or not self.app or not self.app.active_table_handle:
            return
        
        target = self.app.active_table_handle
        from hyde.features.hyde_features import format_table_command
        command = format_table_command(names, target=target)
        self.app.execute_command(command, visible=True)

    def closeEvent(self, event):
        self._closed = True
        try:
            self.kernel_client.iopub_channel.message_received.disconnect(self._handle_iopub_message)
        except Exception:
            pass
        try:
            self.spyder_comm.close()
        finally:
            self.kernel_client.stop_channels()
        super().closeEvent(event)


class NamespaceFilterProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._waves = True
        self._variables = True
        self._strings = True

    def update_filters(self, waves, variables, strings):
        self._waves = waves
        self._variables = variables
        self._strings = strings
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        idx = self.sourceModel().index(source_row, 0, source_parent)
        metadata = self.sourceModel().data(idx, QtCore.Qt.UserRole) or {}

        if not metadata:
            return True

        python_type = metadata.get("python_type", "")
        numpy_type = metadata.get("numpy_type", "")
        normalized = python_type.lower()

        is_wave = normalized in {"ndarray", "dataframe"} or numpy_type == "Array"
        is_variable = normalized in {"int", "float", "complex"}
        is_string = normalized == "str"

        return (
            (self._waves and is_wave)
            or (self._variables and is_variable)
            or (self._strings and is_string)
        )
