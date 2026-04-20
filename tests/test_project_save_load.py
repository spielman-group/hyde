import os
import sys
import time
import unittest
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jupyter_client import BlockingKernelClient
from labscript_utils.ls_zprocess import ProcessTree
from qtutils.qt import QtWidgets

import tomllib

import hyde
from hyde.user_interface.project_state import (
    read_history,
    read_session,
    try_read_history,
    try_read_session,
    write_history,
    write_session,
)


def wait_for_code_ok(client, code, timeout=10):
    deadline = time.time() + timeout
    last_reply = None
    while time.time() < deadline:
        msg_id = client.execute(code)
        while time.time() < deadline:
            reply = client.get_shell_msg(timeout=5)
            if reply["parent_header"].get("msg_id") != msg_id:
                continue
            last_reply = reply
            if reply["content"]["status"] == "ok":
                return
            break
        time.sleep(0.1)
    raise AssertionError(f"Code did not succeed: {code!r}\nLast reply: {last_reply!r}")


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

    def parentWidget(self):
        return self._subwindow


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

            command_subwindow.setGeometry(1, 2, 300, 200)
            logging_subwindow.setGeometry(3, 4, 310, 210)
            procedures_subwindow.setGeometry(5, 6, 320, 220)
            data_browser_subwindow.setGeometry(7, 8, 330, 230)
            table_subwindow.setGeometry(9, 10, 340, 240)

            command_subwindow.show()
            logging_subwindow.hide()
            procedures_subwindow.show()
            data_browser_subwindow.show()
            table_subwindow.hide()

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
            self.assertFalse(session["tool_windows"]["logging"]["visible"])
            self.assertFalse(session["data_browser"]["variables"])
            self.assertEqual(session["tables"][0]["handle"], "Table0")
            self.assertEqual(session["tables"][0]["names"], ["a", "b"])

    def test_write_and_read_session_without_active_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "session_no_active.hy")
            os.makedirs(project_dir)

            main_window = QtWidgets.QMainWindow()
            mdi_area = QtWidgets.QMdiArea()
            main_window.setCentralWidget(mdi_area)
            main_window.show()

            command_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            logging_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            procedures_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())
            data_browser_subwindow = mdi_area.addSubWindow(QtWidgets.QWidget())

            data_browser = DummyDataBrowser()
            data_browser.ui.wavesCheckBox.setChecked(True)
            data_browser.ui.variablesCheckBox.setChecked(True)
            data_browser.ui.stringsCheckBox.setChecked(True)
            data_browser.ui.infoCheckBox.setChecked(True)

            app = type("DummyApp", (), {})()
            app.ui = main_window
            app.command_subwindow = command_subwindow
            app.logging_subwindow = logging_subwindow
            app.procedures_subwindow = procedures_subwindow
            app.data_browser_subwindow = data_browser_subwindow
            app.data_browser = data_browser
            app.tables = {}
            app.active_table_handle = None
            app.table_counter = 0

            write_session(app, project_dir)
            session = read_session(project_dir)

            self.assertNotIn("active_table_handle", session)
            self.assertEqual(session["table_counter"], 0)
            self.assertEqual(session["tables"], [])

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
            procedures_init = os.path.join(project_dir, "procedures", "__init__.py")
            self.assertTrue(os.path.exists(procedures_init))
            self.assertFalse(os.path.exists(os.path.join(project_dir, "procedures", "master.py")))
            self.assertFalse(os.path.exists(os.path.join(project_dir, "procedures", "__pycache__")))

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

            from hyde.user_interface.main import HydeApp

            self.assertEqual(HydeApp.resolve_startup_project(app), os.path.abspath(project_dir))


