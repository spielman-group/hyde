import os
import shutil
import threading
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore

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
        self.logging_subwindow.resize(800, 600)
        self.logging_subwindow.hide()

        # Initialize Procedure Browser as an MDI sub-window
        initial_procedures_dir = get_project_paths(project_dir)[1]
        self.procedure_browser = ProcedureBrowser(procedures_dir=initial_procedures_dir)
        self.procedures_subwindow = self.ui.mdiArea.addSubWindow(self.procedure_browser)
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
        
        # Connect Application events
        self.ui.actionNew.triggered.connect(self.choose_project)
        self.ui.actionLoad.triggered.connect(self.choose_project)
        self.ui.actionQuit.triggered.connect(self.qapplication.quit)
        self.ui.actionLogging.triggered.connect(self.show_logging_window)
        self.ui.actionProcedures.triggered.connect(self.show_procedures_window)
        self.qapplication.aboutToQuit.connect(self.shutdown_watchdog)

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
            dialog = QtWidgets.QFileDialog(
                self.ui,
                "Open or Create Hyde Project",
                DEFAULT_PROJECTS_DIR,
            )
            dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
            dialog.setFileMode(QtWidgets.QFileDialog.Directory)
            dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptOpen)
            dialog.setLabelText(QtWidgets.QFileDialog.Accept, "Open / Create")
            dialog.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
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

            if not os.path.isdir(project_dir):
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
            sub_window = self.ui.mdiArea.addSubWindow(self.command_window)
            self.command_window.show()
            
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
