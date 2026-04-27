import logging
import os
import time
from labscript_utils.plugins import MenuContext
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from qtutils.outputbox import BLUE, GREEN, ORANGE, RED, WHITE
from labscript_utils.filewatcher import FileWatcher
from zmq.error import ZMQError

from hyde.paths import (
    CONNECTION_FILE,
    HYDE_DIR,
    KERNEL_LAUNCHER,
    get_project_paths,
)
from hyde.features.hyde_features import (
    format_procedures_bootstrap_code,
)
from hyde.user_interface.table import TableState
from hyde.user_interface.file_dialogs import (
    HealProjectDialog,
    LoadProjectDialog,
    LoadProjectState,
    NewProjectDialog,
    QuitCommand,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
    SaveProjectCommand,
)
from hyde.user_interface.command_window import CommandWindow
from hyde.user_interface.logging_window import LoggingWindow
from hyde.user_interface.procedure_browser import ProcedureBrowser
from hyde.user_interface.data_browser import DataBrowser
from hyde.user_interface.runtime_helper import HYDE_REMOTE_PORT, RemoteRequestServer, RuntimeHelper
from hyde.user_interface.project_state import (
    clear_tables,
    try_read_history,
    try_read_session,
    restore_data_browser_state,
    restore_main_window,
    restore_tables,
    restore_tool_windows,
    write_history,
    write_session,
)
from hyde.user_interface.save_window_dialog import SaveWindowDialog
from hyde.user_interface.window_macro_store import (
    MacroStoreError,
    inspect_macro_conflict,
    write_macro_source,
)
from hyde.user_interface.plugin_tools import HydeMDIContext, HydePluginManager

qt_slot = getattr(QtCore, "Slot", QtCore.pyqtSlot)


def hyde_logger(obj=None):
    if obj is not None and hasattr(obj, "logger"):
        return obj.logger
    return logging.getLogger("hyde")

class PersistentSubwindowFilter(QtCore.QObject):
    """Turn MDI close requests into hide requests so tool windows persist."""

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Close:
            watched.hide()
            event.ignore()
            return True
        return super().eventFilter(watched, event)


def connect_logger_to_output_box(logger_name, output_box):
    class OutputBoxLogHandler(logging.Handler):
        def emit(self, record):
            message = self.format(record)
            raw_message = record.getMessage()
            # OutputBox.write() is the thread-safe entry point here: it pushes
            # text through OutputBox's internal socket/queue path and its
            # add_text() method is already marshalled onto the Qt main thread.
            if raw_message.startswith("[Hyde state] "):
                prefix, _, _ = message.partition(raw_message)
                header, rest = raw_message.split("\nstate:\n", 1)
                header = f"{prefix}{header}" if prefix else header
                state_text, python_text = rest.split("\npython:\n", 1)
                output_box.write(f"{header}\n", color=ORANGE)
                output_box.write("state:\n", color=ORANGE)
                output_box.write(f"{state_text}\n", color=GREEN)
                output_box.write("python:\n", color=ORANGE)
                output_box.write(f"{python_text}\n", color=BLUE)
            else:
                output_box.write(
                    f"{message}\n",
                    color=RED if record.levelno >= logging.WARNING else WHITE,
                )

    logger = logging.getLogger(logger_name)
    handler = OutputBoxLogHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    return handler

