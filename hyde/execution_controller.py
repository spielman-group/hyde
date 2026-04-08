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

    def start(self):
        if self.child is not None and self.child.poll() is None:
            return
        subprocess_path = os.path.join(os.path.dirname(__file__), "execution_subprocess.py")
        self.to_child, self.from_child, self.child = self.process_tree.subprocess(
            subprocess_path, startup_timeout=20
        )
        self._closing = False
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def execute(self, code, echo=True, record_history=True):
        return self.send("execute", {"code": code, "echo": echo, "record_history": record_history})

    def send(self, command, payload=None):
        request_id = uuid.uuid4().hex
        self.to_child.put((request_id, command, payload))
        return request_id

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
