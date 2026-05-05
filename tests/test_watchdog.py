import os
import queue
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.figure_comm import COMM_TARGET, register_auxiliary_figure_comm_sink
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.main import HydeApp
from hyde.user_interface.main.frontend_kernel import FrontendKernelService
from hyde.user_interface.main.runtime_helper import RuntimeHelper
from hyde.user_interface.plugins.remote_requests import RemoteRequestServer
from qtutils.qt import QtWidgets


class FakeKernelClient:
    def __init__(self):
        self.calls = []

    def execute(self, code, silent=True):
        self.calls.append((code, silent))

    def shutdown(self, reply=False, timeout=None):
        self.calls.append(("shutdown", reply if timeout is None else (reply, timeout)))


class FakeApp:
    def __init__(self):
        self.calls = []
        self.shutting_down = False

    def enter_no_project_state(self):
        self.calls.append(("enter_no_project_state",))

    def activate_project(self, path):
        self.calls.append(("activate_project", path))

    def on_project_state_result(self, data):
        self.calls.append(("project_state_result", data))

    def request_gui_quit(self):
        self.calls.append(("request_gui_quit",))

    def on_kernel_crashed(self):
        self.calls.append(("kernel_crashed",))

    def on_kernel_ready(self):
        self.calls.append(("kernel_ready",))

    def emit_plugin_event(self, name, data=None):
        self.calls.append(("plugin_event", name, data))


class FakeStatusBar:
    def __init__(self):
        self.messages = []
        self.cleared = 0

    def showMessage(self, message, timeout=0):
        self.messages.append((message, timeout))

    def clearMessage(self):
        self.cleared += 1


class FakeJoinThread:
    def join(self, timeout=None):
        self.timeout = timeout

    def is_alive(self):
        return False


class FakeCommManager:
    def __init__(self):
        self.targets = {}

    def register_target(self, target_name, callback):
        self.targets[target_name] = callback


class FakeAuxComm:
    def __init__(self, comm_id="comm-1"):
        self.comm_id = comm_id
        self._on_msg = None
        self._on_close = None

    def on_msg(self, callback):
        self._on_msg = callback

    def on_close(self, callback):
        self._on_close = callback


