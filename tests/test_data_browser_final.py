import os
import sys
import time
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="hyde-mpl-"))
os.environ.setdefault("IPYTHONDIR", tempfile.mkdtemp(prefix="hyde-ipython-"))

from jupyter_client import BlockingKernelClient
from labscript_utils.ls_zprocess import ProcessTree
from qtutils.qt import QtWidgets, QtCore

from hyde.features.hyde_features import format_procedures_bootstrap_code
from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
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


def start_kernel(process_tree, connection_file, process_name):
    process_tree.zlock_client.set_process_name(process_name)
    _, _, child = process_tree.subprocess(
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
    return child, client


class TestDataBrowserFinal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def setUp(self):
        self.process_tree = ProcessTree.instance()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_dir = os.path.join(self.tmpdir.name, "browser_test.hy")
        self.procedures_dir = os.path.join(self.project_dir, "procedures")
        os.makedirs(self.procedures_dir)
        self.procedures_init = os.path.join(self.procedures_dir, "__init__.py")
        with open(self.procedures_init, "w", encoding="utf-8") as f:
            f.write(
                "import numpy as np\n"
                "import pandas as pd\n"
                "arr = np.array([1, 2, 3])\n"
                "df = pd.DataFrame({'x': [1, 2]})\n"
                "val = 10\n"
                "s = 'hello'\n"
            )

        self.connection_file = os.path.join(self.tmpdir.name, "kernel-hyde.json")
        self.kernel_process, self.client = start_kernel(
            self.process_tree,
            self.connection_file,
            "hyde-data-browser-test",
        )
        wait_for_code_ok(
            self.client,
            format_procedures_bootstrap_code(
                self.project_dir,
                os.path.dirname(HYDE_DIR),
                reset_namespace=True,
            ),
        )

        self.browser = DataBrowser(connection_file=self.connection_file)
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
        if hasattr(self, "kernel_process") and self.kernel_process is not None and self.kernel_process.poll() is None:
            self.kernel_process.terminate()
            self.kernel_process.wait(timeout=10)
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

    def test_namespace_updates_after_procedures_bootstrap_rerun(self):
        with open(self.procedures_init, "w", encoding="utf-8") as f:
            f.write(
                "import numpy as np\n"
                "import pandas as pd\n"
                "arr = np.array([4, 5, 6])\n"
                "df = pd.DataFrame({'x': [3, 4]})\n"
                "val = 42\n"
                "s = 'updated'\n"
                "reloaded_name = 7\n"
            )
        wait_for_code_ok(
            self.client,
            format_procedures_bootstrap_code(
                self.project_dir,
                os.path.dirname(HYDE_DIR),
                reset_namespace=False,
            ),
        )
        wait_until(
            lambda: "reloaded_name" in current_names(self.browser),
            timeout=15,
            message="Browser did not refresh after procedures bootstrap rerun.",
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
