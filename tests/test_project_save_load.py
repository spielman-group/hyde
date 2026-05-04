import os
import sys
import time
import unittest
import tempfile
import builtins
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="hyde-mpl-"))
os.environ.setdefault("IPYTHONDIR", tempfile.mkdtemp(prefix="hyde-ipython-"))

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from jupyter_client import BlockingKernelClient
from labscript_utils.ls_zprocess import ProcessTree
from qtutils.qt import QtWidgets, QtCore

import tomllib
from unittest.mock import patch

import hyde
from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.plugins.command_window import (
    CommandWindow,
    CommandWindowService,
    Plugin as CommandWindowPlugin,
)
from hyde.user_interface.plugins.procedure_browser import Plugin as ProcedureBrowserPlugin
from hyde.user_interface.plugins.file_dialogs.dialogs import SaveAsProjectDialog
from hyde.user_interface.main import HydeApp
from hyde.user_interface.main.project_state import (
    read_history,
    read_session,
    try_read_history,
    try_read_session,
    write_history,
    write_session,
)


def lookup_menu_action(app, location, text, path=()):
    action = app.lookup_menu_action(location, text, path=path)
    if action is None:
        raise AssertionError(
            f"Could not find menu action {location!r} / {path!r} / {text!r}"
        )
    return action


class DummySplash:
    def update_text(self, text):
        del text

    def hide(self):
        return None


def process_events(duration=0.05):
    deadline = time.time() + duration
    while time.time() < deadline:
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 10)
        time.sleep(0.01)


