from qtutils.qt import QtCore
from hyde.user_interface.base_hyde_widgets import active_interactive_window
from hyde.user_interface.shared.plugin import (
    HydePlugin,
    apply_saveable_window_state,
    blank_window_icon,
)
from hyde.user_interface.shared.project import resolve_requested_name

from .window import (
    TableIR,
    TableWidget,
)


class TableWorkspaceService:
    def __init__(self, plugin):
        self.plugin = plugin
        self.tables = {}
        self.active_table_handle = None

    def has_active_table(self):
        return self.active_table_handle is not None

    def lookup_table(self, handle):
        return self.tables.get(handle)

    def iter_open_tables(self):
        return sorted(self.tables.items())

    def open_table(
        self,
        names,
        name=None,
        geometry=None,
        column_widths=None,
        window_state=None,
    ):
        handle = resolve_requested_name(
            "Table",
            self.tables,
            requested_name=name,
        )

        services = dict(self.plugin.services)
        services["save_window_dialog_service"] = self.plugin.services[
            "save_window_dialog_service"
        ]
        table = TableWidget(
            handle,
            names,
            services=services,
            geometry=geometry,
            column_widths=column_widths,
        )
        subwindow = self.plugin.services["mdi_area"].addSubWindow(table)
        subwindow.setWindowIcon(blank_window_icon())
        # Table windows own a real close path with prompt/cleanup, so they keep
        # Qt's normal delete-on-close behavior instead of the persistent tool-
        # window wrapper that turns close into hide.
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        table.bind_subwindow(subwindow, stable_name=handle)
        stable_name = table.window_handle()
        self.tables[stable_name] = table

        subwindow.setWindowTitle(table.formatted_window_title())
        subwindow.show()
        apply_saveable_window_state(subwindow, window_state)
        # Keep the workspace as the signal receiver rather than hiding it in a
        # partial. PyQt weakly tracks bound-method receivers, so deferred Qt
        # destruction cannot call a Python callable whose owner was collected.
        subwindow.setProperty("hyde_workspace_handle", stable_name)
        subwindow.destroyed.connect(self._on_subwindow_destroyed)
        return table

    def append_to_table(self, names, name):
        table = self.tables.get(name)
        if table is None:
            return None
        table.append_columns(names)
        subwindow = table.parentWidget()
        if subwindow is not None:
            subwindow.show()
            subwindow.setFocus()
            subwindow.raise_()
        return table

    def on_table_data(self, data):
        request_id = data.get("request_id")
        table_data = data.get("data", {})
        for table in list(self.tables.values()):
            table.on_data_received(table_data, request_id)

    def on_subwindow_activated(self, subwindow):
        if subwindow is None:
            self.active_table_handle = None
            return
        widget = subwindow.widget()
        if isinstance(widget, TableWidget):
            self.active_table_handle = widget.window_handle()
        else:
            self.active_table_handle = None

    def clear(self):
        for table in list(self.tables.values()):
            subwindow = table.parentWidget()
            if subwindow is None:
                continue
            save_window_dialog_service = table.services.pop(
                "save_window_dialog_service",
                None,
            )
            table_handle = table.window_handle()
            if hasattr(table, "shutdown_client"):
                table.shutdown_client()
            subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
            subwindow.close()
            if (
                save_window_dialog_service is not None
                and self.tables.get(table_handle) is table
            ):
                table.services["save_window_dialog_service"] = save_window_dialog_service
        self.tables.clear()
        self.active_table_handle = None

    def _remove_table(self, handle):
        tables = getattr(self, "tables", None)
        if tables is None:
            return
        tables.pop(handle, None)
        if self.active_table_handle == handle:
            self.active_table_handle = None

    def _on_subwindow_destroyed(self, subwindow=None):
        if subwindow is None:
            return
        handle = subwindow.property("hyde_workspace_handle")
        if handle is not None:
            self._remove_table(str(handle))


class TableFeatureService:
    def __init__(self, plugin):
        self.plugin = plugin

    def has_active_table(self):
        return self.plugin.workspace.has_active_table()

    def show_new_table_dialog(self, objects_metadata, preselection=None, parent=None):
        from hyde.user_interface.plugins.table_interactive.dialogs import NewTableDialog

        dialog = NewTableDialog(
            objects_metadata,
            preselection=preselection,
            services=self.plugin.services,
            parent=parent,
        )
        if not dialog.exec():
            return False
        return True

    def append_to_active_table(self, names):
        active_table_handle = self.plugin.workspace.active_table_handle
        if not names or active_table_handle is None:
            return False

        table_ir = TableIR(
            names=tuple(names or ()),
            name=active_table_handle,
            command="append",
        )
        self.plugin.services["python_execution_service"].execute_visible(
            table_ir.python_source()
        )
        return True


