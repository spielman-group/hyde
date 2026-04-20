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

from jupyter_client import BlockingKernelClient
from labscript_utils.ls_zprocess import ProcessTree
from qtutils.qt import QtWidgets, QtCore

import tomllib
from unittest.mock import patch

import hyde
from hyde.paths import KERNEL_LAUNCHER
from hyde.user_interface.main import HydeApp
from hyde.user_interface.project_state import (
    read_history,
    read_session,
    try_read_history,
    try_read_session,
    clear_tables,
    write_history,
    write_session,
)


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


class DummyCommandWindow:
    def __init__(self, history):
        self._history = list(history)

    def history_entries(self):
        return list(self._history)


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
    def __init__(self, handle, names, subwindow):
        self.handle = handle
        self.names = list(names)
        self._subwindow = subwindow
        self.shutdown_calls = 0

    def parentWidget(self):
        return self._subwindow

    def shutdown_client(self):
        self.shutdown_calls += 1


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
            write_history(DummyCommandWindow(["a = 1", "hyde.table(a)"]), project_dir)
            self.assertEqual(read_history(project_dir), ["a = 1", "hyde.table(a)"])

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

            app = type("DummyApp", (), {})()
            app.ui = main_window
            app.command_subwindow = command_subwindow
            app.logging_subwindow = logging_subwindow
            app.procedures_subwindow = procedures_subwindow
            app.data_browser_subwindow = data_browser_subwindow
            app.data_browser = data_browser
            app.tables = {"Table0": DummyTable("Table0", ["a", "b"], table_subwindow)}
            app.active_table_handle = "Table0"
            app.table_counter = 4

            write_session(app, project_dir)
            session = read_session(project_dir)

            self.assertEqual(session["active_table_handle"], "Table0")
            self.assertEqual(session["table_counter"], 4)
            self.assertFalse(session["data_browser"]["variables"])
            self.assertEqual(session["tables"][0]["handle"], "Table0")
            self.assertEqual(session["tables"][0]["names"], ["a", "b"])

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

            command_window = DummyCommandWindow(["a = 1", "hyde.save_project()"])
            write_history(command_window, project_dir)

            warnings = []

            class DummyApp:
                pass

            app = DummyApp()
            app.current_project_dir = project_dir
            app.command_window = type(
                "HistorySink",
                (),
                {"restore_history_entries": lambda self, entries: setattr(self, "entries", list(entries))},
            )()
            app.ui = QtWidgets.QMainWindow()
            app.tables = {}
            app.active_table_handle = None
            app.table_counter = 0

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
            self.assertEqual(app.command_window.entries, ["a = 1", "hyde.save_project()"])

    def test_resolve_startup_project_uses_cli_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "startup.hy")
            os.makedirs(project_dir)
            app = type("DummyApp", (), {"argv": [project_dir]})()
            self.assertEqual(HydeApp.resolve_startup_project(app), os.path.abspath(project_dir))

    def test_save_project_as_prompts_before_overwriting_non_empty_target(self):
        app = type("DummyApp", (), {})()
        app.current_project_dir = None
        app.command_window = object()

        with tempfile.TemporaryDirectory() as tmpdir:
            app.current_project_dir = os.path.join(tmpdir, "current.hy")
            os.makedirs(app.current_project_dir)
            target = os.path.join(tmpdir, "target.hy")
            os.makedirs(target)
            with open(os.path.join(target, "keep.txt"), "w", encoding="utf-8") as handle:
                handle.write("keep")

            prompted = []
            executed = []

            app.prompt_for_save_as_project = lambda: target
            app.project_target_needs_confirmation = lambda project_dir: HydeApp.project_target_needs_confirmation(
                app, project_dir
            )
            app.confirm_overwrite_project = lambda project_dir: prompted.append(project_dir) or False
            app.execute_command = lambda code, visible=True: executed.append((code, visible))

            HydeApp.save_project_as(app)

            self.assertEqual(prompted, [target])
            self.assertEqual(executed, [])

    def test_clear_tables_forces_close_without_macro_prompt_path(self):
        subwindow = type("Subwindow", (), {"close": lambda self: setattr(self, "closed", True)})()
        subwindow.closed = False
        table = DummyTable("Table0", ["a"], subwindow)
        app = type("DummyApp", (), {})()
        app.tables = {"Table0": table}
        app.active_table_handle = "Table0"
        app.table_counter = 1

        clear_tables(app)

        self.assertEqual(table.shutdown_calls, 1)
        self.assertTrue(subwindow.closed)
        self.assertEqual(app.tables, {})
        self.assertIsNone(app.active_table_handle)
        self.assertEqual(app.table_counter, 0)

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

    def test_startup_enters_no_project_state(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name("hyde-startup-test")
        app = HydeApp(self.qapp, process_tree, DummySplash(), argv=[])
        try:
            wait_until(lambda: app._startup_complete, timeout=30, message="Hyde did not finish startup.")
            self.assertIsNone(app.current_project_dir)
            self.assertIsNotNone(app.kernel_process)
            self.assertIsNone(app.kernel_process.poll())
            self.assertFalse(app.command_subwindow.isVisible())
            self.assertFalse(app.procedures_subwindow.isVisible())
            self.assertFalse(app.data_browser_subwindow.isVisible())
            self.assertTrue(app.ui.actionNew.isEnabled())
            self.assertTrue(app.ui.actionLoad.isEnabled())
            self.assertTrue(app.ui.actionLogging.isEnabled())
            self.assertTrue(app.ui.actionQuit.isEnabled())
            self.assertFalse(app.ui.actionSave.isEnabled())
            self.assertFalse(app.ui.actionSave_As.isEnabled())
            self.assertFalse(app.ui.actionSave_Copy.isEnabled())
            self.assertFalse(app.ui.actionCommandWindow.isEnabled())
            self.assertFalse(app.ui.actionProcedures.isEnabled())
            self.assertFalse(app.ui.actionDataBrowser.isEnabled())
            self.assertFalse(app.ui.actionNew_Table.isEnabled())
        finally:
            app.finalize_quit()
            wait_until(
                lambda: app.command_window is None and app.data_browser is None,
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

            wait_for_code_ok(
                client,
                "from hyde.features.hyde_features import format_procedures_bootstrap_code\n"
                "from hyde.paths import HYDE_DIR\n"
                f"exec(format_procedures_bootstrap_code({project_dir!r}, HYDE_DIR, reset_namespace=False))\n"
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
