from __future__ import annotations

import threading
import time


class RuntimeHelper:
    """Background helper for Lane 1 kernel control messages."""

    def __init__(self, shell_services, from_kernel, kernel_process, on_kernel_crashed):
        self.shell_services = shell_services
        self.from_kernel = from_kernel
        self.kernel_process = kernel_process
        self.on_kernel_crashed = on_kernel_crashed
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
                self.shell_services["enter_no_project_state"]()
            elif task == "ACTIVATE_PROJECT":
                self.shell_services["activate_project"](data.get("path"))
            elif task == "QUIT_REQUESTED":
                self._stopping.set()
                self.shell_services["request_gui_quit"]()
                return
            elif task == "PROJECT_STATE_RESULT":
                self.shell_services["on_project_state_result"](data)
            else:
                self.shell_services["emit_plugin_event"](
                    "kernel_message",
                    {
                        "task": task,
                        "data": data,
                    },
                )
