import os
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from labscript_utils.filewatcher import FileWatcher
from zmq.error import ZMQError

from hyde.paths import (
    CONNECTION_FILE,
    DEFAULT_PROJECTS_DIR,
    HYDE_DIR,
    KERNEL_LAUNCHER,
    get_project_paths,
)
from hyde.features.hyde_features import (
    format_load_project_command,
    format_new_project_command,
    format_procedures_bootstrap_code,
    format_publish_table_macros_command,
    format_quit_command,
    format_save_project_command,
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

class PersistentSubwindowFilter(QtCore.QObject):
    """Turn MDI close requests into hide requests so tool windows persist."""

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Close:
            watched.hide()
            event.ignore()
            return True
        return super().eventFilter(watched, event)

class ProjectSelectionDialog(QtWidgets.QFileDialog):
    def __init__(self, parent=None, title="Open or Create Hyde Project", accept_label="Open / Create"):
        super().__init__(parent, title, DEFAULT_PROJECTS_DIR)
        self._selected_path = None
        self.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        self.setFileMode(QtWidgets.QFileDialog.Directory)
        self.setAcceptMode(QtWidgets.QFileDialog.AcceptOpen)
        self.setLabelText(QtWidgets.QFileDialog.Accept, accept_label)
        self.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        self._file_name_edit = self.findChild(QtWidgets.QLineEdit, 'fileNameEdit')
        self._accept_button = None
        for button in self.findChildren(QtWidgets.QPushButton):
            if button.text() == self.labelText(QtWidgets.QFileDialog.Accept):
                self._accept_button = button
                break
        if self._file_name_edit is not None:
            self._file_name_edit.textChanged.connect(self.update_accept_button)
        self.currentChanged.connect(lambda _path: self.update_accept_button())
        self.directoryEntered.connect(lambda _path: self.update_accept_button())
        self.update_accept_button()

    def current_project_path(self):
        if self._file_name_edit is not None:
            text = self._file_name_edit.text().strip()
            if text:
                return os.path.abspath(self.directory().absoluteFilePath(text))
        selected_files = super().selectedFiles()
        if selected_files:
            return os.path.abspath(selected_files[0])
        return None

    def update_accept_button(self):
        if self._accept_button is None:
            return
        project_dir = self.current_project_path()
        enabled = bool(project_dir and os.path.basename(project_dir).endswith('.hy'))
        self._accept_button.setEnabled(enabled)

    def accept(self):
        project_dir = self.current_project_path()
        if project_dir is None:
            return
        self._selected_path = project_dir
        QtWidgets.QDialog.accept(self)

    def selectedFiles(self):
        if self._selected_path is not None:
            return [self._selected_path]
        return super().selectedFiles()

class HydeMainWindow(QtWidgets.QMainWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    def closeEvent(self, event):
        if self.app.shutting_down:
            return super().closeEvent(event)
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
        self.table_macros = []
        self._startup_complete = False
        
        # Load the UI
        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), 'main.ui')
        self.ui = loader.load(ui_path, HydeMainWindow(self))

        
        # Initialize Logging Window as an MDI sub-window
        self.logging_window = LoggingWindow()
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
        self.ui.actionSave.triggered.connect(self.save_project)
        self.ui.actionSave_As.triggered.connect(self.save_project_as)
        self.ui.actionSave_Copy.triggered.connect(self.save_project_copy)
        self.ui.actionQuit.triggered.connect(self.request_quit)
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
    def open_table(self, names, target=None, visible_title=None):
        """
        Open a new table or append to an existing one.
        Called via ProcessTree relay or Data Browser.
        
        Args:
            names: Variable names to display.
            target: Optional internal handle (e.g. 'Table0').
            visible_title: Optional UI label for the window.
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
        handle = target if target else f"Table{self.table_counter}"
        self.table_counter += 1
        
        table = TableWidget(handle, names, app=self)
        subwindow = self.ui.mdiArea.addSubWindow(table)
        self.tables[handle] = table
        
        # UI title vs internal handle
        title = visible_title if visible_title else f"{handle}: {', '.join(names)}"
        subwindow.setWindowTitle(title)
        
        subwindow.show()
        
        # When subwindow is destroyed, remove from registry
        subwindow.destroyed.connect(lambda: self.tables.pop(handle, None))

    def request_save_table_macro(self, table_widget):
        current_name = table_widget.default_macro_name()
        while True:
            dialog = SaveWindowDialog(default_name=current_name, parent=self.ui)
            if dialog.exec_() != QtWidgets.QDialog.Accepted:
                return False
            if dialog.choice == SaveWindowDialog.NO_SAVE:
                return True
            if dialog.choice != SaveWindowDialog.SAVE:
                return False

            macro_name = dialog.macro_name()
            current_name = macro_name
            try:
                macro_source = table_widget.recreation_function_source(macro_name)
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

    def _pick_project_dir(self, title, accept_label, suggested_name=None):
        """Show a project directory picker. Returns an absolute .hy path or None."""
        os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
        suggested_name = suggested_name or 'untitled.hy'
        suggested_path = os.path.join(DEFAULT_PROJECTS_DIR, suggested_name)
        dialog = ProjectSelectionDialog(self.ui, title=title, accept_label=accept_label)
        dialog.selectFile(suggested_path)
        if not dialog.exec_():
            return None
        project_dir = dialog.selectedFiles()[0]
        if not project_dir:
            return None
        project_dir = os.path.abspath(project_dir)
        if not project_dir.endswith('.hy'):
            QtWidgets.QMessageBox.warning(
                self.ui, "Invalid Project Directory",
                "Hyde projects must be directories ending in .hy.",
            )
            return None
        if os.path.exists(project_dir) and not os.path.isdir(project_dir):
            QtWidgets.QMessageBox.warning(
                self.ui, "Invalid Project Path",
                f"{project_dir} is not a directory.",
            )
            return None
        return project_dir

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
        project_dir = self._pick_project_dir("Create New Hyde Project", "Create New")
        if project_dir:
            overwrite = False
            if self.project_target_needs_confirmation(project_dir):
                if not self.confirm_overwrite_project(project_dir):
                    return
                overwrite = True
            self.begin_project_operation("Creating Hyde project...")
            self.execute_command(
                format_new_project_command(project_dir, load=True, overwrite=overwrite),
                visible=True,
            )

    def choose_project(self, checked=False):
        project_dir = self._pick_project_dir("Open Hyde Project", "Open")
        if project_dir:
            self.begin_project_operation("Loading Hyde project...")
            self.execute_command(format_load_project_command(project_dir), visible=True)

    def prompt_for_save_as_project(self):
        suggested_name = (
            os.path.splitext(os.path.basename(self.current_project_dir))[0] + '.hy'
            if self.current_project_dir else 'untitled.hy'
        )
        return self._pick_project_dir("Save Hyde Project As", "Save As", suggested_name=suggested_name)

    def save_project(self, checked=False):
        del checked
        if not self.current_project_dir or self.command_window is None:
            return
        self.begin_project_operation("Saving Hyde project...")
        self.execute_command(format_save_project_command(mode='save'), visible=True)

    def save_project_as(self, checked=False):
        del checked
        if not self.current_project_dir or self.command_window is None:
            return
        project_dir = self.prompt_for_save_as_project()
        if project_dir is None:
            return
        if os.path.abspath(project_dir) == os.path.abspath(self.current_project_dir):
            self.save_project()
            return
        if self.project_target_needs_confirmation(project_dir) and not self.confirm_overwrite_project(project_dir):
            return
        self.begin_project_operation("Saving Hyde project...")
        self.execute_command(format_save_project_command(project_dir, mode='save_as', overwrite=True), visible=True)

    def save_project_copy(self, checked=False):
        del checked
        if not self.current_project_dir or self.command_window is None:
            return
        project_dir = self.prompt_for_save_as_project()
        if project_dir is None:
            return
        if os.path.abspath(project_dir) == os.path.abspath(self.current_project_dir):
            self.save_project()
            return
        if self.project_target_needs_confirmation(project_dir) and not self.confirm_overwrite_project(project_dir):
            return
        self.begin_project_operation("Saving Hyde project copy...")
        self.execute_command(format_save_project_command(project_dir, mode='copy', overwrite=True), visible=True)

    def request_quit(self, checked=False):
        del checked
        if self.shutting_down:
            return
        if self.command_window is None:
            self.finalize_quit()
            return
        self.execute_command(format_quit_command(), visible=True)

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
        self.queue_background_command(format_publish_table_macros_command(), silent=True)
                
    @inmain_decorator()
    def finalize_startup(self):
        try:
            self.splash.update_text('Connecting to Jupyter Kernel Socket...')
            self._rebuild_kernel_windows()
            self.enter_no_project_state()
            if not self._startup_complete:
                self.ui.show()
                self.splash.hide()
                self._startup_complete = True
                startup_project = self.resolve_startup_project()
                if startup_project is not None:
                    QtCore.QTimer.singleShot(
                        100,
                        lambda path=startup_project: self._load_startup_project(path),
                    )
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
        self.execute_command(format_load_project_command(path), visible=True)

    @inmain_decorator()
    def on_kernel_ready(self):
        self.finalize_startup()

    @inmain_decorator()
    def on_kernel_crashed(self):
        if self.shutting_down:
            return
        self.enter_no_project_state()
        self.end_project_operation()
        if self.runtime_helper is not None:
            self.runtime_helper = None
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
                if path and (
                    self.current_project_dir is None
                    or os.path.abspath(self.current_project_dir) != os.path.abspath(path)
                ):
                    self.activate_project(path)
                self.restore_project_session()
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Load Warnings", "\\n".join(errors))

    @inmain_decorator()
    def on_visible_command_executed(self, msg):
        content = msg.get("content", {})
        if content.get("status") != "ok":
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
        QtCore.QTimer.singleShot(0, self.finalize_quit)

    def finalize_quit(self):
        if self.shutting_down:
            return
        self._mark_shutting_down()
        self.shutdown_runtime()
        self.ui.close()

    def shutdown_runtime(self):
        if self._runtime_shutdown:
            return
        self._runtime_shutdown = True
        self.stop_project_watcher()
        if self.remote_server is not None:
            self.remote_server.shutdown()
            self.remote_server = None
        kernel_client = None
        if self.command_window is not None and self.command_window.kernel_client is not None:
            kernel_client = self.command_window.kernel_client
        elif self.runtime_helper is not None and self.runtime_helper.kernel_client is not None:
            kernel_client = self.runtime_helper.kernel_client
        if kernel_client is not None:
            try:
                kernel_client.shutdown(reply=False)
            except Exception:
                pass
        if self.runtime_helper is not None:
            helper = self.runtime_helper
            self.runtime_helper = None
            helper.stop()
            helper.thread.join(timeout=2)
        if self.kernel_process is not None and self.kernel_process.poll() is None:
            try:
                self.kernel_process.wait(timeout=5)
            except Exception:
                self.kernel_process.terminate()
                try:
                    self.kernel_process.wait(timeout=5)
                except Exception:
                    pass
        self._shutdown_kernel_windows()


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
