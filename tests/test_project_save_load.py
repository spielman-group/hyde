import os
import sys
import time
import unittest
import tempfile
import builtins
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="hyde-mpl-"))
os.environ.setdefault("IPYTHONDIR", tempfile.mkdtemp(prefix="hyde-ipython-"))

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from jupyter_client import BlockingKernelClient
from labscript_utils.ls_zprocess import ProcessTree
from qtutils.qt import QtWidgets, QtCore, QtGui

import tomllib

import hyde
import hyde.project_tools
from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.shared.core import RuntimeCommandState
from hyde.user_interface.main import HydeApp
from hyde.user_interface.main.project_state import (
    capture_session,
    write_session,
)
from hyde.user_interface.shared.plugin import HydeMDIContext, HydePlugin
from hyde.user_interface.plugins.figure import FigureWorkspaceService
from hyde.user_interface.plugins.figure.window import FigureState
from hyde.user_interface.plugins.table import TableWorkspaceService


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


class DummyPythonTerminalService:
    def __init__(self, history=None):
        self._history = list(history or [])
        self.restored_entries = None

    def history_entries(self):
        return list(self._history)

    def restore_history_entries(self, entries):
        self.restored_entries = list(entries)


class DummyExecutionService:
    def __init__(self, events):
        self.events = events

    def execute_hidden(self, code, silent=True):
        self.events.append(("session_source", code, silent))
        return True


class DummyWindowExecutionService:
    def __init__(self):
        self.hidden_calls = []

    def execute_hidden(self, code, silent=True):
        self.hidden_calls.append((code, silent))
        return True


class DummyNamespaceViewService:
    def namespace_view(self):
        return {}

    def connect_namespace_view_updated(self, callback):
        del callback

    def disconnect_namespace_view_updated(self, callback):
        del callback


