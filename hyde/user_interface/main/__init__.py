import os
import threading
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore

from hyde.paths import (
    EXECUTION_CONTROLLER, 
    CONNECTION_FILE, 
    DEFAULT_PROJECT_DIR, 
    PROCEDURES_DIR, 
    MASTER_SCRIPT
)
from hyde.user_interface.command_window import CommandWindow
from hyde.user_interface.logging_window import LoggingWindow
from hyde.user_interface.procedure_browser import ProcedureBrowser

class HydeMainWindow(QtWidgets.QMainWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

class HydeApp:
    def __init__(self, qapplication, process_tree, splash):
        self.qapplication = qapplication
        self.process_tree = process_tree
        self.splash = splash
        
        # Load the UI
        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), 'main.ui')
        self.ui = loader.load(ui_path, HydeMainWindow(self))
        
        # Bootstrap the default project structure
        self.bootstrap_project()

        
        # Initialize Logging Window as an MDI sub-window
        self.logging_window = LoggingWindow()
        self.logging_subwindow = self.ui.mdiArea.addSubWindow(self.logging_window)
        self.logging_subwindow.resize(800, 600)
        self.logging_subwindow.hide()
        
        # Initialize Procedure Browser as an MDI sub-window
        self.procedure_browser = ProcedureBrowser(procedures_dir=PROCEDURES_DIR)
        self.procedures_subwindow = self.ui.mdiArea.addSubWindow(self.procedure_browser)
        self.procedures_subwindow.resize(300, 500)
        self.procedures_subwindow.hide()

        # Initialize FileSystemWatcher for master.py "Run-on-Save" behavior
        self.watcher = QtCore.QFileSystemWatcher()
        if os.path.exists(MASTER_SCRIPT):
            self.watcher.addPath(MASTER_SCRIPT)
        self.watcher.fileChanged.connect(self.on_master_script_changed)
        
        # Spawn the Watchdog execution subprocess
        self.to_worker, self.from_worker, self.worker = self.process_tree.subprocess(
            EXECUTION_CONTROLLER,
            args=[CONNECTION_FILE],
            output_redirection_port=self.logging_window.port
        )
        
        # Start daemon thread listening to Watchdog alerts
        self.listener_thread = threading.Thread(target=self.listen_for_watchdog)
        self.listener_thread.daemon = True
        self.listener_thread.start()
        
        # Connect Application events
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

    def on_master_script_changed(self, path):
        """Called by the watcher whenever master.py is saved."""
        print(f"[Hyde] Master script changed: {path}. Re-executing...")
        # Re-add path because some editors do an atomic save that breaks the watcher
        self.watcher.addPath(path)
        self.execute_master_script()


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
            
            # Execute the project master script to establish an explicit environment
            self.execute_master_script()
            
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
        """Ensures the default project directory structure exists."""
        if not os.path.exists(DEFAULT_PROJECT_DIR):
            print(f"[Hyde] Bootstrapping default project at {DEFAULT_PROJECT_DIR}")
            os.makedirs(PROCEDURES_DIR, exist_ok=True)
            
        if not os.path.exists(MASTER_SCRIPT):
            with open(MASTER_SCRIPT, "w") as f:
                f.write("# Hyde Master Script\n")
                f.write("# Use this file to define your environment explicitly.\n\n")
                f.write("import hyde         # Hyde-specific functions (e.g. open_table)\n")
                f.write("import numpy as np \n")
                f.write("import matplotlib\n")
                f.write("# matplotlib.use('Hyde')  # Explicitly set the Hyde backend (when implemented)\n")
                f.write("import matplotlib.pyplot as plt \n")
                f.write("import lmfit        # For curve fitting\n\n")
                f.write('print("Hyde environment initialized from master.py")\n')

    def execute_master_script(self):
        """Tells the kernel to execute the master script."""
        if os.path.exists(MASTER_SCRIPT):
            print(f"[Hyde] Executing master script: {MASTER_SCRIPT}")
            init_code = (
                f"import os\n"
                f"os.chdir('{DEFAULT_PROJECT_DIR}')\n"
                f"with open('{MASTER_SCRIPT}') as f:\n"
                f"    exec(f.read())\n"
            )
            self.command_window.execute(init_code, hidden=False)