class HydeMainWindow(QtWidgets.QMainWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    @qt_slot()
    def _on_kernel_ready(self):
        self.app.finalize_startup()

    def closeEvent(self, event):
        if self.app._close_ready:
            return super().closeEvent(event)
        if self.app.shutting_down:
            self.app.begin_shutdown_from_close_event()
        else:
            self.app.request_quit()
        event.ignore()

class HydeApp:
    def __init__(self, qapplication, process_tree, splash, argv=None):
        self.logger = logging.getLogger("hyde")
        self.qapplication = qapplication
        self.process_tree = process_tree
        self.splash = splash
        self.argv = argv or []
        self.current_project_dir = None
        self.procedures_dir = None
        self.procedures_init = None
        self.kernel_to_child = None
        self.kernel_from_child = None
        self.kernel_process = None
        self.runtime_helper = None
        self.filewatcher = None
        self.remote_server = None
        self._subwindow_filters = []
        self.tables = {}  # {handle: TableWidget}
        self.active_table_handle = None
        self.table_counter = 0
        self.command_window = None
        self.command_subwindow = None
        self.data_browser = None
        self.data_browser_subwindow = None
        self.shutting_down = False
        self._runtime_shutdown = False
        self._close_ready = False
        self._quit_command_sent = False
        self._quit_deadline = None
        self.table_macros = []
        self._startup_complete = False
        self.plugin_manager = HydePluginManager(
            plugin_package="hyde.user_interface",
            plugins_dir=os.path.dirname(os.path.dirname(__file__)),
            logger=logging.getLogger("hyde"),
        )
        
        # Load the UI
        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), 'main.ui')
        self.ui = loader.load(ui_path, HydeMainWindow(self))
        self.ui.mdiArea.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.mdiArea.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.menuFile.clear()
        self.ui.menuWindow.clear()
        self.plugin_manager.discover_modules()
        self.plugin_manager.instantiate_plugins()
        self.setup_plugins()
        self._ensure_static_plugin_windows()
        self.logging_handler = connect_logger_to_output_box(
            "hyde",
            self.logging_window.output_box,
        )

        # Track active subwindow for "Active Table" rule
        self.ui.mdiArea.subWindowActivated.connect(self._on_subwindow_activated)
        self.ui.menuTableMacros.aboutToShow.connect(self.rebuild_table_macros_menu)
        self.qapplication.aboutToQuit.connect(self._mark_shutting_down)

        try:
            self.remote_server = RemoteRequestServer(self, HYDE_REMOTE_PORT)
        except ZMQError as exc:
            hyde_logger(self).warning(
                "Could not start lyse-compatible remote listener: %s", exc
            )
            self.remote_server = None
        self.start_kernel_runtime()

    def build_plugin_services(self):
        return {
            "app": self,
            "ui": self.ui,
            "mdi_area": self.ui.mdiArea,
            "menu_context": getattr(self, "menu_context", None),
            "mdi_context": getattr(self, "mdi_context", None),
            "execute_command": self.execute_command,
            "queue_background_command": self.queue_background_command,
            "open_table": self.open_table,
            "request_quit": self.request_quit,
            "choose_new_project": self.choose_new_project,
            "choose_project": self.choose_project,
            "choose_heal_project": self.choose_heal_project,
            "save_project": self.save_project,
            "save_project_as": self.save_project_as,
            "save_project_copy": self.save_project_copy,
            "show_new_table_dialog": self.show_new_table_dialog,
            "show_window": self.show_plugin_window,
            "on_visible_command_executed": self.on_visible_command_executed,
            "request_window_macros": self.request_window_macros,
        }

    def setup_plugins(self):
        self.menu_context = MenuContext(logger=logging.getLogger("hyde"))
        self.menu_context.register_location("file", self.ui.menuFile)
        self.menu_context.register_location("window", self.ui.menuWindow)

        self.mdi_context = HydeMDIContext(
            self.ui.mdiArea,
            configure_subwindow=self.configure_persistent_subwindow,
            created_callback=self._register_plugin_window,
        )

        self.plugin_manager.register_context("menus", self.menu_context)
        self.plugin_manager.register_context("mdi", self.mdi_context)

        plugin_data = {
            "services": self.plugin_manager.collect_services(
                self.build_plugin_services()
            ),
        }
        self.plugin_manager.setup_contexts(plugin_data)
        self.menu_context.render()
        if getattr(self.ui, "menuTableMacros", None) is not None:
            self.ui.menuWindow.addMenu(self.ui.menuTableMacros)
        self._bind_plugin_action_aliases()
        self.plugin_manager.setup_complete(plugin_data)

    def _bind_plugin_action_aliases(self):
        mapping = {
            "actionNew": (self.ui.menuFile, "New..."),
            "actionLoad": (self.ui.menuFile, "Load..."),
            "actionHeal_Project": (self.ui.menuFile, "Heal Project..."),
            "actionSave": (self.ui.menuFile, "Save"),
            "actionSave_As": (self.ui.menuFile, "Save As..."),
            "actionSave_Copy": (self.ui.menuFile, "Save a Copy..."),
            "actionQuit": (self.ui.menuFile, "Quit"),
            "actionCommandWindow": (self.ui.menuWindow, "Command Window"),
            "actionLogging": (self.ui.menuWindow, "Logging"),
            "actionProcedures": (self.ui.menuWindow, "Procedures"),
            "actionDataBrowser": (self.ui.menuWindow, "Data Browser"),
            "actionNew_Table": (self.ui.menuWindow, "New Table..."),
        }
        for attr_name, (menu, text) in mapping.items():
            setattr(self.ui, attr_name, self._find_menu_action(menu, text))

    def _find_menu_action(self, menu, text):
        for action in menu.actions():
            if action.text() == text:
                return action
        return None

    def _register_plugin_window(self, key, widget, subwindow):
        mapping = {
            "logging": ("logging_window", "logging_subwindow"),
            "procedures": ("procedure_browser", "procedures_subwindow"),
            "command_window": ("command_window", "command_subwindow"),
            "data_browser": ("data_browser", "data_browser_subwindow"),
        }
        widget_attr, subwindow_attr = mapping.get(key, (None, None))
        if widget_attr is None:
            return
        setattr(self, widget_attr, widget)
        setattr(self, subwindow_attr, subwindow)

    def _ensure_static_plugin_windows(self):
        self.mdi_context.ensure_widget("logging")
        self.logging_subwindow.hide()
        self.mdi_context.ensure_widget("procedures")
        self.procedures_subwindow.hide()

    def show_plugin_window(self, key):
        return self.mdi_context.show(key)

    def emit_plugin_event(self, name, data=None):
        payload = {} if data is None else data
        logger = logging.getLogger("hyde")
        for handler in self.plugin_manager.get_event_handlers(name):
            try:
                handler(payload)
            except Exception:
                logger.exception(
                    "Plugin event handler failed for '%s'.", name
                )
        return payload

    @inmain_decorator()
    def show_command_window(self, checked=False):
        del checked
        self.show_plugin_window("command_window")

    @inmain_decorator()
    def show_logging_window(self, checked=False):
        del checked
        self.show_plugin_window("logging")

    @inmain_decorator()
    def show_procedures_window(self, checked=False):
        del checked
        self.show_plugin_window("procedures")

    @inmain_decorator()
    def show_data_browser(self, checked=False):
        del checked
        self.show_plugin_window("data_browser")

    def start_kernel_runtime(self):
        hyde_logger(self).info(
            "Starting Hyde kernel runtime with connection_file=%s", CONNECTION_FILE
        )
        if os.path.exists(CONNECTION_FILE):
            hyde_logger(self).debug(
                "Removing stale kernel connection file %s before restart.",
                CONNECTION_FILE,
            )
            os.remove(CONNECTION_FILE)
        self.kernel_to_child, self.kernel_from_child, self.kernel_process = self.process_tree.subprocess(
            KERNEL_LAUNCHER,
            args=["-f", CONNECTION_FILE],
            output_redirection_port=self.logging_window.port,
            startup_timeout=60,
        )
        hyde_logger(self).info(
            "Started Hyde kernel subprocess pid=%s with output redirection port=%s",
            getattr(self.kernel_process, "pid", None),
            self.logging_window.port,
        )
        self.runtime_helper = RuntimeHelper(
            self,
            CONNECTION_FILE,
            self.kernel_from_child,
            self.kernel_process,
        )
        self.runtime_helper.start()

    def stop_project_watcher(self):
        if self.filewatcher is not None:
            self.filewatcher.stop()
            self.filewatcher = None

    def restart_project_watcher(self):
        self.stop_project_watcher()
        if self.current_project_dir is None or self.procedures_dir is None or self.procedures_init is None:
            return
        watched_files = [self.procedures_init] if os.path.exists(self.procedures_init) else []
        self.filewatcher = FileWatcher(
            self.on_procedure_change,
            files=watched_files,
            folders=[self.procedures_dir],
            hashable_types=[".py"],
            interval=0.5,
        )

    def queue_background_command(self, code, silent=True):
        if self.runtime_helper is None:
            return
        self.runtime_helper.enqueue_execute(code, silent=silent)

    def on_procedure_change(self, name, info, event=None):
        del info
        if event == "original":
            return
        if name != "all" and not name.endswith(".py"):
            return
        if self.current_project_dir is None:
            return
        self.queue_background_command(
            format_procedures_bootstrap_code(
                self.current_project_dir,
                os.path.dirname(HYDE_DIR),
                reset_namespace=False,
            ),
            silent=True,
        )

    def execute_command(self, code, visible=True):
        """
        Execute a command in the kernel with a choice of visibility policy.
        
        Visible commands appear in the console history and history pane.
        Muted commands (visible=False) execute silently to avoid console clutter.
        """
        if visible:
            if self.command_window:
                self.command_window.execute(code, hidden=False)
            return
        self.queue_background_command(code, silent=True)

    @inmain_decorator()
    def open_table(self, names, target=None, visible_title=None, geometry=None, column_widths=None):
        """
        Open a new table or append to an existing one.
        Called via ProcessTree relay or Data Browser.
        
        Args:
            names: Variable names to display.
            target: Optional internal handle (e.g. 'Table0').
            visible_title: Optional UI label for the window.
            geometry: Optional saved subwindow geometry.
            column_widths: Optional saved widths keyed by column name.
        """
        from hyde.user_interface.table import TableWidget

        if target is not None and target in self.tables:
            table = self.tables[target]
            table.append_columns(names)
            table.parentWidget().show()
            table.parentWidget().setFocus()
            table.parentWidget().raise_()
            return

        # Create new table
        if target is not None:
            handle = target
        else:
            handle = visible_title or f"Table{self.table_counter}"
            self.table_counter += 1
        
        table = TableWidget(
            handle,
            names,
            app=self,
            visible_title=visible_title,
            geometry=geometry,
            column_widths=column_widths,
        )
        subwindow = self.ui.mdiArea.addSubWindow(table)
        table.bind_subwindow(subwindow)
        self.tables[handle] = table
        
        # UI title vs internal handle
        title = visible_title if visible_title else f"{handle}: {', '.join(names)}"
        subwindow.setWindowTitle(title)
        
        subwindow.show()
        
        # When subwindow is destroyed, remove from registry
        subwindow.destroyed.connect(lambda: self.tables.pop(handle, None))

    def request_save_table_macro(self, table_state):
        while True:
            dialog = SaveWindowDialog(table_state=table_state, parent=self.ui)
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
                QtWidgets.QMessageBox.warning(self.ui, "Invalid Macro Name", str(exc))
                continue

            conflict = inspect_macro_conflict(self.procedures_init, macro_name)
            if conflict is not None:
                response = QtWidgets.QMessageBox.question(
                    self.ui,
                    "Overwrite Recreation Macro",
                    f"A function named {macro_name} already exists in procedures/__init__.py.\n\n"
                    "Overwrite that function?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No,
                )
                if response != QtWidgets.QMessageBox.Yes:
                    continue

            write_macro_source(self.procedures_init, macro_name, macro_source)
            self.reload_procedures()
            return True

    def rebuild_table_macros_menu(self):
        menu = self.ui.menuTableMacros
        menu.clear()
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
                lambda checked=False, command=invocation: self.execute_command(command, visible=True)
            )

    def show_new_table_dialog(self):
        """Opens the New Table dialog with current namespace metadata."""
        from hyde.user_interface.new_table_dialog import NewTableDialog

        metadata = (
            self.data_browser.namespace_view()
            if hasattr(self, 'data_browser')
            else {}
        )
        
        dialog = NewTableDialog(metadata, parent=self.ui)
        if dialog.exec_():
            command = dialog.get_command()
            if command:
                # Use visible execution for setup actions
                self.execute_command(command, visible=True)

    def _on_subwindow_activated(self, subwindow):
        if subwindow is None:
            return
        widget = subwindow.widget()
        from hyde.user_interface.table import TableWidget
        if isinstance(widget, TableWidget):
            self.active_table_handle = widget.handle
        else:
            self.active_table_handle = None

    def configure_persistent_subwindow(self, subwindow):
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        event_filter = PersistentSubwindowFilter(subwindow)
        subwindow.installEventFilter(event_filter)
        self._subwindow_filters.append(event_filter)

    def resolve_startup_project(self):
        if not self.argv:
            return None
        candidate = os.path.abspath(self.argv[0])
        if candidate.endswith('.hy') and os.path.isdir(candidate):
            return candidate
        return None

    def confirm_overwrite_project(self, project_dir):
        response = QtWidgets.QMessageBox.question(
            self.ui,
            "Overwrite Project",
            (
                f"{project_dir} already exists.\n\n"
                "Overwrite the existing path?"
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def project_target_needs_confirmation(self, project_dir):
        if not os.path.exists(project_dir):
            return False
        if not os.path.isdir(project_dir):
            return True
        with os.scandir(project_dir) as entries:
            return any(entries)

    def begin_project_operation(self, label):
        self.set_project_status_message(label)

    def set_project_status_message(self, label):
        self.ui.statusbar.showMessage(label)

    def clear_project_status_message(self):
        self.ui.statusbar.clearMessage()

    def end_project_operation(self):
        self.clear_project_status_message()

    def _set_project_action_state(self, has_project):
        self.ui.actionNew.setEnabled(True)
        self.ui.actionLoad.setEnabled(True)
        self.ui.actionHeal_Project.setEnabled(True)
        self.ui.actionLogging.setEnabled(True)
        self.ui.actionQuit.setEnabled(True)
        self.ui.actionSave.setEnabled(has_project)
        self.ui.actionSave_As.setEnabled(has_project)
        self.ui.actionSave_Copy.setEnabled(has_project)
        self.ui.actionCommandWindow.setEnabled(has_project)
        self.ui.actionProcedures.setEnabled(has_project)
        self.ui.actionDataBrowser.setEnabled(has_project)
        self.ui.actionNew_Table.setEnabled(has_project)
        self.ui.menuTableMacros.setEnabled(has_project and bool(self.table_macros))

    def choose_new_project(self, checked=False):
        del checked
        NewProjectDialog(self).run()

    def choose_project(self, checked=False):
        del checked
        LoadProjectDialog(self).run()

    def choose_heal_project(self, checked=False):
        del checked
        HealProjectDialog(self).run()

    def save_project(self, checked=False):
        del checked
        SaveProjectCommand(self).run()

    def save_project_as(self, checked=False):
        del checked
        SaveAsProjectDialog(self).run()

    def save_project_copy(self, checked=False):
        del checked
        SaveCopyProjectDialog(self).run()

    def request_quit(self, checked=False):
        del checked
        hyde_logger(self).warning(
            "GUI request_quit invoked; dispatching visible Hyde quit command."
        )
        QuitCommand(self).run()

    @inmain_decorator()
    def enter_no_project_state(self):
        self.current_project_dir = None
        self.procedures_dir = None
        self.procedures_init = None
        self.stop_project_watcher()
        clear_tables(self)
        self.table_macros = []
        self.rebuild_table_macros_menu()
        self.procedure_browser.set_procedures_dir(None)
        self.ui.setWindowTitle("Hyde")
        if self.command_subwindow is not None:
            self.command_subwindow.hide()
        if self.procedures_subwindow is not None:
            self.procedures_subwindow.hide()
        if self.data_browser_subwindow is not None:
            self.data_browser_subwindow.hide()
        self._set_project_action_state(False)
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event("enter_no_project_state", {})

    @inmain_decorator()
    def activate_project(self, project_dir):
        if not project_dir:
            return
        project_dir = os.path.abspath(project_dir)
        if self.current_project_dir is not None and os.path.abspath(self.current_project_dir) == project_dir:
            return
        self.current_project_dir, self.procedures_dir, self.procedures_init = get_project_paths(project_dir)
        self.procedure_browser.set_procedures_dir(self.procedures_dir)
        self.ui.setWindowTitle(f"Hyde - {os.path.basename(self.current_project_dir)}")
        self.restart_project_watcher()
        self._set_project_action_state(True)
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event(
                "project_activated",
                {
                    "project_dir": self.current_project_dir,
                    "procedures_dir": self.procedures_dir,
                },
            )

    def reload_procedures(self):
        if self.current_project_dir is None:
            return
        self.queue_background_command(
            format_procedures_bootstrap_code(
                self.current_project_dir,
                os.path.dirname(HYDE_DIR),
                reset_namespace=False,
            ),
            silent=True,
        )

    def request_window_macros(self, kind='table'):
        if kind != 'table':
            return
        state = TableState()
        self.queue_background_command(
            state.source_for_command("publish_table_macros"),
            silent=True,
        )
                
    @inmain_decorator()
    def finalize_startup(self):
        try:
            startup_project = None
            if not self._startup_complete:
                hyde_logger(self).info("Finalizing Hyde startup after kernel ready.")
                self.ui.show()
                self.splash.hide()
                self._startup_complete = True
                startup_project = self.resolve_startup_project()
            self.set_project_status_message("Connecting to Jupyter Kernel Socket...")
            self._rebuild_kernel_windows()
            self.enter_no_project_state()
            if startup_project is not None:
                QtCore.QTimer.singleShot(
                    100,
                    lambda path=startup_project: self._load_startup_project(path),
                )
            else:
                self.clear_project_status_message()
        except Exception:
            hyde_logger(self).exception("Hyde finalize_startup failed unexpectedly.")

    def _shutdown_kernel_windows(self):
        hyde_logger(self).debug(
            "Shutting down kernel windows: command_window=%s data_browser=%s",
            self.command_window is not None,
            self.data_browser is not None,
        )
        if self.data_browser is not None:
            self.mdi_context.destroy("data_browser")
        if self.command_window is not None:
            self.mdi_context.destroy("command_window")

    def _rebuild_kernel_windows(self):
        hyde_logger(self).info("Rebuilding kernel-backed Hyde windows.")
        self._shutdown_kernel_windows()
        self.mdi_context.ensure_widget("command_window")
        self.mdi_context.ensure_widget("data_browser")

    def _load_startup_project(self, path):
        self.begin_project_operation("Loading Hyde project...")
        state = LoadProjectState()
        state.set_project_dir(path)
        self.execute_command(state.python_source(), visible=True)

    @inmain_decorator()
    def on_kernel_ready(self):
        hyde_logger(self).info(
            "Hyde kernel reported ready for pid=%s",
            getattr(self.kernel_process, "pid", None),
        )
        self.finalize_startup()

    @inmain_decorator()
    def on_kernel_crashed(self):
        if self.shutting_down:
            hyde_logger(self).warning(
                "Ignoring on_kernel_crashed because Hyde is already shutting down."
            )
            return
        kernel_process = getattr(self, "kernel_process", None)
        hyde_logger(self).error(
            "Hyde detected kernel crash: pid=%s returncode=%s quit_command_sent=%s current_project_dir=%s",
            getattr(kernel_process, "pid", None),
            None if kernel_process is None else kernel_process.poll(),
            getattr(self, "_quit_command_sent", None),
            getattr(self, "current_project_dir", None),
        )
        self._quit_command_sent = False
        self.enter_no_project_state()
        self.end_project_operation()
        if self.runtime_helper is not None:
            helper = self.runtime_helper
            self.runtime_helper = None
            helper.stop()
        self._shutdown_kernel_windows()
        QtWidgets.QMessageBox.warning(
            self.ui,
            "Kernel Crashed",
            "The IPython execution kernel died unexpectedly. Hyde is reconnecting to a fresh kernel.",
        )
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event("kernel_crashed", {})
        self.start_kernel_runtime()

    @inmain_decorator()
    def on_table_data(self, data):
        request_id = data.get('request_id')
        table_data = data.get('data', {})
        for table in self.tables.values():
            table.on_data_received(table_data, request_id)

    @inmain_decorator()
    def on_project_state_result(self, data):
        operation = data.get('operation')
        success = bool(data.get('success', False))
        path = data.get('path')
        errors = list(data.get('errors', []))

        self.end_project_operation()

        if operation == 'save':
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Save Warnings", "\\n".join(errors))
            if success:
                write_session(self, path)
                if self.command_window is not None:
                    write_history(self.command_window, path)
            
        elif operation == 'new':
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Creation Warnings", "\\n".join(errors))

        elif operation == 'load':
            if success:
                self.restore_project_session()
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Load Warnings", "\\n".join(errors))
        elif operation == 'heal':
            if success and errors:
                QtWidgets.QMessageBox.information(self.ui, "Project Heal Complete", "\\n".join(errors))
            elif not success and errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Heal Warnings", "\\n".join(errors))

    @inmain_decorator()
    def on_visible_command_executed(self, msg):
        content = msg.get("content", {})
        if content.get("status") != "ok":
            self._quit_command_sent = False
            self.end_project_operation()

    @inmain_decorator()
    def update_table_macros(self, macros):
        self.table_macros = [
            {
                "name": macro["name"],
                "args": list(macro.get("args", [])),
            }
            for macro in macros
        ]
        self.rebuild_table_macros_menu()
        self._set_project_action_state(self.current_project_dir is not None)

    def _mark_shutting_down(self):
        hyde_logger(self).warning("Qt aboutToQuit received; marking Hyde as shutting down.")
        self.shutting_down = True

    @inmain_decorator()
    def request_gui_quit(self):
        hyde_logger(self).warning("Kernel requested GUI quit; closing Hyde main window.")
        self.shutting_down = True
        self.ui.close()

    def finalize_quit(self):
        if self._close_ready:
            return
        hyde_logger(self).warning("Finalizing Hyde quit by closing the main window.")
        self.shutting_down = True
        self.ui.close()

    def begin_shutdown_from_close_event(self):
        if self._runtime_shutdown:
            return
        hyde_logger(self).warning("Beginning Hyde runtime shutdown from close event.")
        self.shutdown_runtime()

    def shutdown_runtime(self):
        if self._runtime_shutdown:
            return
        kernel_process = getattr(self, "kernel_process", None)
        hyde_logger(self).warning(
            "Starting Hyde runtime shutdown: kernel_pid=%s kernel_returncode=%s quit_command_sent=%s",
            getattr(kernel_process, "pid", None),
            None if kernel_process is None else kernel_process.poll(),
            getattr(self, "_quit_command_sent", None),
        )
        self._runtime_shutdown = True
        self._quit_deadline = time.monotonic() + 2.0
        self.stop_project_watcher()
        if self.remote_server is not None:
            hyde_logger(self).debug("Shutting down Hyde remote request server.")
            self.remote_server.shutdown()
            self.remote_server = None
        helper = self.runtime_helper
        if helper is not None and helper.kernel_client is not None:
            try:
                hyde_logger(self).debug("Requesting kernel_client shutdown(reply=False).")
                helper.kernel_client.shutdown(reply=False)
            except Exception:
                hyde_logger(self).exception("Kernel client shutdown request failed.")
        elif self.command_window is not None and self.command_window.kernel_client is not None:
            try:
                hyde_logger(self).debug(
                    "Requesting command_window kernel_client shutdown(reply=False)."
                )
                self.command_window.kernel_client.shutdown(reply=False)
            except Exception:
                hyde_logger(self).exception(
                    "Command window kernel client shutdown request failed."
                )
        if self.runtime_helper is not None:
            self.runtime_helper = None
            helper.stop()
        self._shutdown_kernel_windows()
        QtCore.QTimer.singleShot(0, self._complete_shutdown_runtime)

    def _complete_shutdown_runtime(self):
        if self.runtime_helper is not None:
            return
        kernel_running = self.kernel_process is not None and self.kernel_process.poll() is None
        quit_deadline = self._quit_deadline
        if kernel_running and quit_deadline is not None and time.monotonic() < quit_deadline:
            hyde_logger(self).debug(
                "Waiting for kernel pid=%s to exit cleanly before forcing shutdown.",
                getattr(self.kernel_process, "pid", None),
            )
            QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
            return
        if kernel_running:
            hyde_logger(self).warning(
                "Kernel pid=%s still running after quit deadline; terminating it.",
                getattr(self.kernel_process, "pid", None),
            )
            self.kernel_process.terminate()
            if self.kernel_process.poll() is None:
                QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
                return
        hyde_logger(self).warning("Hyde runtime shutdown complete; allowing main window close.")
        self._close_ready = True
        self.ui.close()


    def restore_project_session(self):
        warnings = []
        history_entries, history_error = try_read_history(self.current_project_dir)
        if history_error:
            warnings.append(f"terminal/history.py: {history_error}")
        if self.command_window is not None:
            self.command_window.restore_history_entries(history_entries)
        session, session_error = try_read_session(self.current_project_dir)
        if session_error:
            warnings.append(f"session.toml: {session_error}")
        if warnings:
            QtWidgets.QMessageBox.warning(
                self.ui,
                "Project Session Restore Warnings",
                "\n".join(warnings),
            )
        clear_tables(self)
        if not session:
            return
        restore_main_window(self, session)
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event("project_loaded", {"session": session})
        else:
            restore_data_browser_state(self, session)
            restore_tables(self, session)
            restore_tool_windows(self, session)