def wait_until(predicate, timeout=10, message="condition not met"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        process_events()
        if predicate():
            return
    raise AssertionError(message)


def execute_and_wait(client, code, timeout=10):
    msg_id = client.execute(code)
    deadline = time.time() + timeout
    last_reply = None
    while time.time() < deadline:
        reply = client.get_shell_msg(timeout=5)
        if reply["parent_header"].get("msg_id") != msg_id:
            continue
        last_reply = reply
        return reply
    raise AssertionError(f"Code did not return a reply: {code!r}\nLast reply: {last_reply!r}")


def wait_for_code_ok(client, code, timeout=10):
    reply = execute_and_wait(client, code, timeout=timeout)
    if reply["content"]["status"] != "ok":
        raise AssertionError(f"Code did not succeed: {code!r}\nReply: {reply!r}")


def start_kernel(process_tree, connection_file, process_name):
    process_tree.zlock_client.set_process_name(process_name)
    to_child, from_child, child = process_tree.subprocess(
        KERNEL_LAUNCHER,
        args=["-f", connection_file],
        startup_timeout=60,
    )
    deadline = time.time() + 30
    while time.time() < deadline and not os.path.exists(connection_file):
        time.sleep(0.1)
    if not os.path.exists(connection_file):
        raise AssertionError(f"Kernel connection file was not created: {connection_file}")
    client = BlockingKernelClient(connection_file=connection_file)
    client.load_connection_file()
    client.start_channels()
    client.wait_for_ready(timeout=15)
    return to_child, from_child, child, client


def collect_kernel_messages(from_child, timeout=10, stop_when=None):
    deadline = time.time() + timeout
    messages = []
    while time.time() < deadline:
        try:
            task, data = from_child.get(timeout=0.5)
        except Exception:
            continue
        messages.append((task, data))
        if stop_when is not None and stop_when(task, data):
            return messages
    raise AssertionError(f"Timed out waiting for kernel messages. Saw: {messages!r}")


class DummyCommandWindowService:
    def __init__(self, history=None):
        self._history = list(history or [])
        self.restored_entries = None

    def history_entries(self):
        return list(self._history)

    def restore_history_entries(self, entries):
        self.restored_entries = list(entries)


class DummyDataBrowserUI:
    def __init__(self):
        self.wavesCheckBox = QtWidgets.QCheckBox()
        self.variablesCheckBox = QtWidgets.QCheckBox()
        self.stringsCheckBox = QtWidgets.QCheckBox()
        self.infoCheckBox = QtWidgets.QCheckBox()


class DummyDataBrowser:
    def __init__(self):
        self.ui = DummyDataBrowserUI()


class DummyTable:
    def __init__(self, handle, names, subwindow, column_widths=None):
        self.handle = handle
        self.names = list(names)
        self._subwindow = subwindow
        self.column_widths = dict(column_widths or {})
        self.table_state = type(
            "DummyTableState",
            (),
            {
                "normalized_state": lambda state_self: {
                    "feature": "table",
                    "settings": {
                        "geometry": [
                            self._subwindow.geometry().x(),
                            self._subwindow.geometry().y(),
                            self._subwindow.geometry().width(),
                            self._subwindow.geometry().height(),
                        ],
                        "column_widths": dict(self.column_widths),
                    },
                }
            },
        )()
        self.shutdown_calls = 0

    def parentWidget(self):
        return self._subwindow

    def capture_layout_state(self):
        return None

    def shutdown_client(self):
        self.shutdown_calls += 1


class PluginManagerStub:
    def __init__(self, plugins=None, services=None):
        self.plugins = dict(plugins or {})
        self.services = dict(services or {})

    def get_event_handlers(self, name):
        handlers = []
        for plugin in self.plugins.values():
            plugin_handlers = getattr(plugin, "get_event_handlers", lambda: {})()
            handler = plugin_handlers.get(name)
            if handler is not None:
                handlers.append(handler)
        return handlers


class TestProjectStateHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def test_write_and_read_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "history.hy")
            os.makedirs(os.path.join(project_dir, "terminal"))
            app = type("DummyApp", (), {})()
            app.plugin_manager = PluginManagerStub(
                services={
                    "visible_command_service": DummyCommandWindowService(
                        ["a = 1", "hyde.table(a)"]
                    )
                }
            )
            write_history(app, project_dir)
            self.assertEqual(read_history(project_dir), ["a = 1", "hyde.table(a)"])

    def test_command_window_records_visible_commands_from_execute_source(self):
        class FakeSignal:
            def connect(self, callback):
                del callback

        class FakeChannel:
            def __init__(self):
                self.message_received = FakeSignal()

        class FakeHeartbeatChannel:
            def __init__(self):
                self.kernel_died = FakeSignal()

        class FakeKernelClient:
            def __init__(self, connection_file):
                self.connection_file = connection_file
                self.started_channels = FakeSignal()
                self.stopped_channels = FakeSignal()
                self.iopub_channel = FakeChannel()
                self.shell_channel = FakeChannel()
                self.stdin_channel = FakeChannel()
                self.hb_channel = FakeHeartbeatChannel()
                self.channels_running = False

            def load_connection_file(self):
                return None

            def start_channels(self):
                return None

        recorded = []

        with patch(
            "hyde.user_interface.plugins.command_window.QtKernelClient",
            FakeKernelClient,
        ):
            with patch(
                "qtconsole.rich_jupyter_widget.RichJupyterWidget.execute",
                return_value="executed",
            ):
                widget = CommandWindow(
                    connection_file="kernel-hyde.json",
                    history_sink=recorded.append,
                )
                self.assertEqual(widget.execute(source="x = 1", hidden=False), "executed")
                widget.execute(source="hyde.save_project()", hidden=False)
                widget.execute(source="hidden = 1", hidden=True)

        self.assertEqual(recorded, ["x = 1", "hyde.save_project()"])

    def test_command_window_plugin_uses_lookup_menu_action_service(self):
        action = QtWidgets.QAction("Command Window")
        lookup_menu_action = unittest.mock.Mock(return_value=action)
        ui = type("UI", (), {"menuWindow": QtWidgets.QMenu()})()
        plugin = CommandWindowPlugin(initial_settings={})

        plugin.plugin_setup_complete(
            {"services": {"ui": ui, "lookup_menu_action": lookup_menu_action}}
        )

        self.assertIs(plugin._action, action)

    def test_procedure_browser_plugin_uses_lookup_menu_action_service(self):
        class FakeMdiContext:
            def __init__(self):
                self.ensure_calls = []
                self._subwindow = QtWidgets.QMdiSubWindow()

            def ensure_widget(self, key):
                self.ensure_calls.append(key)
                return object()

            def subwindow(self, key):
                del key
                return self._subwindow

        action = QtWidgets.QAction("Procedures")
        lookup_menu_action = unittest.mock.Mock(return_value=action)
        ui = type("UI", (), {"menuWindow": QtWidgets.QMenu()})()
        mdi_context = FakeMdiContext()
        plugin = ProcedureBrowserPlugin(initial_settings={})

        plugin.plugin_setup_complete(
            {
                "services": {
                    "ui": ui,
                    "mdi_context": mdi_context,
                    "lookup_menu_action": lookup_menu_action,
                }
            }
        )

        self.assertEqual(mdi_context.ensure_calls, ["procedures"])
        self.assertIs(plugin._action, action)

    def test_command_window_service_keeps_authoritative_history_without_widget(self):
        class FakeWidget:
            def __init__(self):
                self.restored_entries = None

            def restore_history_entries(self, entries):
                self.restored_entries = list(entries)

        class FakeMdiContext:
            def __init__(self, widget):
                self.current_widget = widget

            def ensure_widget(self, key):
                del key
                return self.current_widget

            def widget(self, key):
                del key
                return self.current_widget

            def subwindow(self, key):
                del key
                return None

            def destroy(self, key):
                del key
                self.current_widget = None

        widget = FakeWidget()
        mdi_context = FakeMdiContext(widget)
        plugin = type("PluginStub", (), {"services": {"mdi_context": mdi_context}})()
        service = CommandWindowService(plugin)

        service.restore_history_entries(["a = 1"])
        service.record_history_entry("hyde.save_project()")
        mdi_context.current_widget = None

        self.assertEqual(widget.restored_entries, ["a = 1"])
        self.assertEqual(
            service.history_entries(),
            ["a = 1", "hyde.save_project()"],
        )

    def test_write_and_read_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "session.hy")
            os.makedirs(project_dir)

            main_window = QtWidgets.QMainWindow()
            mdi_area = QtWidgets.QMdiArea()
            main_window.setCentralWidget(mdi_area)
            main_window.show()

            command_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            logging_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            procedures_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            data_browser_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            table_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())

            data_browser = DummyDataBrowser()
            data_browser.ui.wavesCheckBox.setChecked(True)
            data_browser.ui.variablesCheckBox.setChecked(False)
            data_browser.ui.stringsCheckBox.setChecked(True)
            data_browser.ui.infoCheckBox.setChecked(False)

            class SessionPlugin:
                def get_save_data(self):
                    return {
                        "tool_windows": {
                            "command": {
                                "visible": bool(command_subwindow.isVisible()),
                                "geometry": [
                                    command_subwindow.geometry().x(),
                                    command_subwindow.geometry().y(),
                                    command_subwindow.geometry().width(),
                                    command_subwindow.geometry().height(),
                                ],
                            },
                        },
                        "data_browser": {
                            "waves": bool(data_browser.ui.wavesCheckBox.isChecked()),
                            "variables": bool(data_browser.ui.variablesCheckBox.isChecked()),
                            "strings": bool(data_browser.ui.stringsCheckBox.isChecked()),
                            "info": bool(data_browser.ui.infoCheckBox.isChecked()),
                        },
                        "active_table_handle": "Table0",
                        "table_counter": 4,
                        "tables": [
                            {
                                "handle": "Table0",
                                "title": table_subwindow.windowTitle(),
                                "names": ["a", "b"],
                                "hidden": not table_subwindow.isVisible(),
                                "geometry": [5, 42, 510, 242],
                                "column_widths": {"a": 120, "b": 260},
                            }
                        ],
                    }

            table_subwindow.setWindowTitle("Table_Fun")
            table_subwindow.setGeometry(QtCore.QRect(5, 42, 510, 242))

            app = type("DummyApp", (), {})()
            app.ui = main_window
            app.plugin_manager = PluginManagerStub({"session": SessionPlugin()})

            write_session(app, project_dir)
            session = read_session(project_dir)

            self.assertEqual(session["active_table_handle"], "Table0")
            self.assertEqual(session["table_counter"], 4)
            self.assertFalse(session["data_browser"]["variables"])
            self.assertEqual(session["tables"][0]["handle"], "Table0")
            self.assertEqual(session["tables"][0]["names"], ["a", "b"])
            self.assertEqual(session["tables"][0]["column_widths"], {"a": 120, "b": 260})

    def test_session_round_trip_restores_table_column_widths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "roundtrip.hy")
            os.makedirs(project_dir)

            main_window = QtWidgets.QMainWindow()
            mdi_area = QtWidgets.QMdiArea()
            main_window.setCentralWidget(mdi_area)
            table_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            table_subwindow.setWindowTitle("Table_Fun")
            table_subwindow.setGeometry(QtCore.QRect(5, 42, 510, 242))

            class SavingPlugin:
                def get_save_data(self):
                    return {
                        "active_table_handle": "Table0",
                        "table_counter": 4,
                        "tables": [
                            {
                                "handle": "Table0",
                                "title": table_subwindow.windowTitle(),
                                "names": ["a", "b"],
                                "hidden": False,
                                "geometry": [5, 42, 510, 242],
                                "column_widths": {"a": 120, "b": 260},
                            }
                        ],
                    }

            source_app = type("SourceApp", (), {})()
            source_app.ui = main_window
            source_app.plugin_manager = PluginManagerStub({"session": SavingPlugin()})

            write_session(source_app, project_dir)

            open_calls = []

            class RestoredApp:
                pass

            restored_app = RestoredApp()
            restored_app.ui = main_window
            restored_app.current_project_dir = project_dir
            command_window_service = DummyCommandWindowService()
            restored_app.plugin_service = lambda key: (
                command_window_service if key == "visible_command_service" else None
            )

            class RestoringPlugin:
                def __init__(self):
                    self.table_counter = 0
                    self.active_table_handle = None

                def get_event_handlers(self):
                    return {"project_loaded": self.on_project_loaded}

                def on_project_loaded(self, data):
                    session = data["session"]
                    for table_state in session.get("tables", []):
                        open_calls.append(
                            (
                                list(table_state.get("names", [])),
                                table_state.get("handle"),
                                table_state.get("title"),
                                table_state.get("geometry"),
                                dict(table_state.get("column_widths", {})),
                            )
                        )
                    self.table_counter = int(session.get("table_counter", 0))
                    self.active_table_handle = session.get("active_table_handle")

            restoring_plugin = RestoringPlugin()
            restored_app.plugin_manager = PluginManagerStub({"session": restoring_plugin})
            restored_app.emit_plugin_event = (
                lambda name, data=None: HydeApp.emit_plugin_event(restored_app, name, data)
            )

            HydeApp.restore_project_session(restored_app)

            self.assertEqual(
                open_calls,
                [
                    (
                        ["a", "b"],
                        "Table0",
                        table_subwindow.windowTitle(),
                        [5, 42, 510, 242],
                        {"a": 120, "b": 260},
                    )
                ],
            )
            self.assertEqual(restoring_plugin.table_counter, 4)
            self.assertEqual(restoring_plugin.active_table_handle, "Table0")

    def test_try_read_session_returns_error_for_malformed_toml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "broken_session.hy")
            os.makedirs(project_dir)
            with open(os.path.join(project_dir, "session.toml"), "w", encoding="utf-8") as handle:
                handle.write("[main_window\nbroken = true\n")
            session, error = try_read_session(project_dir)
            self.assertEqual(session, {})
            self.assertIsInstance(error, str)
            self.assertTrue(error)

    def test_try_read_history_returns_error_for_malformed_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "broken_history.hy")
            terminal_dir = os.path.join(project_dir, "terminal")
            os.makedirs(terminal_dir)
            with open(os.path.join(terminal_dir, "history.py"), "w", encoding="utf-8") as handle:
                handle.write("history = [\n")
            history, error = try_read_history(project_dir)
            self.assertEqual(history, [])
            self.assertIsInstance(error, str)
            self.assertTrue(error)

    def test_new_project_creates_default_procedures_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "new_project.hy")
            hyde.new_project(project_dir, load=False)
            self.assertTrue(os.path.exists(os.path.join(project_dir, "manifest.toml")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "session.toml")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "terminal", "history.py")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "procedures", "__init__.py")))
            self.assertFalse(os.path.exists(os.path.join(project_dir, "procedures", "master.py")))

    def test_gui_mode_rebinds_quit_and_exit_to_hyde_quit(self):
        original_quit = builtins.quit
        original_exit = builtins.exit
        original_main_quit = sys.modules["__main__"].__dict__.get("quit")
        original_main_exit = sys.modules["__main__"].__dict__.get("exit")
        original_hyde = sys.modules["__main__"].__dict__.get("hyde")
        try:
            hyde.gui_mode(True)

            self.assertIs(sys.modules["__main__"].__dict__["hyde"], hyde)
            self.assertIs(sys.modules["__main__"].__dict__["quit"], hyde.quit)
            self.assertIs(sys.modules["__main__"].__dict__["exit"], hyde.quit)
            self.assertIs(builtins.quit, hyde.quit)
            self.assertIs(builtins.exit, hyde.quit)
        finally:
            hyde.gui_mode(False)
            if original_main_quit is None:
                sys.modules["__main__"].__dict__.pop("quit", None)
            else:
                sys.modules["__main__"].__dict__["quit"] = original_main_quit
            if original_main_exit is None:
                sys.modules["__main__"].__dict__.pop("exit", None)
            else:
                sys.modules["__main__"].__dict__["exit"] = original_main_exit
            if original_hyde is None:
                sys.modules["__main__"].__dict__.pop("hyde", None)
            else:
                sys.modules["__main__"].__dict__["hyde"] = original_hyde
            builtins.quit = original_quit
            builtins.exit = original_exit

    def test_restore_project_session_warns_on_malformed_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "broken.hy")
            terminal_dir = os.path.join(project_dir, "terminal")
            os.makedirs(terminal_dir)
            with open(os.path.join(project_dir, "session.toml"), "w", encoding="utf-8") as handle:
                handle.write("not = [valid toml")

            command_window_service = DummyCommandWindowService(
                ["a = 1", "hyde.save_project()"]
            )
            history_app = type("HistoryApp", (), {})()
            history_app.plugin_manager = PluginManagerStub(
                services={"visible_command_service": command_window_service}
            )
            write_history(history_app, project_dir)

            warnings = []

            class DummyApp:
                pass

            app = DummyApp()
            app.current_project_dir = project_dir
            restore_service = DummyCommandWindowService()
            app.plugin_service = lambda key: (
                restore_service if key == "visible_command_service" else None
            )
            app.ui = QtWidgets.QMainWindow()

            from hyde.user_interface import main as main_module

            original_warning = main_module.QtWidgets.QMessageBox.warning
            main_module.QtWidgets.QMessageBox.warning = staticmethod(
                lambda *args, **kwargs: warnings.append(args[2] if len(args) > 2 else "")
            )
            try:
                main_module.HydeApp.restore_project_session(app)
            finally:
                main_module.QtWidgets.QMessageBox.warning = original_warning

            self.assertTrue(warnings)
            self.assertEqual(
                restore_service.restored_entries,
                ["a = 1", "hyde.save_project()"],
            )

    def test_project_state_result_save_and_copy_write_target_without_restoring_session(self):
        from hyde.user_interface import main as main_module

        for mode in ("save", "copy"):
            with self.subTest(mode=mode):
                calls = []
                app = type("DummyApp", (), {})()
                app.ui = QtWidgets.QMainWindow()
                app.current_project_dir = f"/tmp/current-{mode}.hy"
                app.end_project_operation = lambda: calls.append(("end", None))
                app.restore_project_session = lambda: calls.append(("restore", None))

                with patch.object(
                    main_module,
                    "write_session",
                    side_effect=lambda _app, path: calls.append(("session", path)),
                ):
                    with patch.object(
                        main_module,
                        "write_history",
                        side_effect=lambda _app, path: calls.append(("history", path)),
                    ):
                        with patch.object(
                            main_module.QtWidgets.QMessageBox,
                            "warning",
                            side_effect=lambda *args, **kwargs: calls.append(("warning", args[2])),
                        ):
                            main_module.HydeApp.on_project_state_result(
                                app,
                                {
                                    "operation": "save",
                                    "mode": mode,
                                    "success": True,
                                    "path": f"/tmp/{mode}-target.hy",
                                    "errors": [],
                                },
                            )

                self.assertEqual(
                    calls,
                    [
                        ("end", None),
                        ("session", f"/tmp/{mode}-target.hy"),
                        ("history", f"/tmp/{mode}-target.hy"),
                    ],
                )

    def test_project_state_result_save_as_restores_saved_target_session(self):
        from hyde.user_interface import main as main_module

        calls = []
        target_dir = "/tmp/save-as-target.hy"
        app = type("DummyApp", (), {})()
        app.ui = QtWidgets.QMainWindow()
        app.current_project_dir = target_dir
        app.end_project_operation = lambda: calls.append(("end", None))
        app.restore_project_session = lambda: calls.append(
            ("restore", app.current_project_dir)
        )

        with patch.object(
            main_module,
            "write_session",
            side_effect=lambda _app, path: calls.append(("session", path)),
        ):
            with patch.object(
                main_module,
                "write_history",
                side_effect=lambda _app, path: calls.append(("history", path)),
            ):
                with patch.object(
                    main_module.QtWidgets.QMessageBox,
                    "warning",
                    side_effect=lambda *args, **kwargs: calls.append(("warning", args[2])),
                ):
                    main_module.HydeApp.on_project_state_result(
                        app,
                        {
                            "operation": "save",
                            "mode": "save_as",
                            "success": True,
                            "path": target_dir,
                            "errors": [],
                        },
                    )

        self.assertEqual(
            calls,
            [
                ("end", None),
                ("session", target_dir),
                ("history", target_dir),
                ("restore", target_dir),
            ],
        )

    def test_resolve_startup_project_uses_cli_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "startup.hy")
            os.makedirs(project_dir)
            app = type("DummyApp", (), {"argv": [project_dir]})()
            self.assertEqual(HydeApp.resolve_startup_project(app), os.path.abspath(project_dir))

    def test_save_project_as_prompts_before_overwriting_non_empty_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = type("DummyApp", (), {})()
            app.ui = type("UI", (), {})()
            app.ui.statusbar = type(
                "StatusBar",
                (),
                {"showMessage": lambda self, message, timeout=0: None, "clearMessage": lambda self: None},
            )()
            app.current_project_dir = os.path.join(tmpdir, "current.hy")
            app.get_current_project_dir = lambda: app.current_project_dir
            app.visible_command_service = lambda: type(
                "VisibleCommandService",
                (),
                {"widget": lambda self: object()},
            )()
            os.makedirs(app.current_project_dir)
            target = os.path.join(tmpdir, "target.hy")
            os.makedirs(target)
            with open(os.path.join(target, "keep.txt"), "w", encoding="utf-8") as handle:
                handle.write("keep")

            prompted = []
            executed = []

            app.begin_project_operation = lambda label: HydeApp.begin_project_operation(app, label)
            app.project_target_needs_confirmation = lambda project_dir: HydeApp.project_target_needs_confirmation(
                app, project_dir
            )
            app.confirm_overwrite_project = lambda project_dir: prompted.append(project_dir) or False
            app.execute_command = lambda code, visible=True: executed.append((code, visible))
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
            }

            parent = QtWidgets.QWidget()
            dialog = SaveAsProjectDialog(app.services, parent=parent)
            dialog.selectFile(target)
            with patch.object(
                SaveAsProjectDialog,
                "exec_",
                return_value=QtWidgets.QDialog.Accepted,
            ):
                with patch.object(
                    SaveAsProjectDialog,
                    "selectedFiles",
                    return_value=[target],
                ):
                    self.assertFalse(dialog.run())

            self.assertEqual(prompted, [target])
            self.assertEqual(executed, [])
            dialog.close()
            parent.close()

    def test_save_project_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project = os.path.join(tmpdir, "current.hy")
            os.makedirs(source_project)
            hyde.HYDE_PROJECT_DIR = source_project
            try:
                with patch("hyde.project_tools.resolve_project_dir", side_effect=lambda path: Path(path)):
                    with patch("hyde.project_tools.ensure_project_dirs"):
                        with patch("hyde.project_tools.iter_saveable_objects", return_value=[]):
                            with patch("hyde.project_tools.write_manifest"):
                                result = hyde.save_project(mode="save")
                self.assertIsNone(result)
            finally:
                hyde.HYDE_PROJECT_DIR = None

    def test_heal_project_prints_recreated_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "heal_print.hy")
            os.makedirs(project_dir)
            with patch("builtins.print") as mock_print:
                healed_paths = hyde.heal_project(project_dir)
            self.assertTrue(healed_paths)
            mock_print.assert_called_once()
            printed = mock_print.call_args[0][0]
            self.assertIn(
                f"Recreated missing project files in {Path(project_dir).resolve()}:",
                printed,
            )
            self.assertIn("procedures/__init__.py", printed)

class TestHydeStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def test_startup_tolerates_missing_runtime_output_service(self):
        class FakeMenu:
            def clear(self):
                return None

        class FakeMdiArea:
            def setHorizontalScrollBarPolicy(self, policy):
                del policy

            def setVerticalScrollBarPolicy(self, policy):
                del policy

        class FakeUI:
            def __init__(self):
                self.mdiArea = FakeMdiArea()
                self.menuFile = FakeMenu()
                self.menuWindow = FakeMenu()

        class FakeUiLoader:
            def load(self, path, parent):
                del path, parent
                return FakeUI()

        class FakePluginManager:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self.services = {}

            def discover_modules(self):
                return {}

            def instantiate_plugins(self):
                return None

        with patch("hyde.user_interface.main.UiLoader", FakeUiLoader):
            with patch("hyde.user_interface.main.HydePluginManager", FakePluginManager):
                with patch.object(HydeApp, "setup_plugins", lambda self: None):
                    with patch.object(HydeApp, "start_kernel_runtime", lambda self: None):
                        app = HydeApp(
                            self.qapp,
                            process_tree=object(),
                            splash=DummySplash(),
                            argv=[],
                        )

        self.assertIsNone(app.logging_handler)

    def test_startup_tolerates_broken_runtime_output_service_output_box(self):
        class FakeMenu:
            def clear(self):
                return None

        class FakeMdiArea:
            def setHorizontalScrollBarPolicy(self, policy):
                del policy

            def setVerticalScrollBarPolicy(self, policy):
                del policy

        class FakeUI:
            def __init__(self):
                self.mdiArea = FakeMdiArea()
                self.menuFile = FakeMenu()
                self.menuWindow = FakeMenu()

        class FakeUiLoader:
            def load(self, path, parent):
                del path, parent
                return FakeUI()

        class BrokenLoggingService:
            def output_box(self):
                raise RuntimeError("broken output box")

        class FakePluginManager:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self.services = {
                    "runtime_output_service": BrokenLoggingService(),
                }

            def discover_modules(self):
                return {}

            def instantiate_plugins(self):
                return None

        with patch("hyde.user_interface.main.UiLoader", FakeUiLoader):
            with patch("hyde.user_interface.main.HydePluginManager", FakePluginManager):
                with patch.object(HydeApp, "setup_plugins", lambda self: None):
                    with patch.object(HydeApp, "start_kernel_runtime", lambda self: None):
                        app = HydeApp(
                            self.qapp,
                            process_tree=object(),
                            splash=DummySplash(),
                            argv=[],
                        )

        self.assertIsNone(app.logging_handler)

    def test_start_kernel_runtime_tolerates_broken_runtime_output_service_port(self):
        class FakeProcessTree:
            def __init__(self):
                self.calls = []

            def subprocess(self, path, args=None, output_redirection_port=None, startup_timeout=None):
                self.calls.append(
                    (path, list(args or []), output_redirection_port, startup_timeout)
                )
                return "to-kernel", "from-kernel", object()

        class FakeRuntimeHelper:
            def __init__(self, app, connection_file, from_kernel, kernel_process):
                self.app = app
                self.connection_file = connection_file
                self.from_kernel = from_kernel
                self.kernel_process = kernel_process
                self.started = False

            def start(self):
                self.started = True

        class BrokenLoggingService:
            def port(self):
                raise RuntimeError("broken port")

        dummy_app = type("DummyApp", (), {})()
        dummy_app.process_tree = FakeProcessTree()
        dummy_app.plugin_service = lambda key: (
            BrokenLoggingService() if key == "runtime_output_service" else None
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
        _, _, output_redirection_port, startup_timeout = dummy_app.process_tree.calls[0]
        self.assertIsNone(output_redirection_port)
        self.assertEqual(startup_timeout, 60)
        self.assertIsInstance(dummy_app.runtime_helper, FakeRuntimeHelper)
        self.assertTrue(dummy_app.runtime_helper.started)

    def test_startup_enters_no_project_state(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name("hyde-startup-test")
        app = HydeApp(self.qapp, process_tree, DummySplash(), argv=[])
        try:
            wait_until(lambda: app._startup_complete, timeout=60, message="Hyde did not finish startup.")
            self.assertIsNone(app.current_project_dir)
            self.assertIsNotNone(app.kernel_process)
            self.assertIsNone(app.kernel_process.poll())
            self.assertFalse(
                app.plugin_service("visible_command_service").subwindow().isVisible()
            )
            self.assertFalse(
                app.mdi_context.subwindow("procedures").isVisible()
            )
            self.assertFalse(
                app.plugin_service("namespace_view_service").subwindow().isVisible()
            )
            self.assertTrue(lookup_menu_action(app, "file", "New...").isEnabled())
            self.assertTrue(lookup_menu_action(app, "file", "Load...").isEnabled())
            self.assertTrue(lookup_menu_action(app, "window", "Logging").isEnabled())
            self.assertTrue(lookup_menu_action(app, "file", "Quit").isEnabled())
            self.assertFalse(lookup_menu_action(app, "file", "Save").isEnabled())
            self.assertFalse(lookup_menu_action(app, "file", "Save As...").isEnabled())
            self.assertFalse(lookup_menu_action(app, "file", "Save a Copy...").isEnabled())
            self.assertFalse(
                lookup_menu_action(app, "window", "Command Window").isEnabled()
            )
            self.assertFalse(lookup_menu_action(app, "window", "Procedures").isEnabled())
            self.assertFalse(lookup_menu_action(app, "window", "Data Browser").isEnabled())
            self.assertFalse(lookup_menu_action(app, "window", "New Table...").isEnabled())
        finally:
            app.finalize_quit()
            wait_until(
                lambda: (
                    app.plugin_service("visible_command_service").widget() is None
                    and app.plugin_service("namespace_view_service").widget() is None
                ),
                timeout=10,
                message="Hyde did not finish asynchronous shutdown.",
            )
            process_events(0.2)


class TestProjectSaveLoadIntegration(unittest.TestCase):
    def setUp(self):
        self.process_tree = ProcessTree.instance()
        self.tmpdir = tempfile.TemporaryDirectory()
        self._connection_counter = 0

    def tearDown(self):
        self.tmpdir.cleanup()

    def _start_kernel(self, name):
        self._connection_counter += 1
        connection_file = os.path.join(self.tmpdir.name, f"{name}.{self._connection_counter}.json")
        return start_kernel(self.process_tree, connection_file, f"hyde-{name}-test")

    def _project(self, name, procedures_text, extra_procedure_files=None):
        project_dir = os.path.join(self.tmpdir.name, name)
        procedures_dir = os.path.join(project_dir, "procedures")
        os.makedirs(procedures_dir)
        with open(os.path.join(procedures_dir, "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write(procedures_text)
        for relative_path, contents in (extra_procedure_files or {}).items():
            file_path = os.path.join(procedures_dir, relative_path)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(contents)
        return project_dir

    def _collect_operation_messages(self, from_child, operation):
        return collect_kernel_messages(
            from_child,
            timeout=15,
            stop_when=lambda task, data: task == "PROJECT_STATE_RESULT" and data.get("operation") == operation,
        )

    def test_save_project_writes_manifest_and_excludes_packages(self):
        project_dir = self._project(
            "save_project.hy",
            (
                "import hyde\n"
                "import numpy as np\n"
                "from numpy import random\n"
                "class Box:\n"
                "    def __init__(self, value):\n"
                "        self.value = value\n"
            ),
        )
        _, from_child, child, client = self._start_kernel("save-project")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            load_messages = self._collect_operation_messages(from_child, "load")
            self.assertEqual(load_messages[0][0], "ENTER_NO_PROJECT_STATE")
            self.assertIn(("ACTIVATE_PROJECT", {"path": os.path.realpath(project_dir)}), [(t, {"path": os.path.realpath(d["path"])} if isinstance(d, dict) and "path" in d else d) for t, d in load_messages if t == "ACTIVATE_PROJECT"])

            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "arr = np.arange(4)\n"
                "boxed = Box(7)\n"
                "In = ['ignore-me']\n"
                "Out = {1: 'ignore-me-too'}\n"
                "hyde.save_project()\n",
            )
            result_messages = self._collect_operation_messages(from_child, "save")
            result = result_messages[-1][1]
            self.assertTrue(result["success"])

            manifest_path = os.path.join(project_dir, "manifest.toml")
            with open(manifest_path, "rb") as handle:
                manifest = tomllib.load(handle)
            object_names = {entry["name"] for entry in manifest["objects"]}
            self.assertIn("arr", object_names)
            self.assertIn("boxed", object_names)
            self.assertNotIn("hyde", object_names)
            self.assertNotIn("np", object_names)
            self.assertNotIn("random", object_names)
            self.assertNotIn("Box", object_names)
            self.assertNotIn("In", object_names)
            self.assertNotIn("Out", object_names)
            self.assertTrue(os.path.exists(os.path.join(project_dir, "data", "arr.npy")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "data", "boxed.pkl")))
        finally:
            client.stop_channels()
            child.terminate()

    def test_load_project_resets_to_no_project_then_restores_objects(self):
        project_a_dir = self._project(
            "project_a.hy",
            (
                "import hyde\n"
                "import numpy as np\n"
                "class Box:\n"
                "    def __init__(self, value):\n"
                "        self.value = value\n"
                "VALUE = 1\n"
            ),
        )
        project_b_dir = self._project(
            "project_b.hy",
            "import hyde\nVALUE = 100\nOTHER = 5\n",
        )
        _, from_child, child, client = self._start_kernel("load-project")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_a_dir!r})")
            self._collect_operation_messages(from_child, "load")
            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "arr = np.arange(5)\n"
                "boxed = Box(9)\n"
                "VALUE = 22\n"
                "hyde.save_project()\n",
            )
            self._collect_operation_messages(from_child, "save")

            wait_for_code_ok(client, f"hyde.load_project({project_b_dir!r})")
            messages = self._collect_operation_messages(from_child, "load")
            task_names = [task for task, _ in messages]
            self.assertLess(task_names.index("ENTER_NO_PROJECT_STATE"), task_names.index("ACTIVATE_PROJECT"))
            wait_for_code_ok(
                client,
                "assert VALUE == 100\n"
                "assert OTHER == 5\n"
                "assert 'arr' not in globals()\n"
                "assert 'boxed' not in globals()\n",
            )

            wait_for_code_ok(client, f"hyde.load_project({project_a_dir!r})")
            messages = self._collect_operation_messages(from_child, "load")
            task_names = [task for task, _ in messages]
            self.assertLess(task_names.index("ENTER_NO_PROJECT_STATE"), task_names.index("ACTIVATE_PROJECT"))
            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "assert np.array_equal(arr, np.arange(5))\n"
                "assert boxed.value == 9\n"
                "assert VALUE == 22\n",
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_failed_load_leaves_kernel_in_no_project_state(self):
        good_project = self._project("good.hy", "import hyde\nVALUE = 1\n")
        broken_project = self._project("broken.hy", "import hyde\nraise RuntimeError('boom')\n")
        _, from_child, child, client = self._start_kernel("failed-load")
        try:
            wait_for_code_ok(client, f"hyde.load_project({good_project!r})")
            self._collect_operation_messages(from_child, "load")
            wait_for_code_ok(client, "stale_value = 123\n")

            reply = execute_and_wait(client, f"hyde.load_project({broken_project!r})")
            self.assertEqual(reply["content"]["status"], "error")
            messages = self._collect_operation_messages(from_child, "load")
            task_names = [task for task, _ in messages]
            self.assertIn("ENTER_NO_PROJECT_STATE", task_names)
            self.assertNotIn("ACTIVATE_PROJECT", task_names)
            result = messages[-1][1]
            self.assertFalse(result["success"])
            wait_for_code_ok(
                client,
                "import hyde\n"
                "import os\n"
                "import sys\n"
                "assert hyde.HYDE_PROJECT_DIR is None\n"
                "assert 'stale_value' not in globals()\n"
                f"assert os.path.realpath(os.getcwd()) not in ({os.path.realpath(good_project)!r}, {os.path.realpath(broken_project)!r})\n"
                f"assert {os.path.realpath(good_project)!r} not in [os.path.realpath(path or os.getcwd()) for path in sys.path]\n"
                f"assert {os.path.realpath(os.path.join(good_project, 'procedures'))!r} not in [os.path.realpath(path or os.getcwd()) for path in sys.path]\n"
                f"assert {os.path.realpath(broken_project)!r} not in [os.path.realpath(path or os.getcwd()) for path in sys.path]\n"
                f"assert {os.path.realpath(os.path.join(broken_project, 'procedures'))!r} not in [os.path.realpath(path or os.getcwd()) for path in sys.path]\n",
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_load_project_errors_on_missing_required_project_files(self):
        project_dir = os.path.join(self.tmpdir.name, "missing_init.hy")
        os.makedirs(project_dir)
        _, from_child, child, client = self._start_kernel("missing-init")
        try:
            reply = execute_and_wait(client, f"hyde.load_project({project_dir!r})")
            self.assertEqual(reply["content"]["status"], "error")
            messages = self._collect_operation_messages(from_child, "load")
            result = messages[-1][1]
            self.assertFalse(result["success"])
            self.assertFalse(os.path.exists(os.path.join(project_dir, "procedures", "__init__.py")))
            self.assertTrue(
                any("Missing required project file" in error for error in result["errors"]),
                result["errors"],
            )
            self.assertTrue(
                any("hyde.heal_project(" in error for error in result["errors"]),
                result["errors"],
            )
            wait_for_code_ok(
                client,
                "import hyde\n"
                "assert hyde.HYDE_PROJECT_DIR is None\n",
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_heal_project_recreates_missing_template_files_for_existing_project(self):
        project_dir = os.path.join(self.tmpdir.name, "heal_existing.hy")
        os.makedirs(project_dir)
        _, from_child, child, client = self._start_kernel("heal-existing")
        try:
            wait_for_code_ok(client, f"hyde.heal_project({project_dir!r})")
            messages = self._collect_operation_messages(from_child, "heal")
            result = messages[-1][1]
            self.assertTrue(result["success"])
            self.assertTrue(os.path.exists(os.path.join(project_dir, "procedures", "__init__.py")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "manifest.toml")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "session.toml")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "terminal", "history.py")))
            self.assertTrue(
                any(
                    f"Recreated missing project files in {Path(project_dir).resolve()}:" in error
                    for error in result["errors"]
                ),
                result["errors"],
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_heal_project_requires_existing_hy_directory(self):
        project_dir = os.path.join(self.tmpdir.name, "does_not_exist.hy")
        _, from_child, child, client = self._start_kernel("heal-missing-dir")
        try:
            reply = execute_and_wait(client, f"hyde.heal_project({project_dir!r})")
            self.assertEqual(reply["content"]["status"], "error")
            messages = self._collect_operation_messages(from_child, "heal")
            result = messages[-1][1]
            self.assertFalse(result["success"])
            self.assertTrue(
                any("does not exist" in error for error in result["errors"]),
                result["errors"],
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_procedure_reload_removes_deleted_exports_but_keeps_user_globals(self):
        project_dir = self._project(
            "reload_exports.hy",
            "import hyde\nKEEP = 1\nREMOVE_ME = 2\n",
        )
        _, from_child, child, client = self._start_kernel("reload-exports")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            self._collect_operation_messages(from_child, "load")
            wait_for_code_ok(client, "user_value = 99\n")

            with open(os.path.join(project_dir, "procedures", "__init__.py"), "w", encoding="utf-8") as handle:
                handle.write("import hyde\nKEEP = 3\n")

            reload_state = RuntimeCommandState()
            reload_state.set_reload_procedures(
                project_dir,
                os.path.dirname(HYDE_DIR),
                reset_namespace=False,
            )
            wait_for_code_ok(
                client,
                f"exec({reload_state.python_source()!r})\n"
                "assert KEEP == 3\n"
                "assert 'REMOVE_ME' not in globals()\n"
                "assert user_value == 99\n",
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_save_project_as_switches_active_project_directory(self):
        project_dir = self._project("save_as_source.hy", "import hyde\nVALUE = 1\n")
        target_dir = os.path.join(self.tmpdir.name, "save_as_target.hy")
        _, from_child, child, client = self._start_kernel("save-as")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            self._collect_operation_messages(from_child, "load")

            wait_for_code_ok(
                client,
                f"VALUE = 7\nhyde.save_project({target_dir!r}, mode='save_as', overwrite=True)\n",
            )
            messages = self._collect_operation_messages(from_child, "save")
            self.assertIn("ACTIVATE_PROJECT", [task for task, _ in messages])
            result = messages[-1][1]
            self.assertTrue(result["success"])
            self.assertEqual(result["mode"], "save_as")
            wait_for_code_ok(
                client,
                "import os\n"
                "import hyde\n"
                f"assert os.path.realpath(os.getcwd()) == {os.path.realpath(target_dir)!r}\n"
                f"assert os.path.realpath(hyde.HYDE_PROJECT_DIR) == {os.path.realpath(target_dir)!r}\n"
                "assert VALUE == 7\n",
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_save_project_copy_preserves_procedures_tree_without_switching_projects(self):
        project_dir = self._project(
            "source_project.hy",
            "import hyde\nimport helper_module\nVALUE = helper_module.VALUE\n",
            extra_procedure_files={"helper_module.py": "VALUE = 17\n"},
        )
        target_dir = os.path.join(self.tmpdir.name, "copied_project.hy")
        _, from_child, child, client = self._start_kernel("copy-project")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            self._collect_operation_messages(from_child, "load")

            wait_for_code_ok(
                client,
                f"hyde.save_project({target_dir!r}, mode='copy', overwrite=True)\n",
            )
            messages = self._collect_operation_messages(from_child, "save")
            self.assertNotIn("ACTIVATE_PROJECT", [task for task, _ in messages])
            self.assertTrue(os.path.exists(os.path.join(target_dir, "procedures", "__init__.py")))
            self.assertTrue(os.path.exists(os.path.join(target_dir, "procedures", "helper_module.py")))
            wait_for_code_ok(
                client,
                "import os\n"
                "import hyde\n"
                f"assert os.path.realpath(hyde.HYDE_PROJECT_DIR) == {os.path.realpath(project_dir)!r}\n",
            )
        finally:
            client.stop_channels()
            child.terminate()

    def test_fresh_kernel_exposes_hyde_namespace_before_and_after_project_load(self):
        project_dir = self._project("namespace.hy", "import hyde\nVALUE = 1\n")
        _, from_child, child, client = self._start_kernel("namespace")
        try:
            wait_for_code_ok(client, "assert hyde.HYDE_GUI is True\n")
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            self._collect_operation_messages(from_child, "load")
            wait_for_code_ok(client, "assert hyde.HYDE_GUI is True\n")
        finally:
            client.stop_channels()
            child.terminate()


if __name__ == "__main__":
    unittest.main()