class TestProjectSaveLoadIntegration(unittest.TestCase):
    def setUp(self):
        self.process_tree = ProcessTree.instance()
        self.process_tree.zlock_client.set_process_name("hyde-save-load-test")
        self.controller_path = os.path.abspath(
            os.path.join(os.path.dirname(hyde.__file__), "execution", "execution_controller.py")
        )
        self.tmpdir = tempfile.TemporaryDirectory()
        self._connection_counter = 0

    def tearDown(self):
        self.tmpdir.cleanup()

    def _start_project(self, project_name, procedures_text, extra_procedure_files=None):
        project_dir = os.path.join(self.tmpdir.name, project_name)
        procedures_dir = os.path.join(project_dir, "procedures")
        os.makedirs(procedures_dir)
        procedures_init = os.path.join(procedures_dir, "__init__.py")
        self._connection_counter += 1
        connection_file = os.path.join(
            self.tmpdir.name,
            f"{project_name}.{self._connection_counter}.json",
        )
        with open(procedures_init, "w", encoding="utf-8") as handle:
            handle.write(procedures_text)
        for relative_path, contents in (extra_procedure_files or {}).items():
            file_path = os.path.join(procedures_dir, relative_path)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(contents)

        to_worker, from_worker, worker = self.process_tree.subprocess(
            self.controller_path,
            args=[connection_file],
        )
        to_worker.put([
            "WATCH_PROJECT",
            {
                "project_dir": project_dir,
                "procedures_dir": procedures_dir,
                "procedures_init": procedures_init,
            },
        ])

        saw_ready = False
        saw_reloaded = False
        client = None
        deadline = time.time() + 20
        while time.time() < deadline and not (saw_ready and saw_reloaded):
            task, data = from_worker.get(timeout=15)
            if task == "KERNEL_READY":
                saw_ready = True
                connection_path = Path(connection_file)
                wait_deadline = time.time() + 10
                while time.time() < wait_deadline and not connection_path.exists():
                    time.sleep(0.1)
                client = BlockingKernelClient(connection_file=connection_file)
                client.load_connection_file()
                client.start_channels()
                client.wait_for_ready(timeout=5)
            elif task == "PROCEDURES_RELOADED":
                saw_reloaded = True
        self.assertTrue(saw_ready)
        self.assertTrue(saw_reloaded)
        self.assertIsNotNone(client)
        return project_dir, to_worker, from_worker, worker, client

    def test_save_project_writes_manifest_and_excludes_packages(self):
        procedures = (
            "import hyde\n"
            "import numpy as np\n"
            "from numpy import random\n"
            "class Box:\n"
            "    def __init__(self, value):\n"
            "        self.value = value\n"
        )
        project_dir, to_worker, from_worker, worker, client = self._start_project(
            "save_project.hy",
            procedures,
        )
        try:
            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "arr = np.arange(4)\n"
                "boxed = Box(7)\n"
                "In = ['ignore-me']\n"
                "Out = {1: 'ignore-me-too'}\n"
                "import hyde; hyde.save_project()\n",
            )
            deadline = time.time() + 10
            result = None
            while time.time() < deadline and result is None:
                task, data = from_worker.get(timeout=10)
                if task == "PROJECT_STATE_RESULT" and data.get("operation") == "save":
                    result = data
            self.assertIsNotNone(result)
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
            to_worker.put(["QUIT", None])
            worker.wait(timeout=10)

    def test_load_project_restores_saved_objects_after_procedures(self):
        procedures_a = (
            "import hyde\n"
            "import numpy as np\n"
            "class Box:\n"
            "    def __init__(self, value):\n"
            "        self.value = value\n"
            "VALUE = 1\n"
        )
        project_dir, to_worker, from_worker, worker, client = self._start_project(
            "load_project.hy",
            procedures_a,
        )
        try:
            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "arr = np.arange(5)\n"
                "boxed = Box(9)\n"
                "VALUE = 22\n"
                "import hyde; hyde.save_project()\n",
            )
            deadline = time.time() + 10
            while time.time() < deadline:
                task, data = from_worker.get(timeout=10)
                if task == "PROJECT_STATE_RESULT" and data.get("operation") == "save":
                    break

            project_b_dir = os.path.join(self.tmpdir.name, "other_project.hy")
            procedures_b_dir = os.path.join(project_b_dir, "procedures")
            os.makedirs(procedures_b_dir)
            procedures_b_init = os.path.join(procedures_b_dir, "__init__.py")
            with open(procedures_b_init, "w", encoding="utf-8") as handle:
                handle.write("import hyde\nVALUE = 100\nOTHER = 5\n")

            to_worker.put([
                "WATCH_PROJECT",
                {
                    "project_dir": project_b_dir,
                    "procedures_dir": procedures_b_dir,
                    "procedures_init": procedures_b_init,
                },
            ])
            deadline = time.time() + 10
            saw_reloaded = False
            while time.time() < deadline and not saw_reloaded:
                task, data = from_worker.get(timeout=10)
                if task == "PROCEDURES_RELOADED":
                    saw_reloaded = True
            self.assertTrue(saw_reloaded)
            wait_for_code_ok(
                client,
                "assert VALUE == 100\n"
                "assert OTHER == 5\n"
                "assert 'arr' not in globals()\n"
                "assert 'boxed' not in globals()\n",
            )

            wait_for_code_ok(client, f"import hyde; hyde.load_project({project_dir!r})")

            deadline = time.time() + 10
            load_request = None
            while time.time() < deadline and load_request is None:
                task, data = from_worker.get(timeout=10)
                if task == "PROJECT_LOAD_REQUEST":
                    load_request = data
            self.assertIsNotNone(load_request)
            self.assertEqual(os.path.realpath(load_request["path"]), os.path.realpath(project_dir))

            deadline = time.time() + 10
            result = None
            while time.time() < deadline and result is None:
                task, data = from_worker.get(timeout=10)
                if task == "PROJECT_STATE_RESULT" and data.get("operation") == "load":
                    result = data
            self.assertIsNotNone(result)
            self.assertTrue(result["success"])

            wait_for_code_ok(
                client,
                "import numpy as np\n"
                "assert np.array_equal(arr, np.arange(5))\n"
                "assert boxed.value == 9\n"
                "assert VALUE == 22\n",
            )

            with open(
                os.path.join(project_dir, "procedures", "__init__.py"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "import hyde\n"
                    "import numpy as np\n"
                    "class Box:\n"
                    "    def __init__(self, value):\n"
                    "        self.value = value\n"
                    "VALUE = 33\n"
                )

            deadline = time.time() + 10
            saw_reloaded = False
            while time.time() < deadline and not saw_reloaded:
                task, data = from_worker.get(timeout=10)
                if task == "PROCEDURES_RELOADED":
                    saw_reloaded = True
            self.assertTrue(saw_reloaded)
            wait_for_code_ok(client, "assert VALUE == 33")
        finally:
            client.stop_channels()
            to_worker.put(["QUIT", None])
            worker.wait(timeout=10)

    def test_save_project_as_switches_active_project_directory(self):
        project_dir, to_worker, from_worker, worker, client = self._start_project(
            "save_as_source.hy",
            "import hyde\nVALUE = 1\n",
        )
        target_dir = os.path.join(self.tmpdir.name, "save_as_target.hy")
        try:
            wait_for_code_ok(
                client,
                f"VALUE = 7\nimport hyde; hyde.save_project({target_dir!r}, mode='save_as', overwrite=True)\n",
            )

            deadline = time.time() + 10
            load_request = None
            save_result = None
            while time.time() < deadline and (load_request is None or save_result is None):
                task, data = from_worker.get(timeout=10)
                if task == "PROJECT_LOAD_REQUEST":
                    load_request = data
                elif task == "PROJECT_STATE_RESULT" and data.get("operation") == "save":
                    save_result = data

            self.assertIsNotNone(load_request)
            self.assertEqual(os.path.realpath(load_request["path"]), os.path.realpath(target_dir))
            self.assertIsNotNone(save_result)
            self.assertTrue(save_result["success"])
            self.assertEqual(save_result["mode"], "save_as")

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
            to_worker.put(["QUIT", None])
            worker.wait(timeout=10)

    def test_save_project_copy_preserves_procedures_tree(self):
        procedures = (
            "import hyde\n"
            "import helper_module\n"
            "VALUE = helper_module.VALUE\n"
        )
        project_dir, to_worker, from_worker, worker, client = self._start_project(
            "source_project.hy",
            procedures,
            extra_procedure_files={"helper_module.py": "VALUE = 17\n"},
        )
        target_dir = os.path.join(self.tmpdir.name, "copied_project.hy")
        try:
            wait_for_code_ok(
                client,
                "import os\n"
                f"os.chdir({project_dir!r})\n"
                f"import hyde; hyde.save_project({target_dir!r}, mode='copy', overwrite=True)\n",
            )
            deadline = time.time() + 10
            result = None
            while time.time() < deadline and result is None:
                task, data = from_worker.get(timeout=10)
                if task == "PROJECT_STATE_RESULT" and data.get("operation") == "save":
                    result = data
            self.assertIsNotNone(result)
            self.assertTrue(result["success"])
            self.assertTrue(os.path.exists(os.path.join(target_dir, "procedures", "__init__.py")))
            self.assertTrue(os.path.exists(os.path.join(target_dir, "procedures", "helper_module.py")))
        finally:
            client.stop_channels()
            to_worker.put(["QUIT", None])
            worker.wait(timeout=10)

    def test_switching_projects_clears_stale_kernel_objects(self):
        project_a_dir, to_worker, from_worker, worker, client = self._start_project(
            "project_a.hy",
            "import hyde\nVALUE_A = 1\n",
        )
        try:
            wait_for_code_ok(client, "stale_value = 123\nVALUE_A = 9\n")

            project_b_dir = os.path.join(self.tmpdir.name, "project_b.hy")
            procedures_dir = os.path.join(project_b_dir, "procedures")
            os.makedirs(procedures_dir)
            procedures_init = os.path.join(procedures_dir, "__init__.py")
            with open(procedures_init, "w", encoding="utf-8") as handle:
                handle.write("import hyde\nVALUE_B = 2\n")

            to_worker.put([
                "WATCH_PROJECT",
                {
                    "project_dir": project_b_dir,
                    "procedures_dir": procedures_dir,
                    "procedures_init": procedures_init,
                },
            ])

            deadline = time.time() + 10
            saw_reloaded = False
            while time.time() < deadline and not saw_reloaded:
                task, data = from_worker.get(timeout=10)
                if task == "PROCEDURES_RELOADED":
                    saw_reloaded = True
            self.assertTrue(saw_reloaded)

            wait_for_code_ok(
                client,
                "assert VALUE_B == 2\n"
                "assert 'stale_value' not in globals()\n"
                "assert 'VALUE_A' not in globals()\n",
            )
        finally:
            client.stop_channels()
            to_worker.put(["QUIT", None])
            worker.wait(timeout=10)

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

            def prompt_for_save_as_project():
                return target

            def confirm_overwrite_project(project_dir):
                prompted.append(project_dir)
                return False

            def execute_command(code, visible=True):
                executed.append((code, visible))

            app.prompt_for_save_as_project = prompt_for_save_as_project
            app.confirm_overwrite_project = confirm_overwrite_project
            app.execute_command = execute_command
            app.load_project = lambda *args, **kwargs: None

            from hyde.user_interface.main import HydeApp

            HydeApp.save_project_as(app)

            self.assertEqual(prompted, [target])
            self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
