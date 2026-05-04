import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugins.remote_requests import RemoteRequestServer


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
class TestRuntimeArchitecture(unittest.TestCase):
    def test_hyde_start_kernel_runtime_launches_kernel_child_directly(self):
        class FakeProcessTree:
            def __init__(self):
                self.calls = []

            def subprocess(self, path, args=None, output_redirection_port=None, startup_timeout=None):
                self.calls.append((path, list(args or []), output_redirection_port, startup_timeout))
                process = type("FakeProcess", (), {"poll": lambda self: None})()
                return "to-kernel", "from-kernel", process

        class FakeRuntimeHelper:
            def __init__(self, app, connection_file, from_kernel, kernel_process):
                self.app = app
                self.connection_file = connection_file
                self.from_kernel = from_kernel
                self.kernel_process = kernel_process
                self.started = False

            def start(self):
                self.started = True

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
        self.assertTrue(dummy_app.runtime_helper.started)

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
        dummy_app = type("DummyApp", (), {})()
        dummy_app.shutting_down = False
        dummy_app._quit_command_sent = True
        dummy_app.runtime_helper = helper
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
                ("kernel_crashed", {}),
                ("restart_runtime",),
            ],
        )
        warning.assert_called_once()

    def test_shutdown_runtime_requests_kernel_shutdown_and_schedules_completion(self):
        kernel_client = FakeKernelClient()
        process_calls = []

        helper = type("Helper", (), {})()
        helper.kernel_client = None
        helper.thread = FakeJoinThread()
        helper.stop = lambda: process_calls.append(("helper_stop",))

        dummy_app = type("DummyApp", (), {})()
        dummy_app._runtime_shutdown = False
        dummy_app.stop_project_watcher = lambda: process_calls.append(("stop_watcher",))
        dummy_app.plugin_service = lambda key: (
            type("CommandWindowService", (), {"kernel_client": lambda self: kernel_client})()
            if key == "visible_command_service"
            else None
        )
        dummy_app.runtime_helper = helper
        dummy_app.emit_plugin_event = lambda name, data=None: process_calls.append((name, data))
        dummy_app._complete_shutdown_runtime = lambda: process_calls.append(("complete_shutdown",))

        with patch("hyde.user_interface.main.time.monotonic", return_value=10.0):
            with patch("hyde.user_interface.main.QtCore.QTimer.singleShot", side_effect=lambda delay, fn: process_calls.append(("singleShot", delay, fn))):
                HydeApp.shutdown_runtime(dummy_app)

        self.assertEqual(kernel_client.calls, [("shutdown", False)])
        self.assertEqual(dummy_app._quit_deadline, 12.0)
        self.assertEqual(process_calls[0], ("stop_watcher",))
        self.assertEqual(process_calls[1], ("application_shutdown", {}))
        self.assertEqual(process_calls[2], ("helper_stop",))
        self.assertEqual(process_calls[3], ("kernel_crashed", {}))
        self.assertEqual(process_calls[4][0:2], ("singleShot", 0))
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
