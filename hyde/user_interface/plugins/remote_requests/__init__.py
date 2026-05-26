import logging

from labscript_utils import shared_drive
from labscript_utils.labconfig import LabConfig
from labscript_utils.ls_zprocess import ZMQServer
from zmq.error import ZMQError

from hyde.user_interface.plugins.file.dialogs import HydeAppIR
from hyde.user_interface.shared.plugin import HydePlugin


def _remote_port():
    try:
        return int(LabConfig().get("ports", "lyse"))
    except Exception:
        return 42519


class RemoteRequestServer(ZMQServer):
    """Lyse-compatible request server owned by the remote-requests plugin."""

    def __init__(self, execute_hidden, port, current_app_ir=None):
        self.execute_hidden = execute_hidden
        self.current_app_ir = current_app_ir or (lambda: HydeAppIR())
        super().__init__(port=port, bind_address="tcp://*")

    def handler(self, request_data):
        if request_data == "hello":
            return "hello"
        if isinstance(request_data, dict) and "filepath" in request_data:
            request_data = shared_drive.path_to_local(str(request_data["filepath"]))
            if isinstance(request_data, bytes):
                request_data = request_data.decode("utf8")
        if isinstance(request_data, str):
            app_ir = self.current_app_ir()
            request_ir = app_ir.with_remote_request(request_data)
            if not self.execute_hidden(
                app_ir.current_diff(request_ir).python_source(),
                silent=True,
            ):
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

    def setup(self, data=None):
        del data
        try:
            self.server = RemoteRequestServer(
                self.services["python_execution_service"].execute_hidden,
                _remote_port(),
                current_app_ir=self.services.get("get_current_app_ir"),
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
