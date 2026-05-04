import os
import sys
import time
import tempfile
import unittest
from unittest.mock import Mock, patch

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

from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.plugins.data_browser import DataBrowser, Plugin


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


def select_names(browser, names):
    browser.ui.treeView.clearSelection()
    current_index = QtCore.QModelIndex()
    for index_position, name in enumerate(names):
        for row in range(browser.proxy_model.rowCount()):
            index = browser.proxy_model.index(row, 0)
            if browser.proxy_model.data(index) == name:
                browser.ui.treeView.selectionModel().select(
                    index,
                    (
                        QtCore.QItemSelectionModel.ClearAndSelect
                        if index_position == 0
                        else QtCore.QItemSelectionModel.Select
                    )
                    | QtCore.QItemSelectionModel.Rows,
                )
                current_index = index
                break
        else:
            raise AssertionError(
                f"Could not find row {name!r} in browser view: {current_names(browser)!r}"
            )
    if current_index.isValid():
        browser.ui.treeView.setCurrentIndex(current_index)
    process_events()


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
        bootstrap = RuntimeCommandState()
        bootstrap.set_reload_procedures(
            self.project_dir,
            os.path.dirname(HYDE_DIR),
            reset_namespace=True,
        )
        wait_for_code_ok(
            self.client,
            bootstrap.python_source(),
        )

        self.browser = DataBrowser(
            connection_file=self.connection_file,
            services={
                "execute_command": (
                    lambda code, visible=True: self.client.execute(
                        code,
                        silent=not visible,
                    )
                )
            },
        )
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
            self.browser.shutdown()
            self.browser.deleteLater()
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
        bootstrap = RuntimeCommandState()
        bootstrap.set_reload_procedures(
            self.project_dir,
            os.path.dirname(HYDE_DIR),
            reset_namespace=False,
        )
        wait_for_code_ok(
            self.client,
            bootstrap.python_source(),
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
            select_name(self.browser, "val")
            self.browser._delete_selected()
            wait_until(
                lambda: "val" not in current_names(self.browser),
                timeout=10,
                message="Delete action did not remove the object from the browser view.",
            )
            wait_for_code_ok(self.client, "assert 'val' not in globals()")
        finally:
            QtWidgets.QMessageBox.question = original_question


class TestDataBrowserSelectionRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def _make_browser(self, metadata_by_name):
        browser = DataBrowser.__new__(DataBrowser)
        QtWidgets.QWidget.__init__(browser)
        browser.services = {}
        browser._closed = False
        browser._last_view = dict(metadata_by_name)
        browser.ui = type("UI", (), {})()
        browser.ui.treeView = QtWidgets.QTreeView(browser)
        browser.ui.infoText = QtWidgets.QTextEdit(browser)
        browser.ui.infoPane = QtWidgets.QWidget(browser)
        browser.ui.wavesCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.variablesCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.stringsCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.infoCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.deleteButton = QtWidgets.QPushButton(browser)
        browser.ui.plotCheckBox = QtWidgets.QCheckBox(browser)
        browser.model = QtGui.QStandardItemModel(0, 3, browser)
        browser.proxy_model = QtCore.QSortFilterProxyModel(browser)
        browser.proxy_model.setSourceModel(browser.model)
        browser.ui.treeView.setModel(browser.proxy_model)
        browser.ui.treeView.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        browser.ui.treeView.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        for name, metadata in metadata_by_name.items():
            item = QtGui.QStandardItem(name)
            item.setData({"name": name, **metadata}, QtCore.Qt.UserRole)
            browser.model.appendRow([item, QtGui.QStandardItem(""), QtGui.QStandardItem("")])
        return browser

    def _force_selected_names(self, browser, names):
        indexes = []
        for name in names:
            for row in range(browser.proxy_model.rowCount()):
                index = browser.proxy_model.index(row, 0)
                if browser.proxy_model.data(index) == name:
                    indexes.append(index)
                    break
            else:
                raise AssertionError(
                    f"Could not find row {name!r} in browser view: {current_names(browser)!r}"
                )
        browser._candidate_selection_indexes = lambda: list(indexes)

    def test_table_dispatch_requires_entire_selection_to_be_eligible(self):
        table_feature = Mock()
        table_feature.has_active_table.return_value = True
        browser = self._make_browser(
            {
                "arr": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "f"},
                "val": {"python_type": "int"},
            }
        )
        browser.services["table_feature"] = table_feature

        self._force_selected_names(browser, ["arr", "val"])

        self.assertEqual(browser._selected_table_names(), [])
        browser._edit_selected()
        browser._append_to_table_selected()

        table_feature.show_new_table_dialog.assert_not_called()
        table_feature.append_to_active_table.assert_not_called()

    def test_context_menu_disables_table_actions_for_mixed_selection(self):
        table_feature = Mock()
        table_feature.has_active_table.return_value = True
        browser = self._make_browser(
            {
                "arr": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "f"},
                "val": {"python_type": "int"},
            }
        )
        browser.services["table_feature"] = table_feature
        self._force_selected_names(browser, ["arr", "val"])
        created_menus = []

        class FakeAction:
            def __init__(self, text):
                self.text = text
                self.enabled = True

            def setEnabled(self, value):
                self.enabled = bool(value)

        class FakeMenu:
            def __init__(self, parent=None):
                del parent
                self.actions = []
                created_menus.append(self)

            def addAction(self, text):
                action = FakeAction(text)
                self.actions.append(action)
                return action

            def addSeparator(self):
                return None

            def exec_(self, position):
                del position
                return None

        with patch("hyde.user_interface.plugins.data_browser.QtWidgets.QMenu", FakeMenu):
            browser._show_context_menu(QtCore.QPoint(0, 0))

        self.assertEqual(len(created_menus), 1)
        action_state = {
            action.text: action.enabled for action in created_menus[0].actions
        }
        self.assertFalse(action_state["Edit"])
        self.assertFalse(action_state["Append to Table"])

    def test_table_dispatch_uses_all_selected_eligible_names(self):
        table_feature = Mock()
        table_feature.has_active_table.return_value = True
        browser = self._make_browser(
            {
                "arr": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "f"},
                "arr2": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "i"},
            }
        )
        browser.services["table_feature"] = table_feature

        self._force_selected_names(browser, ["arr", "arr2"])

        self.assertEqual(browser._selected_table_names(), ["arr", "arr2"])
        browser._edit_selected()
        browser._append_to_table_selected()

        table_feature.show_new_table_dialog.assert_called_once_with(
            browser.namespace_view(),
            preselection=["arr", "arr2"],
            parent=browser,
        )
        table_feature.append_to_active_table.assert_called_once_with(["arr", "arr2"])

    def test_close_event_hides_persistent_window_without_shutdown(self):
        browser = DataBrowser.__new__(DataBrowser)
        QtWidgets.QWidget.__init__(browser)
        browser.services = {}
        browser._closed = False
        browser.shutdown = Mock()
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(browser)
        subwindow.show()
        process_events()

        event = QtGui.QCloseEvent()
        browser.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertFalse(subwindow.isVisible())
        browser.shutdown.assert_not_called()


class TestDataBrowserRefreshTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def _make_browser(self):
        browser = DataBrowser.__new__(DataBrowser)
        QtWidgets.QWidget.__init__(browser)
        browser.services = {}
        browser._closed = False
        browser._external_requests_in_flight = set()
        browser._refresh_in_flight = False
        browser._refresh_pending = False
        browser._last_view = {}
        browser._update_ui = Mock()
        browser.kernel_client = type(
            "KernelClient",
            (),
            {"session": type("Session", (), {"session": "browser-session"})()},
        )()
        callbacks = []

        class FakeSpyderComm:
            def request_namespace_view(self, callback):
                callbacks.append(callback)

        browser.spyder_comm = FakeSpyderComm()
        return browser, callbacks

    def _status_message(self, state, session, msg_id="msg-id"):
        return {
            "header": {"msg_type": "status"},
            "parent_header": {"session": session, "msg_id": msg_id},
            "content": {"execution_state": state},
        }

    def _deliver_next_view(self, callbacks, view):
        callback = callbacks.pop(0)
        callback(view)
        process_events()

    def test_browser_owned_status_messages_do_not_complete_refresh(self):
        browser, callbacks = self._make_browser()

        browser.refresh_namespace()
        browser._handle_iopub_message(self._status_message("busy", "browser-session"))
        browser._handle_iopub_message(self._status_message("idle", "browser-session"))

        self.assertTrue(browser._refresh_in_flight)
        self.assertFalse(browser._refresh_pending)
        self.assertFalse(browser._external_requests_in_flight)
        self.assertEqual(len(callbacks), 1)

        self._deliver_next_view(callbacks, {"stale": {"type": "int"}})

        self.assertFalse(browser._refresh_in_flight)
        self.assertEqual(browser.namespace_view(), {"stale": {"type": "int"}})
        self.assertEqual(callbacks, [])

    def test_external_idle_during_refresh_queues_fresh_follow_up_view(self):
        browser, callbacks = self._make_browser()

        browser.refresh_namespace()
        browser._handle_iopub_message(self._status_message("busy", "external-session"))
        browser._handle_iopub_message(self._status_message("idle", "external-session"))

        self.assertTrue(browser._refresh_in_flight)
        self.assertTrue(browser._refresh_pending)
        self.assertFalse(browser._external_requests_in_flight)
        self.assertEqual(len(callbacks), 1)

        self._deliver_next_view(callbacks, {"stale": {"type": "int"}})

        self.assertTrue(browser._refresh_in_flight)
        self.assertFalse(browser._refresh_pending)
        self.assertEqual(len(callbacks), 1)

        self._deliver_next_view(callbacks, {"fresh": {"type": "float"}})

        self.assertFalse(browser._refresh_in_flight)
        self.assertEqual(browser.namespace_view(), {"fresh": {"type": "float"}})
        self.assertEqual(callbacks, [])

    def test_external_activity_around_refresh_still_fetches_fresh_view(self):
        browser, callbacks = self._make_browser()

        browser._handle_iopub_message(self._status_message("busy", "external-session"))
        browser.refresh_namespace()
        self._deliver_next_view(callbacks, {"stale": {"type": "int"}})

        self.assertFalse(browser._refresh_in_flight)
        self.assertTrue(browser._external_requests_in_flight)
        self.assertEqual(browser.namespace_view(), {"stale": {"type": "int"}})

        browser._handle_iopub_message(self._status_message("idle", "external-session"))
        self.assertTrue(browser._refresh_in_flight)
        self.assertFalse(browser._external_requests_in_flight)
        self.assertEqual(len(callbacks), 1)

        self._deliver_next_view(callbacks, {"fresh": {"type": "float"}})

        self.assertFalse(browser._refresh_in_flight)
        self.assertEqual(browser.namespace_view(), {"fresh": {"type": "float"}})
        self.assertEqual(callbacks, [])

    def test_overlapping_external_sessions_refresh_only_after_last_idle(self):
        browser, callbacks = self._make_browser()

        browser.refresh_namespace()
        browser._handle_iopub_message(
            self._status_message("busy", "external-session", msg_id="a")
        )
        browser._handle_iopub_message(
            self._status_message("busy", "external-session", msg_id="b")
        )
        browser._handle_iopub_message(
            self._status_message("idle", "external-session", msg_id="a")
        )

        self.assertTrue(browser._external_requests_in_flight)
        self.assertFalse(browser._refresh_pending)
        self.assertEqual(len(callbacks), 1)

        browser._handle_iopub_message(
            self._status_message("idle", "external-session", msg_id="b")
        )

        self.assertFalse(browser._external_requests_in_flight)
        self.assertTrue(browser._refresh_pending)
        self.assertEqual(len(callbacks), 1)


class TestDataBrowserPluginSetup(unittest.TestCase):
    def test_plugin_uses_lookup_menu_action_service(self):
        action = QtWidgets.QAction("Data Browser")
        lookup_menu_action = Mock(return_value=action)
        ui = type("UI", (), {"menuWindow": QtWidgets.QMenu()})()
        plugin = Plugin(initial_settings={})

        plugin.plugin_setup_complete(
            {"services": {"ui": ui, "lookup_menu_action": lookup_menu_action}}
        )

        self.assertIs(plugin._action, action)


if __name__ == "__main__":
    unittest.main()
