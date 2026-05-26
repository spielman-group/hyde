import copy
import keyword
import os
import time

from qtutils import inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from spyder_kernels.comms.commbase import CommBase, CommError
from hyde.features.base import is_eligible_for_numeric_series
from hyde.user_interface.base_hyde_widgets import HydeToolWidget
from hyde.user_interface.shared.core import HydeIR
from hyde.user_interface.shared.plugin import HydeToolWindowPlugin, HydeToolWindowService

NAMESPACE_VIEW_SETTINGS = {
    "check_all": False,
    "exclude_private": True,
    "exclude_uppercase": False,
    "exclude_capitalized": False,
    "exclude_unsupported": True,
    "excluded_names": ["project_root", "name", "original_ps1"],
    "minmax": False,
    "show_callable_attributes": False,
    "show_special_attributes": False,
    "exclude_callables_and_modules": True,
    "filter_on": True,
}


class PythonVariablesIR(HydeIR):
    def __init__(
        self,
        *,
        arrays=True,
        variables=True,
        strings=True,
        info=True,
        delete_names=(),
    ):
        self.arrays = bool(arrays)
        self.variables = bool(variables)
        self.strings = bool(strings)
        self.info = bool(info)
        self.delete_names = tuple(str(name) for name in delete_names if str(name).strip())

    def with_view_state(self, *, arrays, variables, strings, info):
        return type(self)(
            arrays=arrays,
            variables=variables,
            strings=strings,
            info=info,
            delete_names=self.delete_names,
        )

    def with_delete_names(self, names):
        return type(self)(
            arrays=self.arrays,
            variables=self.variables,
            strings=self.strings,
            info=self.info,
            delete_names=tuple(names),
        )

    def session_state(self):
        return {
            "arrays": self.arrays,
            "variables": self.variables,
            "strings": self.strings,
            "info": self.info,
        }

    def validate(self):
        for name in self.delete_names:
            if not name.isidentifier() or keyword.iskeyword(name):
                raise ValueError(f"Invalid Python variable name: {name!r}")
        return self

    def _python_source(self):
        if not self.delete_names:
            return ""
        return f"del {', '.join(self.delete_names)}"


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


class PythonVariables(HydeToolWidget):
    ui_filename = os.path.join("plugins", "python_variables_tool", "python_variables.ui")
    namespace_view_updated = QtCore.Signal(object)

    def __init__(self, services=None, session_key=None, *args, **kwargs):
        super().__init__(
            services=services,
            session_key=session_key,
            *args,
            **kwargs,
        )
        self._execute_requests_in_flight = set()
        self._refresh_in_flight = False
        self._refresh_pending = False
        self._closed = False

        self.model = QtGui.QStandardItemModel(0, 3)
        self.model.setHorizontalHeaderLabels(["Name", "Type", "Value"])
        self.proxy_model = NamespaceFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.widget_ir = PythonVariablesIR(
            arrays=self.ui.arraysCheckBox.isChecked(),
            variables=self.ui.variablesCheckBox.isChecked(),
            strings=self.ui.stringsCheckBox.isChecked(),
            info=self.ui.infoCheckBox.isChecked(),
        )
        self.ui.treeView.setModel(self.proxy_model)
        self.ui.treeView.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.treeView.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        kernel_runtime_service = self.services.get("kernel_runtime_service")
        self.kernel_client = None
        if kernel_runtime_service is not None:
            self.kernel_client = kernel_runtime_service.kernel_client()
        if self.kernel_client is None:
            raise RuntimeError(
                "PythonVariables requires a shared kernel client from "
                "kernel_runtime_service."
            )

        self.spyder_comm = SpyderFrontendComm(self.kernel_client)
        self.kernel_client.iopub_channel.message_received.connect(self._handle_iopub_message)

        self.ui.arraysCheckBox.toggled.connect(self._on_view_state_changed)
        self.ui.variablesCheckBox.toggled.connect(self._on_view_state_changed)
        self.ui.stringsCheckBox.toggled.connect(self._on_view_state_changed)
        self.ui.infoCheckBox.toggled.connect(self._on_view_state_changed)
        self.ui.deleteButton.clicked.connect(self._delete_selected)
        self.ui.treeView.customContextMenuRequested.connect(self._show_context_menu)
        self.ui.treeView.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.ui.plotCheckBox.setEnabled(False)

        self._apply_widget_ir_view_state()
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
        if msg_type != "status" or not self._is_execute_status_message(msg):
            return
        state = msg["content"].get("execution_state")
        request_key = self._execute_request_key(msg)
        if state == "busy":
            self._execute_requests_in_flight.add(request_key)
        elif state == "idle":
            had_execute_activity = bool(self._execute_requests_in_flight)
            self._execute_requests_in_flight.discard(request_key)
            if had_execute_activity and not self._execute_requests_in_flight:
                self.refresh_namespace()

    def _execute_request_key(self, msg):
        parent_header = msg.get("parent_header", {})
        return (
            parent_header.get("session"),
            parent_header.get("msg_id"),
        )

    def _is_execute_status_message(self, msg):
        parent_header = msg.get("parent_header", {})
        return (
            parent_header.get("msg_type") == "execute_request"
            and bool(parent_header.get("msg_id"))
        )

    def _on_namespace_view(self, view):
        self._refresh_in_flight = False
        self._apply_namespace_view(view or {})
        if self._refresh_pending and not self._closed:
            self._refresh_pending = False
            QtCore.QTimer.singleShot(0, self.refresh_namespace)

    @inmain_decorator()
    def _apply_namespace_view(self, view):
        self._last_view = copy.deepcopy(dict(view or {}))
        self._update_ui(self._last_view)
        self.namespace_view_updated.emit(copy.deepcopy(self._last_view))

    def namespace_view(self):
        """Return the latest cached namespace metadata snapshot."""
        return copy.deepcopy(getattr(self, "_last_view", {}) or {})

    def get_session_toml_data(self):
        return self.widget_ir.session_state()

    def restore_session_toml_data(self, info):
        self.widget_ir = self.widget_ir.with_view_state(
            arrays=bool(info.get("arrays", True)),
            variables=bool(info.get("variables", True)),
            strings=bool(info.get("strings", True)),
            info=bool(info.get("info", True)),
        )
        self._sync_controls_from_widget_ir()
        self._apply_widget_ir_view_state()

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

    @inmain_decorator()
    def _update_ui(self, view):
        self.model.removeRows(0, self.model.rowCount())
        excluded_names = set(NAMESPACE_VIEW_SETTINGS.get("excluded_names", ()))
        for name, metadata in sorted(view.items()):
            if name in excluded_names:
                continue
            name_item = QtGui.QStandardItem(name)
            type_item = QtGui.QStandardItem(metadata.get("type", ""))
            value_item = QtGui.QStandardItem(metadata.get("view", ""))
            name_item.setData({"name": name, **metadata}, QtCore.Qt.UserRole)
            self.model.appendRow([name_item, type_item, value_item])
        self._apply_widget_ir_view_state()

    def _sync_controls_from_widget_ir(self):
        for widget, checked in (
            (self.ui.arraysCheckBox, self.widget_ir.arrays),
            (self.ui.variablesCheckBox, self.widget_ir.variables),
            (self.ui.stringsCheckBox, self.widget_ir.strings),
            (self.ui.infoCheckBox, self.widget_ir.info),
        ):
            blocker = QtCore.QSignalBlocker(widget)
            widget.setChecked(bool(checked))
            del blocker

    def _apply_widget_ir_view_state(self):
        self.proxy_model.update_filters(
            arrays=self.widget_ir.arrays,
            variables=self.widget_ir.variables,
            strings=self.widget_ir.strings,
        )
        self.ui.infoPane.setVisible(self.widget_ir.info)

    def _on_view_state_changed(self):
        self.widget_ir = self.widget_ir.with_view_state(
            arrays=self.ui.arraysCheckBox.isChecked(),
            variables=self.ui.variablesCheckBox.isChecked(),
            strings=self.ui.stringsCheckBox.isChecked(),
            info=self.ui.infoCheckBox.isChecked(),
        )
        self._apply_widget_ir_view_state()

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
            if not name or not is_eligible_for_numeric_series(metadata):
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
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return
        payload = self.widget_ir.with_delete_names(names).python_source(log=False)
        if payload:
            python_execution_service.execute_hidden(payload)

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

class NamespaceFilterProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._arrays = True
        self._variables = True
        self._strings = True

    def update_filters(self, arrays, variables, strings):
        self._arrays = arrays
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

        is_array = normalized in {"ndarray", "dataframe"} or numpy_type == "Array"
        is_variable = normalized in {"int", "float", "complex"}
        is_string = normalized == "str"

        return (
            (self._arrays and is_array)
            or (self._variables and is_variable)
            or (self._strings and is_string)
        )


class PythonVariablesService(HydeToolWindowService):
    def __init__(self, plugin, window_key=None):
        super().__init__(plugin, window_key=window_key)
        self._namespace_view = {}
        self._callbacks = []
        self._observed_widget = None

    def observe_widget(self, widget):
        if widget is self._observed_widget:
            return widget
        if self._observed_widget is not None:
            try:
                self._observed_widget.namespace_view_updated.disconnect(
                    self.publish_namespace_view
                )
            except Exception:
                pass
        self._observed_widget = widget
        if widget is None:
            return None
        widget.namespace_view_updated.connect(self.publish_namespace_view)
        self.publish_namespace_view(widget.namespace_view())
        return widget

    def publish_namespace_view(self, view):
        self._namespace_view = copy.deepcopy(dict(view or {}))
        payload = copy.deepcopy(self._namespace_view)
        for callback in list(self._callbacks):
            callback(copy.deepcopy(payload))

    def namespace_view(self):
        widget = self.widget()
        if widget is not None and widget is not self._observed_widget:
            self.observe_widget(widget)
        return copy.deepcopy(self._namespace_view)

    def connect_namespace_view_updated(self, callback):
        if callback not in self._callbacks:
            self._callbacks.append(callback)
        widget = self.widget()
        if widget is not None and widget is not self._observed_widget:
            self.observe_widget(widget)
        return True

    def disconnect_namespace_view_updated(self, callback):
        if callback not in self._callbacks:
            return False
        self._callbacks.remove(callback)
        return True


class Plugin(HydeToolWindowPlugin):
    session_key = "python_variables_tool"
    window_title = "Python Variables"
    menu_name = "Python Variables"
    menu_order = 60
    restore_on_project_loaded = True
    enable_action_with_project = True
    hide_on_enter_no_project = True
    ensure_widget_on_kernel_ready = True
    destroy_widget_on_kernel_crash = True

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.python_variables_service = PythonVariablesService(self)

    def get_services(self):
        return {
            "namespace_view_service": self.python_variables_service,
        }

    def create_tool_window_widget(self, parent=None):
        widget = PythonVariables(
            services=self.services,
            session_key=self.session_key,
            parent=parent,
        )
        self.python_variables_service.observe_widget(widget)
        return widget
