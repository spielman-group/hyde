import os
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.execution.comms import FIGURE_COMM_TARGET
from hyde.user_interface.plugins.figure_interactive.matplotlib_support import (
    register_auxiliary_figure_comm_sink,
)
from hyde.user_interface.main import HydeApp
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.plugins.kernel_runtime import (
    FrontendKernelService,
    Plugin as KernelRuntimePlugin,
    PythonExecutionService,
    RuntimeHelper,
)
from hyde.user_interface.plugins.remote_requests import RemoteRequestServer
from qtutils.qt import QtCore, QtWidgets


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


class FinishedCollector:
    """Bound-method callback receiver; see STYLE.md on Qt receiver lifetimes."""

    def __init__(self):
        self.finished = []

    def collect(self, request):
        self.finished.append(request)


class FakeShellChannel:
    def __init__(self):
        self.message_received = FakeSignal()


class FinishedCollector:
    """Bound-method callback receiver; see STYLE.md on Qt receiver lifetimes."""

    def __init__(self):
        self.finished = []

    def collect(self, request):
        self.finished.append(request)


class ReplyCollector:
    """Bound-method signal receiver; see STYLE.md on Qt receiver lifetimes."""

    def __init__(self):
        self.replies = []

    def collect(self, msg_id, content):
        self.replies.append((msg_id, content))

    def msg_ids(self):
        return [msg_id for msg_id, _ in self.replies]


