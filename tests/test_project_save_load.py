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

import hyde
import hyde.project_tools
from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.main import HydeApp
from hyde.user_interface.main.project_state import (
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


class DummyPythonTerminalService:
    def __init__(self, history=None):
        self._history = list(history or [])
        self.restored_entries = None

    def history_entries(self):
        return list(self._history)

    def restore_history_entries(self, entries):
        self.restored_entries = list(entries)


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

    def test_write_session_merges_plugin_toml_and_python_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "session_routes.hy")
            os.makedirs(project_dir)

            main_window = QtWidgets.QMainWindow()

            class SavingPlugin:
                def get_session_toml_data(self):
                    return {
                        "tool_windows": {"logging": {"visible": True}},
                        "table_counter": 4,
                    }

                def get_session_restore_source(self):
                    return (
                        "@hyde.table(register=False)\n"
                        "def Table0(a, b):\n"
                        "    hyde.table(a, b, title='Table_Fun', geometry=(5, 42, 510, 242), "
                        "column_widths={'a': 120, 'b': 260})\n\n"
                        "Table0(a, b)\n"
                    )

            source_app = type("SourceApp", (), {})()
            source_app.ui = main_window
            source_app.plugin_manager = PluginManagerStub({"session": SavingPlugin()})

            write_session(source_app, project_dir)

            session = tomllib.loads((Path(project_dir) / "session.toml").read_text())
            session_source = (Path(project_dir) / "session.py").read_text()

            self.assertTrue(session["tool_windows"]["logging"]["visible"])
            self.assertEqual(session["table_counter"], 4)
            self.assertIn("@hyde.table(register=False)", session_source)
            self.assertIn("Table0(a, b)", session_source)
            self.assertIn("geometry=(5, 42, 510, 242)", session_source)
            self.assertIn("column_widths={'a': 120, 'b': 260}", session_source)

    def test_restore_project_session_runs_session_python_after_project_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "session_restore.hy"
            project_dir.mkdir()
            (project_dir / "session.toml").write_text("format_version = 1\n", encoding="utf-8")
            (project_dir / "session.py").write_text("print('restore from session.py')\n", encoding="utf-8")
            terminal_dir = project_dir / "terminal"
            terminal_dir.mkdir()
            (terminal_dir / "history.py").write_text("history = []\n", encoding="utf-8")

            events = []

            class RestoringPlugin:
                def get_event_handlers(self):
                    return {"project_loaded": self.on_project_loaded}

                def on_project_loaded(self, data):
                    del data
                    events.append("project_loaded")

            restored_app = type("RestoredApp", (), {})()
            restored_app.ui = QtWidgets.QMainWindow()
            restored_app.current_project_dir = str(project_dir)
            restored_app.plugin_manager = PluginManagerStub({"session": RestoringPlugin()})
            restored_app.plugin_service = lambda key: (
                DummyPythonTerminalService() if key == "visible_terminal_service" else None
            )
            restored_app.queue_background_command = (
                lambda code, silent=True: events.append(("session_source", code, silent)) or True
            )
            restored_app.emit_plugin_event = (
                lambda name, data=None: HydeApp.emit_plugin_event(restored_app, name, data)
            )

            HydeApp.restore_project_session(restored_app)

            self.assertEqual(events[0], "project_loaded")
            self.assertEqual(events[1][0], "session_source")
            self.assertIn("restore from session.py", events[1][1])
            self.assertTrue(events[1][2])

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

class TestHydeStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

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
                app.plugin_service("visible_terminal_service").subwindow().isVisible()
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
                lookup_menu_action(app, "window", "Python Terminal").isEnabled()
            )
            self.assertFalse(lookup_menu_action(app, "window", "Procedures").isEnabled())
            self.assertFalse(lookup_menu_action(app, "window", "Python Variables").isEnabled())
            self.assertFalse(lookup_menu_action(app, "window", "New Table...").isEnabled())
        finally:
            app.finalize_quit()
            wait_until(
                lambda: (
                    app.plugin_service("visible_terminal_service").widget() is None
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

    def test_save_project_persists_live_matplotlib_figures_and_axes(self):
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
            self.assertIn("fig", object_names)
            self.assertIn("ax", object_names)
            self.assertTrue(os.path.exists(os.path.join(project_dir, "data", "fig.pkl")))
            self.assertTrue(os.path.exists(os.path.join(project_dir, "data", "ax.pkl")))
        finally:
            client.stop_channels()
            child.terminate()

    def test_load_project_restores_pickled_matplotlib_figures_and_axes(self):
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
                "assert 'fig' in globals()\n"
                "assert 'ax' in globals()\n"
                "assert len(fig.axes) == 1\n"
                "assert ax.figure is not None\n"
                "assert fig.canvas.__class__.__name__ == 'FigureCanvasAgg'\n"
                "from matplotlib._pylab_helpers import Gcf\n"
                "assert len(Gcf.get_all_fig_managers()) == 0\n"
                "assert len(fig.axes[0].lines) == 1\n"
                "assert len(ax.lines) == 1\n",
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
