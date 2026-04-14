import os
import shutil
import threading
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui

from hyde.paths import (
    EXECUTION_CONTROLLER, 
    CONNECTION_FILE, 
    DEFAULT_PROJECTS_DIR,
    DEFAULT_PROJECT_TEMPLATE,
    DEFAULT_PROCEDURES_INIT_TEMPLATE,
    get_project_paths,
)
from hyde.user_interface.command_window import CommandWindow
from hyde.user_interface.logging_window import LoggingWindow
from hyde.user_interface.procedure_browser import ProcedureBrowser
from hyde.user_interface.data_browser import DataBrowser
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

class HydeApp:
    def __init__(self, qapplication, process_tree, splash, argv=None):
        self.qapplication = qapplication
        self.process_tree = process_tree
        self.splash = splash
        self.argv = argv or []
        self.current_project_dir = None
        self.procedures_dir = None
        self.procedures_init = None
        self.to_worker = None
        self.from_worker = None
        self.worker = None
        self._subwindow_filters = []
        self.tables = {}  # {handle: TableWidget}
        self.active_table_handle = None
        self.table_counter = 0
        self.command_window = None
        self.command_subwindow = None
        self.data_browser = None
        self.data_browser_subwindow = None
        self._procedures_ready = False
        self._pending_project_state_load = False
        self._pending_session_restore = False
        self._pending_project_switch = None
        self.shutting_down = False
        self.table_macros = []
        
        # Load the UI
        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), 'main.ui')
        self.ui = loader.load(ui_path, HydeMainWindow(self))

        
        selection = self.resolve_startup_project()
        if selection is None:
            self.splash.hide()
            QtCore.QTimer.singleShot(0, self.qapplication.quit)
            return
        project_dir, create_if_missing = selection

        # Initialize Logging Window as an MDI sub-window
        self.logging_window = LoggingWindow()
        self.logging_subwindow = self.ui.mdiArea.addSubWindow(self.logging_window)
        self.configure_persistent_subwindow(self.logging_subwindow)
        self.logging_subwindow.resize(800, 600)
        self.logging_subwindow.hide()

        # Initialize Procedure Browser as an MDI sub-window
        initial_procedures_dir = get_project_paths(project_dir)[1]
        self.procedure_browser = ProcedureBrowser(procedures_dir=initial_procedures_dir)
        self.procedures_subwindow = self.ui.mdiArea.addSubWindow(self.procedure_browser)
        self.configure_persistent_subwindow(self.procedures_subwindow)
        self.procedures_subwindow.resize(300, 500)
        self.procedures_subwindow.hide()

        self.load_project(project_dir, create_if_missing=create_if_missing)
        
        # Spawn the Watchdog execution subprocess
        self.to_worker, self.from_worker, self.worker = self.process_tree.subprocess(
            EXECUTION_CONTROLLER,
            args=[CONNECTION_FILE],
            output_redirection_port=self.logging_window.port
        )
        self.configure_execution_watchdog()
        
        # Start daemon thread listening to Watchdog alerts
        self.listener_thread = threading.Thread(target=self.listen_for_watchdog)
        self.listener_thread.daemon = True
        self.listener_thread.start()
        
        # Track active subwindow for "Active Table" rule
        self.ui.mdiArea.subWindowActivated.connect(self._on_subwindow_activated)
        
        # Connect Application events
        self.ui.actionNew.triggered.connect(self.choose_project)
        self.ui.actionLoad.triggered.connect(self.choose_project)
        self.ui.actionSave.triggered.connect(self.save_project)
        self.ui.actionSave_As.triggered.connect(self.save_project_as)
        self.ui.actionQuit.triggered.connect(self.qapplication.quit)
        self.ui.actionCommandWindow.triggered.connect(self.show_command_window)
        self.ui.actionLogging.triggered.connect(self.show_logging_window)
        self.ui.actionProcedures.triggered.connect(self.show_procedures_window)
        self.ui.actionDataBrowser.triggered.connect(self.show_data_browser)
        self.ui.actionNew_Table.triggered.connect(self.show_new_table_dialog)
        self.ui.menuTableMacros.aboutToShow.connect(self.rebuild_table_macros_menu)
        self.qapplication.aboutToQuit.connect(self._mark_shutting_down)
        self.qapplication.aboutToQuit.connect(self.shutdown_watchdog)

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

    def execute_command(self, code, visible=True):
        """
        Execute a command in the kernel with a choice of visibility policy.
        
        Visible commands appear in the console history and history pane.
        Muted commands (visible=False) execute silently to avoid console clutter.
        """
        if self.command_window:
            self.command_window.execute(code, hidden=not visible)

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
        if self.argv:
            candidate = os.path.abspath(self.argv[0])
            if candidate.endswith('.hy') and os.path.isdir(candidate):
                return candidate, False
        return self.prompt_for_project_selection()

    def prompt_for_project_selection(self):
        os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
        suggested_path = os.path.join(DEFAULT_PROJECTS_DIR, 'untitled.hy')

        while True:
            dialog = ProjectSelectionDialog(self.ui)
            dialog.selectFile(suggested_path)
            if not dialog.exec_():
                return None
            project_dir = dialog.selectedFiles()[0]
            if not project_dir:
                return None
            project_dir = os.path.abspath(project_dir)
            if not project_dir.endswith('.hy'):
                QtWidgets.QMessageBox.warning(
                    self.ui,
                    "Invalid Project Directory",
                    "Hyde projects must be directories ending in .hy.",
                )
                suggested_path = project_dir
                continue

            if os.path.exists(project_dir) and not os.path.isdir(project_dir):
                QtWidgets.QMessageBox.warning(
                    self.ui,
                    "Invalid Project Path",
                    f"{project_dir} is not a directory.",
                )
                suggested_path = project_dir
                continue

            manifest_path = os.path.join(project_dir, 'manifest.toml')
            session_path = os.path.join(project_dir, 'session.toml')
            if os.path.exists(manifest_path) or os.path.exists(session_path):
                return project_dir, False

            response = QtWidgets.QMessageBox.question(
                self.ui,
                "Initialize Project",
                f"Initialize a Hyde project in\n{project_dir}?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if response == QtWidgets.QMessageBox.Yes:
                return project_dir, True
            suggested_path = project_dir

    def choose_project(self, checked=False):
        selection = self.prompt_for_project_selection()
        if selection is None:
            return
        project_dir, create_if_missing = selection
        self.load_project(project_dir, create_if_missing=create_if_missing)

    def prompt_for_save_as_project(self):
        os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
        suggested_path = os.path.join(
            DEFAULT_PROJECTS_DIR,
            f"{os.path.splitext(os.path.basename(self.current_project_dir or 'untitled.hy'))[0]}.hy",
        )
        dialog = ProjectSelectionDialog(
            self.ui,
            title="Save Hyde Project As",
            accept_label="Save As",
        )
        dialog.selectFile(suggested_path)
        if not dialog.exec_():
            return None
        project_dir = dialog.selectedFiles()[0]
        if not project_dir:
            return None
        project_dir = os.path.abspath(project_dir)
        if not project_dir.endswith('.hy'):
            QtWidgets.QMessageBox.warning(
                self.ui,
                "Invalid Project Directory",
                "Hyde projects must be directories ending in .hy.",
            )
            return None
        if os.path.exists(project_dir) and not os.path.isdir(project_dir):
            QtWidgets.QMessageBox.warning(
                self.ui,
                "Invalid Project Path",
                f"{project_dir} is not a directory.",
            )
            return None
        return project_dir

    def confirm_overwrite_project(self, project_dir):
        response = QtWidgets.QMessageBox.question(
            self.ui,
            "Overwrite Project",
            (
                f"{project_dir} already exists and is not empty.\n\n"
                "Overwrite the existing project contents?"
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def write_project_session(self, project_dir):
        write_session(self, project_dir)
        if self.command_window is not None:
            write_history(self.command_window, project_dir)

    def request_kernel_project_save(self, project_dir):
        self.execute_command(
            f"import hyde; hyde.save_state({project_dir!r});",
            visible=True,
        )

    def save_project_state(self, project_dir):
        self.write_project_session(project_dir)
        self.request_kernel_project_save(project_dir)

    def save_project(self, checked=False):
        del checked
        if not self.current_project_dir or self.command_window is None:
            return
        self.save_project_state(self.current_project_dir)

    def save_project_as(self, checked=False):
        del checked
        if not self.current_project_dir or self.command_window is None:
            return
        project_dir = self.prompt_for_save_as_project()
        if project_dir is None:
            return
        if project_dir == self.current_project_dir:
            self.save_project()
            return
        if (
            os.path.exists(project_dir)
            and project_dir != self.current_project_dir
            and os.path.isdir(project_dir)
            and os.listdir(project_dir)
            and not self.confirm_overwrite_project(project_dir)
        ):
            return
        if not os.path.exists(project_dir):
            shutil.copytree(
                self.current_project_dir,
                project_dir,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        else:
            shutil.copytree(
                self.current_project_dir,
                project_dir,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        self.save_project_state(project_dir)
        self._pending_project_switch = project_dir

    def load_project(self, project_dir, create_if_missing=False):
        switching = self.current_project_dir is not None
        if switching:
            clear_tables(self)
        self.current_project_dir, self.procedures_dir, self.procedures_init = get_project_paths(project_dir)
        if create_if_missing:
            self.bootstrap_project()
        else:
            os.makedirs(self.procedures_dir, exist_ok=True)
        self.procedure_browser.set_procedures_dir(self.procedures_dir)
        self.ui.setWindowTitle(f"Hyde - {os.path.basename(self.current_project_dir)}")
        if not os.path.exists(self.procedures_init):
            self.offer_to_create_procedures_init()
        self._procedures_ready = False
        self._pending_project_state_load = True
        self._pending_session_restore = False
        self.configure_execution_watchdog()
        self.table_macros = []
        self.rebuild_table_macros_menu()

    def configure_execution_watchdog(self):
        if self.to_worker is None:
            return
        self.to_worker.put([
            'WATCH_PROJECT',
            {
                'project_dir': self.current_project_dir,
                'procedures_dir': self.procedures_dir,
                'procedures_init': self.procedures_init,
            },
        ])

    def reload_procedures(self):
        if self.to_worker is None:
            return
        self.to_worker.put(['RELOAD_PROCEDURES', None])

    def request_window_macros(self, kind='table'):
        if self.to_worker is None:
            return
        self.to_worker.put(['REFRESH_WINDOW_MACROS', {'kind': kind}])

    def offer_to_create_procedures_init(self):
        response = QtWidgets.QMessageBox.question(
            self.ui,
            "Missing procedures/__init__.py",
            (
                f"{self.procedures_init} is missing.\n\n"
                "Create a default procedures/__init__.py template for this project?"
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if response == QtWidgets.QMessageBox.Yes:
            self.write_default_procedures_init()

    def write_default_procedures_init(self):
        os.makedirs(self.procedures_dir, exist_ok=True)
        shutil.copy2(DEFAULT_PROCEDURES_INIT_TEMPLATE, self.procedures_init)
        self.configure_execution_watchdog()

    def listen_for_watchdog(self):
        """Poll the ProcessTree queue for kernel/watchdog state updates."""
        while True:
            try:
                task, data = self.from_worker.get()
                if task == 'KERNEL_READY':
                    self.finalize_startup()
                elif task == 'OPEN_TABLE':
                    names = data.get('names', [])
                    target = data.get('target')
                    visible_title = data.get('title')
                    self.open_table(names, target, visible_title=visible_title)
                elif task == 'TABLE_DATA':
                    # Relay to tables; they ignore if request_id doesn't match
                    request_id = data.get('request_id')
                    table_data = data.get('data', {})
                    for table in self.tables.values():
                        table.on_data_received(table_data, request_id)
                elif task == 'PROCEDURES_RELOADED':
                    self.on_procedures_reloaded(data.get('ok', False))
                elif task == 'PROJECT_STATE_RESULT':
                    self.on_project_state_result(data)
                elif task == 'KERNEL_CRASHED':
                    self.show_crash_alert()
                elif task == 'WINDOW_MACROS':
                    kind = data.get('kind')
                    macros = data.get('macros', [])
                    if kind == 'table':
                        self.update_table_macros(macros)
            except Exception:
                pass
                
    @inmain_decorator()
    def finalize_startup(self):
        try:
            self.splash.update_text('Connecting to Jupyter Kernel Socket...')
            
            # Instantiate Command Window bypassing ProcessTree and targeting ZMQ
            self.command_window = CommandWindow(connection_file=CONNECTION_FILE)
            self.command_subwindow = self.ui.mdiArea.addSubWindow(self.command_window)
            self.configure_persistent_subwindow(self.command_subwindow)
            self.command_window.show()
            
            # Instantiate Data Browser with its own client
            self.data_browser = DataBrowser(connection_file=CONNECTION_FILE, app=self)
            self.data_browser_subwindow = self.ui.mdiArea.addSubWindow(self.data_browser)
            self.configure_persistent_subwindow(self.data_browser_subwindow)
            self.data_browser.show()

            self.maybe_trigger_project_state_load()
            self.request_window_macros('table')
            
            # Release the splash screen and manifest the GUI
            self.ui.show()
            self.splash.hide()
            
        except Exception:
            import traceback
            traceback.print_exc()
        
    @inmain_decorator()
    def show_crash_alert(self):
        QtWidgets.QMessageBox.warning(self.ui, "Kernel Crashed", "The IPython execution kernel has died unexpectedly. It is being restarted in the background. Your interface state is now disconnected.")

    @inmain_decorator()
    def on_procedures_reloaded(self, ok):
        self._procedures_ready = bool(ok)
        if self.data_browser is not None:
            self.data_browser.refresh_namespace()
        self.request_window_macros('table')
        self.maybe_trigger_project_state_load()

    def maybe_trigger_project_state_load(self):
        if not self._pending_project_state_load:
            return
        if not self._procedures_ready:
            return
        if self.command_window is None:
            return
        self._pending_project_state_load = False
        self._pending_session_restore = True
        self.execute_command(
            f"import hyde; hyde.load_state({self.current_project_dir!r});",
            visible=True,
        )

    @inmain_decorator()
    def on_project_state_result(self, data):
        operation = data.get('operation')
        success = bool(data.get('success', False))
        path = data.get('path')
        errors = list(data.get('errors', []))
        if operation == 'save':
            if errors:
                QtWidgets.QMessageBox.warning(
                    self.ui,
                    "Project Save Warnings",
                    "\n".join(errors),
                )
            if success and self._pending_project_switch == path:
                self._pending_project_switch = None
                self.load_project(path, create_if_missing=False)
        elif operation == 'load':
            if errors:
                QtWidgets.QMessageBox.warning(
                    self.ui,
                    "Project Load Warnings",
                    "\n".join(errors),
                )
            if success and self._pending_session_restore and path == self.current_project_dir:
                self._pending_session_restore = False
                self.restore_project_session()

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

    def _mark_shutting_down(self):
        self.shutting_down = True

    def shutdown_watchdog(self):
        print("[Hyde] Sending QUIT signal to execution Watchdog...")
        try:
            self.to_worker.put(['QUIT', None])
        except Exception:
            pass

    def bootstrap_project(self):
        """Ensures the selected project directory structure exists."""
        print(f"[Hyde] Bootstrapping project at {self.current_project_dir}")
        shutil.copytree(DEFAULT_PROJECT_TEMPLATE, self.current_project_dir, dirs_exist_ok=True)
        if not os.path.exists(self.procedures_init):
            self.write_default_procedures_init()

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
        if not session:
            return
        restore_main_window(self, session)
        restore_data_browser_state(self, session)
        clear_tables(self)
        restore_tables(self, session)
        restore_tool_windows(self, session)
