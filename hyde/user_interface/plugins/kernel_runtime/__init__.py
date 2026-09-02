import logging
import os
import threading
import time

from qtconsole.client import QtKernelClient
from qtutils import inmain_decorator
from qtutils.qt import QtCore

from hyde.paths import CONNECTION_FILE, KERNEL_LAUNCHER
from hyde.user_interface.shared.plugin import (
    HydePlugin,
    SETUP_PRIORITY_RUNTIME_START,
)
from hyde.user_interface.shared.core import log_hyde_dispatch_debug


qt_slot = getattr(QtCore, "Slot", QtCore.pyqtSlot)
LOGGER = logging.getLogger("hyde")


def _reply_error_text(content):
    status = str(content.get("status") or "").strip().lower()
    if status == "aborted":
        # The kernel aborts everything queued behind a non-silent request that
        # raised, so a GUI request can be cancelled by the user's own failing
        # cell without ever running. Say so, rather than reporting a bare
        # protocol word.
        return "the kernel aborted it after an earlier error"
    ename = str(content.get("ename") or "").strip()
    evalue = str(content.get("evalue") or "").strip()
    if ename and evalue:
        return f"{ename}: {evalue}"
    return ename or evalue or status


class KernelRequest:
    """One GUI-initiated kernel request, from sent to settled.

    Identity is the kernel's `msg_id`, which it quotes in `parent_header` when
    it answers. A pending request is one the kernel has not answered yet, which
    is not the same as a late one: the kernel runs a single request at a time,
    so a request issued while the user's own cell is running waits its turn.
    There is no timeout, and waiting is not failing.

    Only `FrontendKernelService` settles a request. Callers read it.
    """

    PENDING = None
    RAN = "ran"
    RAISED = "raised"
    ABANDONED = "abandoned"

    def __init__(self, msg_id, code):
        self.msg_id = str(msg_id)
        self.code = str(code)
        self.outcome = self.PENDING
        self.error = ""

    def is_pending(self):
        return self.outcome is self.PENDING

    def ran(self):
        return self.outcome == self.RAN

    def settle(self, outcome, error=""):
        """Owner-only. Returns False if the request was already settled."""
        if not self.is_pending():
            return False
        self.outcome = outcome
        self.error = str(error)
        return True


class FrontendKernelService(QtCore.QObject):
    """The GUI's one client onto the kernel's shell channel.

    Requests carry identity: `request` hands back a handle bearing the `msg_id`
    the kernel quotes in `parent_header` when it answers, so a caller can tell
    its own reply from anyone else's and learn whether its command ran or
    raised.
    """

    ready = QtCore.Signal()

    def __init__(self, connection_file, parent=None):
        super().__init__(parent)
        self.connection_file = connection_file
        self._kernel_client = None
        self._ready = False
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._try_connect)
        self._connecting = False
        self._ready_probe_msg_id = None
        self._ready_probe_at = None
        self._pending_requests = {}

    def start(self):
        if self._kernel_client is not None or self._poll_timer.isActive():
            return
        self._poll_timer.start()
        self._try_connect()

    def stop(self):
        self._poll_timer.stop()
        self._connecting = False
        client = self._kernel_client
        self._kernel_client = None
        self._ready = False
        self._ready_probe_msg_id = None
        self._ready_probe_at = None
        self._abandon_pending_requests("The kernel is no longer available.")
        if client is None:
            return
        try:
            client.shell_channel.message_received.disconnect(self._on_shell_message)
        except Exception:
            pass
        try:
            client.stop_channels()
        except Exception:
            LOGGER.exception("Failed to stop shared frontend kernel client channels.")

    def is_ready(self):
        return self._ready

    def kernel_client(self):
        return self._kernel_client

    def execute(self, code, silent=True):
        """Send `code` and return the request's `msg_id`, or None if not sent.

        Callers that only need "was it sent" keep working unchanged: a sent
        request yields a non-empty id, an unsent one yields None.
        """
        if self._kernel_client is None or not self._ready:
            return None
        msg_id = self._kernel_client.execute(code, silent=bool(silent))
        return None if msg_id is None else str(msg_id)

    def request(self, code, *, on_finished):
        """Send `code` and correlate its reply. Main thread only.

        Returns a `KernelRequest`, or None if there is no kernel to ask.
        `on_finished(request)` is called exactly once: when the kernel answers,
        or when the kernel goes away with the request still outstanding. It is
        never called for a timeout, because there is none.
        """
        msg_id = self.execute(code, silent=True)
        if msg_id is None:
            return None
        # Safe against a reply racing this line: shell-channel messages are
        # delivered on the Qt event loop, which cannot run until this returns.
        request = KernelRequest(msg_id, code)
        self._pending_requests[msg_id] = (request, on_finished)
        return request

    def pending_requests(self):
        return tuple(request for request, _ in self._pending_requests.values())

    def _settle_request(self, msg_id, content):
        entry = self._pending_requests.pop(msg_id, None)
        if entry is None:
            return
        request, on_finished = entry
        # Anything that is not "ok" -- an error, an abort from the user
        # interrupting -- means the command did not run to completion.
        if str(content.get("status") or "").lower() == "ok":
            request.settle(KernelRequest.RAN)
        else:
            request.settle(KernelRequest.RAISED, _reply_error_text(content))
        on_finished(request)

    def _abandon_pending_requests(self, reason):
        # A dead kernel settles every outstanding request at once. Nothing is
        # left waiting for a reply that can no longer arrive.
        entries = list(self._pending_requests.values())
        self._pending_requests.clear()
        for request, on_finished in entries:
            request.settle(KernelRequest.ABANDONED, reason)
            on_finished(request)

    def shutdown_kernel(self):
        if self._kernel_client is None:
            return False
        self._kernel_client.shutdown(restart=False)
        return True

    def _try_connect(self):
        if self._connecting:
            return
        if self._kernel_client is None and not os.path.exists(self.connection_file):
            return
        if self._kernel_client is None:
            self._connecting = True
            client = QtKernelClient(connection_file=self.connection_file)
            client.load_connection_file()
            client.start_channels()
            client.shell_channel.message_received.connect(self._on_shell_message)
            self._kernel_client = client
            self._ready = False
            self._connecting = False
            self._send_readiness_probe(force=True)
            return
        self._send_readiness_probe()

    def _send_readiness_probe(self, force=False):
        if self._kernel_client is None or self._ready:
            return
        now = time.monotonic()
        if (
            not force
            and self._ready_probe_at is not None
            and now - self._ready_probe_at < 0.5
        ):
            return
        self._ready_probe_msg_id = self._kernel_client.kernel_info()
        self._ready_probe_at = now

    def _on_shell_message(self, message):
        if self._kernel_client is None:
            return
        msg_type = (
            message.get("msg_type")
            or message.get("header", {}).get("msg_type")
        )
        parent_msg_id = message.get("parent_header", {}).get("msg_id")
        if not self._ready:
            # Readiness is the only thing worth reading before the kernel says
            # hello; the channel stays connected afterwards to carry replies.
            if msg_type == "kernel_info_reply":
                self._accept_readiness_reply(parent_msg_id)
            return
        if msg_type != "execute_reply" or not parent_msg_id:
            return
        self._settle_request(str(parent_msg_id), dict(message.get("content") or {}))

    def _accept_readiness_reply(self, parent_msg_id):
        if self._ready_probe_msg_id and parent_msg_id not in (None, self._ready_probe_msg_id):
            return
        self._ready = True
        self._ready_probe_msg_id = None
        self._ready_probe_at = None
        self._poll_timer.stop()
        self.ready.emit()


