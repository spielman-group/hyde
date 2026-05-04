from __future__ import annotations

import os
import queue
import threading
import time

from jupyter_client import BlockingKernelClient
from qtutils.qt import QtCore


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
                QtCore.QMetaObject.invokeMethod(
                    self.app.ui,
                    "_on_kernel_ready",
                    QtCore.Qt.QueuedConnection,
                )
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
            if task == "ENTER_NO_PROJECT_STATE":
                self.app.enter_no_project_state()
            elif task == "ACTIVATE_PROJECT":
                self.app.activate_project(data.get("path"))
            elif task == "QUIT_REQUESTED":
                self._stopping.set()
                self.app.request_gui_quit()
                return
            elif task == "PROJECT_STATE_RESULT":
                self.app.on_project_state_result(data)
            else:
                self.app.emit_plugin_event(
                    "kernel_message",
                    {
                        "task": task,
                        "data": data,
                    },
                )
