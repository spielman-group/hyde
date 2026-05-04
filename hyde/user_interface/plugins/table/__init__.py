from labscript_utils.plugins import BasePlugin
from qtutils.qt import QtCore, QtWidgets
from hyde.user_interface.base import RuntimeCommandState

from .window import (
    TableState,
    TableWidget,
    prompt_to_save_table_macro,
)


class TableWorkspaceService:
    def __init__(self, plugin):
        self.plugin = plugin
        self.tables = {}
        self.active_table_handle = None
        self.table_counter = 0

    def has_active_table(self):
        return self.active_table_handle is not None

    def lookup_table(self, handle):
        return self.tables.get(handle)

    def iter_open_tables(self):
        return sorted(self.tables.items())

    def _next_table_handle(self):
        handle = f"Table{self.table_counter}"
        while handle in self.tables:
            self.table_counter += 1
            handle = f"Table{self.table_counter}"
        self.table_counter += 1
        return handle

    def open_table(
        self,
        names,
        target=None,
        visible_title=None,
        geometry=None,
        column_widths=None,
    ):
        if target is not None and target in self.tables:
            table = self.tables[target]
            table.append_columns(names)
            subwindow = table.parentWidget()
            subwindow.show()
            subwindow.setFocus()
            subwindow.raise_()
            return table

        if target is not None:
            handle = target
        else:
            handle = self._next_table_handle()

        services = dict(self.plugin.services)
        services["request_save_table_macro"] = self.plugin.request_save_table_macro
        table = TableWidget(
            handle,
            names,
            services=services,
            visible_title=visible_title,
            geometry=geometry,
            column_widths=column_widths,
        )
        subwindow = self.plugin.services["mdi_area"].addSubWindow(table)
        # Table windows own a real close path with prompt/cleanup, so they keep
        # Qt's normal delete-on-close behavior instead of the persistent tool-
        # window wrapper that turns close into hide.
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        table.bind_subwindow(subwindow)
        self.tables[handle] = table

        title = visible_title if visible_title else f"{handle}: {', '.join(names)}"
        subwindow.setWindowTitle(title)
        subwindow.show()
        subwindow.destroyed.connect(
            lambda _=None, table_handle=handle: self._remove_table(table_handle)
        )
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
            self.active_table_handle = widget.handle
        else:
            self.active_table_handle = None

    def clear(self):
        for table in list(self.tables.values()):
            subwindow = table.parentWidget()
            if subwindow is None:
                continue
            original_callback = table.services.pop("request_save_table_macro", None)
            if hasattr(table, "shutdown_client"):
                table.shutdown_client()
            subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
            subwindow.close()
            if (
                original_callback is not None
                and table.handle in self.tables
            ):
                table.services["request_save_table_macro"] = original_callback
        self.tables.clear()
        self.active_table_handle = None
        self.table_counter = 0

    def _remove_table(self, handle):
        self.tables.pop(handle, None)
        if self.active_table_handle == handle:
            self.active_table_handle = None


class TableFeatureService:
    def __init__(self, plugin):
        self.plugin = plugin

    def has_active_table(self):
        return self.plugin.workspace.has_active_table()

    def show_new_table_dialog(self, objects_metadata, preselection=None, parent=None):
        from hyde.user_interface.plugins.table.dialogs import NewTableDialog

        dialog = NewTableDialog(
            objects_metadata,
            preselection=preselection,
            parent=parent,
        )
        if not dialog.exec_():
            return False

        command = dialog.get_command()
        if not command:
            return False

        self.plugin.services["execute_command"](command, visible=True)
        return True

    def append_to_active_table(self, names):
        active_table_handle = self.plugin.workspace.active_table_handle
        if not names or active_table_handle is None:
            return False

        state = TableState()
        state.set_items(names)
        state.set_command("append")
        state.set_target(active_table_handle)
        self.plugin.services["execute_command"](state.python_source(), visible=True)
        return True


