from __future__ import annotations

from labscript_utils.ls_zprocess import ZMQServer
from qtutils import inmain_decorator

from .message_handling import HydeInbox, handle_lyse_request


class HydeMessageServer(ZMQServer):
    def __init__(self, app, port):
        self.app = app
        self.inbox = HydeInbox()
        super().__init__(port)

    def handler(self, request_data):
        return handle_lyse_request(request_data, self.inbox, self._queue_filepath)

    @inmain_decorator(wait_for_return=True)
    def _queue_filepath(self, filepath):
        self.app.handle_incoming_filepath(filepath)
        return filepath

