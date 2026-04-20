from __future__ import annotations

import os
import queue
import threading
import time

from jupyter_client import BlockingKernelClient
from labscript_utils.labconfig import LabConfig
from labscript_utils import shared_drive
from labscript_utils.ls_zprocess import ZMQServer

from hyde.features.hyde_features import format_remote_command

try:
    HYDE_REMOTE_PORT = int(LabConfig().get("ports", "lyse"))
except Exception:
    HYDE_REMOTE_PORT = 42519


class RuntimeHelper:
    """GUI-owned background helper for silent kernel work and kernel signals."""

    def __init__(self, app, connection_file, from_kernel, kernel_process):
        self.app = app
        self.connection_file = connection_file
        self.from_kernel = from_kernel
        self.kernel_process = kernel_process
        self.command_queue = queue.Queue()
        self.kernel_client = None
        self._ready_notified = False
        self._stopping = threading.Event()
        self.thread = threading.Thread(target=self.mainloop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stopping.set()
        self.command_queue.put(("QUIT", None))

    def enqueue_execute(self, code, silent=True):
        self.command_queue.put(
            (
                "EXECUTE_COMMAND",
                {
                    "code": code,
                    "silent": bool(silent),
                },
            )
        )

    def is_ready(self):
        return self.kernel_client is not None and self.kernel_process.poll() is None

    def mainloop(self):
        try:
            while not self._stopping.is_set():
                if not self._ensure_kernel_client():
                    if self._stopping.is_set():
                        break
                    if self.kernel_process.poll() is not None:
                        self.app.on_kernel_crashed()
                        return
                    time.sleep(0.1)
                    continue

                self._drain_kernel_messages()
                self._drain_commands()

                if self.kernel_process.poll() is not None:
                    self._close_kernel_client()
                    if not self._stopping.is_set():
                        self.app.on_kernel_crashed()
                    return

                time.sleep(0.05)
        finally:
            self._close_kernel_client()

    def _ensure_kernel_client(self):
        if self.kernel_client is not None:
            return True
        if not os.path.exists(self.connection_file):
            return False
        client = BlockingKernelClient(connection_file=self.connection_file)
        client.load_connection_file()
        client.start_channels()
        try:
            client.wait_for_ready(timeout=5)
        except Exception:
            client.stop_channels()
            return False
        self.kernel_client = client
        if not self._ready_notified:
            self._ready_notified = True
            if not self._stopping.is_set():
                self.app.on_kernel_ready()
        return True

    def _close_kernel_client(self):
        if self.kernel_client is None:
            return
        try:
            self.kernel_client.stop_channels()
        finally:
            self.kernel_client = None

    def _drain_commands(self):
        while True:
            try:
                task, data = self.command_queue.get_nowait()
            except queue.Empty:
                return
            if task == "QUIT":
                return
            if task != "EXECUTE_COMMAND":
                continue
            if self.kernel_client is None or self.kernel_process.poll() is not None:
                continue
            self.kernel_client.execute(
                data["code"],
                silent=data.get("silent", True),
            )

    def _drain_kernel_messages(self):
        while True:
            try:
                task, data = self.from_kernel.get(timeout=0.01)
            except Exception:
                return
            if task == "OPEN_TABLE_REQUEST":
                self.app.open_table(
                    data.get("names", []),
                    data.get("target"),
                    visible_title=data.get("title"),
                )
            elif task == "TABLE_DATA_RESPONSE":
                self.app.on_table_data(data)
            elif task == "ENTER_NO_PROJECT_STATE":
                self.app.enter_no_project_state()
            elif task == "ACTIVATE_PROJECT":
                self.app.activate_project(data.get("path"))
            elif task == "QUIT_REQUESTED":
                self._stopping.set()
                self.app.request_gui_quit()
                return
            elif task == "PROJECT_STATE_RESULT":
                self.app.on_project_state_result(data)
            elif task == "WINDOW_MACROS_RESPONSE":
                if data.get("kind") == "table":
                    self.app.update_table_macros(data.get("macros", []))


class RemoteRequestServer(ZMQServer):
    """Lyse-compatible request server owned by the GUI process."""

    def __init__(self, app, port):
        self.app = app
        super().__init__(port=port, bind_address="tcp://*")

    def handler(self, request_data):
        if request_data == "hello":
            return "hello"
        if isinstance(request_data, dict) and "filepath" in request_data:
            request_data = shared_drive.path_to_local(str(request_data["filepath"]))
            if isinstance(request_data, bytes):
                request_data = request_data.decode("utf8")
        if isinstance(request_data, str):
            runtime_helper = getattr(self.app, "runtime_helper", None)
            if runtime_helper is None:
                return "error: kernel unavailable"
            runtime_helper.enqueue_execute(format_remote_command(request_data), silent=False)
            return "added successfully"
        return (
            "error: operation not supported. Recognised requests are:\n "
            "'hello'\n {'filepath': <some_agnostic_path>}\n <some_agnostic_path>"
        )