class TestRuntimeArchitecture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_register_auxiliary_figure_comm_sink_absorbs_opened_comm(self):
        client = type("FakeClient", (), {"comm_manager": FakeCommManager()})()

        self.assertTrue(register_auxiliary_figure_comm_sink(client, "runtime_helper"))

        handler = client.comm_manager.targets[COMM_TARGET]
        comm = FakeAuxComm("aux-1")
        handler(comm, {"content": {"data": {"figure_number": 1}}})

        self.assertIsNotNone(comm._on_msg)
        self.assertIsNotNone(comm._on_close)

    def test_frontend_kernel_service_marks_ready_from_kernel_info_reply(self):
        class FakeSignal:
            def __init__(self):
                self._callbacks = []

            def connect(self, callback):
                self._callbacks.append(callback)

            def disconnect(self, callback):
                self._callbacks.remove(callback)

            def emit(self, message=None):
                for callback in list(self._callbacks):
                    if message is None:
                        callback()
                    else:
                        callback(message)

        class FakeShellChannel:
            def __init__(self):
                self.message_received = FakeSignal()

        class FakeKernelClient:
            def __init__(self, connection_file):
                self.connection_file = connection_file
                self.shell_channel = FakeShellChannel()
                self.start_channels_calls = 0
                self.stop_channels_calls = 0
                self.kernel_info_calls = 0

            def load_connection_file(self):
                return None

            def start_channels(self):
                self.start_channels_calls += 1

            def stop_channels(self):
                self.stop_channels_calls += 1

            def kernel_info(self):
                self.kernel_info_calls += 1
                return f"msg-{self.kernel_info_calls}"

        with tempfile.TemporaryDirectory() as tmpdir:
            connection_file = os.path.join(tmpdir, "kernel.json")
            with open(connection_file, "w", encoding="utf-8"):
                pass
            ready_events = []
            with patch(
                "hyde.user_interface.main.frontend_kernel.QtKernelClient",
                FakeKernelClient,
            ):
                service = FrontendKernelService(connection_file)
                service.ready.connect(lambda: ready_events.append("ready"))

                service._try_connect()
                self.assertFalse(service.is_ready())
                self.assertEqual(service.kernel_client().start_channels_calls, 1)
                self.assertEqual(service.kernel_client().kernel_info_calls, 1)

                service.kernel_client().shell_channel.message_received.emit(
                    {
                        "header": {"msg_type": "kernel_info_reply"},
                        "parent_header": {"msg_id": "msg-1"},
                    }
                )

                self.assertTrue(service.is_ready())
                self.assertEqual(ready_events, ["ready"])

    def test_runtime_helper_executes_queued_command_through_shared_frontend_service(self):
        executed = []
        frontend_kernel_service = type(
            "FrontendKernelService",
            (),
            {
                "is_ready": lambda self: True,
                "execute": lambda self, code, silent=True: executed.append((code, silent)) or True,
            },
        )()
        helper = RuntimeHelper(
            app=type("FakeApp", (), {"ui": object()})(),
            frontend_kernel_service=frontend_kernel_service,
            from_kernel=queue.Queue(),
            kernel_process=type("FakeProcess", (), {"poll": lambda self: None})(),
        )
        helper.enqueue_execute("print('hello')", silent=True)
        helper._drain_commands()

        self.assertEqual(executed, [("print('hello')", True)])

    def test_hyde_start_kernel_runtime_launches_kernel_child_directly(self):
        class FakeProcessTree:
            def __init__(self):
                self.calls = []

            def subprocess(self, path, args=None, output_redirection_port=None, startup_timeout=None):
                self.calls.append((path, list(args or []), output_redirection_port, startup_timeout))
                process = type("FakeProcess", (), {"poll": lambda self: None})()
                return "to-kernel", "from-kernel", process

        class FakeRuntimeHelper:
            def __init__(self, app, frontend_kernel_service, from_kernel, kernel_process):
                self.app = app
                self.frontend_kernel_service = frontend_kernel_service
                self.from_kernel = from_kernel
                self.kernel_process = kernel_process
                self.started = False

            def start(self):
                self.started = True

        class FakeFrontendKernelService:
            def __init__(self):
                self.calls = []

            def stop(self):
                self.calls.append("stop")

            def start(self):
                self.calls.append("start")

        dummy_app = type("DummyApp", (), {})()
        dummy_app.process_tree = FakeProcessTree()
        dummy_app.plugin_service = lambda key: (
            type("LoggingService", (), {"port": lambda self: 12345})()
            if key == "runtime_output_service"
            else None
        )
        dummy_app.runtime_helper = None
        dummy_app.kernel_to_child = None
        dummy_app.kernel_from_child = None
        dummy_app.kernel_process = None
        dummy_app.frontend_kernel_service = FakeFrontendKernelService()

        with tempfile.TemporaryDirectory() as tmpdir:
            connection_file = os.path.join(tmpdir, "kernel-hyde.json")
            with patch("hyde.user_interface.main.CONNECTION_FILE", connection_file):
                with patch("hyde.user_interface.main.RuntimeHelper", FakeRuntimeHelper):
                    HydeApp.start_kernel_runtime(dummy_app)

        self.assertEqual(len(dummy_app.process_tree.calls), 1)
        path, args, port, startup_timeout = dummy_app.process_tree.calls[0]
        self.assertEqual(path, KERNEL_LAUNCHER)
        self.assertEqual(args, ["-f", connection_file])
        self.assertEqual(port, 12345)
        self.assertEqual(startup_timeout, 60)
        self.assertEqual(dummy_app.kernel_to_child, "to-kernel")
        self.assertEqual(dummy_app.kernel_from_child, "from-kernel")
        self.assertIsInstance(dummy_app.runtime_helper, FakeRuntimeHelper)
        self.assertIs(dummy_app.runtime_helper.frontend_kernel_service, dummy_app.frontend_kernel_service)
        self.assertTrue(dummy_app.runtime_helper.started)
        self.assertEqual(dummy_app.frontend_kernel_service.calls, ["stop", "start"])

    def test_procedure_change_enqueues_silent_reload_on_runtime_queue(self):
        queued = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.current_project_dir = "/tmp/project.hy"
        dummy_app.queue_background_command = lambda code, silent=True: queued.append((code, silent))

        HydeApp.on_procedure_change(dummy_app, "procedures/example.py", {}, event="modified")

        self.assertEqual(len(queued), 1)
        code, silent = queued[0]
        self.assertTrue(silent)
        self.assertIn("execute_procedures_bootstrap", code)
        self.assertIn("/tmp/project.hy", code)
        self.assertIn(os.path.dirname(HYDE_DIR), code)
        self.assertIn("reset_namespace=False", code)

    def test_queue_background_command_uses_runtime_helper_queue(self):
        queued = []
        runtime_helper = type(
            "RuntimeHelper",
            (),
            {"enqueue_execute": lambda self, code, silent=True: queued.append((code, silent))},
        )()
        dummy_app = type("DummyApp", (), {"runtime_helper": runtime_helper})()

        self.assertTrue(HydeApp.queue_background_command(dummy_app, "x = 1", silent=False))
        self.assertEqual(queued, [("x = 1", False)])

    def test_remote_request_server_queues_visible_remote_execution(self):
        queued = []
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.enqueue_command = lambda code, silent=True: queued.append((code, silent)) or True

        self.assertEqual(server.handler("hello"), "hello")
        self.assertEqual(server.handler("/path/to/file.h5"), "added successfully")
        state = RuntimeCommandState()
        state.set_remote_request("/path/to/file.h5")
        self.assertEqual(queued, [(state.python_source(), False)])

    def test_on_kernel_crashed_stops_helper_before_restart(self):
        calls = []
        helper = type("Helper", (), {"stop": lambda self: calls.append(("helper_stop",))})()
        frontend_kernel_service = type(
            "FrontendKernelService",
            (),
            {"stop": lambda self: calls.append(("frontend_stop",))},
        )()
        dummy_app = type("DummyApp", (), {})()
        dummy_app.shutting_down = False
        dummy_app._quit_command_sent = True
        dummy_app.runtime_helper = helper
        dummy_app.frontend_kernel_service = frontend_kernel_service
        dummy_app.ui = object()
        dummy_app.enter_no_project_state = lambda: calls.append(("no_project",))
        dummy_app.end_project_operation = lambda: calls.append(("end",))
        dummy_app.emit_plugin_event = lambda name, data=None: calls.append((name, data))
        dummy_app.start_kernel_runtime = lambda: calls.append(("restart_runtime",))

        with patch("hyde.user_interface.main.QtWidgets.QMessageBox.warning") as warning:
            HydeApp.on_kernel_crashed(dummy_app)

        self.assertFalse(dummy_app._quit_command_sent)
        self.assertIsNone(dummy_app.runtime_helper)
        self.assertEqual(
            calls,
            [
                ("no_project",),
                ("end",),
                ("helper_stop",),
                ("frontend_stop",),
                ("kernel_crashed", {}),
                ("restart_runtime",),
            ],
        )
        warning.assert_called_once()

    def test_shutdown_runtime_requests_kernel_shutdown_and_schedules_completion(self):
        process_calls = []
        frontend_kernel_service = type(
            "FrontendKernelService",
            (),
            {
                "shutdown_kernel": lambda self, reply=False: process_calls.append(
                    ("shutdown_kernel", reply)
                ),
                "stop": lambda self: process_calls.append(("frontend_stop",)),
            },
        )()
        helper = type("Helper", (), {"stop": lambda self: process_calls.append(("helper_stop",))})()

        dummy_app = type("DummyApp", (), {})()
        dummy_app._runtime_shutdown = False
        dummy_app.stop_project_watcher = lambda: process_calls.append(("stop_watcher",))
        dummy_app.runtime_helper = helper
        dummy_app.frontend_kernel_service = frontend_kernel_service
        dummy_app.emit_plugin_event = lambda name, data=None: process_calls.append((name, data))
        dummy_app._complete_shutdown_runtime = lambda: process_calls.append(("complete_shutdown",))

        with patch("hyde.user_interface.main.time.monotonic", return_value=10.0):
            with patch("hyde.user_interface.main.QtCore.QTimer.singleShot", side_effect=lambda delay, fn: process_calls.append(("singleShot", delay, fn))):
                HydeApp.shutdown_runtime(dummy_app)

        self.assertEqual(dummy_app._quit_deadline, 12.0)
        self.assertEqual(process_calls[0], ("stop_watcher",))
        self.assertEqual(process_calls[1], ("application_shutdown", {}))
        self.assertEqual(process_calls[2], ("shutdown_kernel", False))
        self.assertEqual(process_calls[3], ("helper_stop",))
        self.assertEqual(process_calls[4], ("frontend_stop",))
        self.assertEqual(process_calls[5], ("kernel_crashed", {}))
        self.assertEqual(process_calls[6][0:2], ("singleShot", 0))
        self.assertIsNone(dummy_app.runtime_helper)

    def test_complete_shutdown_runtime_closes_when_kernel_already_stopped(self):
        process_calls = []

        class DummyProcess:
            def poll(self):
                return 0

        dummy_app = type("DummyApp", (), {})()
        dummy_app.runtime_helper = None
        dummy_app.kernel_process = DummyProcess()
        dummy_app._quit_deadline = 0.0
        dummy_app.ui = type("UI", (), {"close": lambda self: process_calls.append(("close",))})()

        HydeApp._complete_shutdown_runtime(dummy_app)

        self.assertEqual(process_calls, [("close",)])



if __name__ == "__main__":
    unittest.main()
