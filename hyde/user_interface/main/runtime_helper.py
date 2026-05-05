from __future__ import annotations

import queue
import threading
import time


class RuntimeHelper:
    """GUI-owned background helper for kernel process signals and silent execution."""

    def __init__(self, app, frontend_kernel_service, from_kernel, kernel_process):
        self.app = app
        self.frontend_kernel_service = frontend_kernel_service
        self.from_kernel = from_kernel
        self.kernel_process = kernel_process
        self.command_queue = queue.Queue()
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
        return (
            self.kernel_process.poll() is None
            and self.frontend_kernel_service is not None
            and self.frontend_kernel_service.is_ready()
        )

    def mainloop(self):
        while not self._stopping.is_set():
            if self.kernel_process.poll() is not None:
                if not self._stopping.is_set():
                    self.app.on_kernel_crashed()
                return
            self._drain_commands()

            try:
                task, data = self.from_kernel.get(timeout=0.01)
            except Exception:
                time.sleep(0.05)
                continue
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

    def _drain_commands(self):
        if self.frontend_kernel_service is None or not self.frontend_kernel_service.is_ready():
            return
        while not self._stopping.is_set():
            try:
                task, data = self.command_queue.get_nowait()
            except queue.Empty:
                return
            if task == "QUIT":
                return
            if task != "EXECUTE_COMMAND":
                continue
            executed = self.frontend_kernel_service.execute(
                data["code"],
                silent=data.get("silent", True),
            )
            if not executed:
                self.command_queue.put((task, data))
                return
