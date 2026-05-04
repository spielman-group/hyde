from labscript_utils.plugins import BasePlugin

from hyde.user_interface.table import (
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
            handle = visible_title or f"Table{self.table_counter}"
            self.table_counter += 1

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
        configure_subwindow = self.plugin.services.get(
            "configure_persistent_subwindow"
        )
        if configure_subwindow is not None:
            configure_subwindow(subwindow)
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

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})
        if self._signals_connected:
            return
        self.services["mdi_area"].subWindowActivated.connect(
            self.workspace.on_subwindow_activated
        )
        self.services["ui"].menuTableMacros.aboutToShow.connect(
            self.rebuild_table_macros_menu
        )
        self.rebuild_table_macros_menu()
        self._signals_connected = True

    def get_services(self):
        return {
            "table_feature": self.table_feature,
            "table_workspace": self.workspace,
        }

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
        self.table_feature.show_new_table_dialog(
            self.services["get_namespace_view"](),
            parent=self.services["ui"],
        )

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "project_loaded": self.on_project_loaded,
            "project_activated": self.on_project_activated,
            "window_macros_updated": self.on_window_macros_updated,
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

    def on_window_macros_updated(self, data):
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
        menu = self.services["ui"].menuTableMacros
        menu.clear()
        has_project = self.services["get_current_project_dir"]() is not None
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
            invocation = f"{macro_name}({', '.join(macro_args)})"
            action = menu.addAction(macro_name)
            action.triggered.connect(
                lambda checked=False, command=invocation: self.services[
                    "execute_command"
                ](command, visible=True)
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
        self.services["queue_background_command"](code, silent=silent)
