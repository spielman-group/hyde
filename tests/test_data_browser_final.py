import os
import sys
import time
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jupyter_client import BlockingKernelClient
from labscript_utils.ls_zprocess import ProcessTree
from qtutils.qt import QtWidgets, QtCore

import hyde
from hyde.paths import CONNECTION_FILE
from hyde.user_interface.data_browser import DataBrowser


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


def current_names(browser):
    names = []
    for row in range(browser.proxy_model.rowCount()):
        index = browser.proxy_model.index(row, 0)
        names.append(browser.proxy_model.data(index))
    return names


def select_name(browser, name):
    for row in range(browser.proxy_model.rowCount()):
        index = browser.proxy_model.index(row, 0)
        if browser.proxy_model.data(index) == name:
            browser.ui.treeView.clearSelection()
            browser.ui.treeView.selectionModel().select(
                index,
                QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
            )
            browser.ui.treeView.setCurrentIndex(index)
            process_events()
            return
    raise AssertionError(f"Could not find row {name!r} in browser view: {current_names(browser)!r}")


class TestDataBrowserFinal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def setUp(self):
        self.process_tree = ProcessTree.instance()
        self.process_tree.zlock_client.set_process_name("hyde-data-browser-test")
        self.controller_path = os.path.abspath(
            os.path.join(os.path.dirname(hyde.__file__), "execution", "execution_controller.py")
        )

        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_dir = os.path.join(self.tmpdir.name, "browser_test.hy")
        self.procedures_dir = os.path.join(self.project_dir, "procedures")
        os.makedirs(self.procedures_dir)
        self.procedures_init = os.path.join(self.procedures_dir, "__init__.py")
        with open(self.procedures_init, "w") as f:
            f.write(
                "import numpy as np\n"
                "import pandas as pd\n"
                "arr = np.array([1, 2, 3])\n"
                "df = pd.DataFrame({'x': [1, 2]})\n"
                "val = 10\n"
                "s = 'hello'\n"
            )

        self.to_worker, self.from_worker, self.worker = self.process_tree.subprocess(
            self.controller_path,
            args=[CONNECTION_FILE],
        )
        self.to_worker.put(
            [
                "WATCH_PROJECT",
                {
                    "project_dir": self.project_dir,
                    "procedures_dir": self.procedures_dir,
                    "procedures_init": self.procedures_init,
                },
            ]
        )
        task, data = self.from_worker.get(timeout=15)
        self.assertEqual(task, "KERNEL_READY")
        self.assertEqual(data, CONNECTION_FILE)

        self.client = BlockingKernelClient(connection_file=CONNECTION_FILE)
        self.client.load_connection_file()
        self.client.start_channels()
        self.client.wait_for_ready(timeout=5)

        self.browser = DataBrowser(connection_file=CONNECTION_FILE)
        self.browser.show()
        process_events(0.2)
        wait_until(
            lambda: {"arr", "df", "val", "s"}.issubset(set(current_names(self.browser))),
            timeout=15,
            message="Initial namespace view did not populate.",
        )

    def tearDown(self):
        if hasattr(self, "browser") and self.browser is not None:
            self.browser.close()
            process_events(0.2)
        if hasattr(self, "client") and self.client is not None:
            self.client.stop_channels()
        if hasattr(self, "to_worker") and self.to_worker is not None:
            self.to_worker.put(["QUIT", None])
        if hasattr(self, "worker") and self.worker is not None:
            self.worker.wait(timeout=10)
        if hasattr(self, "tmpdir"):
            self.tmpdir.cleanup()

    def test_initial_namespace_population(self):
        self.assertTrue({"arr", "df", "val", "s"}.issubset(set(current_names(self.browser))))

    def test_namespace_updates_after_kernel_execution(self):
        wait_for_code_ok(self.client, "new_scalar = 99")
        wait_until(
            lambda: "new_scalar" in current_names(self.browser),
            timeout=10,
            message="Browser did not refresh after kernel execution.",
        )

    def test_namespace_updates_after_procedure_reload(self):
        with open(self.procedures_init, "w") as f:
            f.write(
                "import numpy as np\n"
                "import pandas as pd\n"
                "arr = np.array([4, 5, 6])\n"
                "df = pd.DataFrame({'x': [3, 4]})\n"
                "val = 42\n"
                "s = 'updated'\n"
                "reloaded_name = 7\n"
            )
        wait_until(
            lambda: "reloaded_name" in current_names(self.browser),
            timeout=15,
            message="Browser did not refresh after procedures reload.",
        )

    def test_unrelated_comm_traffic_is_ignored(self):
        before = sorted(current_names(self.browser))
        wait_for_code_ok(
            self.client,
            "from ipykernel.comm import Comm\n"
            "unrelated = Comm(target_name='unrelated_target')\n"
            "unrelated.send({'type': 'UNRELATED'})\n",
        )
        process_events(0.5)
        after = sorted(current_names(self.browser))
        self.assertEqual(before, after)

    def test_filter_behavior_and_info_toggle(self):
        self.assertTrue(self.browser.ui.infoPane.isVisible())

        self.browser.ui.variablesCheckBox.setChecked(False)
        self.browser.ui.stringsCheckBox.setChecked(False)
        process_events()
        self.assertEqual(sorted(current_names(self.browser)), ["arr", "df"])

        self.browser.ui.wavesCheckBox.setChecked(False)
        self.browser.ui.variablesCheckBox.setChecked(True)
        process_events()
        self.assertEqual(current_names(self.browser), ["val"])

        self.browser.ui.variablesCheckBox.setChecked(False)
        self.browser.ui.stringsCheckBox.setChecked(True)
        process_events()
        self.assertEqual(current_names(self.browser), ["s"])

        self.browser.ui.infoCheckBox.setChecked(False)
        process_events()
        self.assertFalse(self.browser.ui.infoPane.isVisible())

        self.browser.ui.infoCheckBox.setChecked(True)
        process_events()
        self.assertTrue(self.browser.ui.infoPane.isVisible())

    def test_selection_updates_info_pane(self):
        select_name(self.browser, "arr")
        wait_until(
            lambda: "name: arr" in self.browser.ui.infoText.toPlainText(),
            timeout=5,
            message="Selecting a row did not populate the info pane.",
        )

    def test_delete_action_removes_object_from_namespace_view(self):
        original_question = QtWidgets.QMessageBox.question
        QtWidgets.QMessageBox.question = lambda *args, **kwargs: QtWidgets.QMessageBox.Yes
        try:
            self.browser._selected_names = lambda: ["val"]
            self.browser._delete_selected()
            wait_until(
                lambda: "val" not in current_names(self.browser),
                timeout=10,
                message="Delete action did not remove the object from the browser view.",
            )
            wait_for_code_ok(self.client, "assert 'val' not in globals()")
        finally:
            QtWidgets.QMessageBox.question = original_question


if __name__ == "__main__":
    unittest.main()
