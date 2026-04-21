import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
import logging
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hyde
from hyde.features.hyde_features import SimpleHydeCommandCodec
from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.main import HydeApp, connect_logger_to_output_box
from qtutils.outputbox import BLUE, GREEN, ORANGE
from hyde.user_interface.file_dialogs import (
    HealProjectDialog,
    LoadProjectDialog,
    NewProjectDialog,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
    SaveProjectCommand,
)
from hyde.user_interface.table import TableWidget
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


def make_project_app():
    ui = type("UI", (), {})()
    app = type("DummyApp", (), {})()
    app.ui = ui
    app.ui.statusbar = FakeStatusBar()
    app.current_project_dir = None
    app.command_window = object()
    app.set_project_status_message = app.ui.statusbar.showMessage
    app.clear_project_status_message = app.ui.statusbar.clearMessage
    app.begin_project_operation = lambda label: HydeApp.begin_project_operation(app, label)
    app.execute_command_calls = []
    app.execute_command = lambda code, visible=True: app.execute_command_calls.append((code, visible))
    app.project_target_needs_confirmation = lambda project_dir: HydeApp.project_target_needs_confirmation(
        app, project_dir
    )
    app.confirm_overwrite_project = lambda project_dir: True
    return app


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

        HydeApp._load_startup_project(dummy_app, "/tmp/project.hy")
        HydeApp.on_project_state_result(dummy_app, {"operation": "load", "success": True})

        self.assertEqual(dummy_app.ui.statusbar.messages, [("Loading Hyde project...", 0)])
        self.assertEqual(dummy_app.ui.statusbar.cleared, 1)
        self.assertEqual(
            calls,
            [
                ("execute", "hyde.load_project('/tmp/project.hy')", True),
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

    def test_finalize_startup_hides_splash_and_uses_status_bar(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app._startup_complete = False
        dummy_app.splash = type("Splash", (), {"hide": lambda self: calls.append(("hide_splash",))})()
        dummy_app._rebuild_kernel_windows = lambda: calls.append(("rebuild",))
        dummy_app.enter_no_project_state = lambda: calls.append(("no_project",))
        dummy_app.ui = type(
            "UI",
            (),
            {
                "show": lambda self: calls.append(("show",)),
                "statusbar": FakeStatusBar(),
            },
        )()
        dummy_app.set_project_status_message = dummy_app.ui.statusbar.showMessage
        dummy_app.clear_project_status_message = dummy_app.ui.statusbar.clearMessage
        dummy_app.resolve_startup_project = lambda: None

        HydeApp.finalize_startup(dummy_app)

        self.assertEqual(calls, [("show",), ("hide_splash",), ("rebuild",), ("no_project",)])
        self.assertTrue(dummy_app._startup_complete)
        self.assertEqual(dummy_app.ui.statusbar.messages, [("Connecting to Jupyter Kernel Socket...", 0)])
        self.assertEqual(dummy_app.ui.statusbar.cleared, 1)

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
        dummy_app._shutdown_kernel_windows = lambda: calls.append(("shutdown_windows",))
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
                ("shutdown_windows",),
                ("restart_runtime",),
            ],
        )
        warning.assert_called_once()

    def test_project_selection_dialog_requires_existing_project_for_open(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "missing.hy")
            existing = os.path.join(tmpdir, "existing.hy")
            os.makedirs(existing)

            dialog = LoadProjectDialog()
            dialog.selectFile(missing)
            dialog._sync_state_from_widgets()
            dialog.update_accept_button()
            self.assertFalse(dialog._accept_button.isEnabled())

            dialog.selectFile(existing)
            dialog._sync_state_from_widgets()
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

    def test_load_project_dialog_dispatches_visible_load_command(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "load_target.hy")
            os.makedirs(project_dir)
            dummy_app = make_project_app()
            parent = QtWidgets.QWidget()
            dialog = LoadProjectDialog(dummy_app, parent=parent)
            dialog._selected_path = project_dir
            with patch.object(LoadProjectDialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
                self.assertTrue(dialog.run())

            self.assertEqual(dummy_app.ui.statusbar.messages, [("Loading Hyde project...", 0)])
            self.assertEqual(
                dummy_app.execute_command_calls,
                [(f"hyde.load_project({project_dir!r})", True)],
            )
            dialog.close()
            parent.close()

    def test_heal_project_dialog_dispatches_visible_heal_command(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "heal_target.hy")
            os.makedirs(project_dir)
            dummy_app = make_project_app()
            parent = QtWidgets.QWidget()
            dialog = HealProjectDialog(dummy_app, parent=parent)
            dialog._selected_path = project_dir
            with patch.object(HealProjectDialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
                self.assertTrue(dialog.run())

            self.assertEqual(dummy_app.ui.statusbar.messages, [("Healing Hyde project...", 0)])
            self.assertEqual(
                dummy_app.execute_command_calls,
                [(f"hyde.heal_project({project_dir!r})", True)],
            )
            dialog.close()
            parent.close()

    def test_choose_new_project_conflict_prompts_and_dispatches_overwrite(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            with open(os.path.join(project_dir, "keep.txt"), "w", encoding="utf-8") as handle:
                handle.write("keep")

            dummy_app = make_project_app()
            prompts = []
            dummy_app.confirm_overwrite_project = lambda target: prompts.append(target) or True

            parent = QtWidgets.QWidget()
            dialog = NewProjectDialog(dummy_app, parent=parent)
            dialog._selected_path = project_dir
            with patch.object(NewProjectDialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
                self.assertTrue(dialog.run())

            self.assertEqual(prompts, [project_dir])
            self.assertEqual(dummy_app.ui.statusbar.messages, [("Creating Hyde project...", 0)])
            self.assertEqual(
                dummy_app.execute_command_calls,
                [(f"hyde.new_project({project_dir!r}, load=True, overwrite=True)", True)],
            )
            dialog.close()
            parent.close()

    def test_table_visible_title_becomes_default_macro_name(self):
        table = TableWidget.__new__(TableWidget)
        table.handle = "Table0"
        table._default_macro_name = table.handle

        TableWidget.set_default_macro_name(table, "Table_Fun")
        self.assertEqual(TableWidget.default_macro_name(table), "Table_Fun")

    def test_invalid_table_title_falls_back_to_handle_for_macro_name(self):
        table = TableWidget.__new__(TableWidget)
        table.handle = "Table0"
        table._default_macro_name = table.handle

        TableWidget.set_default_macro_name(table, "Table Fun")
        self.assertEqual(TableWidget.default_macro_name(table), "Table0")

    def test_simple_command_codec_is_deterministic(self):
        state = SimpleHydeCommandCodec.default_state()
        state = SimpleHydeCommandCodec.update_state(state, {"type": "set_command", "command": "save_project"})
        state = SimpleHydeCommandCodec.update_state(
            state,
            {"type": "set", "path": ("settings", "mode"), "value": "copy"},
        )
        state = SimpleHydeCommandCodec.update_state(
            state,
            {"type": "set", "path": ("settings", "project_dir"), "value": "/tmp/project.hy"},
        )
        state = SimpleHydeCommandCodec.update_state(
            state,
            {"type": "set", "path": ("settings", "overwrite"), "value": True},
        )

        self.assertEqual(
            SimpleHydeCommandCodec.state_to_python(state),
            "hyde.save_project('/tmp/project.hy', mode='copy', overwrite=True)",
        )

    def test_hyde_gui_state_python_source_logs_debug_when_enabled(self):
        state = SaveProjectCommand(make_project_app()).state
        with patch("hyde.user_interface.base.hyde.HYDE_DEBUG", True):
            with patch("hyde.user_interface.base.logging.getLogger") as get_logger:
                logger = get_logger.return_value
                self.assertEqual(state.python_source(), "hyde.save_project(mode='save')")
        logger.debug.assert_called_once()
        message = logger.debug.call_args.args[0]
        self.assertIn("[Hyde state] %s", message)
        self.assertIn("state:", message)
        self.assertIn("python:", message)
        self.assertIn("SaveProjectState", logger.debug.call_args.args[1])
        self.assertIn("hyde.save_project(mode='save')", logger.debug.call_args.args[3])

    def test_hyde_gui_state_python_source_skips_debug_when_disabled(self):
        state = SaveProjectCommand(make_project_app()).state
        with patch("hyde.user_interface.base.hyde.HYDE_DEBUG", False):
            with patch("hyde.user_interface.base.logging.getLogger") as get_logger:
                self.assertEqual(state.python_source(), "hyde.save_project(mode='save')")
        get_logger.assert_not_called()

    def test_connect_logger_to_output_box_splits_hyde_state_debug_colors(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])
        output_box = type("OutputBox", (), {"write": lambda self, text, color=None: None})()
        logger = logging.getLogger("hyde-test-colored")
        handlers_before = list(logger.handlers)
        level_before = logger.level
        try:
            with patch.object(output_box, "write") as output_write:
                logger.setLevel(logging.DEBUG)
                connect_logger_to_output_box("hyde-test-colored", output_box)
                logger.debug("[Hyde state] SaveProjectState\nstate:\n{'a': 1}\npython:\nhyde.save_project()")
            self.assertEqual(output_write.call_count, 5)
            self.assertEqual(output_write.call_args_list[0].kwargs["color"], ORANGE)
            self.assertEqual(output_write.call_args_list[2].kwargs["color"], GREEN)
            self.assertEqual(output_write.call_args_list[4].kwargs["color"], BLUE)
        finally:
            logger.handlers = handlers_before
            logger.setLevel(level_before)

    def test_save_project_command_noops_without_active_project(self):
        dummy_app = make_project_app()
        dummy_app.current_project_dir = None
        dummy_app.command_window = None

        self.assertFalse(SaveProjectCommand(dummy_app).run())
        self.assertEqual(dummy_app.execute_command_calls, [])
        self.assertEqual(dummy_app.ui.statusbar.messages, [])

    def test_save_as_current_project_path_falls_back_to_plain_save(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_app = make_project_app()
            dummy_app.current_project_dir = os.path.join(tmpdir, "current.hy")
            os.makedirs(dummy_app.current_project_dir)

            parent = QtWidgets.QWidget()
            dialog = SaveAsProjectDialog(dummy_app, parent=parent)
            dialog._selected_path = dummy_app.current_project_dir
            with patch.object(SaveAsProjectDialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
                self.assertTrue(dialog.run())

            self.assertEqual(dummy_app.ui.statusbar.messages, [("Saving Hyde project...", 0)])
            self.assertEqual(dummy_app.execute_command_calls, [("hyde.save_project(mode='save')", True)])
            dialog.close()
            parent.close()

    def test_save_copy_current_project_path_falls_back_to_plain_save(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_app = make_project_app()
            dummy_app.current_project_dir = os.path.join(tmpdir, "current.hy")
            os.makedirs(dummy_app.current_project_dir)

            parent = QtWidgets.QWidget()
            dialog = SaveCopyProjectDialog(dummy_app, parent=parent)
            dialog._selected_path = dummy_app.current_project_dir
            with patch.object(SaveCopyProjectDialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
                self.assertTrue(dialog.run())

            self.assertEqual(dummy_app.ui.statusbar.messages, [("Saving Hyde project...", 0)])
            self.assertEqual(dummy_app.execute_command_calls, [("hyde.save_project(mode='save')", True)])
            dialog.close()
            parent.close()

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
