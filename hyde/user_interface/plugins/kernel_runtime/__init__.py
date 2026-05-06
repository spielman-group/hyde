import os
import time

from qtutils import inmain_decorator
from qtutils.qt import QtCore

from hyde.paths import CONNECTION_FILE, KERNEL_LAUNCHER
from hyde.user_interface.main.frontend_kernel import FrontendKernelService
from hyde.user_interface.main.runtime_helper import RuntimeHelper
from hyde.user_interface.plugin_tools import HydePlugin


qt_slot = getattr(QtCore, "Slot", QtCore.pyqtSlot)


class _MainThreadExecutor(QtCore.QObject):
    execute_requested = QtCore.Signal(str, bool)

    def __init__(self, execute_callback, parent=None):
        super().__init__(parent)
        self._execute_callback = execute_callback
        self.execute_requested.connect(self._execute)

    @qt_slot(str, bool)
    def _execute(self, code, silent):
        self._execute_callback(code, silent=silent)


class KernelRuntimeService:
    def __init__(self, plugin):
        self.plugin = plugin

    def frontend_kernel_service(self):
        return self.plugin.frontend_kernel_service

    def is_ready(self):
        service = self.frontend_kernel_service()
        return service is not None and service.is_ready()

    def kernel_client(self):
        service = self.frontend_kernel_service()
        return None if service is None else service.kernel_client()

    def execute(self, code, silent=True):
        return self.plugin.execute_frontend(code, silent=silent)

    def register_comm_target(self, target_name, callback):
        client = self.kernel_client()
        comm_manager = None if client is None else getattr(client, "comm_manager", None)
        if comm_manager is None:
            return False
        comm_manager.register_target(target_name, callback)
        return True


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.kernel_runtime_service = KernelRuntimeService(self)
        self.frontend_kernel_service = None
        self.runtime_helper = None
        self.kernel_to_child = None
        self.kernel_from_child = None
        self.kernel_process = None
        self._quit_deadline = None
        self._main_thread_executor = None
        self._shutdown_requested = False

    def get_services(self):
        return {
            "kernel_runtime_service": self.kernel_runtime_service,
        }

    def on_setup_complete(self, data=None):
        del data
        if self.frontend_kernel_service is None:
            ui_parent = self.services["ui"]
            if not isinstance(ui_parent, QtCore.QObject):
                ui_parent = None
            self.frontend_kernel_service = FrontendKernelService(
                CONNECTION_FILE,
                parent=ui_parent,
            )
            self.frontend_kernel_service.ready.connect(self.services["on_kernel_ready"])
            self._main_thread_executor = _MainThreadExecutor(
                self._execute_frontend,
                parent=ui_parent,
            )
        self.start_runtime()

    def get_event_handlers(self):
        return {
            "request_runtime_shutdown": self.on_request_runtime_shutdown,
        }

    def start_runtime(self):
        if os.path.exists(CONNECTION_FILE):
            os.remove(CONNECTION_FILE)
        output_redirection_port = None
        logging_service = self.services.get("runtime_output_service")
        if logging_service is not None:
            try:
                output_redirection_port = logging_service.port()
            except Exception:
                output_redirection_port = None
        (
            self.kernel_to_child,
            self.kernel_from_child,
            self.kernel_process,
        ) = self.services["process_tree"].subprocess(
            KERNEL_LAUNCHER,
            args=["-f", CONNECTION_FILE],
            output_redirection_port=output_redirection_port,
            startup_timeout=60,
        )
        self.frontend_kernel_service.stop()
        self.frontend_kernel_service.start()
        self.runtime_helper = RuntimeHelper(
            self.services,
            self.kernel_from_child,
            self.kernel_process,
            self._handle_kernel_crash,
        )
        self.runtime_helper.start()

    def execute_frontend(self, code, silent=True):
        if self.frontend_kernel_service is None or not self.frontend_kernel_service.is_ready():
            return False
        current_thread = QtCore.QThread.currentThread()
        executor_thread = self._main_thread_executor.thread()
        if current_thread is executor_thread:
            return self._execute_frontend(code, silent=silent)
        self._main_thread_executor.execute_requested.emit(str(code), bool(silent))
        return True

    def _execute_frontend(self, code, silent=True):
        service = self.frontend_kernel_service
        if service is None:
            return False
        return service.execute(code, silent=bool(silent))

    @inmain_decorator()
    def _handle_kernel_crash(self):
        if self.services["get_shutting_down"]():
            return
        self.stop_runtime(shutdown_kernel=False)
        self.services["on_kernel_crashed"]()
        self.start_runtime()

    @inmain_decorator()
    def on_request_runtime_shutdown(self, data):
        del data
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        self._quit_deadline = time.monotonic() + 2.0
        self.stop_runtime(shutdown_kernel=True)
        QtCore.QTimer.singleShot(0, self._complete_shutdown_runtime)

    def stop_runtime(self, shutdown_kernel):
        helper = self.runtime_helper
        self.runtime_helper = None
        if helper is not None:
            helper.stop()
        if shutdown_kernel and self.frontend_kernel_service is not None:
            try:
                self.frontend_kernel_service.shutdown_kernel(reply=False)
            except Exception:
                pass
        if self.frontend_kernel_service is not None:
            self.frontend_kernel_service.stop()

    @inmain_decorator()
    def _complete_shutdown_runtime(self):
        kernel_running = self.kernel_process is not None and self.kernel_process.poll() is None
        if (
            kernel_running
            and self._quit_deadline is not None
            and time.monotonic() < self._quit_deadline
        ):
            QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
            return
        if kernel_running:
            self.kernel_process.terminate()
            if self.kernel_process.poll() is None:
                QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
                return
        self.services["finalize_quit"]()
