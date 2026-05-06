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
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.figure_comm import (
    COMM_TARGET,
    register_auxiliary_figure_comm_sink,
)
from hyde.user_interface.main import HydeApp
from hyde.user_interface.main.frontend_kernel import FrontendKernelService
from hyde.user_interface.main.runtime_helper import RuntimeHelper
from hyde.user_interface.plugins.kernel_runtime import Plugin as KernelRuntimePlugin
from hyde.user_interface.plugins.remote_requests import RemoteRequestServer
from qtutils.qt import QtWidgets


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
    def __init__(self):
        self.calls = []

    def execute(self, code, silent=True):
        self.calls.append((code, silent))

    def shutdown(self, reply=False, timeout=None):
        self.calls.append(("shutdown", reply if timeout is None else (reply, timeout)))


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
        class FakeQtKernelClient:
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
                FakeQtKernelClient,
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

    def test_runtime_helper_routes_lane_one_messages_and_kernel_messages(self):
        calls = []
        from_kernel = queue.Queue()
        helper = None

        def stop_after_kernel_message(name, data=None):
            calls.append((name, data))
            helper.stop()

        shell_services = {
            "enter_no_project_state": lambda: calls.append(("no_project",)),
            "activate_project": lambda path: calls.append(("activate_project", path)),
            "on_project_state_result": lambda data: calls.append(
                ("project_state_result", data)
            ),
            "request_gui_quit": lambda: calls.append(("request_gui_quit",)),
            "emit_plugin_event": stop_after_kernel_message,
        }
        from_kernel.put(("ENTER_NO_PROJECT_STATE", None))
        from_kernel.put(("ACTIVATE_PROJECT", {"path": "/tmp/demo.hy"}))
        from_kernel.put(("PROJECT_STATE_RESULT", {"operation": "load"}))
        from_kernel.put(("TABLE_DATA_RESPONSE", {"request_id": "r1"}))
        helper = RuntimeHelper(
            shell_services=shell_services,
            from_kernel=from_kernel,
            kernel_process=type("FakeProcess", (), {"poll": lambda self: None})(),
            on_kernel_crashed=lambda: calls.append(("kernel_crashed",)),
        )

        helper.start()
        helper.thread.join(timeout=1.0)

        self.assertFalse(helper.thread.is_alive())
        self.assertEqual(
            calls,
            [
                ("no_project",),
                ("activate_project", "/tmp/demo.hy"),
                ("project_state_result", {"operation": "load"}),
                (
                    "kernel_message",
                    {
                        "task": "TABLE_DATA_RESPONSE",
                        "data": {"request_id": "r1"},
                    },
                ),
            ],
        )

    def test_runtime_helper_quit_requested_routes_to_shell_quit(self):
        calls = []
        from_kernel = queue.Queue()
        from_kernel.put(("QUIT_REQUESTED", None))
        helper = RuntimeHelper(
            shell_services={
                "enter_no_project_state": lambda: None,
                "activate_project": lambda path: None,
                "on_project_state_result": lambda data: None,
                "request_gui_quit": lambda: calls.append(("request_gui_quit",)),
                "emit_plugin_event": lambda name, data=None: None,
            },
            from_kernel=from_kernel,
            kernel_process=type("FakeProcess", (), {"poll": lambda self: None})(),
            on_kernel_crashed=lambda: calls.append(("kernel_crashed",)),
        )

        helper.start()
        helper.thread.join(timeout=1.0)

        self.assertEqual(calls, [("request_gui_quit",)])

    def test_runtime_helper_reports_kernel_process_death(self):
        calls = []
        helper = RuntimeHelper(
            shell_services={
                "enter_no_project_state": lambda: None,
                "activate_project": lambda path: None,
                "on_project_state_result": lambda data: None,
                "request_gui_quit": lambda: None,
                "emit_plugin_event": lambda name, data=None: None,
            },
            from_kernel=queue.Queue(),
            kernel_process=type("DeadProcess", (), {"poll": lambda self: 1})(),
            on_kernel_crashed=lambda: calls.append(("kernel_crashed",)),
        )

        helper.start()
        helper.thread.join(timeout=1.0)

        self.assertEqual(calls, [("kernel_crashed",)])

    def test_kernel_runtime_plugin_starts_shared_frontend_client_and_worker(self):
        class FakeProcessTree:
            def __init__(self):
                self.calls = []

            def subprocess(
                self,
                path,
                args=None,
                output_redirection_port=None,
                startup_timeout=None,
            ):
                self.calls.append(
                    (path, list(args or []), output_redirection_port, startup_timeout)
                )
                process = type("FakeProcess", (), {"poll": lambda self: None})()
                return "to-kernel", "from-kernel", process

        class FakeRuntimeHelper:
            def __init__(self, shell_services, from_kernel, kernel_process, on_kernel_crashed):
                self.shell_services = shell_services
                self.from_kernel = from_kernel
                self.kernel_process = kernel_process
                self.on_kernel_crashed = on_kernel_crashed
                self.started = False

            def start(self):
                self.started = True

        class FakeFrontendKernelService:
            def __init__(self, connection_file, parent=None):
                self.connection_file = connection_file
                self.parent = parent
                self.calls = []
                self.ready = FakeSignal()

            def stop(self):
                self.calls.append("stop")

            def start(self):
                self.calls.append("start")

            def kernel_client(self):
                return None

        services = {
            "ui": object(),
            "process_tree": FakeProcessTree(),
            "runtime_output_service": type(
                "LoggingService", (), {"port": lambda self: 12345}
            )(),
            "emit_plugin_event": lambda name, data=None: None,
            "on_kernel_ready": lambda: None,
            "on_kernel_crashed": lambda: None,
            "enter_no_project_state": lambda: None,
            "activate_project": lambda path: None,
            "on_project_state_result": lambda data: None,
            "request_gui_quit": lambda: None,
            "get_shutting_down": lambda: False,
            "finalize_quit": lambda: None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            connection_file = os.path.join(tmpdir, "kernel-hyde.json")
            with patch(
                "hyde.user_interface.plugins.kernel_runtime.CONNECTION_FILE",
                connection_file,
            ):
                with patch(
                    "hyde.user_interface.plugins.kernel_runtime.FrontendKernelService",
                    FakeFrontendKernelService,
                ):
                    with patch(
                        "hyde.user_interface.plugins.kernel_runtime.RuntimeHelper",
                        FakeRuntimeHelper,
                    ):
                        plugin = KernelRuntimePlugin({})
                        plugin.plugin_setup_complete({"services": services})

        runtime_service = plugin.kernel_runtime_service
        self.assertIsInstance(plugin.runtime_helper, FakeRuntimeHelper)
        self.assertIs(plugin.runtime_helper.shell_services, services)
        self.assertTrue(plugin.runtime_helper.started)
        self.assertIsInstance(plugin.frontend_kernel_service, FakeFrontendKernelService)
        self.assertEqual(plugin.frontend_kernel_service.calls, ["stop", "start"])
        self.assertEqual(len(services["process_tree"].calls), 1)
        path, args, port, startup_timeout = services["process_tree"].calls[0]
        self.assertEqual(path, KERNEL_LAUNCHER)
        self.assertEqual(args, ["-f", connection_file])
        self.assertEqual(port, 12345)
        self.assertEqual(startup_timeout, 60)
        self.assertIsNone(runtime_service.kernel_client())

    def test_kernel_runtime_plugin_shutdown_finalizes_when_process_is_stopped(self):
        calls = []

        class FakeFrontendKernelService:
            def __init__(self, connection_file, parent=None):
                self.connection_file = connection_file
                self.parent = parent
                self.ready = FakeSignal()

            def stop(self):
                calls.append(("frontend_stop",))

            def start(self):
                calls.append(("frontend_start",))

            def shutdown_kernel(self, reply=False):
                calls.append(("shutdown_kernel", reply))

            def is_ready(self):
                return True

            def execute(self, code, silent=True):
                calls.append(("execute", code, silent))
                return True

            def kernel_client(self):
                return FakeKernelClient()

        plugin = KernelRuntimePlugin({})
        plugin.services = {
            "ui": object(),
            "process_tree": type("UnusedProcessTree", (), {})(),
            "emit_plugin_event": lambda name, data=None: None,
            "on_kernel_ready": lambda: None,
            "on_kernel_crashed": lambda: None,
            "enter_no_project_state": lambda: None,
            "activate_project": lambda path: None,
            "on_project_state_result": lambda data: None,
            "request_gui_quit": lambda: None,
            "get_shutting_down": lambda: True,
            "finalize_quit": lambda: calls.append(("finalize_quit",)),
        }
        plugin.frontend_kernel_service = FakeFrontendKernelService("/tmp/kernel.json")
        plugin.runtime_helper = type(
            "Helper", (), {"stop": lambda self: calls.append(("helper_stop",))}
        )()
        plugin.kernel_process = type("StoppedProcess", (), {"poll": lambda self: 0})()

        with patch(
            "hyde.user_interface.plugins.kernel_runtime.QtCore.QTimer.singleShot",
            side_effect=lambda delay, fn: fn(),
        ):
            plugin.on_request_runtime_shutdown({})

        self.assertEqual(
            calls,
            [
                ("helper_stop",),
                ("shutdown_kernel", False),
                ("frontend_stop",),
                ("finalize_quit",),
            ],
        )

    def test_kernel_runtime_plugin_shutdown_waits_then_terminates_running_process(self):
        calls = []
        timer_delays = []

        class FakeFrontendKernelService:
            def __init__(self, connection_file, parent=None):
                self.connection_file = connection_file
                self.parent = parent
                self.ready = FakeSignal()

            def stop(self):
                calls.append(("frontend_stop",))

            def shutdown_kernel(self, reply=False):
                calls.append(("shutdown_kernel", reply))

        class RunningProcess:
            def __init__(self):
                self.terminated = False

            def poll(self):
                return 0 if self.terminated else None

            def terminate(self):
                calls.append(("terminate",))
                self.terminated = True

        plugin = KernelRuntimePlugin({})
        plugin.services = {
            "ui": object(),
            "process_tree": type("UnusedProcessTree", (), {})(),
            "emit_plugin_event": lambda name, data=None: None,
            "on_kernel_ready": lambda: None,
            "on_kernel_crashed": lambda: None,
            "enter_no_project_state": lambda: None,
            "activate_project": lambda path: None,
            "on_project_state_result": lambda data: None,
            "request_gui_quit": lambda: None,
            "get_shutting_down": lambda: True,
            "finalize_quit": lambda: calls.append(("finalize_quit",)),
        }
        plugin.frontend_kernel_service = FakeFrontendKernelService("/tmp/kernel.json")
        plugin.runtime_helper = type(
            "Helper", (), {"stop": lambda self: calls.append(("helper_stop",))}
        )()
        plugin.kernel_process = RunningProcess()

        with patch(
            "hyde.user_interface.plugins.kernel_runtime.time.monotonic",
            side_effect=[100.0, 100.0, 102.5],
        ):
            with patch(
                "hyde.user_interface.plugins.kernel_runtime.QtCore.QTimer.singleShot",
                side_effect=lambda delay, fn: (
                    timer_delays.append(delay),
                    fn(),
                )[-1],
            ):
                plugin.on_request_runtime_shutdown({})

        self.assertEqual(timer_delays, [0, 50])
        self.assertEqual(
            calls,
            [
                ("helper_stop",),
                ("shutdown_kernel", False),
                ("frontend_stop",),
                ("terminate",),
                ("finalize_quit",),
            ],
        )

    def test_hyde_procedure_change_uses_hidden_execution_service(self):
        queued = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.current_project_dir = "/tmp/project.hy"
        dummy_app.plugin_service = lambda key: (
            type(
                "ExecutionService",
                (),
                {"execute_hidden": lambda self, code, silent=True: queued.append((code, silent))},
            )()
            if key == "python_execution_service"
            else None
        )

        HydeApp.on_procedure_change(
            dummy_app,
            "procedures/example.py",
            {},
            event="modified",
        )

        self.assertEqual(len(queued), 1)
        code, silent = queued[0]
        self.assertTrue(silent)
        self.assertIn("execute_procedures_bootstrap", code)
        self.assertIn("/tmp/project.hy", code)
        self.assertIn(os.path.dirname(HYDE_DIR), code)
        self.assertIn("reset_namespace=False", code)

    def test_remote_request_server_uses_hidden_execution_with_non_silent_flag(self):
        queued = []
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.execute_hidden = (
            lambda code, silent=True: queued.append((code, silent)) or True
        )

        self.assertEqual(server.handler("hello"), "hello")
        self.assertEqual(server.handler("/path/to/file.h5"), "added successfully")
        state = RuntimeCommandState()
        state.set_remote_request("/path/to/file.h5")
        self.assertEqual(queued, [(state.python_source(), False)])

    def test_on_kernel_crashed_resets_shell_state_without_runtime_restart(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.shutting_down = False
        dummy_app._quit_command_sent = True
        dummy_app.ui = object()
        dummy_app.enter_no_project_state = lambda: calls.append(("no_project",))
        dummy_app.end_project_operation = lambda: calls.append(("end",))
        dummy_app.emit_plugin_event = lambda name, data=None: calls.append((name, data))

        with patch("hyde.user_interface.main.QtWidgets.QMessageBox.warning") as warning:
            HydeApp.on_kernel_crashed(dummy_app)

        self.assertFalse(dummy_app._quit_command_sent)
        self.assertEqual(
            calls,
            [
                ("no_project",),
                ("end",),
                ("kernel_crashed", {}),
            ],
        )
        warning.assert_called_once()

    def test_begin_shutdown_from_close_event_emits_shutdown_events_once(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app._runtime_shutdown = False
        dummy_app.stop_project_watcher = lambda: calls.append(("stop_watcher",))
        dummy_app.emit_plugin_event = lambda name, data=None: calls.append((name, data))

        HydeApp.begin_shutdown_from_close_event(dummy_app)
        HydeApp.begin_shutdown_from_close_event(dummy_app)

        self.assertTrue(dummy_app._runtime_shutdown)
        self.assertEqual(
            calls,
            [
                ("stop_watcher",),
                ("application_shutdown", {}),
                ("request_runtime_shutdown", {}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