class RuntimeHelper:
    """Background helper for Lane 1 kernel control messages."""

    def __init__(
        self,
        from_kernel,
        kernel_process,
        on_kernel_crashed,
        *,
        enter_no_project_state,
        activate_project,
        on_project_state_result,
        request_gui_quit,
        emit_plugin_event,
    ):
        self.from_kernel = from_kernel
        self.kernel_process = kernel_process
        self.on_kernel_crashed = on_kernel_crashed
        self.enter_no_project_state = enter_no_project_state
        self.activate_project = activate_project
        self.on_project_state_result = on_project_state_result
        self.request_gui_quit = request_gui_quit
        self.emit_plugin_event = emit_plugin_event
        self._stopping = threading.Event()
        self.thread = threading.Thread(target=self.mainloop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stopping.set()

    def mainloop(self):
        while not self._stopping.is_set():
            if self.kernel_process.poll() is not None:
                if not self._stopping.is_set():
                    self.on_kernel_crashed()
                return

            try:
                task, data = self.from_kernel.get(timeout=0.01)
            except Exception:
                time.sleep(0.05)
                continue

            if task == "ENTER_NO_PROJECT_STATE":
                self.enter_no_project_state()
            elif task == "ACTIVATE_PROJECT":
                self.activate_project(data.get("path"))
            elif task == "QUIT_REQUESTED":
                self._stopping.set()
                self.request_gui_quit()
                return
            elif task == "PROJECT_STATE_RESULT":
                self.on_project_state_result(data)
            else:
                self.emit_plugin_event(
                    "kernel_message",
                    {
                        "task": task,
                        "data": data,
                    },
                )


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

    def is_ready(self):
        service = self.plugin.frontend_kernel_service
        return service is not None and service.is_ready()

    def kernel_client(self):
        service = self.plugin.frontend_kernel_service
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


class PythonExecutionService:
    def __init__(self, plugin):
        self.plugin = plugin

    def execute_hidden(self, code, silent=True):
        return self.plugin.execute_frontend(code, silent=silent)

    def request(self, code, *, on_finished):
        """Dispatch `code` and correlate its reply. Main thread only.

        The third verb on this surface. `execute_hidden` and `execute_visible`
        answer "was it sent"; `request` answers "what happened", by handing back
        a `KernelRequest` that settles when the kernel replies.
        """
        return self.plugin.request_frontend(code, on_finished)

    def execute_visible(self, code):
        visible_terminal_service = self.plugin.services.get("visible_terminal_service")
        if visible_terminal_service is None:
            return False
        log_hyde_dispatch_debug("visible", code)
        visible_terminal_service.execute_visible(code)
        return True


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.kernel_runtime_service = KernelRuntimeService(self)
        self.python_execution_service = PythonExecutionService(self)
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
            "python_execution_service": self.python_execution_service,
        }

    def get_menu_contributions(self):
        return [
            {
                "location": "file",
                "group": "application",
                "order": 110,
                "name": "Kill Kernel",
                "action": self.kill_kernel,
            },
        ]

    def get_setup_activities(self):
        return super().get_setup_activities() + [
            {
                "name": "start_runtime",
                "priority": SETUP_PRIORITY_RUNTIME_START,
                "action": self.start_runtime_activity,
            },
        ]

    def setup(self, data=None):
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
                self.execute_frontend,
                parent=ui_parent,
            )

    def start_runtime_activity(self, data=None):
        del data
        self.start_runtime()

    def get_event_handlers(self):
        return {
            "request_runtime_shutdown": self.on_request_runtime_shutdown,
        }

    def start_runtime(self):
        if os.path.exists(CONNECTION_FILE):
            os.remove(CONNECTION_FILE)
        output_redirection_port = None
        # Logging owns output policy; kernel launch only needs its port.
        logging_service = self.services.get("runtime_output_service")
        if logging_service is not None:
            try:
                output_redirection_port = logging_service.port()
            except Exception:
                output_redirection_port = None
                LOGGER.exception(
                    "Failed to acquire runtime output redirection port; "
                    "launching kernel without redirected runtime output."
                )
            if output_redirection_port is None:
                LOGGER.info(
                    "Launching kernel without redirected runtime output: "
                    "runtime output service returned no port."
                )
            else:
                LOGGER.info(
                    "Launching kernel with runtime output redirection port %s.",
                    output_redirection_port,
                )
        else:
            LOGGER.info(
                "Launching kernel without redirected runtime output: "
                "runtime output service is unavailable."
            )
        (
            self.kernel_to_child,
            self.kernel_from_child,
            self.kernel_process,
        ) = self.services["process_tree"].subprocess(
            KERNEL_LAUNCHER,
            args=["-f", CONNECTION_FILE],
            output_redirection_port=output_redirection_port,
            startup_timeout=60,
            # Longer than zprocess's default, because a kernel busy with the
            # user's own work does not answer promptly and must not be killed
            # for it. Which zprocess accepts these is a packaging question.
            heartbeat_interval=10,
            allowed_missed_heartbeats=10,
        )
        self.frontend_kernel_service.stop()
        self.frontend_kernel_service.start()
        self.runtime_helper = RuntimeHelper(
            self.kernel_from_child,
            self.kernel_process,
            self._handle_kernel_crash,
            enter_no_project_state=self.services["enter_no_project_state"],
            activate_project=self.services["activate_project"],
            on_project_state_result=self.services["on_project_state_result"],
            request_gui_quit=self.services["request_gui_quit"],
            emit_plugin_event=self.services["emit_plugin_event"],
        )
        self.runtime_helper.start()

    def execute_frontend(self, code, silent=True):
        if self.frontend_kernel_service is None or not self.frontend_kernel_service.is_ready():
            return False
        code = str(code)
        log_hyde_dispatch_debug("hidden", code)
        current_thread = QtCore.QThread.currentThread()
        executor_thread = self._main_thread_executor.thread()
        if current_thread is executor_thread:
            # Dispatch answers "was it sent"; the request id belongs to callers
            # that go to FrontendKernelService for a correlated request.
            return bool(self.frontend_kernel_service.execute(code, silent=bool(silent)))
        self._main_thread_executor.execute_requested.emit(code, bool(silent))
        return True

    def request_frontend(self, code, on_finished):
        if self.frontend_kernel_service is None or not self.frontend_kernel_service.is_ready():
            return None
        executor = self._main_thread_executor
        if executor is not None and QtCore.QThread.currentThread() is not executor.thread():
            # execute_hidden marshals; a correlated request cannot, because the
            # msg_id has to come back to the caller now. Refusing beats sending
            # from the wrong thread and corrupting the client's sockets.
            LOGGER.warning(
                "A correlated kernel request was issued off the GUI thread and refused."
            )
            return None
        code = str(code)
        log_hyde_dispatch_debug("hidden", code)
        return self.frontend_kernel_service.request(code, on_finished=on_finished)

    def kill_kernel(self, checked=False):
        del checked
        if self.kernel_process is None or self.kernel_process.poll() is not None:
            return False
        self.kernel_process.terminate()
        return True

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
        # Application shutdown asks the live kernel to exit through Jupyter
        # first; _complete_shutdown_runtime owns the bounded wait and fallback
        # SIGTERM path.
        helper = self.runtime_helper
        self.runtime_helper = None
        if helper is not None:
            helper.stop()
        if shutdown_kernel and self.frontend_kernel_service is not None:
            try:
                self.frontend_kernel_service.shutdown_kernel()
            except Exception:
                LOGGER.exception("Failed to request kernel shutdown.")
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