class Plugin(BasePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}
        self.workspace = TableWorkspaceService(self)
        self.table_feature = TableFeatureService(self)
        self.table_macros = []
        self._signals_connected = False
        self._new_table_action = None
        self._macro_menu = None

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})
        if self._signals_connected:
            return
        lookup_menu_action = self.services.get("lookup_menu_action")
        if lookup_menu_action is not None:
            self._new_table_action = lookup_menu_action("window", "New Table...")
        self._macro_menu = self._ensure_macro_menu()
        self.services["mdi_area"].subWindowActivated.connect(
            self.workspace.on_subwindow_activated
        )
        self._macro_menu.aboutToShow.connect(self.rebuild_table_macros_menu)
        self.rebuild_table_macros_menu()
        self._signals_connected = True

    def get_services(self):
        return {"table_feature": self.table_feature}

    def get_menu_contributions(self):
        return [
            {
                "location": "window",
                "group": "tables",
                "order": 20,
                "name": "New Table...",
                "action": self.show_new_table_dialog,
            }
        ]

    def show_new_table_dialog(self, checked=False):
        del checked
        data_browser_service = self.services.get("namespace_view_service")
        self.table_feature.show_new_table_dialog(
            {} if data_browser_service is None else data_browser_service.namespace_view(),
            parent=self.services["ui"],
        )

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "kernel_message": self.on_kernel_message,
            "project_loaded": self.on_project_loaded,
            "project_activated": self.on_project_activated,
        }

    def get_save_data(self):
        tables = []
        for handle, table in self.workspace.iter_open_tables():
            table.capture_layout_state()
            subwindow = table.parentWidget()
            table_settings = table.table_state.normalized_state()["settings"]
            tables.append(
                {
                    "handle": handle,
                    "title": subwindow.windowTitle(),
                    "names": list(table.names),
                    "hidden": not subwindow.isVisible(),
                    "geometry": list(table_settings["geometry"])
                    if table_settings["geometry"] is not None
                    else [
                        subwindow.geometry().x(),
                        subwindow.geometry().y(),
                        subwindow.geometry().width(),
                        subwindow.geometry().height(),
                    ],
                    "column_widths": dict(table_settings.get("column_widths", {})),
                }
            )

        save_data = {
            "table_counter": self.workspace.table_counter,
            "tables": tables,
        }
        if self.workspace.active_table_handle is not None:
            save_data["active_table_handle"] = self.workspace.active_table_handle
        return save_data

    def on_enter_no_project_state(self, data):
        del data
        self.workspace.clear()
        self.table_macros = []
        self.rebuild_table_macros_menu()

    def on_project_loaded(self, data):
        session = data["session"]
        self.workspace.clear()
        saved_counter = int(session.get("table_counter", 0))
        for table_state in session.get("tables", []):
            handle = table_state["handle"]
            self.workspace.open_table(
                table_state.get("names", []),
                target=handle,
                visible_title=table_state.get("title"),
                geometry=table_state.get("geometry"),
                column_widths=table_state.get("column_widths", {}),
            )
            table = self.workspace.lookup_table(handle)
            if table is None:
                continue
            table.parentWidget().setVisible(not bool(table_state.get("hidden", False)))
        self.workspace.table_counter = saved_counter
        self.workspace.active_table_handle = session.get("active_table_handle")

    def on_project_activated(self, data):
        del data
        self.table_macros = []
        self.rebuild_table_macros_menu()
        state = TableState()
        self.plugin_queue_background_command(
            state.source_for_command("publish_table_macros"),
            silent=True,
        )

    def on_kernel_message(self, payload):
        task = payload.get("task")
        data = payload.get("data", {})
        if task == "OPEN_TABLE_REQUEST":
            self.workspace.open_table(
                data.get("names", []),
                data.get("target"),
                visible_title=data.get("title"),
                geometry=data.get("geometry"),
                column_widths=data.get("column_widths"),
            )
            return
        if task == "TABLE_DATA_RESPONSE":
            self.workspace.on_table_data(data)
            return
        if task != "WINDOW_MACROS_RESPONSE":
            return
        if data.get("kind") != "table":
            return
        self.table_macros = [
            {
                "name": macro["name"],
                "args": list(macro.get("args", [])),
            }
            for macro in data.get("macros", [])
        ]
        self.rebuild_table_macros_menu()

    def rebuild_table_macros_menu(self):
        menu = self._macro_menu
        menu.clear()
        has_project = self.services["get_current_project_dir"]() is not None
        if self._new_table_action is not None:
            self._new_table_action.setEnabled(has_project)
        if not has_project:
            menu.setEnabled(False)
            return
        if not self.table_macros:
            placeholder = menu.addAction("No Saved Table Macros")
            placeholder.setEnabled(False)
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        for macro in self.table_macros:
            macro_name = macro["name"]
            macro_args = list(macro.get("args", []))
            action = menu.addAction(macro_name)
            action.triggered.connect(
                lambda checked=False, name=macro_name, args=tuple(macro_args): (
                    self._execute_macro(name, args)
                )
            )

    def request_save_table_macro(self, table_state):
        procedures_init = self.services["get_procedures_init"]()
        if not procedures_init:
            return True
        return prompt_to_save_table_macro(
            table_state,
            parent=self.services["ui"],
            procedures_init=procedures_init,
            reload_procedures=self.services["reload_procedures"],
        )

    def plugin_queue_background_command(self, code, silent=True):
        return self.services["queue_background_command"](code, silent=silent)

    def _execute_macro(self, macro_name, macro_args):
        state = RuntimeCommandState()
        state.set_callable_invocation(macro_name, macro_args)
        self.services["execute_command"](state.python_source(), visible=True)

    def _ensure_macro_menu(self):
        if self._macro_menu is None:
            ui = self.services["ui"]
            self._macro_menu = QtWidgets.QMenu("Table Macros", ui.menuWindow)
            ui.menuWindow.addMenu(self._macro_menu)
        return self._macro_menu