class Plugin(HydePlugin):
    window_macros_menu_title = "Table Macros"
    window_macros_empty_label = "No Saved Table Macros"
    window_macros_new_action_name = "New Table..."
    window_macros_new_action_attr = "_new_table_action"
    window_macros_attr = "table_macros"

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.workspace = TableWorkspaceService(self)
        self.table_feature = TableFeatureService(self)
        self.table_macros = []
        self._signals_connected = False
        self._new_table_action = None
        self._macro_menu = None

    def setup(self, data=None):
        del data
        if self._signals_connected:
            return
        self.setup_configured_window_macros_menu()
        self.services["mdi_area"].subWindowActivated.connect(
            self.workspace.on_subwindow_activated
        )
        self.services["mdi_area"].subWindowActivated.connect(
            self.on_subwindow_activated
        )
        self._signals_connected = True

    def get_services(self):
        return {"table_feature": self.table_feature}

    def get_menu_contributions(self):
        return [
            {
                "location": "window",
                "group": "30_tables",
                "order": 20,
                "name": "New Table...",
                "action": self.show_new_table_dialog,
            },
            {
                "location": "table",
                "group": "10_table",
                "order": 10,
                "name": "Delete Selected Data",
                "action": self.delete_selected_data,
            },
        ]

    def show_new_table_dialog(self, checked=False):
        del checked
        python_variables_service = self.services.get("namespace_view_service")
        self.table_feature.show_new_table_dialog(
            (
                {}
                if python_variables_service is None
                else python_variables_service.namespace_view()
            ),
            parent=self.services["ui"],
        )

    def delete_selected_data(self, checked=False):
        del checked
        widget = active_interactive_window(self.services, TableWidget)
        if widget is None:
            return False
        return widget.request_delete_selected_data()

    def on_subwindow_activated(self, subwindow):
        show_menu = self.services.get("show_menu")
        hide_menu = self.services.get("hide_menu")
        widget = None if subwindow is None else subwindow.widget()
        if isinstance(widget, TableWidget):
            if show_menu is not None:
                show_menu("table")
        elif hide_menu is not None:
            hide_menu("table")

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "kernel_message": self.on_kernel_message,
            "project_loaded": self.on_project_loaded,
            "project_activated": self.on_project_activated,
        }

    def get_session_restore_source(self):
        blocks = []
        for handle, table in self.workspace.iter_open_tables():
            blocks.append(table.session_restore_source().strip())
        return "\n\n".join(blocks) + ("\n" if blocks else "")

    def on_enter_no_project_state(self, data):
        del data
        self.workspace.clear()
        self.table_macros = []
        self.rebuild_configured_window_macros_menu()

    def on_project_loaded(self, data):
        del data
        self.workspace.clear()

    def on_project_activated(self, data):
        del data
        self.table_macros = []
        self.rebuild_configured_window_macros_menu()
        table_ir = TableIR().with_publish_table_macros()
        self.services["python_execution_service"].execute_hidden(
            table_ir.python_source()
        )

    def on_kernel_message(self, payload):
        task = payload.get("task")
        data = payload.get("data", {})
        if task == "OPEN_TABLE_REQUEST":
            self.workspace.open_table(
                data.get("names", []),
                name=data.get("name"),
                geometry=data.get("geometry"),
                column_widths=data.get("column_widths"),
                window_state=data.get("window_state"),
            )
            return
        if task == "APPEND_TABLE_REQUEST":
            self.workspace.append_to_table(
                data.get("names", []),
                data.get("name"),
            )
            return
        if task == "TABLE_DATA_RESPONSE":
            self.workspace.on_table_data(data)
            return
        if task != "TABLE_MACROS_RESPONSE":
            return
        self.table_macros = [
            {
                "name": macro["name"],
                "args": list(macro.get("args", [])),
            }
            for macro in data.get("entries", [])
        ]
        self.rebuild_configured_window_macros_menu()
