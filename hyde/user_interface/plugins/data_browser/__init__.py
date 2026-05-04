import os
import time

from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from qtconsole.client import QtKernelClient
from spyder_kernels.comms.commbase import CommBase, CommError
from hyde.features.hyde_features import is_eligible_for_table
from hyde.paths import CONNECTION_FILE
from hyde.user_interface.base import MutationState
from hyde.user_interface.plugin_tools import HydePlugin

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


class DataBrowser(QtWidgets.QWidget):
    namespace_view_updated = QtCore.Signal(object)

    def __init__(self, connection_file, services=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection_file = connection_file
        self.services = dict(services or {})
        self._external_requests_in_flight = set()
        self._refresh_in_flight = False
        self._refresh_pending = False
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
        self.spyder_comm = SpyderFrontendComm(self.kernel_client)
        self.kernel_client.start_channels()

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
        self._initialize_namespace_sync()

    def _initialize_namespace_sync(self):
        self.spyder_comm.open()
        self.spyder_comm.wait_until_ready()
        self.spyder_comm.configure_namespace_view(NAMESPACE_VIEW_SETTINGS)
        self.refresh_namespace()

    def refresh_namespace(self):
        if self._closed:
            return
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        self.spyder_comm.request_namespace_view(self._on_namespace_view)

    def _handle_iopub_message(self, msg):
        msg_type = msg["header"]["msg_type"]
        if msg_type != "status" or not self._is_external_status_message(msg):
            return
        state = msg["content"].get("execution_state")
        request_key = self._external_request_key(msg)
        if state == "busy":
            self._external_requests_in_flight.add(request_key)
        elif state == "idle":
            had_external_activity = bool(self._external_requests_in_flight)
            self._external_requests_in_flight.discard(request_key)
            if had_external_activity and not self._external_requests_in_flight:
                self.refresh_namespace()

    def _external_request_key(self, msg):
        parent_header = msg.get("parent_header", {})
        return (
            parent_header.get("session"),
            parent_header.get("msg_id"),
        )

    def _is_external_status_message(self, msg):
        parent_session = msg.get("parent_header", {}).get("session")
        if not parent_session:
            return False
        return parent_session != self.kernel_client.session.session

    def _on_namespace_view(self, view):
        self._refresh_in_flight = False
        self._apply_namespace_view(view or {})
        if self._refresh_pending and not self._closed:
            self._refresh_pending = False
            QtCore.QTimer.singleShot(0, self.refresh_namespace)

    @inmain_decorator()
    def _apply_namespace_view(self, view):
        self._last_view = dict(view)
        self._update_ui(self._last_view)
        self.namespace_view_updated.emit(dict(self._last_view))

    def namespace_view(self):
        """Return the latest cached namespace metadata snapshot."""
        return dict(getattr(self, "_last_view", {}) or {})

    def restore_view_state(self, info):
        self.ui.wavesCheckBox.setChecked(bool(info.get("waves", True)))
        self.ui.variablesCheckBox.setChecked(bool(info.get("variables", True)))
        self.ui.stringsCheckBox.setChecked(bool(info.get("strings", True)))
        self.ui.infoCheckBox.setChecked(bool(info.get("info", True)))

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.kernel_client.iopub_channel.message_received.disconnect(
                self._handle_iopub_message
            )
        except Exception:
            pass
        try:
            self.spyder_comm.close()
        except Exception:
            pass
        try:
            for channel_name in ("iopub_channel", "shell_channel", "stdin_channel", "control_channel"):
                channel = getattr(self.kernel_client, channel_name, None)
                if channel is not None and hasattr(channel, "close"):
                    try:
                        channel.close()
                    except Exception:
                        pass
            self.kernel_client.stop_channels()
        except Exception:
            pass

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

    def _candidate_selection_indexes(self):
        selection_model = self.ui.treeView.selectionModel()
        candidate_indexes = selection_model.selectedRows()
        if not candidate_indexes:
            candidate_indexes = selection_model.selectedIndexes()
        if not candidate_indexes and self.ui.treeView.currentIndex().isValid():
            candidate_indexes = [self.ui.treeView.currentIndex()]
        return list(candidate_indexes)

    def _selected_metadata_entries(self):
        entries = []
        seen = set()
        for index in self._candidate_selection_indexes():
            idx = self.proxy_model.mapToSource(index)
            metadata = self.model.itemFromIndex(idx).data(QtCore.Qt.UserRole) or {}
            name = metadata.get("name")
            if name and name in seen:
                continue
            if name:
                seen.add(name)
            entries.append(metadata)
        return entries

    def _primary_selected_metadata(self):
        entries = self._selected_metadata_entries()
        if not entries:
            return {}
        return dict(entries[0])

    def _selected_names(self):
        return [
            metadata["name"]
            for metadata in self._selected_metadata_entries()
            if metadata.get("name")
        ]

    def _selected_table_names(self):
        entries = self._selected_metadata_entries()
        if not entries:
            return []

        names = []
        for metadata in entries:
            name = metadata.get("name")
            if not name or not is_eligible_for_table(metadata):
                return []
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
        execute_command = self.services.get("execute_command")
        for name in names:
            state = MutationState()
            state.set_delete_name(name)
            if execute_command is not None:
                execute_command(state.python_source(), visible=False)

    def _show_context_menu(self, position):
        menu = QtWidgets.QMenu(self)
        copy_action = menu.addAction("Copy Python Expression")
        delete_action = menu.addAction("Delete Object")
        menu.addSeparator()
        edit_action = menu.addAction("Edit")
        append_action = menu.addAction("Append to Table")

        names = self._selected_names()
        table_names = self._selected_table_names()
        enabled = bool(names)
        copy_action.setEnabled(enabled)
        delete_action.setEnabled(enabled)

        edit_action.setEnabled(bool(table_names))

        table_feature = self.services.get("table_feature")
        has_active_table = bool(
            table_feature is not None and table_feature.has_active_table()
        )
        append_action.setEnabled(bool(table_names) and has_active_table)

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
        names = self._selected_table_names()
        if not names:
            return

        table_feature = self.services.get("table_feature")
        if table_feature is None:
            return
        table_feature.show_new_table_dialog(
            self.namespace_view(),
            preselection=names,
            parent=self,
        )

    def _append_to_table_selected(self):
        names = self._selected_table_names()
        table_feature = self.services.get("table_feature")
        if not names or table_feature is None:
            return
        table_feature.append_to_active_table(names)

    def closeEvent(self, event):
        if self._closed:
            super().closeEvent(event)
            return
        get_shutting_down = self.services.get("get_shutting_down")
        if get_shutting_down is not None and get_shutting_down():
            self.shutdown()
            super().closeEvent(event)
            return
        parent = self.parentWidget()
        if parent is not None:
            parent.hide()
        else:
            self.hide()
        event.ignore()


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


class DataBrowserService:
    def __init__(self, plugin):
        self.plugin = plugin

    def ensure_widget(self):
        return self.plugin.ensure_mdi_widget("data_browser")

    def widget(self):
        return self.plugin.mdi_widget("data_browser")

    def subwindow(self):
        return self.plugin.mdi_subwindow("data_browser")

    def destroy(self):
        self.plugin.destroy_mdi_widget("data_browser")

    def namespace_view(self):
        widget = self.ensure_widget()
        return {} if widget is None else widget.namespace_view()

    def connect_namespace_view_updated(self, callback):
        widget = self.widget()
        if widget is None:
            return False
        widget.namespace_view_updated.connect(callback)
        return True

    def disconnect_namespace_view_updated(self, callback):
        widget = self.widget()
        if widget is None:
            return False
        widget.namespace_view_updated.disconnect(callback)
        return True


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.data_browser_service = DataBrowserService(self)
        self._action = None

    def on_setup_complete(self, data=None):
        del data
        self.bind_menu_action("_action", "window", "Data Browser")

    def get_ui_contributions(self):
        return [
            {
                "context": "mdi",
                "key": "data_browser",
                "title": "Data Browser",
                "factory": self.create_widget,
            }
        ]

    def get_menu_contributions(self):
        return [
            {
                "location": "window",
                "group": "tool_windows",
                "order": 60,
                "name": "Data Browser",
                "action": self.show_window,
            }
        ]

    def get_services(self):
        return {
            "namespace_view_service": self.data_browser_service,
        }

    def create_widget(self, parent=None, data=None):
        del data
        return DataBrowser(
            connection_file=CONNECTION_FILE,
            services=self.services,
            parent=parent,
        )

    def show_window(self, checked=False):
        del checked
        self.services["show_window"]("data_browser")

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "kernel_crashed": self.on_kernel_crashed,
            "kernel_ready": self.on_kernel_ready,
            "project_activated": self.on_project_activated,
            "project_loaded": self.on_project_loaded,
        }

    def get_save_data(self):
        widget = self.mdi_widget("data_browser")
        if widget is None:
            return {}
        save_data = self.tool_window_save_data("data_browser")
        save_data["data_browser"] = {
            "waves": bool(widget.ui.wavesCheckBox.isChecked()),
            "variables": bool(widget.ui.variablesCheckBox.isChecked()),
            "strings": bool(widget.ui.stringsCheckBox.isChecked()),
            "info": bool(widget.ui.infoCheckBox.isChecked()),
        }
        return save_data

    def on_project_loaded(self, data):
        session = data["session"]
        widget = self.data_browser_service.ensure_widget()
        self.restore_tool_window(session, "data_browser")
        widget.restore_view_state(session.get("data_browser", {}))

    def on_enter_no_project_state(self, data):
        del data
        self.set_bound_action_enabled("_action", False)
        self.hide_mdi_subwindow("data_browser")

    def on_project_activated(self, data):
        del data
        self.set_bound_action_enabled("_action", True)

    def on_kernel_ready(self, data):
        del data
        self.ensure_mdi_widget("data_browser")

    def on_kernel_crashed(self, data):
        del data
        self.data_browser_service.destroy()
