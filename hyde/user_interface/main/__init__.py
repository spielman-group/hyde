import os
import shutil
import threading
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore, QtGui
from qtconsole.client import QtKernelClient
from spyder_kernels.comms.commbase import CommBase

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

class PersistentSubwindowFilter(QtCore.QObject):
    """Turn MDI close requests into hide requests so tool windows persist."""

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Close:
            watched.hide()
            event.ignore()
            return True
        return super().eventFilter(watched, event)

class ProjectSelectionDialog(QtWidgets.QFileDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Open or Create Hyde Project", DEFAULT_PROJECTS_DIR)
        self._selected_path = None
        self.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        self.setFileMode(QtWidgets.QFileDialog.Directory)
        self.setAcceptMode(QtWidgets.QFileDialog.AcceptOpen)
        self.setLabelText(QtWidgets.QFileDialog.Accept, "Open / Create")
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

class HydeFrontendComm(CommBase):
    """Narrow frontend handler for Hyde-specific UI triggers and data fetching."""

    def __init__(self, kernel_client, app):
        super().__init__()
        self.kernel_client = kernel_client
        self.app = app
        self.comm = None
        self.register_call_handler("open_table", self.app.open_table)

    def on_comm_open(self, comm, msg):
        """Handle incoming comm open from the kernel (open_table intent)."""
        self._register_comm(comm)

    def open(self):
        """Manually open the comm to the kernel for data requests."""
        if self.comm is not None:
            return
        self.comm = self.kernel_client.comm_manager.new_comm('hyde_api')
        self._register_comm(self.comm)

    def request_table_data(self, names, callback):
        """Fetch array data via remote call to the kernel."""
        if self.comm is None:
            self.open()
        self.remote_call(
            comm_id=self.comm.comm_id,
            callback=callback
        ).get_table_data(names)


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
        self.hyde_comm = None
        self.kernel_client = None
        
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
        self.ui.actionQuit.triggered.connect(self.qapplication.quit)
        self.ui.actionCommandWindow.triggered.connect(self.show_command_window)
        self.ui.actionLogging.triggered.connect(self.show_logging_window)
        self.ui.actionProcedures.triggered.connect(self.show_procedures_window)
        self.ui.actionDataBrowser.triggered.connect(self.show_data_browser)
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

    @inmain_decorator()
    def open_table(self, names, target=None):
        """
        Open a new table or append to an existing one.
        Called via hyde_api comm from the kernel.
        """
        from hyde.user_interface.table import TableWidget

        if target is not None and target in self.tables:
            table = self.tables[target]
            table.append_columns(names)
            table.parentWidget().show()
            table.parentWidget().setFocus()
            table.parentWidget().raise_()
            return

        handle = f"Table{self.table_counter}"
        self.table_counter += 1
        
        table = TableWidget(handle, names, connection_file=CONNECTION_FILE, app=self)
        subwindow = self.ui.mdiArea.addSubWindow(table)
        self.tables[handle] = table
        subwindow.setWindowTitle(f"{handle}: {', '.join(names)}")
        subwindow.show()
        
        # When subwindow is destroyed, remove from registry
        subwindow.destroyed.connect(lambda: self.tables.pop(handle, None))

    def _on_subwindow_activated(self, subwindow):
        if subwindow is None:
            return
        widget = subwindow.widget()
        from hyde.user_interface.table import TableWidget
        if isinstance(widget, TableWidget):
            self.active_table_handle = widget.handle

    def execute_command(self, code):
        """Execute a command in the kernel via the app's client."""
        if self.kernel_client is not None:
            self.kernel_client.execute(code)

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

    def load_project(self, project_dir, create_if_missing=False):
        self.current_project_dir, self.procedures_dir, self.procedures_init = get_project_paths(project_dir)
        if create_if_missing:
            self.bootstrap_project()
        else:
            os.makedirs(self.procedures_dir, exist_ok=True)
        self.procedure_browser.set_procedures_dir(self.procedures_dir)
        self.ui.setWindowTitle(f"Hyde - {os.path.basename(self.current_project_dir)}")
        if not os.path.exists(self.procedures_init):
            self.offer_to_create_procedures_init()
        self.configure_execution_watchdog()

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
        while True:
            try:
                task, data = self.from_worker.get()
                if task == 'KERNEL_READY':
                    self.finalize_startup()
                elif task == 'KERNEL_CRASHED':
                    self.show_crash_alert()
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
            
            # Setup Hyde-specific comm channel for UI triggers
            self.kernel_client = QtKernelClient(connection_file=CONNECTION_FILE)
            self.kernel_client.load_connection_file()
            self.kernel_client.start_channels()
            self.hyde_comm = HydeFrontendComm(self.kernel_client, self)
            self.kernel_client.comm_manager.register_target("hyde_api", self.hyde_comm.on_comm_open)

            # Release the splash screen and manifest the GUI
            self.ui.show()
            self.splash.hide()
            
        except Exception:
            import traceback
            traceback.print_exc()
        
    @inmain_decorator()
    def show_crash_alert(self):
        QtWidgets.QMessageBox.warning(self.ui, "Kernel Crashed", "The IPython execution kernel has died unexpectedly. It is being restarted in the background. Your interface state is now disconnected.")

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
