import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import hyde
from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.main import HydeApp, ProjectSelectionDialog
from hyde.user_interface.runtime_helper import RemoteRequestServer, RuntimeHelper
from qtutils.qt import QtWidgets


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class FakeKernelClient:
    def __init__(self):
        self.calls = []

    def execute(self, code, silent=True):
        self.calls.append((code, silent))

    def shutdown(self, reply=False, timeout=None):
        self.calls.append(("shutdown", reply if timeout is None else (reply, timeout)))


class FakeClosableChannel:
    def __init__(self, calls, name):
        self.calls = calls
        self.name = name

    def close(self):
        self.calls.append(("close_channel", self.name))


class FakeApp:
    def __init__(self):
        self.calls = []
        self.shutting_down = False

    def open_table(self, names, target=None, visible_title=None):
        self.calls.append(("open_table", list(names), target, visible_title))

    def on_table_data(self, data):
        self.calls.append(("table_data", data))

    def enter_no_project_state(self):
        self.calls.append(("enter_no_project_state",))

    def activate_project(self, path):
        self.calls.append(("activate_project", path))

    def on_project_state_result(self, data):
        self.calls.append(("project_state_result", data))

    def update_table_macros(self, macros):
        self.calls.append(("update_table_macros", list(macros)))

    def request_gui_quit(self):
        self.calls.append(("request_gui_quit",))

    def on_kernel_crashed(self):
        self.calls.append(("kernel_crashed",))

    def on_kernel_ready(self):
        self.calls.append(("kernel_ready",))


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
    def test_kernel_launcher_runs_spyder_in_process(self):
        launcher_path = Path(os.path.dirname(hyde.__file__)) / "execution" / "kernel_launcher.py"
        source = launcher_path.read_text(encoding="utf-8")

        self.assertIn("from spyder_kernels.console.start import main", source)
        self.assertIn("ProcessTree.connect_to_parent()", source)
        self.assertIn("main()", source)
        self.assertNotIn("subprocess.Popen", source)

    def test_hyde_start_kernel_runtime_launches_kernel_child_directly(self):
        class FakeProcessTree:
            def __init__(self):
                self.calls = []

            def subprocess(self, path, args=None, output_redirection_port=None, startup_timeout=None):
                self.calls.append((path, list(args or []), output_redirection_port, startup_timeout))
                return "to-kernel", "from-kernel", FakeProcess()

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
        dummy_app.logging_window = type("Log", (), {"port": 12345})()
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

    def test_runtime_helper_dispatches_direct_kernel_messages(self):
        app = FakeApp()
        helper = RuntimeHelper.__new__(RuntimeHelper)
        helper.app = app
        helper.from_kernel = queue.Queue()
        helper.kernel_process = FakeProcess()
        helper._stopping = threading.Event()

        helper.from_kernel.put(("OPEN_TABLE_REQUEST", {"names": ["a"], "target": "Table0", "title": "Visible"}))
        helper.from_kernel.put(("TABLE_DATA_RESPONSE", {"data": {"a": [1, 2]}, "request_id": "abc"}))
        helper.from_kernel.put(("ENTER_NO_PROJECT_STATE", None))
        helper.from_kernel.put(("ACTIVATE_PROJECT", {"path": "/tmp/test.hy"}))
        helper.from_kernel.put(("QUIT_REQUESTED", None))
        helper.from_kernel.put(("PROJECT_STATE_RESULT", {"operation": "load", "success": True}))
        helper.from_kernel.put(("WINDOW_MACROS_RESPONSE", {"kind": "table", "macros": [{"name": "Table0", "args": ["a"]}]}))

        helper._drain_kernel_messages()

        self.assertEqual(
            app.calls,
            [
                ("open_table", ["a"], "Table0", "Visible"),
                ("table_data", {"data": {"a": [1, 2]}, "request_id": "abc"}),
                ("enter_no_project_state",),
                ("activate_project", "/tmp/test.hy"),
                ("request_gui_quit",),
            ],
        )
        self.assertTrue(helper._stopping.is_set())

    def test_runtime_helper_executes_background_commands_with_single_kernel_client(self):
        helper = RuntimeHelper.__new__(RuntimeHelper)
        helper.command_queue = queue.Queue()
        helper.kernel_client = FakeKernelClient()
        helper.kernel_process = FakeProcess()
        helper._stopping = threading.Event()

        helper.command_queue.put(("EXECUTE_COMMAND", {"code": "a = 1", "silent": True}))
        helper.command_queue.put(("EXECUTE_COMMAND", {"code": "remote('x')", "silent": False}))
        helper.command_queue.put(("QUIT", None))

        helper._drain_commands()

        self.assertEqual(
            helper.kernel_client.calls,
            [
                ("a = 1", True),
                ("remote('x')", False),
            ],
        )

    def test_request_gui_quit_marks_shutdown_and_closes_window(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.shutting_down = False
        dummy_app.ui = type("UI", (), {"close": lambda self: calls.append(("close",))})()

        HydeApp.request_gui_quit.__wrapped__(dummy_app)

        self.assertTrue(dummy_app.shutting_down)
        self.assertEqual(calls, [("close",)])

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
        app = type("App", (), {})()
        app.runtime_helper = type(
            "Runtime",
            (),
            {"enqueue_execute": lambda self, code, silent=True: queued.append((code, silent))},
        )()
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.app = app

        self.assertEqual(server.handler("hello"), "hello")
        self.assertEqual(server.handler("/path/to/file.h5"), "added successfully")
        self.assertEqual(queued, [("remote('/path/to/file.h5')", False)])

    def test_remote_request_server_normalizes_filepath_payload(self):
        queued = []
        app = type("App", (), {})()
        app.runtime_helper = type(
            "Runtime",
            (),
            {"enqueue_execute": lambda self, code, silent=True: queued.append((code, silent))},
        )()
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.app = app

        with patch("hyde.user_interface.runtime_helper.shared_drive.path_to_local", return_value="/local/path.h5") as localize:
            response = server.handler({"filepath": "Z:\\shared\\path.h5"})

        self.assertEqual(response, "added successfully")
        localize.assert_called_once_with("Z:\\shared\\path.h5")
        self.assertEqual(queued, [("remote('/local/path.h5')", False)])

    def test_startup_project_load_uses_status_bar_instead_of_busy_dialog(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.ui = type("UI", (), {"statusbar": FakeStatusBar()})()
        dummy_app.set_project_status_message = dummy_app.ui.statusbar.showMessage
        dummy_app.clear_project_status_message = dummy_app.ui.statusbar.clearMessage
        dummy_app.begin_project_operation = lambda label: HydeApp.begin_project_operation(dummy_app, label)
        dummy_app.end_project_operation = lambda: HydeApp.end_project_operation(dummy_app)
        dummy_app.execute_command = lambda code, visible=True: calls.append(("execute", code, visible))
        dummy_app.restore_project_session = lambda: calls.append(("restore",))

        with patch("hyde.user_interface.main.format_load_project_command", return_value="LOAD_PROJECT"):
            HydeApp._load_startup_project(dummy_app, "/tmp/project.hy")
            HydeApp.on_project_state_result(dummy_app, {"operation": "load", "success": True})

        self.assertEqual(dummy_app.ui.statusbar.messages, [("Loading Hyde project...", 0)])
        self.assertEqual(dummy_app.ui.statusbar.cleared, 1)
        self.assertEqual(
            calls,
            [
                ("execute", "LOAD_PROJECT", True),
                ("restore",),
            ],
        )

    def test_load_result_restores_session_without_reactivating_project(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.current_project_dir = "/tmp/project.hy"
        dummy_app.end_project_operation = lambda: calls.append(("end",))
        dummy_app.restore_project_session = lambda: calls.append(("restore",))

        HydeApp.on_project_state_result(
            dummy_app,
            {"operation": "load", "success": True, "path": "/tmp/project.hy"},
        )

        self.assertEqual(
            calls,
            [
                ("end",),
                ("restore",),
            ],
        )
        self.assertEqual(dummy_app.current_project_dir, "/tmp/project.hy")

    def test_choose_project_uses_status_bar_operation_message(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.ui = type("UI", (), {"statusbar": FakeStatusBar()})()
        dummy_app.set_project_status_message = dummy_app.ui.statusbar.showMessage
        dummy_app._pick_project_dir = (
            lambda title, accept_label, suggested_name=None, require_existing=False: "/tmp/project.hy"
        )
        dummy_app.begin_project_operation = lambda label: HydeApp.begin_project_operation(dummy_app, label)
        dummy_app.execute_command = lambda code, visible=True: calls.append(("execute", code, visible))

        with patch("hyde.user_interface.main.format_load_project_command", return_value="LOAD_PROJECT"):
            HydeApp.choose_project(dummy_app)

        self.assertEqual(dummy_app.ui.statusbar.messages, [("Loading Hyde project...", 0)])
        self.assertEqual(calls, [("execute", "LOAD_PROJECT", True)])

    def test_choose_heal_project_dispatches_visible_heal_command(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.ui = type("UI", (), {"statusbar": FakeStatusBar()})()
        dummy_app.set_project_status_message = dummy_app.ui.statusbar.showMessage
        dummy_app._pick_project_dir = (
            lambda title, accept_label, suggested_name=None, require_existing=False: "/tmp/project.hy"
        )
        dummy_app.begin_project_operation = lambda label: HydeApp.begin_project_operation(dummy_app, label)
        dummy_app.execute_command = lambda code, visible=True: calls.append(("execute", code, visible))

        with patch("hyde.user_interface.main.format_heal_project_command", return_value="HEAL_PROJECT"):
            HydeApp.choose_heal_project(dummy_app)

        self.assertEqual(dummy_app.ui.statusbar.messages, [("Healing Hyde project...", 0)])
        self.assertEqual(calls, [("execute", "HEAL_PROJECT", True)])

    def test_project_selection_dialog_requires_existing_project_for_open(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "missing.hy")
            existing = os.path.join(tmpdir, "existing.hy")
            os.makedirs(existing)

            dialog = ProjectSelectionDialog(
                title="Open Hyde Project",
                accept_label="Open",
                require_existing=True,
            )
            dialog.selectFile(missing)
            dialog.update_accept_button()
            self.assertFalse(dialog._accept_button.isEnabled())

            dialog.selectFile(existing)
            dialog.update_accept_button()
            self.assertTrue(dialog._accept_button.isEnabled())
            dialog.close()

    def test_visible_command_error_clears_project_status_message(self):
        dummy_app = type("DummyApp", (), {})()
        dummy_app.ui = type("UI", (), {"statusbar": FakeStatusBar()})()
        dummy_app.set_project_status_message = dummy_app.ui.statusbar.showMessage
        dummy_app.clear_project_status_message = dummy_app.ui.statusbar.clearMessage
        dummy_app.begin_project_operation = lambda label: HydeApp.begin_project_operation(dummy_app, label)
        dummy_app.end_project_operation = lambda: HydeApp.end_project_operation(dummy_app)

        HydeApp.begin_project_operation(dummy_app, "Creating Hyde project...")
        HydeApp.on_visible_command_executed(dummy_app, {"content": {"status": "error"}})

        self.assertEqual(dummy_app.ui.statusbar.messages, [("Creating Hyde project...", 0)])
        self.assertEqual(dummy_app.ui.statusbar.cleared, 1)

    def test_choose_new_project_conflict_prompts_and_dispatches_overwrite(self):
        calls = []
        prompts = []
        formatted = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app._pick_project_dir = (
            lambda title, accept_label, suggested_name=None, require_existing=False: "/tmp/existing.hy"
        )
        dummy_app.begin_project_operation = lambda label: calls.append(("begin", label))
        dummy_app.execute_command = lambda code, visible=True: calls.append(("execute", code, visible))
        dummy_app.project_target_needs_confirmation = lambda project_dir: True
        dummy_app.confirm_overwrite_project = lambda project_dir: prompts.append(project_dir) or True

        def fake_format_new_project_command(*args, **kwargs):
            formatted.append((args, kwargs))
            return "NEW_PROJECT"

        with patch("hyde.user_interface.main.format_new_project_command", side_effect=fake_format_new_project_command):
            HydeApp.choose_new_project(dummy_app)

        self.assertEqual(prompts, ["/tmp/existing.hy"])
        self.assertEqual(formatted, [(("/tmp/existing.hy",), {"load": True, "overwrite": True})])
        self.assertEqual(calls, [("begin", "Creating Hyde project..."), ("execute", "NEW_PROJECT", True)])

    def test_request_quit_dispatches_visible_hyde_quit_command(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.shutting_down = False
        dummy_app._quit_command_sent = False
        dummy_app.command_window = object()
        dummy_app.execute_command = lambda code, visible=True: calls.append((code, visible))

        HydeApp.request_quit(dummy_app)

        self.assertEqual(calls, [("hyde.quit()", True)])
        self.assertTrue(dummy_app._quit_command_sent)

    def test_request_quit_without_command_window_starts_close_event_shutdown(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.shutting_down = False
        dummy_app._quit_command_sent = False
        dummy_app.command_window = None
        dummy_app.begin_shutdown_from_close_event = lambda: calls.append(("begin_shutdown",))

        HydeApp.request_quit(dummy_app)

        self.assertEqual(calls, [("begin_shutdown",)])
        self.assertTrue(dummy_app.shutting_down)

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
        dummy_app.remote_server = None
        dummy_app.command_window = type("CommandWindow", (), {"kernel_client": kernel_client})()
        dummy_app.runtime_helper = helper
        dummy_app._shutdown_kernel_windows = lambda: process_calls.append(("shutdown_windows",))
        dummy_app._complete_shutdown_runtime = lambda: process_calls.append(("complete_shutdown",))

        with patch("hyde.user_interface.main.time.monotonic", return_value=10.0):
            with patch("hyde.user_interface.main.QtCore.QTimer.singleShot", side_effect=lambda delay, fn: process_calls.append(("singleShot", delay, fn))):
                HydeApp.shutdown_runtime(dummy_app)

        self.assertEqual(kernel_client.calls, [("shutdown", False)])
        self.assertEqual(dummy_app._quit_deadline, 12.0)
        self.assertEqual(process_calls[0:2], [("stop_watcher",), ("helper_stop",)])
        self.assertEqual(process_calls[2], ("shutdown_windows",))
        self.assertEqual(process_calls[3][0:2], ("singleShot", 0))
        self.assertIsNone(dummy_app.runtime_helper)

    def test_shutdown_runtime_prefers_runtime_helper_blocking_client(self):
        helper_client = FakeKernelClient()
        process_calls = []

        class DummyProcess:
            def poll(self):
                return 0

        helper = type("Helper", (), {})()
        helper.kernel_client = helper_client
        helper.thread = FakeJoinThread()
        helper.stop = lambda: process_calls.append(("helper_stop",))

        command_window_client = FakeKernelClient()

        dummy_app = type("DummyApp", (), {})()
        dummy_app._runtime_shutdown = False
        dummy_app.stop_project_watcher = lambda: process_calls.append(("stop_watcher",))
        dummy_app.remote_server = None
        dummy_app.command_window = type("CommandWindow", (), {"kernel_client": command_window_client})()
        dummy_app.runtime_helper = helper
        dummy_app._shutdown_kernel_windows = lambda: process_calls.append(("shutdown_windows",))
        dummy_app._complete_shutdown_runtime = lambda: process_calls.append(("complete_shutdown",))
        dummy_app.kernel_process = DummyProcess()

        with patch("hyde.user_interface.main.time.monotonic", return_value=10.0):
            with patch("hyde.user_interface.main.QtCore.QTimer.singleShot", side_effect=lambda delay, fn: process_calls.append(("singleShot", delay, fn))):
                HydeApp.shutdown_runtime(dummy_app)

        self.assertEqual(helper_client.calls, [("shutdown", False)])
        self.assertEqual(command_window_client.calls, [])
        self.assertIn(("shutdown_windows",), process_calls)

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
