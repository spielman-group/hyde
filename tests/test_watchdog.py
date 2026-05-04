import os
import tempfile
import unittest
import logging
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.main import HydeApp, connect_logger_to_output_box
from hyde.user_interface.plugins.remote_requests import RemoteRequestServer
from qtutils.outputbox import BLUE, GREEN, ORANGE
from hyde.user_interface.plugins.file_dialogs.dialogs import (
    HealProjectDialog,
    LoadProjectDialog,
    NewProjectDialog,
    SaveCopyProjectState,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
    SaveProjectCommand,
)
from hyde.user_interface.plugins.table import TableWorkspaceService
from hyde.user_interface.plugins.table.window import (
    TableWidget,
    prompt_to_save_table_macro,
)
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


def make_project_app():
    ui = type("UI", (), {})()
    app = type("DummyApp", (), {})()
    app.ui = ui
    app.ui.statusbar = FakeStatusBar()
    app.current_project_dir = None
    app._has_visible_command_target = True
    app._visible_command_service = type("VisibleCommandService", (), {})()
    app._visible_command_service.widget = (
        lambda: object() if app._has_visible_command_target else None
    )
    app.set_project_status_message = app.ui.statusbar.showMessage
    app.clear_project_status_message = app.ui.statusbar.clearMessage
    app.begin_project_operation = lambda label: HydeApp.begin_project_operation(app, label)
    app.execute_command_calls = []
    app.execute_command = lambda code, visible=True: app.execute_command_calls.append((code, visible))
    app.project_target_needs_confirmation = lambda project_dir: HydeApp.project_target_needs_confirmation(
        app, project_dir
    )
    app.confirm_overwrite_project = lambda project_dir: True
    app.get_current_project_dir = lambda: app.current_project_dir
    app.visible_command_service = lambda: app._visible_command_service
    app.get_shutting_down = lambda: getattr(app, "shutting_down", False)
    app.set_shutting_down = lambda value: setattr(app, "shutting_down", bool(value))
    app.get_quit_command_sent = lambda: getattr(app, "_quit_command_sent", False)
    app.set_quit_command_sent = lambda value: setattr(app, "_quit_command_sent", bool(value))
    app.begin_shutdown_from_close_event = lambda: None
    app.services = {
        "ui": app.ui,
        "begin_project_operation": app.begin_project_operation,
        "execute_command": app.execute_command,
        "project_target_needs_confirmation": lambda project_dir: app.project_target_needs_confirmation(
            project_dir
        ),
        "confirm_overwrite_project": lambda project_dir: app.confirm_overwrite_project(
            project_dir
        ),
        "get_current_project_dir": lambda: app.get_current_project_dir(),
        "visible_command_service": app.visible_command_service(),
        "get_shutting_down": lambda: app.get_shutting_down(),
        "set_shutting_down": app.set_shutting_down,
        "get_quit_command_sent": lambda: app.get_quit_command_sent(),
        "set_quit_command_sent": app.set_quit_command_sent,
        "begin_shutdown_from_close_event": app.begin_shutdown_from_close_event,
    }
    return app


