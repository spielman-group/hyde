import os
import threading
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets

from hyde.paths import EXECUTION_CONTROLLER, CONNECTION_FILE
from hyde.user_interface.command_window import CommandWindow
from hyde.user_interface.logging_window import LoggingWindow

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
        
        # Initialize Logging Window as an MDI sub-window
        self.logging_window = LoggingWindow()
        self.logging_subwindow = self.ui.mdiArea.addSubWindow(self.logging_window)
        self.logging_subwindow.resize(800, 600)
        self.logging_subwindow.hide()
        # It remains hidden by default, as specified.
        
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
        self.qapplication.aboutToQuit.connect(self.shutdown_watchdog)

    @inmain_decorator()
    def show_logging_window(self, checked=False):
        self.logging_subwindow.show()
        self.logging_subwindow.setFocus()
        self.logging_subwindow.raise_()


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
