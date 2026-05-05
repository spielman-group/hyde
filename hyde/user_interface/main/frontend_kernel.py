from __future__ import annotations

import logging
import os
import time

from qtconsole.client import QtKernelClient
from qtutils.qt import QtCore


LOGGER = logging.getLogger("hyde")


class FrontendKernelService(QtCore.QObject):
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
        if self._kernel_client is None or not self._ready:
            return False
        self._kernel_client.execute(code, silent=bool(silent))
        return True

    def shutdown_kernel(self, reply=False):
        if self._kernel_client is None:
            return False
        self._kernel_client.shutdown(reply=reply)
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
        if self._ready or self._kernel_client is None:
            return
        msg_type = (
            message.get("msg_type")
            or message.get("header", {}).get("msg_type")
        )
        if msg_type != "kernel_info_reply":
            return
        parent_msg_id = message.get("parent_header", {}).get("msg_id")
        if self._ready_probe_msg_id and parent_msg_id not in (None, self._ready_probe_msg_id):
            return
        self._ready = True
        self._ready_probe_msg_id = None
        self._ready_probe_at = None
        self._poll_timer.stop()
        try:
            self._kernel_client.shell_channel.message_received.disconnect(self._on_shell_message)
        except Exception:
            pass
        self.ready.emit()
