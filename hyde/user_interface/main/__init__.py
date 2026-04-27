import logging
import os
import time
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

qt_slot = getattr(QtCore, "Slot", QtCore.pyqtSlot)

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
        
        # Load the UI
        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), 'main.ui')
        self.ui = loader.load(ui_path, HydeMainWindow(self))
        self.ui.mdiArea.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.mdiArea.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        
        # Initialize Logging Window as an MDI sub-window
        self.logging_window = LoggingWindow()
        self.logging_handler = connect_logger_to_output_box("hyde", self.logging_window.output_box)
        self.logging_subwindow = self.ui.mdiArea.addSubWindow(self.logging_window)
        self.configure_persistent_subwindow(self.logging_subwindow)
        self.logging_subwindow.resize(800, 600)
        self.logging_subwindow.hide()

        # Initialize Procedure Browser as an MDI sub-window (no project dir yet)
        self.procedure_browser = ProcedureBrowser(procedures_dir=None)
        self.procedures_subwindow = self.ui.mdiArea.addSubWindow(self.procedure_browser)
        self.configure_persistent_subwindow(self.procedures_subwindow)
        self.procedures_subwindow.resize(300, 500)
        self.procedures_subwindow.hide()

        # Track active subwindow for "Active Table" rule
        self.ui.mdiArea.subWindowActivated.connect(self._on_subwindow_activated)
        
        # Connect Application events
        self.ui.actionNew.triggered.connect(self.choose_new_project)
        self.ui.actionLoad.triggered.connect(self.choose_project)
        self.ui.actionHeal_Project.triggered.connect(self.choose_heal_project)
        self.ui.actionSave.triggered.connect(self.save_project)
        self.ui.actionSave_As.triggered.connect(self.save_project_as)
        self.ui.actionSave_Copy.triggered.connect(self.save_project_copy)
        self.ui.actionQuit.triggered.connect(self.ui.close)
        self.ui.actionCommandWindow.triggered.connect(self.show_command_window)
        self.ui.actionLogging.triggered.connect(self.show_logging_window)
        self.ui.actionProcedures.triggered.connect(self.show_procedures_window)
        self.ui.actionDataBrowser.triggered.connect(self.show_data_browser)
        self.ui.actionNew_Table.triggered.connect(self.show_new_table_dialog)
        self.ui.menuTableMacros.aboutToShow.connect(self.rebuild_table_macros_menu)
        self.qapplication.aboutToQuit.connect(self._mark_shutting_down)

        try:
            self.remote_server = RemoteRequestServer(self, HYDE_REMOTE_PORT)
        except ZMQError as exc:
            print(f"[Hyde] Could not start lyse-compatible remote listener: {exc}")
            self.remote_server = None
        self.start_kernel_runtime()

    @inmain_decorator()
    def show_command_window(self, checked=False):
        self.command_subwindow.show()
        self.command_subwindow.setFocus()
        self.command_subwindow.raise_()

    @inmain_decorator()
    def show_logging_window(self, checked=False):
        self.logging_subwindow.show()
        self.logging_subwindow.setFocus()
        self.logging_subwindow.raise_()

    @inmain_decorator()
    def show_procedures_window(self, checked=False):
        self.procedures_subwindow.show()
        self.procedures_subwindow.setFocus()
        self.procedures_subwindow.raise_()

    @inmain_decorator()
    def show_data_browser(self, checked=False):
        self.data_browser_subwindow.show()
        self.data_browser_subwindow.setFocus()
        self.data_browser_subwindow.raise_()

    def start_kernel_runtime(self):
        if os.path.exists(CONNECTION_FILE):
            os.remove(CONNECTION_FILE)
        self.kernel_to_child, self.kernel_from_child, self.kernel_process = self.process_tree.subprocess(
            KERNEL_LAUNCHER,
            args=["-f", CONNECTION_FILE],
            output_redirection_port=self.logging_window.port,
            startup_timeout=60,
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
        self.request_window_macros('table')

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
            import traceback
            traceback.print_exc()

    def _shutdown_kernel_windows(self):
        if self.data_browser is not None:
            self.data_browser.shutdown()
            if self.data_browser_subwindow is not None:
                self.ui.mdiArea.removeSubWindow(self.data_browser)
            self.data_browser.deleteLater()
            self.data_browser = None
            self.data_browser_subwindow = None
        if self.command_window is not None:
            self.command_window.shutdown()
            if self.command_subwindow is not None:
                self.ui.mdiArea.removeSubWindow(self.command_window)
            self.command_window.deleteLater()
            self.command_window = None
            self.command_subwindow = None

    def _rebuild_kernel_windows(self):
        self._shutdown_kernel_windows()
        self.command_window = CommandWindow(connection_file=CONNECTION_FILE)
        self.command_window.executed.connect(self.on_visible_command_executed)
        self.command_subwindow = self.ui.mdiArea.addSubWindow(self.command_window)
        self.configure_persistent_subwindow(self.command_subwindow)

        self.data_browser = DataBrowser(connection_file=CONNECTION_FILE, app=self)
        self.data_browser_subwindow = self.ui.mdiArea.addSubWindow(self.data_browser)
        self.configure_persistent_subwindow(self.data_browser_subwindow)

    def _load_startup_project(self, path):
        self.begin_project_operation("Loading Hyde project...")
        state = LoadProjectState()
        state.set_project_dir(path)
        self.execute_command(state.python_source(), visible=True)

    @inmain_decorator()
    def on_kernel_ready(self):
        self.finalize_startup()

    @inmain_decorator()
    def on_kernel_crashed(self):
        if self.shutting_down:
            return
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
        self.shutting_down = True

    @inmain_decorator()
    def request_gui_quit(self):
        self.shutting_down = True
        self.ui.close()

    def finalize_quit(self):
        if self._close_ready:
            return
        self.shutting_down = True
        self.ui.close()

    def begin_shutdown_from_close_event(self):
        if self._runtime_shutdown:
            return
        self.shutdown_runtime()

    def shutdown_runtime(self):
        if self._runtime_shutdown:
            return
        self._runtime_shutdown = True
        self._quit_deadline = time.monotonic() + 2.0
        self.stop_project_watcher()
        if self.remote_server is not None:
            self.remote_server.shutdown()
            self.remote_server = None
        helper = self.runtime_helper
        if helper is not None and helper.kernel_client is not None:
            try:
                helper.kernel_client.shutdown(reply=False)
            except Exception:
                pass
        elif self.command_window is not None and self.command_window.kernel_client is not None:
            try:
                self.command_window.kernel_client.shutdown(reply=False)
            except Exception:
                pass
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
            QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
            return
        if kernel_running:
            self.kernel_process.terminate()
            if self.kernel_process.poll() is None:
                QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
                return
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
        restore_data_browser_state(self, session)
        restore_tables(self, session)
        restore_tool_windows(self, session)
