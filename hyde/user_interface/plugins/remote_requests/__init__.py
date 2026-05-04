import logging

from labscript_utils import shared_drive
from labscript_utils.labconfig import LabConfig
from labscript_utils.ls_zprocess import ZMQServer
from zmq.error import ZMQError

from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.plugin_tools import HydePlugin


def _remote_port():
    try:
        return int(LabConfig().get("ports", "lyse"))
    except Exception:
        return 42519


class RemoteRequestServer(ZMQServer):
    """Lyse-compatible request server owned by the remote-requests plugin."""

    def __init__(self, enqueue_command, port):
        self.enqueue_command = enqueue_command
        super().__init__(port=port, bind_address="tcp://*")

    def handler(self, request_data):
        if request_data == "hello":
            return "hello"
        if isinstance(request_data, dict) and "filepath" in request_data:
            request_data = shared_drive.path_to_local(str(request_data["filepath"]))
            if isinstance(request_data, bytes):
                request_data = request_data.decode("utf8")
        if isinstance(request_data, str):
            state = RuntimeCommandState()
            state.set_remote_request(request_data)
            if not self.enqueue_command(state.python_source(), silent=False):
                return "error: kernel unavailable"
            return "added successfully"
        return (
            "error: operation not supported. Recognised requests are:\n "
            "'hello'\n {'filepath': <some_agnostic_path>}\n <some_agnostic_path>"
        )


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.server = None

    def on_setup_complete(self, data=None):
        del data
        try:
            self.server = RemoteRequestServer(
                self.services["queue_background_command"],
                _remote_port(),
            )
        except ZMQError as exc:
            logging.getLogger("hyde").warning(
                "Could not start lyse-compatible remote listener: %s",
                exc,
            )
            self.server = None

    def get_event_handlers(self):
        return {
            "application_shutdown": self.on_application_shutdown,
        }

    def on_application_shutdown(self, data):
        del data
        if self.server is not None:
            self.server.shutdown()
            self.server = None