class DummySaveWindowDialogService:
    def __init__(self, result=False):
        self.result = bool(result)
        self.calls = []

    def prompt_to_save_window_macro(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.result


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


class SessionRestoreToolWindowPlugin:
    def __init__(self, app, mdi_area, window_keys):
        self.app = app
        self.window_keys = tuple(window_keys)
        self.helper = HydePlugin({})
        self.mdi_context = HydeMDIContext(mdi_area)
        self.helper.services = {
            "mdi_context": self.mdi_context,
            "get_session_restore_presentation_deferred": (
                lambda: getattr(
                    self.app,
                    "_session_restore_presentation_deferred",
                    False,
                )
            ),
            "register_session_restore_tool_window": (
                lambda name, subwindow, info: (
                    self.app._session_restore_tool_windows.__setitem__(
                        name,
                        (subwindow, dict(info)),
                    )
                )
            ),
        }
        for key in self.window_keys:
            self.mdi_context.add(
                "tests",
                {
                    "context": "mdi",
                    "key": key,
                    "title": key,
                    "factory": lambda parent=None, data=None: QtWidgets.QWidget(parent),
                },
                {"services": {}},
            )
            self.helper.ensure_mdi_widget(key)

    def get_event_handlers(self):
        return {"project_loaded": self.on_project_loaded}

    def on_project_loaded(self, data):
        for key in self.window_keys:
            self.helper.restore_tool_window(data["session"], key)

    def subwindow(self, key):
        return self.helper.mdi_subwindow(key)


class TestProjectStateHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def test_write_session_routes_figure_restore_source_to_session_python(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "session_routes.hy")
            os.makedirs(project_dir)

            main_window = QtWidgets.QMainWindow()

            class SavingPlugin:
                def get_session_toml_data(self):
                    return {
                        "tool_windows": {"logging": {"visible": True}},
                    }

                def get_session_restore_source(self):
                    return (
                        "@hyde.figure(window_pos=(5, 42), register=False)\n"
                        "def Figure0(delay, fit_delay):\n"
                        "    fig = plt.figure('Figure0')\n"
                        "    ax = fig.add_subplot(111)\n"
                        "    ax.plot(delay, fit_delay)\n\n"
                        "Figure0(delay, fit_delay)\n"
                    )

            source_app = type("SourceApp", (), {})()
            source_app.ui = main_window
            source_app.plugin_manager = PluginManagerStub({"session": SavingPlugin()})

            write_session(source_app, project_dir)

            session_toml = (Path(project_dir) / "session.toml").read_text()
            session = tomllib.loads(session_toml)
            session_source = (Path(project_dir) / "session.py").read_text()

            self.assertTrue(session["tool_windows"]["logging"]["visible"])
            self.assertNotIn("@hyde.figure", session_toml)
            self.assertIn("@hyde.figure(window_pos=(5, 42), register=False)", session_source)
            self.assertIn("def Figure0(delay, fit_delay):", session_source)
            self.assertIn("Figure0(delay, fit_delay)", session_source)

    def test_restore_project_session_runs_session_python_after_project_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "session_restore.hy"
            project_dir.mkdir()
            (project_dir / "session.toml").write_text(
                "format_version = 1\n",
                encoding="utf-8",
            )
            (project_dir / "session.py").write_text(
                "@hyde.figure(window_pos=(10, 20), register=False)\n"
                "def Figure0(delay):\n"
                "    fig = plt.figure('Figure0')\n"
                "    ax = fig.add_subplot(111)\n"
                "    ax.plot(delay)\n\n"
                "Figure0(delay)\n",
                encoding="utf-8",
            )
            terminal_dir = project_dir / "terminal"
            terminal_dir.mkdir()
            (terminal_dir / "history.py").write_text("history = []\n", encoding="utf-8")

            events = []

            class RestoringPlugin:
                def get_event_handlers(self):
                    return {"project_loaded": self.on_project_loaded}

                def on_project_loaded(self, data):
                    events.append(("project_loaded", data))

            restored_app = type("RestoredApp", (), {})()
            restored_app.ui = QtWidgets.QMainWindow()
            restored_app.current_project_dir = str(project_dir)
            restored_app._session_restore_presentation_deferred = False
            restored_app._session_restore_tool_windows = {}
            restored_app._session_restore_session = None
            restored_app._clear_session_restore_state = (
                lambda: HydeApp._clear_session_restore_state(restored_app)
            )
            restored_app._schedule_session_restore_order_finalize = (
                lambda: HydeApp._schedule_session_restore_order_finalize(restored_app)
            )
            restored_app._finalize_session_restore_order = (
                lambda: HydeApp._finalize_session_restore_order(restored_app)
            )
            restored_app._complete_session_restore = (
                lambda success: HydeApp._complete_session_restore(
                    restored_app,
                    success,
                )
            )
            restored_app.plugin_manager = PluginManagerStub({"session": RestoringPlugin()})
            restored_app.plugin_service = lambda key: (
                DummyPythonTerminalService()
                if key == "visible_terminal_service"
                else DummyExecutionService(events)
                if key == "python_execution_service"
                else None
            )
            restored_app.emit_plugin_event = (
                lambda name, data=None: HydeApp.emit_plugin_event(restored_app, name, data)
            )

            HydeApp.restore_project_session(restored_app)

            self.assertEqual(events[0][0], "project_loaded")
            self.assertEqual(events[1][0], "session_source")
            self.assertIn("@hyde.figure(window_pos=(10, 20), register=False)", events[1][1])
            self.assertIn("Figure0(delay)", events[1][1])
            self.assertIn('hyde.task_complete("session_restore", True)', events[1][1])
            self.assertTrue(events[1][2])

    def test_restore_project_session_finalizes_staged_order_and_states_after_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "session_restore_finalize.hy"
            project_dir.mkdir()
            (project_dir / "session.toml").write_text(
                "\n".join(
                    [
                        "format_version = 1",
                        "",
                        "[main_window]",
                        "mdi_window_order = ['python_terminal', 'Table0', 'logging']",
                        "",
                        "[tool_windows.python_terminal]",
                        "window_state = 'minimized'",
                        "geometry = [10, 20, 240, 160]",
                        "",
                        "[tool_windows.logging]",
                        "window_state = 'visible'",
                        "geometry = [300, 40, 220, 140]",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project_dir / "session.py").write_text(
                "Table0()\n",
                encoding="utf-8",
            )
            terminal_dir = project_dir / "terminal"
            terminal_dir.mkdir()
            (terminal_dir / "history.py").write_text("history = []\n", encoding="utf-8")

            events = []
            main_window = QtWidgets.QMainWindow()
            mdi_area = QtWidgets.QMdiArea()
            main_window.setCentralWidget(mdi_area)
            main_window.mdiArea = mdi_area
            main_window.show()
            self.qapp.processEvents()

            restored_app = type("RestoredApp", (), {})()
            restored_app.ui = main_window
            restored_app.current_project_dir = str(project_dir)
            restored_app._session_restore_presentation_deferred = False
            restored_app._session_restore_tool_windows = {}
            restored_app._session_restore_session = None
            restored_app._clear_session_restore_state = (
                lambda: HydeApp._clear_session_restore_state(restored_app)
            )
            restored_app._schedule_session_restore_order_finalize = (
                lambda: HydeApp._schedule_session_restore_order_finalize(restored_app)
            )
            restored_app._finalize_session_restore_order = (
                lambda: HydeApp._finalize_session_restore_order(restored_app)
            )
            restored_app._complete_session_restore = (
                lambda success: HydeApp._complete_session_restore(
                    restored_app,
                    success,
                )
            )
            tool_plugin = SessionRestoreToolWindowPlugin(
                restored_app,
                mdi_area,
                ("logging", "python_terminal"),
            )
            restored_app.plugin_manager = PluginManagerStub(
                {"tools": tool_plugin},
                services={
                    "visible_terminal_service": DummyPythonTerminalService(),
                    "python_execution_service": DummyExecutionService(events),
                },
            )
            restored_app.plugin_service = (
                lambda key: restored_app.plugin_manager.services.get(key)
            )
            restored_app.emit_plugin_event = (
                lambda name, data=None: HydeApp.emit_plugin_event(
                    restored_app,
                    name,
                    data,
                )
            )

            HydeApp.restore_project_session(restored_app)

            terminal_subwindow = tool_plugin.subwindow("python_terminal")
            self.assertTrue(terminal_subwindow.isVisible())
            self.assertFalse(terminal_subwindow.isMinimized())

            restored_table = mdi_area.addSubWindow(QtWidgets.QLabel("Table0"))
            restored_table.setObjectName("Table0")
            restored_table.show()
            self.qapp.processEvents()

            HydeApp.on_task_complete(
                restored_app,
                {"name": "session_restore", "success": True},
            )
            self.qapp.processEvents()

            order = [
                subwindow.objectName()
                for subwindow in mdi_area.subWindowList(QtWidgets.QMdiArea.StackingOrder)
                if str(subwindow.objectName()).strip()
            ]
            self.assertEqual(order, ["python_terminal", "Table0", "logging"])
            self.assertTrue(terminal_subwindow.isMinimized())
            self.assertIn('hyde.task_complete("session_restore", True)', events[0][1])

    def test_restore_project_session_skips_finalization_after_failed_session_restore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "session_restore_failure.hy"
            project_dir.mkdir()
            (project_dir / "session.toml").write_text(
                "\n".join(
                    [
                        "format_version = 1",
                        "",
                        "[main_window]",
                        "mdi_window_order = ['python_terminal', 'Table0', 'logging']",
                        "",
                        "[tool_windows.python_terminal]",
                        "window_state = 'minimized'",
                        "geometry = [10, 20, 240, 160]",
                        "",
                        "[tool_windows.logging]",
                        "window_state = 'visible'",
                        "geometry = [300, 40, 220, 140]",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project_dir / "session.py").write_text(
                "Table0()\n",
                encoding="utf-8",
            )
            terminal_dir = project_dir / "terminal"
            terminal_dir.mkdir()
            (terminal_dir / "history.py").write_text("history = []\n", encoding="utf-8")

            events = []
            main_window = QtWidgets.QMainWindow()
            mdi_area = QtWidgets.QMdiArea()
            main_window.setCentralWidget(mdi_area)
            main_window.mdiArea = mdi_area
            main_window.show()
            self.qapp.processEvents()

            restored_app = type("RestoredApp", (), {})()
            restored_app.ui = main_window
            restored_app.current_project_dir = str(project_dir)
            restored_app._session_restore_presentation_deferred = False
            restored_app._session_restore_tool_windows = {}
            restored_app._session_restore_session = None
            restored_app._clear_session_restore_state = (
                lambda: HydeApp._clear_session_restore_state(restored_app)
            )
            restored_app._schedule_session_restore_order_finalize = (
                lambda: HydeApp._schedule_session_restore_order_finalize(restored_app)
            )
            restored_app._finalize_session_restore_order = (
                lambda: HydeApp._finalize_session_restore_order(restored_app)
            )
            restored_app._complete_session_restore = (
                lambda success: HydeApp._complete_session_restore(
                    restored_app,
                    success,
                )
            )
            tool_plugin = SessionRestoreToolWindowPlugin(
                restored_app,
                mdi_area,
                ("logging", "python_terminal"),
            )
            restored_app.plugin_manager = PluginManagerStub(
                {"tools": tool_plugin},
                services={
                    "visible_terminal_service": DummyPythonTerminalService(),
                    "python_execution_service": DummyExecutionService(events),
                },
            )
            restored_app.plugin_service = (
                lambda key: restored_app.plugin_manager.services.get(key)
            )
            restored_app.emit_plugin_event = (
                lambda name, data=None: HydeApp.emit_plugin_event(
                    restored_app,
                    name,
                    data,
                )
            )

            HydeApp.restore_project_session(restored_app)

            terminal_subwindow = tool_plugin.subwindow("python_terminal")
            restored_table = mdi_area.addSubWindow(QtWidgets.QLabel("Table0"))
            restored_table.setObjectName("Table0")
            restored_table.show()
            self.qapp.processEvents()
            initial_order = [
                subwindow.objectName()
                for subwindow in mdi_area.subWindowList(QtWidgets.QMdiArea.StackingOrder)
                if str(subwindow.objectName()).strip()
            ]

            HydeApp.on_task_complete(
                restored_app,
                {"name": "session_restore", "success": False},
            )
            self.qapp.processEvents()

            final_order = [
                subwindow.objectName()
                for subwindow in mdi_area.subWindowList(QtWidgets.QMdiArea.StackingOrder)
                if str(subwindow.objectName()).strip()
            ]
            self.assertEqual(final_order, initial_order)
            self.assertFalse(terminal_subwindow.isMinimized())
            self.assertIn('hyde.task_complete("session_restore", False)', events[0][1])

    def test_capture_session_records_named_mdi_window_order(self):
        main_window = QtWidgets.QMainWindow()
        mdi_area = QtWidgets.QMdiArea()
        main_window.setCentralWidget(mdi_area)
        main_window.mdiArea = mdi_area
        main_window.show()
        self.qapp.processEvents()

        created = []
        for name in ("logging", "python_terminal", "Table0"):
            subwindow = mdi_area.addSubWindow(QtWidgets.QLabel(name))
            subwindow.setObjectName(name)
            subwindow.show()
            created.append(subwindow)
        unnamed = mdi_area.addSubWindow(QtWidgets.QLabel("unnamed"))
        unnamed.setObjectName("   ")
        unnamed.show()
        created.append(unnamed)
        self.qapp.processEvents()

        created[0].raise_()
        created[2].raise_()
        created[1].raise_()
        self.qapp.processEvents()

        app = type("CaptureApp", (), {})()
        app.ui = main_window

        session = capture_session(app)

        self.assertEqual(
            session["main_window"]["mdi_window_order"],
            ["logging", "Table0", "python_terminal"],
        )

    def test_capture_session_records_hidden_named_mdi_window_order(self):
        main_window = QtWidgets.QMainWindow()
        mdi_area = QtWidgets.QMdiArea()
        main_window.setCentralWidget(mdi_area)
        main_window.mdiArea = mdi_area
        main_window.show()
        self.qapp.processEvents()

        subwindows = {}
        for name in ("logging", "Table0", "Figure0", "python_terminal"):
            subwindow = mdi_area.addSubWindow(QtWidgets.QLabel(name))
            subwindow.setObjectName(name)
            subwindow.show()
            subwindows[name] = subwindow
        self.qapp.processEvents()

        subwindows["logging"].hide()
        subwindows["Table0"].raise_()
        subwindows["Figure0"].raise_()
        subwindows["python_terminal"].raise_()
        self.qapp.processEvents()

        app = type("CaptureApp", (), {})()
        app.ui = main_window

        session = capture_session(app)

        self.assertEqual(
            session["main_window"]["mdi_window_order"],
            ["logging", "Table0", "Figure0", "python_terminal"],
        )

    def _figure_ir_with_title(self, title):
        state = FigureState()
        state.set_title(title)
        state.set_x_name("delay")
        state.set_items(["fit_delay"])
        return figure_ir_from_live_state(state.normalized_state())

    def _figure_png_base64(self):
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data().toBase64()).decode("ascii")

    def test_restore_project_session_finalizes_mixed_workspace_after_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "session_restore_mixed.hy"
            project_dir.mkdir()
            (project_dir / "session.toml").write_text(
                "\n".join(
                    [
                        "format_version = 1",
                        "",
                        "[main_window]",
                        "mdi_window_order = ['logging', 'Table0', 'Figure0', 'python_terminal']",
                        "",
                        "[tool_windows.python_terminal]",
                        "window_state = 'minimized'",
                        "geometry = [10, 20, 240, 160]",
                        "",
                        "[tool_windows.logging]",
                        "window_state = 'hidden'",
                        "geometry = [300, 40, 220, 140]",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (project_dir / "session.py").write_text(
                "\n".join(
                    [
                        "@hyde.table(register=False)",
                        "def Table0(a):",
                        "    hyde.create_table(a, name='Table0')",
                        "",
                        "Table0(a)",
                        "",
                        "@hyde.figure(window_pos=(40, 60), window_state='minimized', register=False)",
                        "def Figure0(delay, fit_delay):",
                        "    fig = plt.figure('Figure0')",
                        "    ax = fig.add_subplot(111)",
                        "    ax.plot(delay, fit_delay, label='fit_delay')",
                        "    fig.show()",
                        "",
                        "Figure0(delay, fit_delay)",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            terminal_dir = project_dir / "terminal"
            terminal_dir.mkdir()
            (terminal_dir / "history.py").write_text("history = []\n", encoding="utf-8")

            events = []
            main_window = QtWidgets.QMainWindow()
            mdi_area = QtWidgets.QMdiArea()
            main_window.setCentralWidget(mdi_area)
            main_window.mdiArea = mdi_area
            main_window.show()
            self.qapp.processEvents()

            restored_app = type("RestoredApp", (), {})()
            restored_app.ui = main_window
            restored_app.current_project_dir = str(project_dir)
            restored_app._session_restore_presentation_deferred = False
            restored_app._session_restore_tool_windows = {}
            restored_app._session_restore_session = None
            restored_app._clear_session_restore_state = (
                lambda: HydeApp._clear_session_restore_state(restored_app)
            )
            restored_app._schedule_session_restore_order_finalize = (
                lambda: HydeApp._schedule_session_restore_order_finalize(restored_app)
            )
            restored_app._finalize_session_restore_order = (
                lambda: HydeApp._finalize_session_restore_order(restored_app)
            )
            restored_app._complete_session_restore = (
                lambda success: HydeApp._complete_session_restore(
                    restored_app,
                    success,
                )
            )
            tool_plugin = SessionRestoreToolWindowPlugin(
                restored_app,
                mdi_area,
                ("logging", "python_terminal"),
            )
            restored_app.plugin_manager = PluginManagerStub(
                {"tools": tool_plugin},
                services={
                    "visible_terminal_service": DummyPythonTerminalService(),
                    "python_execution_service": DummyExecutionService(events),
                },
            )
            restored_app.plugin_service = (
                lambda key: restored_app.plugin_manager.services.get(key)
            )
            restored_app.emit_plugin_event = (
                lambda name, data=None: HydeApp.emit_plugin_event(
                    restored_app,
                    name,
                    data,
                )
            )

            HydeApp.restore_project_session(restored_app)

            HydeApp.on_task_complete(
                restored_app,
                {"name": "session_restore", "success": True},
            )

            table_plugin = type("TablePluginStub", (), {})()
            table_plugin.services = {
                "mdi_area": mdi_area,
                "namespace_view_service": DummyNamespaceViewService(),
                "python_execution_service": DummyWindowExecutionService(),
                "save_window_dialog_service": DummySaveWindowDialogService(),
            }
            table_workspace = TableWorkspaceService(table_plugin)
            restored_table = table_workspace.open_table(
                ["a"],
                name="Table0",
            )

            figure_plugin = type("FigurePluginStub", (), {})()
            figure_plugin.services = {
                "mdi_area": mdi_area,
                "namespace_view_service": DummyNamespaceViewService(),
                "python_execution_service": DummyWindowExecutionService(),
                "save_window_dialog_service": DummySaveWindowDialogService(),
                "get_shutting_down": lambda: False,
            }
            figure_workspace = FigureWorkspaceService(figure_plugin)
            figure_ir = self._figure_ir_with_title("Figure0")
            png_base64 = self._figure_png_base64()
            figure_payload = {
                "figure_number": 1,
                "title": "Figure0",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "Figure0",
                    "call_source": "fig = plt.figure('Figure0')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {
                        "window_pos": [40, 60],
                        "window_state": "minimized",
                    },
                },
            }
            figure_workspace.open_or_update_figure(figure_payload)
            figure_workspace.open_or_update_figure(
                {
                    **figure_payload,
                    "image_png_base64": png_base64,
                }
            )
            self.qapp.processEvents()

            terminal_subwindow = tool_plugin.subwindow("python_terminal")
            logging_subwindow = tool_plugin.subwindow("logging")
            table_subwindow = restored_table.parentWidget()
            figure_subwindow = figure_workspace.figures[1].parentWidget()

            self.assertTrue(logging_subwindow.isHidden())
            self.assertTrue(terminal_subwindow.isMinimized())
            self.assertTrue(table_subwindow.isVisible())
            self.assertFalse(table_subwindow.isMinimized())
            self.assertTrue(figure_subwindow.isMinimized())

            visible_order = [
                subwindow.objectName()
                for subwindow in mdi_area.subWindowList(QtWidgets.QMdiArea.StackingOrder)
                if str(subwindow.objectName()).strip() and not subwindow.isHidden()
            ]
            self.assertEqual(
                visible_order,
                ["Table0", "Figure0", "python_terminal"],
            )
            self.assertIn('hyde.task_complete("session_restore", True)', events[0][1])

            figure_workspace.clear()
            table_workspace.clear()
            main_window.close()

    def test_materialize_project_template_skips_gitkeep_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "heal_existing.hy"
            project_dir.mkdir()

            created_paths = hyde.project_tools.materialize_project_template(
                project_dir,
                missing_only=True,
            )

            self.assertTrue((project_dir / "procedures" / "__init__.py").exists())
            self.assertTrue((project_dir / "manifest.toml").exists())
            self.assertTrue((project_dir / "session.toml").exists())
            self.assertTrue((project_dir / "session.py").exists())
            self.assertTrue((project_dir / "terminal" / "history.py").exists())
            self.assertFalse((project_dir / "data" / ".gitkeep").exists())
            self.assertNotIn("data/.gitkeep", created_paths)

    def test_gui_mode_rebinds_quit_and_exit_to_hyde_quit(self):
        original_quit = builtins.quit
        original_exit = builtins.exit
        original_main_quit = sys.modules["__main__"].__dict__.get("quit")
        original_main_exit = sys.modules["__main__"].__dict__.get("exit")
        original_hyde = sys.modules["__main__"].__dict__.get("hyde")
        try:
            with patch(
                "hyde.execution.kernel_signals.install_signal_marker_handlers"
            ) as install_handlers, patch(
                "hyde.execution.kernel_signals.restore_signal_marker_handlers"
            ) as restore_handlers:
                hyde.gui_mode(True)

                self.assertIs(sys.modules["__main__"].__dict__["hyde"], hyde)
                self.assertIs(sys.modules["__main__"].__dict__["quit"], hyde.quit)
                self.assertIs(sys.modules["__main__"].__dict__["exit"], hyde.quit)
                self.assertIs(builtins.quit, hyde.quit)
                self.assertIs(builtins.exit, hyde.quit)
                install_handlers.assert_called_once_with()

                hyde.gui_mode(False)
                restore_handlers.assert_called_once_with()
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

class TestHydeStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def _record_quit_requests(self, app):
        quit_requests = []
        helper = app.plugin_manager.plugins["kernel_runtime"].runtime_helper
        request_gui_quit = helper.request_gui_quit

        def record_request_gui_quit():
            quit_requests.append("QUIT_REQUESTED")
            request_gui_quit()

        helper.request_gui_quit = record_request_gui_quit
        return quit_requests

    def test_startup_enters_no_project_state(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name("hyde-startup-test")
        app = HydeApp(self.qapp, process_tree, DummySplash(), argv=[])
        try:
            wait_until(lambda: app._startup_complete, timeout=60, message="Hyde did not finish startup.")
            self.assertIsNone(app.current_project_dir)
            self.assertTrue(app.plugin_service("kernel_runtime_service").is_ready())
            self.assertIsNotNone(app.plugin_service("kernel_runtime_service").kernel_client())
            self.assertFalse(
                app.plugin_service("visible_terminal_service").subwindow().isVisible()
            )
            self.assertFalse(
                app.mdi_context.subwindow("procedures").isVisible()
            )
            app.plugin_service("namespace_view_service").ensure_widget()
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
                lookup_menu_action(app, "window", "Python Terminal").isEnabled()
            )
            self.assertFalse(lookup_menu_action(app, "window", "Procedures").isEnabled())
            self.assertFalse(lookup_menu_action(app, "window", "Python Variables").isEnabled())
            self.assertFalse(lookup_menu_action(app, "window", "New Table...").isEnabled())
        finally:
            app.begin_shutdown_from_close_event()
            wait_until(
                lambda: app._close_ready,
                timeout=10,
                message="Hyde did not finish asynchronous shutdown.",
            )
            process_events(0.2)

    def test_file_quit_action_shuts_down_live_kernel_and_app(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name("hyde-file-quit-test")
        app = HydeApp(self.qapp, process_tree, DummySplash(), argv=[])
        try:
            wait_until(
                lambda: app._startup_complete
                and app.plugin_service("kernel_runtime_service").is_ready(),
                timeout=60,
                message="Hyde did not finish startup with a ready kernel.",
            )
            quit_requests = self._record_quit_requests(app)
            kernel_process = app.plugin_manager.plugins["kernel_runtime"].kernel_process
            original_terminate = kernel_process.terminate
            forced_terminations = []

            def record_terminate(*args, **kwargs):
                forced_terminations.append("terminate")
                return original_terminate(*args, **kwargs)

            kernel_process.terminate = record_terminate

            lookup_menu_action(app, "file", "Quit").trigger()

            wait_until(
                lambda: quit_requests and app._close_ready,
                timeout=10,
                message=(
                    "File -> Quit did not receive the live kernel quit message "
                    "and complete Hyde shutdown."
                ),
            )
            self.assertEqual(quit_requests, ["QUIT_REQUESTED"])
            self.assertEqual(forced_terminations, [])
            self.assertIsNotNone(kernel_process.poll())
            self.assertTrue(app.shutting_down)
            self.assertTrue(app._runtime_shutdown)
        finally:
            if not app._close_ready:
                app.begin_shutdown_from_close_event()
                wait_until(
                    lambda: app._close_ready,
                    timeout=10,
                    message="Hyde did not finish cleanup shutdown.",
            )
            process_events(0.2)

    def test_main_window_close_requests_kernel_quit_and_shuts_down_app(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name("hyde-window-close-test")
        app = HydeApp(self.qapp, process_tree, DummySplash(), argv=[])
        try:
            wait_until(
                lambda: app._startup_complete
                and app.plugin_service("kernel_runtime_service").is_ready(),
                timeout=60,
                message="Hyde did not finish startup with a ready kernel.",
            )
            quit_requests = self._record_quit_requests(app)

            app.ui.close()

            wait_until(
                lambda: quit_requests and app._close_ready,
                timeout=10,
                message=(
                    "Main-window close did not receive the live kernel quit "
                    "message and complete Hyde shutdown."
                ),
            )
            self.assertEqual(quit_requests, ["QUIT_REQUESTED"])
            self.assertTrue(app.shutting_down)
            self.assertTrue(app._runtime_shutdown)
        finally:
            if not app._close_ready:
                app.begin_shutdown_from_close_event()
                wait_until(
                    lambda: app._close_ready,
                    timeout=10,
                    message="Hyde did not finish cleanup shutdown.",
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

    def test_task_complete_publishes_process_tree_completion_message(self):
        with patch("hyde.execution.ipc.put_parent_message") as put_parent_message:
            hyde.task_complete("session_restore", success=False)

        put_parent_message.assert_called_once_with(
            [
                "TASK_COMPLETE",
                {"name": "session_restore", "success": False},
            ]
        )

    def test_save_project_excludes_live_matplotlib_figures_and_axes(self):
        project_dir = self._project(
            "save_figure_project.hy",
            (
                "import hyde\n"
                "import matplotlib\n"
                "matplotlib.use('module://hyde.matplotlib_backend')\n"
                "import matplotlib.pyplot as plt\n"
            ),
        )
        _, from_child, child, client = self._start_kernel("save-figure-project")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            self._collect_operation_messages(from_child, "load")

            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "arr = np.arange(4)\n"
                "fig = plt.figure('Figure0')\n"
                "ax = fig.add_subplot(111)\n"
                "ax.plot(arr, label='arr')\n"
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
            self.assertNotIn("fig", object_names)
            self.assertNotIn("ax", object_names)
            self.assertTrue(os.path.exists(os.path.join(project_dir, "data", "arr.npy")))
            self.assertFalse(os.path.exists(os.path.join(project_dir, "data", "fig.pkl")))
            self.assertFalse(os.path.exists(os.path.join(project_dir, "data", "ax.pkl")))
        finally:
            client.stop_channels()
            child.terminate()

    def test_load_project_does_not_restore_live_matplotlib_figures_and_axes(self):
        project_dir = self._project(
            "load_figure_project.hy",
            (
                "import hyde\n"
                "import matplotlib\n"
                "matplotlib.use('module://hyde.matplotlib_backend')\n"
                "import matplotlib.pyplot as plt\n"
            ),
        )
        _, from_child, child, client = self._start_kernel("load-figure-project-save")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            self._collect_operation_messages(from_child, "load")

            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "arr = np.arange(4)\n"
                "fig = plt.figure('Figure0')\n"
                "ax = fig.add_subplot(111)\n"
                "ax.plot(arr, label='arr')\n"
                "hyde.save_project()\n",
            )
            self._collect_operation_messages(from_child, "save")
        finally:
            client.stop_channels()
            child.terminate()

        _, from_child, child, client = self._start_kernel("load-figure-project-load")
        try:
            wait_for_code_ok(client, f"hyde.load_project({project_dir!r})")
            self._collect_operation_messages(from_child, "load")
            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "assert np.array_equal(arr, np.arange(4))\n"
                "assert 'fig' not in globals()\n"
                "assert 'ax' not in globals()\n"
                "from matplotlib._pylab_helpers import Gcf\n"
                "assert len(Gcf.get_all_fig_managers()) == 0\n",
            )
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


if __name__ == "__main__":
    unittest.main()