class TestRuntimeArchitecture(unittest.TestCase):
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
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.enqueue_command = lambda code, silent=True: queued.append((code, silent)) or True

        self.assertEqual(server.handler("hello"), "hello")
        self.assertEqual(server.handler("/path/to/file.h5"), "added successfully")
        state = RuntimeCommandState()
        state.set_remote_request("/path/to/file.h5")
        self.assertEqual(queued, [(state.python_source(), False)])

    def test_remote_request_server_normalizes_filepath_payload(self):
        queued = []
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.enqueue_command = lambda code, silent=True: queued.append((code, silent)) or True

        with patch(
            "hyde.user_interface.plugins.remote_requests.shared_drive.path_to_local",
            return_value="/local/path.h5",
        ) as localize:
            response = server.handler({"filepath": "Z:\\shared\\path.h5"})

        self.assertEqual(response, "added successfully")
        localize.assert_called_once_with("Z:\\shared\\path.h5")
        state = RuntimeCommandState()
        state.set_remote_request("/local/path.h5")
        self.assertEqual(queued, [(state.python_source(), False)])

    def test_remote_request_server_rejects_requests_without_runtime_queue(self):
        server = RemoteRequestServer.__new__(RemoteRequestServer)
        server.enqueue_command = lambda code, silent=True: False

        self.assertEqual(
            server.handler("/path/to/file.h5"),
            "error: kernel unavailable",
        )

    def test_startup_project_load_is_requested_via_plugin_event(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.ui = type("UI", (), {"statusbar": FakeStatusBar()})()
        dummy_app.set_project_status_message = dummy_app.ui.statusbar.showMessage
        dummy_app.clear_project_status_message = dummy_app.ui.statusbar.clearMessage
        dummy_app.begin_project_operation = lambda label: HydeApp.begin_project_operation(dummy_app, label)
        dummy_app.end_project_operation = lambda: HydeApp.end_project_operation(dummy_app)
        dummy_app.emit_plugin_event = lambda name, data=None: calls.append((name, data))
        dummy_app.restore_project_session = lambda: calls.append(("restore",))

        HydeApp._load_startup_project(dummy_app, "/tmp/project.hy")
        HydeApp.on_project_state_result(dummy_app, {"operation": "load", "success": True})

        self.assertEqual(dummy_app.ui.statusbar.cleared, 1)
        self.assertEqual(
            calls,
            [
                ("request_project_load", {"project_dir": "/tmp/project.hy"}),
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
        dummy_app.emit_plugin_event = lambda name, data=None: calls.append((name, data))
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

        self.assertEqual(
            calls,
            [("show",), ("hide_splash",), ("kernel_ready", {}), ("no_project",)],
        )
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

    def test_project_selection_dialog_requires_existing_project_for_open(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "missing.hy")
            existing = os.path.join(tmpdir, "existing.hy")
            os.makedirs(existing)

            dummy_app = make_project_app()
            parent = QtWidgets.QWidget()
            dialog = LoadProjectDialog(dummy_app.services, parent=parent)
            try:
                dialog.selectFile(missing)
                dialog._sync_state_from_widgets()
                dialog.update_accept_button()
                self.assertFalse(dialog._accept_button.isEnabled())

                dialog.selectFile(existing)
                dialog._sync_state_from_widgets()
                dialog.update_accept_button()
                self.assertTrue(dialog._accept_button.isEnabled())
            finally:
                dialog.close()
                parent.close()

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
            dialog = LoadProjectDialog(dummy_app.services, parent=parent)
            dialog.selectFile(project_dir)
            with patch.object(
                LoadProjectDialog,
                "exec_",
                return_value=QtWidgets.QDialog.Accepted,
            ):
                with patch.object(
                    LoadProjectDialog,
                    "selectedFiles",
                    return_value=[project_dir],
                ):
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
            dialog = HealProjectDialog(dummy_app.services, parent=parent)
            dialog.selectFile(project_dir)
            with patch.object(
                HealProjectDialog,
                "exec_",
                return_value=QtWidgets.QDialog.Accepted,
            ):
                with patch.object(
                    HealProjectDialog,
                    "selectedFiles",
                    return_value=[project_dir],
                ):
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
            dialog = NewProjectDialog(dummy_app.services, parent=parent)
            dialog.selectFile(project_dir)
            with patch.object(
                NewProjectDialog,
                "exec_",
                return_value=QtWidgets.QDialog.Accepted,
            ):
                with patch.object(
                    NewProjectDialog,
                    "selectedFiles",
                    return_value=[project_dir],
                ):
                    self.assertTrue(dialog.run())

            self.assertEqual(prompts, [project_dir])
            self.assertEqual(dummy_app.ui.statusbar.messages, [("Creating Hyde project...", 0)])
            self.assertEqual(
                dummy_app.execute_command_calls,
                [(f"hyde.new_project({project_dir!r}, load=True, overwrite=True)", True)],
            )
            dialog.close()
            parent.close()

    def test_table_widget_initializes_table_and_mutation_state(self):
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication([])

        class FakeUI:
            def __init__(self):
                self.tableView = QtWidgets.QTableView()
                self.valueEdit = QtWidgets.QLineEdit()
                self.cellInfoLabel = QtWidgets.QLabel()
                self.gearButton = QtWidgets.QToolButton()

        with patch("hyde.user_interface.plugins.table.window.UiLoader") as loader_cls:
            loader_cls.return_value.load.return_value = FakeUI()
            with patch("hyde.user_interface.plugins.table.window.QtCore.QTimer.singleShot", lambda *_args, **_kwargs: None):
                table = TableWidget("Table0", ["a"])

        try:
            from hyde.user_interface.base import MutationState
            from hyde.user_interface.plugins.table.window import TableState

            self.assertIsInstance(table.table_state, TableState)
            self.assertIsInstance(table.mutation_state, MutationState)
        finally:
            table.close()

    def test_table_workspace_uses_visible_title_as_handle(self):
        created = {}

        class FakeSubwindow:
            def __init__(self):
                self.window_title = None
                self.shown = False
                self.destroyed = type("Signal", (), {"connect": lambda self, callback: None})()

            def setAttribute(self, attribute, value):
                del attribute, value

            def setWindowTitle(self, title):
                self.window_title = title

            def show(self):
                self.shown = True

        class FakeMdiArea:
            def __init__(self):
                self.subwindow = FakeSubwindow()

            def addSubWindow(self, widget):
                created["widget"] = widget
                return self.subwindow

        class FakeTableWidget:
            def __init__(
                self,
                handle,
                names,
                services=None,
                visible_title=None,
                geometry=None,
                column_widths=None,
            ):
                self.handle = handle
                self.names = list(names)
                self.services = dict(services or {})
                self.visible_title = visible_title
                self.geometry = geometry
                self.column_widths = column_widths
                self.bound_subwindow = None

            def bind_subwindow(self, subwindow):
                self.bound_subwindow = subwindow

        plugin = type("Plugin", (), {})()
        plugin.services = {
            "mdi_area": FakeMdiArea(),
            "configure_persistent_subwindow": lambda subwindow: None,
        }
        plugin.request_save_table_macro = lambda table_state: True
        workspace = TableWorkspaceService(plugin)

        with patch("hyde.user_interface.plugins.table.TableWidget", FakeTableWidget):
            workspace.open_table(["b", "c"], visible_title="Table_Fun")

        self.assertEqual(created["widget"].handle, "Table0")
        self.assertEqual(created["widget"].visible_title, "Table_Fun")
        self.assertIs(created["widget"].bound_subwindow, plugin.services["mdi_area"].subwindow)
        self.assertIs(workspace.tables["Table0"], created["widget"])
        self.assertEqual(plugin.services["mdi_area"].subwindow.window_title, "Table_Fun")
        self.assertEqual(workspace.table_counter, 1)

    def test_prompt_to_save_table_macro_launches_dialog_with_table_state(self):
        table_state = object()
        calls = {}

        class FakeDialog:
            SAVE = 1
            NO_SAVE = 2
            CANCEL = 0

            def __init__(self, table_state, parent=None):
                calls["table_state"] = table_state
                calls["parent"] = parent
                self.choice = self.SAVE

            def exec_(self):
                return QtWidgets.QDialog.Accepted

            def macro_name(self):
                return "Table_Save"

            def macro_source(self):
                return "macro source"

        parent = object()
        reload_procedures = lambda: calls.setdefault("reloaded", 0) or calls.__setitem__("reloaded", 1)

        with patch("hyde.user_interface.plugins.table.window.SaveWindowDialog", FakeDialog):
            with patch("hyde.user_interface.plugins.table.window.inspect_macro_conflict", return_value=None):
                with patch("hyde.user_interface.plugins.table.window.write_macro_source") as write_macro_source:
                    result = prompt_to_save_table_macro(
                        table_state,
                        parent=parent,
                        procedures_init="/tmp/procedures/__init__.py",
                        reload_procedures=reload_procedures,
                    )

        self.assertTrue(result)
        self.assertIs(calls["table_state"], table_state)
        self.assertIs(calls["parent"], parent)
        write_macro_source.assert_called_once_with(
            "/tmp/procedures/__init__.py",
            "Table_Save",
            "macro source",
        )
        self.assertEqual(calls["reloaded"], 1)

    def test_simple_command_codec_is_deterministic(self):
        state = SaveCopyProjectState()
        state.set_project_dir("/tmp/project.hy")
        state.set_overwrite(True)
        self.assertEqual(
            state.python_source(),
            "hyde.save_project('/tmp/project.hy', mode='copy', overwrite=True)",
        )

    def test_hyde_gui_state_python_source_logs_debug_when_enabled(self):
        state = SaveProjectCommand(make_project_app().services).state
        with patch("hyde.user_interface.base.hyde.HYDE_DEBUG", True):
            with patch("hyde.user_interface.base.logging.getLogger") as get_logger:
                logger = get_logger.return_value
                self.assertEqual(state.python_source(), "hyde.save_project(mode='save')")
        logger.debug.assert_called_once()
        logged_message = logger.debug.call_args.args[0]
        self.assertIn("[Hyde state] %s", logged_message)
        self.assertIn("state:", logged_message)
        self.assertIn("python:", logged_message)

    def test_hyde_gui_state_python_source_skips_debug_when_disabled(self):
        state = SaveProjectCommand(make_project_app().services).state
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
            rendered_lines = [
                (call.args[0], call.kwargs["color"])
                for call in output_write.call_args_list
            ]
            self.assertEqual(len(rendered_lines), 5)
            self.assertTrue(rendered_lines[0][0].endswith("[Hyde state] SaveProjectState\n"))
            self.assertEqual(rendered_lines[0][1], ORANGE)
            self.assertEqual(rendered_lines[1], ("state:\n", ORANGE))
            self.assertEqual(rendered_lines[2], ("{'a': 1}\n", GREEN))
            self.assertEqual(rendered_lines[3], ("python:\n", ORANGE))
            self.assertEqual(rendered_lines[4], ("hyde.save_project()\n", BLUE))
        finally:
            logger.handlers = handlers_before
            logger.setLevel(level_before)

    def test_save_project_command_noops_without_active_project(self):
        dummy_app = make_project_app()
        dummy_app.current_project_dir = None
        dummy_app._has_visible_command_target = False

        self.assertFalse(SaveProjectCommand(dummy_app.services).run())
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
            dialog = SaveAsProjectDialog(dummy_app.services, parent=parent)
            dialog.selectFile(dummy_app.current_project_dir)
            with patch.object(
                SaveAsProjectDialog,
                "exec_",
                return_value=QtWidgets.QDialog.Accepted,
            ):
                with patch.object(
                    SaveAsProjectDialog,
                    "selectedFiles",
                    return_value=[dummy_app.current_project_dir],
                ):
                    self.assertTrue(dialog.run())

            self.assertEqual(dummy_app.ui.statusbar.messages, [("Saving Hyde project...", 0)])
            self.assertEqual(dummy_app.execute_command_calls, [("hyde.save_project(mode='save')", True)])
            dialog.close()
            parent.close()

    def test_request_quit_dispatches_visible_hyde_quit_command(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.emit_plugin_event = lambda name, data=None: calls.append((name, data))

        HydeApp.request_quit(dummy_app)

        self.assertEqual(calls, [("request_application_quit", {})])

    def test_request_quit_is_plugin_routed_even_without_command_window(self):
        calls = []
        dummy_app = type("DummyApp", (), {})()
        dummy_app.emit_plugin_event = lambda name, data=None: calls.append((name, data))

        HydeApp.request_quit(dummy_app)

        self.assertEqual(calls, [("request_application_quit", {})])

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
        dummy_app.plugin_service = lambda key: (
            type("CommandWindowService", (), {"kernel_client": lambda self: command_window_client})()
            if key == "visible_command_service"
            else None
        )
        dummy_app.runtime_helper = helper
        dummy_app.emit_plugin_event = lambda name, data=None: process_calls.append((name, data))
        dummy_app._complete_shutdown_runtime = lambda: process_calls.append(("complete_shutdown",))
        dummy_app.kernel_process = DummyProcess()

        with patch("hyde.user_interface.main.time.monotonic", return_value=10.0):
            with patch("hyde.user_interface.main.QtCore.QTimer.singleShot", side_effect=lambda delay, fn: process_calls.append(("singleShot", delay, fn))):
                HydeApp.shutdown_runtime(dummy_app)

        self.assertEqual(helper_client.calls, [("shutdown", False)])
        self.assertEqual(command_window_client.calls, [])
        self.assertIn(("application_shutdown", {}), process_calls)
        self.assertIn(("kernel_crashed", {}), process_calls)

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