class FakeKernelClient:
    def __init__(self):
        self.calls = []
        self.shell_channel = FakeShellChannel()
        self.execute_calls = 0

    def execute(self, code, silent=True):
        self.calls.append((code, silent))
        self.execute_calls += 1
        return f"execute-{self.execute_calls}"

    def shutdown(self, restart=False):
        self.calls.append(("shutdown", restart))

    def stop_channels(self):
        self.calls.append(("stop_channels",))


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

        handler = client.comm_manager.targets[FIGURE_COMM_TARGET]
        comm = FakeAuxComm("aux-1")
        handler(comm, {"content": {"data": {"figure_number": 1}}})

        self.assertIsNotNone(comm._on_msg)
        self.assertIsNotNone(comm._on_close)

    def test_app_ir_preserves_session_restore_python_source(self):
        app_ir = HydeAppIR(current_project_dir="/tmp/demo.hy")
        restore_ir = app_ir.with_session_restore_source("x = 1")

        source = app_ir.current_diff(restore_ir).python_source(log=False)

        self.assertEqual("x = 1\n", source)

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
                "hyde.user_interface.plugins.kernel_runtime.QtKernelClient",
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

    def test_frontend_kernel_service_reports_no_request_when_kernel_is_absent(self):
        service = FrontendKernelService("/tmp/kernel.json")
        self.assertIsNone(service.execute("value = 1"))

        service._kernel_client = FakeKernelClient()
        self.assertIsNone(service.execute("value = 1"))

    def test_frontend_kernel_service_keeps_listening_for_replies_once_ready(self):
        """Readiness must not deafen the shell channel."""

        class FakeQtKernelClient(FakeKernelClient):
            def __init__(self, connection_file):
                super().__init__()
                self.connection_file = connection_file

            def load_connection_file(self):
                return None

            def start_channels(self):
                return None

            def kernel_info(self):
                return "probe-1"

        with tempfile.TemporaryDirectory() as tmpdir:
            connection_file = os.path.join(tmpdir, "kernel.json")
            with open(connection_file, "w", encoding="utf-8"):
                pass
            with patch(
                "hyde.user_interface.plugins.kernel_runtime.QtKernelClient",
                FakeQtKernelClient,
            ):
                service = FrontendKernelService(connection_file)
                service._try_connect()
                channel = service.kernel_client().shell_channel
                channel.message_received.emit(
                    {
                        "header": {"msg_type": "kernel_info_reply"},
                        "parent_header": {"msg_id": "probe-1"},
                    }
                )
                self.assertTrue(service.is_ready())

                collector = FinishedCollector()
                request = service.request(
                    "after_ready()", on_finished=collector.collect
                )
                channel.message_received.emit(
                    {
                        "header": {"msg_type": "execute_reply"},
                        "parent_header": {"msg_id": request.msg_id},
                        "content": {"status": "ok"},
                    }
                )

                self.assertEqual(collector.finished, [request])

    def _ready_service_with_client(self):
        service = FrontendKernelService("/tmp/kernel.json")
        client = FakeKernelClient()
        service._kernel_client = client
        service._ready = True
        client.shell_channel.message_received.connect(service._on_shell_message)
        return service, client

    @staticmethod
    def _execute_reply(msg_id, content):
        return {
            "header": {"msg_type": "execute_reply"},
            "parent_header": {"msg_id": msg_id},
            "content": content,
        }

    def test_kernel_request_finishes_as_ran_when_the_command_succeeds(self):
        service, client = self._ready_service_with_client()
        collector = FinishedCollector()

        request = service.request("copy_me()", on_finished=collector.collect)
        self.assertEqual("execute-1", request.msg_id)
        self.assertTrue(request.is_pending())
        self.assertEqual(collector.finished, [])

        client.shell_channel.message_received.emit(
            self._execute_reply(request.msg_id, {"status": "ok"})
        )

        self.assertEqual(collector.finished, [request])
        self.assertFalse(request.is_pending())
        self.assertTrue(request.ran())
        self.assertEqual(request.error, "")

    def test_kernel_request_carries_the_kernel_error_when_the_command_raises(self):
        service, client = self._ready_service_with_client()
        collector = FinishedCollector()

        request = service.request("boom()", on_finished=collector.collect)
        client.shell_channel.message_received.emit(
            self._execute_reply(
                request.msg_id,
                {"status": "error", "ename": "ValueError", "evalue": "no figure"},
            )
        )

        self.assertEqual(collector.finished, [request])
        self.assertFalse(request.ran())
        self.assertEqual(request.error, "ValueError: no figure")

    def test_kernel_request_says_so_when_the_users_own_error_aborted_it(self):
        """A non-silent cell that raises aborts everything queued behind it."""
        service, client = self._ready_service_with_client()
        collector = FinishedCollector()

        request = service.request("copy_me()", on_finished=collector.collect)
        client.shell_channel.message_received.emit(
            self._execute_reply(request.msg_id, {"status": "aborted"})
        )

        self.assertFalse(request.ran())
        self.assertIn("aborted", request.error)
        self.assertNotEqual("aborted", request.error)

    def test_kernel_request_ignores_a_reply_to_a_different_request(self):
        service, client = self._ready_service_with_client()
        collector = FinishedCollector()

        request = service.request("mine()", on_finished=collector.collect)
        client.shell_channel.message_received.emit(
            self._execute_reply("someone-else", {"status": "ok"})
        )

        self.assertTrue(request.is_pending())
        self.assertEqual(collector.finished, [])

    def test_kernel_request_stays_pending_while_the_kernel_is_busy(self):
        """A request queued behind the user's own cell is waiting, not late."""
        service, _ = self._ready_service_with_client()
        collector = FinishedCollector()

        request = service.request("slow()", on_finished=collector.collect)

        self.assertTrue(request.is_pending())
        self.assertEqual(collector.finished, [])
        self.assertEqual(service.pending_requests(), (request,))

    def test_kernel_request_is_abandoned_when_the_kernel_goes_away(self):
        service, _ = self._ready_service_with_client()
        collector = FinishedCollector()

        request = service.request("copy_me()", on_finished=collector.collect)
        service.stop()

        self.assertEqual(collector.finished, [request])
        self.assertFalse(request.is_pending())
        self.assertFalse(request.ran())
        self.assertTrue(request.error)
        self.assertEqual(service.pending_requests(), ())

    def test_kernel_request_is_refused_when_there_is_no_kernel(self):
        service = FrontendKernelService("/tmp/kernel.json")
        collector = FinishedCollector()

        self.assertIsNone(service.request("copy_me()", on_finished=collector.collect))
        self.assertEqual(collector.finished, [])

    def test_a_correlated_request_from_the_wrong_thread_is_refused(self):
        """execute_hidden marshals; a request cannot, so it must refuse."""
        service, client = self._ready_service_with_client()
        plugin = type("Plugin", (), {})()
        plugin.services = {}
        plugin.frontend_kernel_service = service
        plugin._main_thread_executor = type(
            "Executor", (), {"thread": lambda self: object()}
        )()
        plugin.request_frontend = KernelRuntimePlugin.request_frontend.__get__(
            plugin, type(plugin)
        )
        collector = FinishedCollector()

        self.assertIsNone(
            PythonExecutionService(plugin).request(
                "copy_me()", on_finished=collector.collect
            )
        )
        self.assertEqual([], client.calls)

    def test_python_execution_service_dispatches_and_logs_a_correlated_request(self):
        service, client = self._ready_service_with_client()
        plugin = type("Plugin", (), {})()
        plugin.services = {}
        plugin.frontend_kernel_service = service
        plugin._main_thread_executor = type(
            "Executor", (), {"thread": lambda self: QtCore.QThread.currentThread()}
        )()
        plugin.request_frontend = KernelRuntimePlugin.request_frontend.__get__(
            plugin, type(plugin)
        )
        execution_service = PythonExecutionService(plugin)
        collector = FinishedCollector()

        with self.assertLogs("hyde", level="DEBUG") as logs:
            request = execution_service.request(
                "copy_me()", on_finished=collector.collect
            )

        self.assertEqual(client.calls, [("copy_me()", True)])
        output = "\n".join(logs.output)
        self.assertIn("'mode': 'hidden'", output)
        self.assertIn("python:\ncopy_me()", output)

        client.shell_channel.message_received.emit(
            self._execute_reply(request.msg_id, {"status": "ok"})
        )
        self.assertEqual(collector.finished, [request])

    def test_frontend_kernel_service_requests_real_kernel_shutdown(self):
        service = FrontendKernelService("/tmp/kernel.json")
        service._kernel_client = FakeKernelClient()

        self.assertTrue(service.shutdown_kernel())
        self.assertEqual(service.kernel_client().calls, [("shutdown", False)])

    def test_runtime_helper_routes_lane_one_messages_and_kernel_messages(self):
        calls = []
        from_kernel = queue.Queue()
        helper = None

        def stop_after_kernel_message(name, data=None):
            calls.append((name, data))
            helper.stop()

        from_kernel.put(("ENTER_NO_PROJECT_STATE", None))
        from_kernel.put(("ACTIVATE_PROJECT", {"path": "/tmp/demo.hy"}))
        from_kernel.put(("PROJECT_STATE_RESULT", {"operation": "load"}))
        from_kernel.put(("TABLE_DATA_RESPONSE", {"request_id": "r1"}))
        helper = RuntimeHelper(
            from_kernel=from_kernel,
            kernel_process=type("FakeProcess", (), {"poll": lambda self: None})(),
            on_kernel_crashed=lambda: calls.append(("kernel_crashed",)),
            enter_no_project_state=lambda: calls.append(("no_project",)),
            activate_project=lambda path: calls.append(("activate_project", path)),
            on_project_state_result=lambda data: calls.append(
                ("project_state_result", data)
            ),
            request_gui_quit=lambda: calls.append(("request_gui_quit",)),
            emit_plugin_event=stop_after_kernel_message,
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
            from_kernel=from_kernel,
            kernel_process=type("FakeProcess", (), {"poll": lambda self: None})(),
            on_kernel_crashed=lambda: calls.append(("kernel_crashed",)),
            enter_no_project_state=lambda: None,
            activate_project=lambda path: None,
            on_project_state_result=lambda data: None,
            request_gui_quit=lambda: calls.append(("request_gui_quit",)),
            emit_plugin_event=lambda name, data=None: None,
        )

        helper.start()
        helper.thread.join(timeout=1.0)

        self.assertEqual(calls, [("request_gui_quit",)])

    def test_runtime_helper_reports_kernel_process_death(self):
        calls = []
        helper = RuntimeHelper(
            from_kernel=queue.Queue(),
            kernel_process=type("DeadProcess", (), {"poll": lambda self: 1})(),
            on_kernel_crashed=lambda: calls.append(("kernel_crashed",)),
            enter_no_project_state=lambda: None,
            activate_project=lambda path: None,
            on_project_state_result=lambda data: None,
            request_gui_quit=lambda: None,
            emit_plugin_event=lambda name, data=None: None,
        )

        helper.start()
        helper.thread.join(timeout=1.0)

        self.assertEqual(calls, [("kernel_crashed",)])

    def test_a_process_tree_without_permissive_heartbeats_is_named(self):
        """Hyde needs an unmerged zprocess branch and says so when it is absent.

        Without it the kernel launch raised an unexpected-keyword TypeError,
        the plugin host caught it and logged that the plugin "may not be
        functional", and Hyde came up looking normal with no kernel at all.
        """

        class ProcessTreeWithoutHeartbeatOptions:
            def subprocess(
                self,
                path,
                args=None,
                output_redirection_port=None,
                startup_timeout=None,
            ):
                raise AssertionError("should not be reached")

        plugin = KernelRuntimePlugin({})
        plugin.services = {"process_tree": ProcessTreeWithoutHeartbeatOptions()}

        with self.assertRaises(RuntimeError) as caught:
            plugin.start_runtime()

        message = str(caught.exception)
        self.assertIn("zprocess", message)
        self.assertIn("PermissiveHeartBeat", message)
        self.assertIn("heartbeat_interval", message)

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
                heartbeat_interval=None,
                allowed_missed_heartbeats=None,
            ):
                self.calls.append(
                    (
                        path,
                        list(args or []),
                        output_redirection_port,
                        startup_timeout,
                        heartbeat_interval,
                        allowed_missed_heartbeats,
                    )
                )
                process = type("FakeProcess", (), {"poll": lambda self: None})()
                return "to-kernel", "from-kernel", process

        class FakeRuntimeHelper:
            def __init__(
                self,
                from_kernel,
                kernel_process,
                on_kernel_crashed,
                *,
                enter_no_project_state,
                activate_project,
                on_project_state_result,
                request_gui_quit,
                emit_plugin_event,
            ):
                del (
                    from_kernel,
                    kernel_process,
                    on_kernel_crashed,
                    enter_no_project_state,
                    activate_project,
                    on_project_state_result,
                        request_gui_quit,
                    emit_plugin_event,
                )
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
                        for activity in sorted(
                            plugin.get_setup_activities(),
                            key=lambda item: item["priority"],
                        ):
                            activity["action"]({"services": services})

        self.assertIsInstance(plugin.runtime_helper, FakeRuntimeHelper)
        self.assertTrue(plugin.runtime_helper.started)
        self.assertIsInstance(plugin.frontend_kernel_service, FakeFrontendKernelService)
        self.assertEqual(plugin.frontend_kernel_service.calls, ["stop", "start"])
        self.assertEqual(len(services["process_tree"].calls), 1)
        (
            path,
            args,
            port,
            startup_timeout,
            heartbeat_interval,
            allowed_missed_heartbeats,
        ) = services["process_tree"].calls[0]
        self.assertEqual(path, KERNEL_LAUNCHER)
        self.assertEqual(args, ["-f", connection_file])
        self.assertEqual(port, 12345)
        self.assertEqual(startup_timeout, 60)
        self.assertEqual(heartbeat_interval, 10)
        self.assertEqual(allowed_missed_heartbeats, 10)

    def test_kernel_runtime_plugin_logs_runtime_output_port_failure(self):
        class FakeProcessTree:
            def __init__(self):
                self.calls = []

            def subprocess(
                self,
                path,
                args=None,
                output_redirection_port=None,
                startup_timeout=None,
                heartbeat_interval=None,
                allowed_missed_heartbeats=None,
            ):
                self.calls.append(
                    (
                        path,
                        args,
                        output_redirection_port,
                        startup_timeout,
                        heartbeat_interval,
                        allowed_missed_heartbeats,
                    )
                )
                process = type("FakeProcess", (), {"poll": lambda self: None})()
                return "to-kernel", "from-kernel", process

        class BrokenLoggingService:
            def port(self):
                raise RuntimeError("port unavailable")

        class FakeFrontendKernelService:
            def stop(self):
                pass

            def start(self):
                pass

        class FakeRuntimeHelper:
            def __init__(self, *args, **kwargs):
                self.started = False

            def start(self):
                self.started = True

        services = {
            "ui": object(),
            "process_tree": FakeProcessTree(),
            "runtime_output_service": BrokenLoggingService(),
            "emit_plugin_event": lambda name, data=None: None,
            "on_kernel_crashed": lambda: None,
            "enter_no_project_state": lambda: None,
            "activate_project": lambda path: None,
            "on_project_state_result": lambda data: None,
            "request_gui_quit": lambda: None,
        }

        plugin = KernelRuntimePlugin({})
        plugin.services = services
        plugin.frontend_kernel_service = FakeFrontendKernelService()

        with patch(
            "hyde.user_interface.plugins.kernel_runtime.RuntimeHelper",
            FakeRuntimeHelper,
        ):
            with self.assertLogs("hyde", level="ERROR") as logs:
                plugin.start_runtime()

        self.assertIn(
            "Failed to acquire runtime output redirection port",
            "\n".join(logs.output),
        )
        self.assertEqual(services["process_tree"].calls[0][2], None)
        self.assertEqual(services["process_tree"].calls[0][4], 10)
        self.assertEqual(services["process_tree"].calls[0][5], 10)

    def test_kernel_runtime_plugin_contributes_kill_kernel_file_action(self):
        plugin = KernelRuntimePlugin({})

        self.assertEqual(
            plugin.get_menu_contributions(),
            [
                {
                    "location": "file",
                    "group": "application",
                    "order": 110,
                    "name": "Kill Kernel",
                    "action": plugin.kill_kernel,
                },
            ],
        )

    def test_kernel_runtime_plugin_kill_kernel_terminates_running_process(self):
        calls = []

        plugin = KernelRuntimePlugin({})
        plugin.kernel_process = type(
            "RunningProcess",
            (),
            {
                "poll": lambda self: None,
                "terminate": lambda self: calls.append("terminate"),
            },
        )()

        self.assertTrue(plugin.kill_kernel())
        self.assertEqual(calls, ["terminate"])

    def test_kernel_runtime_plugin_kill_kernel_ignores_missing_process(self):
        plugin = KernelRuntimePlugin({})

        self.assertFalse(plugin.kill_kernel())

    def test_kernel_runtime_plugin_kill_kernel_ignores_stopped_process(self):
        calls = []
        plugin = KernelRuntimePlugin({})
        plugin.kernel_process = type(
            "StoppedProcess",
            (),
            {
                "poll": lambda self: 0,
                "terminate": lambda self: calls.append("terminate"),
            },
        )()

        self.assertFalse(plugin.kill_kernel())
        self.assertEqual(calls, [])

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

            def shutdown_kernel(self):
                calls.append(("shutdown_kernel",))

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
                ("shutdown_kernel",),
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

            def shutdown_kernel(self):
                calls.append(("shutdown_kernel",))

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
                ("shutdown_kernel",),
                ("frontend_stop",),
                ("terminate",),
                ("finalize_quit",),
            ],
        )

    def test_hyde_procedure_change_matches_reload_procedures_current_app_ir_dispatch(self):
        reload_calls = []
        procedure_change_calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.current_project_dir = None
        dummy_app.current_app_ir = HydeAppIR(current_project_dir="/tmp/project.hy")
        execution_service = type(
            "ExecutionService",
            (),
            {
                "execute_hidden": (
                    lambda self, code, silent=True: current_queue.append((code, silent))
                )
            },
        )()
        dummy_app.plugin_service = (
            lambda key: execution_service if key == "python_execution_service" else None
        )

        current_queue = reload_calls
        HydeApp.reload_procedures(dummy_app)

        current_queue = procedure_change_calls
        HydeApp.on_procedure_change(
            dummy_app,
            "procedures/example.py",
            {},
            event="modified",
        )

        reload_ir = dummy_app.current_app_ir.with_reload_procedures(
            "/tmp/project.hy",
            os.path.dirname(HYDE_DIR),
            reset_namespace=False,
        )
        self.assertEqual(
            reload_calls,
            [
                (
                    dummy_app.current_app_ir.current_diff(reload_ir).python_source(),
                    True,
                )
            ],
        )
        self.assertEqual(procedure_change_calls, reload_calls)

    def test_hyde_procedure_change_is_safe_from_background_thread(self):
        queued = []
        errors = []
        finished = threading.Event()
        dummy_app = type("DummyApp", (), {})()
        dummy_app.current_project_dir = "/tmp/project.hy"
        dummy_app.plugin_service = lambda key: (
            type(
                "ExecutionService",
                (),
                {
                    "execute_hidden": lambda self, code, silent=True: queued.append(
                        (code, silent)
                    )
                },
            )()
            if key == "python_execution_service"
            else None
        )

        def worker():
            try:
                HydeApp.on_procedure_change(
                    dummy_app,
                    "procedures/example.py",
                    {},
                    event="modified",
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=worker)
        thread.start()
        app = QtWidgets.QApplication.instance()
        self.assertIsNotNone(app)
        for _ in range(100):
            if finished.wait(0.01):
                break
            app.processEvents()
        thread.join(timeout=1.0)

        self.assertEqual(errors, [])
        self.assertTrue(finished.is_set())
        self.assertEqual(len(queued), 1)
        self.assertTrue(queued[0][1])

    def test_remote_request_server_uses_hidden_execution_with_silent_hidden_lane(self):
        queued = []
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.execute_hidden = (
            lambda code, silent=True: queued.append((code, silent)) or True
        )
        server.current_app_ir = lambda: HydeAppIR(current_project_dir="/tmp/demo.hy")

        self.assertEqual(server.handler("hello"), "hello")
        self.assertEqual(server.handler("/path/to/file.h5"), "added successfully")
        app_ir = server.current_app_ir()
        request_ir = app_ir.with_remote_request("/path/to/file.h5")
        self.assertEqual(
            queued,
            [(app_ir.current_diff(request_ir).python_source(), True)],
        )

    def test_app_ir_session_restore_runs_the_session_file_as_written(self):
        """The reply to the request carries the outcome, so nothing reports it twice."""
        app_ir = HydeAppIR(current_project_dir="/tmp/demo.hy")
        restore_ir = app_ir.with_session_restore_source("Table0()\nFigure0(delay)\n")

        source = app_ir.current_diff(restore_ir).python_source()

        self.assertEqual("Table0()\nFigure0(delay)\n", source)

    def test_python_execution_service_logs_hidden_dispatch(self):
        executed = []
        plugin = type("Plugin", (), {})()
        plugin.services = {}
        plugin.frontend_kernel_service = type(
            "FrontendKernelService",
            (),
            {
                "is_ready": lambda self: True,
                "execute": lambda self, code, silent=True: (
                    executed.append((code, silent)) or True
                ),
            },
        )()
        plugin._main_thread_executor = type(
            "Executor", (), {"thread": lambda self: QtCore.QThread.currentThread()}
        )()
        plugin.execute_frontend = KernelRuntimePlugin.execute_frontend.__get__(
            plugin, type(plugin)
        )
        service = plugin.python_execution_service = PythonExecutionService(plugin)

        with self.assertLogs("hyde", level="DEBUG") as logs:
            self.assertTrue(service.execute_hidden("value = 1"))

        self.assertEqual(executed, [("value = 1", True)])
        output = "\n".join(logs.output)
        self.assertIn("[Hyde state] TransportDispatchState", output)
        self.assertIn("'mode': 'hidden'", output)
        self.assertIn("python:\nvalue = 1", output)

    def test_python_execution_service_logs_visible_dispatch(self):
        executed = []
        plugin = type("Plugin", (), {})()
        plugin.services = {
            "visible_terminal_service": type(
                "VisibleTerminalService",
                (),
                {"execute_visible": lambda self, code: executed.append(code)},
            )()
        }
        service = plugin.python_execution_service = PythonExecutionService(plugin)

        with self.assertLogs("hyde", level="DEBUG") as logs:
            self.assertTrue(service.execute_visible("print('alpha')"))

        self.assertEqual(executed, ["print('alpha')"])
        output = "\n".join(logs.output)
        self.assertIn("[Hyde state] TransportDispatchState", output)
        self.assertIn("'mode': 'visible'", output)
        self.assertIn("python:\nprint('alpha')", output)

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
