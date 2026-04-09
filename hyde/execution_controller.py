from __future__ import annotations

import os
import threading
import uuid

from labscript_utils.ls_zprocess import ProcessTree
from qtutils.qt import QtCore


class ExecutionController(QtCore.QObject):
    response_received = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process_tree = ProcessTree.instance()
        self.to_child = None
        self.from_child = None
        self.child = None
        self._reader_thread = None
        self._closing = False
        self._output_redirection_port = None

    def set_output_redirection_port(self, port):
        self._output_redirection_port = port

    def start(self):
        if self.child is not None and self.child.poll() is None:
            return
        subprocess_path = os.path.join(os.path.dirname(__file__), "execution_subprocess.py")
        kwargs = {}
        if self._output_redirection_port is not None:
            kwargs["output_redirection_port"] = self._output_redirection_port
        self.to_child, self.from_child, self.child = self.process_tree.subprocess(
            subprocess_path, startup_timeout=20, **kwargs
        )
        self._closing = False
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def execute(self, code, echo=True, record_history=True, silent=False):
        return self.send(
            "execute",
            {"code": code, "echo": echo, "record_history": record_history, "silent": silent},
        )

    def send(self, command, payload=None):
        request_id = uuid.uuid4().hex
        self.to_child.put((request_id, command, payload))
        return request_id

    def send_and_wait(self, command, payload=None, timeout=5.0):
        request_id = self.send(command, payload)
        import time
        start = time.time()
        while time.time() - start < timeout:
            response = self.from_child.get(timeout=0.1)
            if response.get("request_id") == request_id:
                return response
        raise TimeoutError(f"Timeout waiting for response to {command}")

    def stop(self):
        if self.child is None or self._closing:
            return
        self._closing = True
        try:
            self.send("quit")
        except Exception:
            return

    def _reader_loop(self):
        while not self._closing:
            try:
                response = self.from_child.get()
            except Exception:
                break
            self.response_received.emit(response)
