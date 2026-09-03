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
from qtconsole.client import QtKernelClient
from qtutils.qt import QtWidgets, QtCore, QtGui

from hyde.paths import HYDE_DIR, KERNEL_LAUNCHER
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.main import HydeApp
from hyde.user_interface.shared.plugin import HydeMDIContext
from hyde.user_interface.plugins.python_variables_tool import (
    Plugin as PythonVariablesPlugin,
    PythonVariables,
    PythonVariablesService,
)


class RecordingTableFeature:
    def __init__(self, *, has_active_table):
        self._has_active_table = bool(has_active_table)
        self.new_table_calls = []
        self.append_calls = []

    def has_active_table(self):
        return self._has_active_table

    def show_new_table_dialog(self, namespace_view, *, preselection=None, parent=None):
        self.new_table_calls.append(
            {
                "namespace_view": namespace_view,
                "preselection": list(preselection or []),
                "parent": parent,
            }
        )

    def append_to_active_table(self, names):
        self.append_calls.append(list(names))


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


class TestPythonVariablesFinal(unittest.TestCase):
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
            "hyde-python-variables-test",
        )
        self.shared_client = QtKernelClient(connection_file=self.connection_file)
        self.shared_client.load_connection_file()
        self.shared_client.start_channels()
        bootstrap = HydeAppIR(current_project_dir=self.project_dir)
        reload_ir = bootstrap.with_reload_procedures(
            self.project_dir,
            os.path.dirname(HYDE_DIR),
            reset_namespace=True,
        )
        wait_for_code_ok(
            self.client,
            bootstrap.current_diff(reload_ir).python_source(),
        )

        self.browser = PythonVariables(
            services={
                "python_execution_service": type(
                    "ExecutionService",
                    (),
                    {"execute_hidden": lambda _self, code, silent=True: self.client.execute(
                        code,
                        silent=silent,
                    )},
                )(),
                "kernel_runtime_service": type(
                    "KernelRuntimeService",
                    (),
                    {"kernel_client": lambda _self: self.shared_client},
                )(),
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
        if hasattr(self, "shared_client") and self.shared_client is not None:
            self.shared_client.stop_channels()
        if hasattr(self, "kernel_process") and self.kernel_process is not None and self.kernel_process.poll() is None:
            self.kernel_process.terminate()
            self.kernel_process.wait(timeout=10)
        if hasattr(self, "tmpdir"):
            self.tmpdir.cleanup()

    def test_namespace_updates_after_kernel_execution(self):
        wait_for_code_ok(self.client, "new_scalar = 99")
        wait_until(
            lambda: "new_scalar" in current_names(self.browser),
            timeout=10,
            message="Browser did not refresh after kernel execution.",
        )

    def test_filter_behavior_and_info_toggle(self):
        self.assertIsNone(self.browser.widget_ir)
        self.assertTrue(self.browser.ui.infoPane.isVisible())

        self.browser.ui.variablesCheckBox.setChecked(False)
        self.browser.ui.stringsCheckBox.setChecked(False)
        process_events()
        self.assertFalse(self.browser.ui.variablesCheckBox.isChecked())
        self.assertFalse(self.browser.ui.stringsCheckBox.isChecked())
        self.assertEqual(sorted(current_names(self.browser)), ["arr", "df"])

        self.browser.ui.arraysCheckBox.setChecked(False)
        self.browser.ui.variablesCheckBox.setChecked(True)
        process_events()
        self.assertFalse(self.browser.ui.arraysCheckBox.isChecked())
        self.assertTrue(self.browser.ui.variablesCheckBox.isChecked())
        self.assertEqual(current_names(self.browser), ["val"])

        self.browser.ui.variablesCheckBox.setChecked(False)
        self.browser.ui.stringsCheckBox.setChecked(True)
        process_events()
        self.assertFalse(self.browser.ui.variablesCheckBox.isChecked())
        self.assertTrue(self.browser.ui.stringsCheckBox.isChecked())
        self.assertEqual(current_names(self.browser), ["s"])

        self.browser.ui.infoCheckBox.setChecked(False)
        process_events()
        self.assertFalse(self.browser.ui.infoCheckBox.isChecked())
        self.assertFalse(self.browser.ui.infoPane.isVisible())

        self.browser.ui.infoCheckBox.setChecked(True)
        process_events()
        self.assertTrue(self.browser.ui.infoCheckBox.isChecked())
        self.assertTrue(self.browser.ui.infoPane.isVisible())

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


class TestPythonVariablesSelectionRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def _make_browser(self, metadata_by_name):
        browser = PythonVariables.__new__(PythonVariables)
        QtWidgets.QWidget.__init__(browser)
        browser.services = {}
        browser._shutdown_requested = False
        browser._last_view = dict(metadata_by_name)
        browser.ui = type("UI", (), {})()
        browser.ui.treeView = QtWidgets.QTreeView(browser)
        browser.ui.infoText = QtWidgets.QTextEdit(browser)
        browser.ui.infoPane = QtWidgets.QWidget(browser)
        browser.ui.arraysCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.variablesCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.stringsCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.infoCheckBox = QtWidgets.QCheckBox(browser)
        browser.ui.arraysCheckBox.setChecked(True)
        browser.ui.variablesCheckBox.setChecked(True)
        browser.ui.stringsCheckBox.setChecked(True)
        browser.ui.infoCheckBox.setChecked(True)
        browser.ui.deleteButton = QtWidgets.QPushButton(browser)
        browser.ui.plotCheckBox = QtWidgets.QCheckBox(browser)
        browser.widget_ir = None
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
        table_feature = RecordingTableFeature(has_active_table=True)
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

        self.assertEqual(table_feature.new_table_calls, [])
        self.assertEqual(table_feature.append_calls, [])

    def test_table_actions_forward_all_selected_eligible_names(self):
        table_feature = RecordingTableFeature(has_active_table=True)
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

        self.assertEqual(
            table_feature.new_table_calls,
            [
                {
                    "namespace_view": browser.namespace_view(),
                    "preselection": ["arr", "arr2"],
                    "parent": browser,
                }
            ],
        )
        self.assertEqual(table_feature.append_calls, [["arr", "arr2"]])

    def test_delete_selected_dispatches_transient_hyde_app_ir_delete_python_source(self):
        executed = []
        browser = self._make_browser(
            {
                "arr": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "f"},
                "arr2": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "i"},
            }
        )
        browser.services["python_execution_service"] = type(
            "ExecutionService",
            (),
            {"execute_hidden": lambda _self, code, silent=True: executed.append((code, silent))},
        )()
        self._force_selected_names(browser, ["arr", "arr2"])

        original_question = QtWidgets.QMessageBox.question
        QtWidgets.QMessageBox.question = lambda *args, **kwargs: QtWidgets.QMessageBox.Yes
        try:
            browser._delete_selected()
        finally:
            QtWidgets.QMessageBox.question = original_question

        expected_payload = HydeAppIR().with_delete_names(["arr", "arr2"]).python_source(
            log=False
        )
        self.assertEqual(
            executed,
            [(expected_payload, True)],
        )
        self.assertEqual(
            browser.get_session_toml_data(),
            {
                "arrays": True,
                "variables": True,
                "strings": True,
                "info": True,
            },
        )
        self.assertFalse(hasattr(browser, "app_ir"))
        self.assertIsNone(browser.widget_ir)


class TestHydeAppIRDeleteCommands(unittest.TestCase):
    def test_hyde_app_ir_lowers_delete_namespace_names(self):
        app_ir = HydeAppIR(current_project_dir="/tmp/demo.hy").with_delete_names(
            ["arr", "arr2"]
        )

        self.assertEqual(app_ir.python_source(log=False), "del arr, arr2")

    def test_hyde_app_ir_rejects_invalid_delete_namespace_names(self):
        with self.assertRaisesRegex(ValueError, "Invalid Python variable name"):
            HydeAppIR().with_delete_names(["arr", "for"]).python_source(log=False)

class TestPythonVariablesRefreshTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def _make_browser(self):
        browser = PythonVariables.__new__(PythonVariables)
        QtWidgets.QWidget.__init__(browser)
        browser.services = {}
        browser._shutdown_requested = False
        browser._execute_requests_in_flight = set()
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
            def is_connected(self):
                return True

            def request_namespace_view(self, callback):
                callbacks.append(callback)
                return True

        browser.spyder_comm = FakeSpyderComm()
        return browser, callbacks

    def _status_message(self, state, session, msg_id="msg-id", parent_msg_type="execute_request"):
        return {
            "header": {"msg_type": "status"},
            "parent_header": {
                "session": session,
                "msg_id": msg_id,
                "msg_type": parent_msg_type,
            },
            "content": {"execution_state": state},
        }

    def _deliver_next_view(self, callbacks, view):
        callback = callbacks.pop(0)
        callback(view)
        process_events()

    def test_overlapping_execute_requests_refresh_only_after_last_idle(self):
        browser, callbacks = self._make_browser()

        browser.refresh_namespace()
        browser._handle_iopub_message(
            self._status_message("busy", "browser-session", msg_id="a")
        )
        browser._handle_iopub_message(
            self._status_message("busy", "browser-session", msg_id="b")
        )
        browser._handle_iopub_message(
            self._status_message("idle", "browser-session", msg_id="a")
        )

        self.assertEqual(len(callbacks), 1)

        browser._handle_iopub_message(
            self._status_message("idle", "browser-session", msg_id="b")
        )

        self.assertEqual(len(callbacks), 1)

        self._deliver_next_view(callbacks, {})

        self.assertEqual(len(callbacks), 1)

    def test_comm_status_messages_do_not_trigger_refresh_tracking(self):
        browser, callbacks = self._make_browser()

        browser.refresh_namespace()
        browser._handle_iopub_message(
            self._status_message(
                "busy",
                "browser-session",
                msg_id="comm-1",
                parent_msg_type="comm_msg",
            )
        )
        browser._handle_iopub_message(
            self._status_message(
                "idle",
                "browser-session",
                msg_id="comm-1",
                parent_msg_type="comm_msg",
            )
        )

        self.assertEqual(len(callbacks), 1)

        self._deliver_next_view(callbacks, {})

        self.assertEqual(len(callbacks), 0)


class RecordingStatusMessageService:
    """The shape of `hyde.user_interface.main.StatusMessageService`."""

    def __init__(self):
        self.transient_messages = []

    def show_status_message(self, label):
        del label

    def show_transient_message(self, label):
        self.transient_messages.append(label)

    def clear_status_message(self, label):
        del label
        return None


class FakeJupyterComm:
    """A comm of the shape `CommBase._register_comm` drives."""

    def __init__(self, comm_id):
        self.comm_id = comm_id
        self.sent = []
        self.closed = False

    def on_msg(self, callback):
        self._msg_callback = callback

    def on_close(self, callback):
        self._close_callback = callback

    def send(self, data, buffers=None):
        del buffers
        self.sent.append(data)

    def close(self):
        self.closed = True


class FakeCommManager:
    def __init__(self):
        self.comms = []

    def new_comm(self, name):
        del name
        comm = FakeJupyterComm(f"comm-{len(self.comms)}")
        self.comms.append(comm)
        return comm


class TestPythonVariablesRefreshRecovery(unittest.TestCase):
    """A refresh whose answer never comes must not stall the tool forever.

    These drive the real `SpyderFrontendComm` over a fake Jupyter comm, so a
    lost callback is lost the way spyder-kernels loses one -- it pops the
    waiting callback off its reply waitlist and routes the failure elsewhere --
    rather than the way this file might imagine it.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def _make_browser(self, *, connect=True):
        from hyde.user_interface.plugins.python_variables_tool import (
            NamespaceFilterProxyModel,
            SpyderFrontendComm,
        )

        comm_manager = FakeCommManager()
        kernel_client = type(
            "KernelClient",
            (),
            {
                "comm_manager": comm_manager,
                "session": type("Session", (), {"session": "browser-session"})(),
            },
        )()

        browser = PythonVariables.__new__(PythonVariables)
        QtWidgets.QWidget.__init__(browser)
        self.status_service = RecordingStatusMessageService()
        browser.services = {"status_message_service": self.status_service}
        browser._shutdown_requested = False
        browser._execute_requests_in_flight = set()
        browser._refresh_in_flight = False
        browser._refresh_pending = False
        browser._last_view = {}
        browser.widget_ir = None
        browser.kernel_client = kernel_client
        browser.spyder_comm = SpyderFrontendComm(
            kernel_client,
            browser._on_comm_call_failed,
        )
        browser.ui = type("UI", (), {})()
        browser.ui.infoPane = QtWidgets.QWidget(browser)
        for box_name in (
            "arraysCheckBox",
            "variablesCheckBox",
            "stringsCheckBox",
            "infoCheckBox",
        ):
            box = QtWidgets.QCheckBox(browser)
            box.setChecked(True)
            setattr(browser.ui, box_name, box)
        browser.model = QtGui.QStandardItemModel(0, 3, browser)
        browser.proxy_model = NamespaceFilterProxyModel(browser)
        browser.proxy_model.setSourceModel(browser.model)
        browser.ui.treeView = QtWidgets.QTreeView(browser)
        browser.ui.treeView.setModel(browser.proxy_model)
        self.addCleanup(browser.deleteLater)
        if connect:
            browser.spyder_comm.open()
        return browser, comm_manager

    @staticmethod
    def _pending_call_ids(comm_manager):
        return [
            message["content"]["call_id"]
            for comm in comm_manager.comms
            for message in comm.sent
            if message["spyder_msg_type"] == "remote_call"
            and message["content"]["call_name"] == "get_namespace_view"
        ]

    @staticmethod
    def _answer(browser, comm_manager, call_id, *, view=None, error=None):
        """Reply to a comm call the way the kernel replies to one."""
        comm = comm_manager.comms[-1]
        content = {
            "call_id": call_id,
            "call_name": "get_namespace_view",
            "is_error": error is not None,
            "call_return_value": (
                {
                    "call_name": "get_namespace_view",
                    "call_id": call_id,
                    "etype": "RuntimeError",
                    "args": [error],
                    "error_name": None,
                    "tb": [],
                }
                if error is not None
                else view
            ),
        }
        browser.spyder_comm._comm_message(
            {
                "content": {
                    "comm_id": comm.comm_id,
                    "data": {
                        "spyder_msg_type": "remote_call_reply",
                        "content": content,
                    },
                },
                "buffers": [],
            }
        )
        process_events()

    @staticmethod
    def _scalar_view(value):
        return {"val": {"type": "int", "python_type": "int", "view": str(value)}}

    @staticmethod
    def _shown_values(browser):
        return {
            browser.proxy_model.data(browser.proxy_model.index(row, 0)): (
                browser.proxy_model.data(browser.proxy_model.index(row, 2))
            )
            for row in range(browser.proxy_model.rowCount())
        }

    def test_refresh_recovers_after_the_kernel_loses_a_callback(self):
        browser, comm_manager = self._make_browser()

        browser.refresh_namespace()
        self._answer(
            browser,
            comm_manager,
            self._pending_call_ids(comm_manager)[-1],
            view=self._scalar_view(10),
        )
        self.assertEqual(self._shown_values(browser), {"val": "10"})

        browser.refresh_namespace()
        lost_call_id = self._pending_call_ids(comm_manager)[-1]
        self._answer(
            browser,
            comm_manager,
            lost_call_id,
            error="get_namespace_view blew up in the kernel",
        )
        self.assertEqual(self._shown_values(browser), {"val": "10"})

        browser.refresh_namespace()
        process_events()
        retry_call_ids = self._pending_call_ids(comm_manager)
        self.assertNotIn(
            lost_call_id,
            retry_call_ids[2:],
            "the tool never asked again after a lost callback",
        )
        self.assertEqual(len(retry_call_ids), 3)

        self._answer(
            browser,
            comm_manager,
            retry_call_ids[-1],
            view=self._scalar_view(11),
        )
        self.assertEqual(self._shown_values(browser), {"val": "11"})

    def test_a_lost_callback_says_why_the_refresh_failed(self):
        browser, comm_manager = self._make_browser()

        browser.refresh_namespace()
        with self.assertLogs("hyde", level="WARNING") as captured:
            self._answer(
                browser,
                comm_manager,
                self._pending_call_ids(comm_manager)[-1],
                error="the namespace view is not available",
            )

        self.assertEqual(len(self.status_service.transient_messages), 1)
        reported = self.status_service.transient_messages[0]
        self.assertIn("the namespace view is not available", reported)
        self.assertIn("variables", reported.lower())
        self.assertTrue(
            any("the namespace view is not available" in line for line in captured.output),
            captured.output,
        )

    def test_refresh_recovers_when_the_connection_closes_mid_request(self):
        browser, comm_manager = self._make_browser()

        browser.refresh_namespace()
        self._answer(
            browser,
            comm_manager,
            self._pending_call_ids(comm_manager)[-1],
            view=self._scalar_view(10),
        )
        browser.refresh_namespace()
        outstanding = len(self._pending_call_ids(comm_manager))

        # The kernel closes the comm while the request is outstanding, so
        # nothing is left that could carry the answer back.
        browser.spyder_comm._comm_close(
            {"content": {"comm_id": comm_manager.comms[-1].comm_id}}
        )
        browser.refresh_namespace()
        process_events()
        self.assertEqual(len(self._pending_call_ids(comm_manager)), outstanding)
        self.assertEqual(len(self.status_service.transient_messages), 1)

        browser.spyder_comm.close()
        browser.spyder_comm.open()
        browser.refresh_namespace()
        process_events()
        reconnected_call_ids = self._pending_call_ids(comm_manager)
        self.assertEqual(len(reconnected_call_ids), outstanding + 1)

        self._answer(
            browser,
            comm_manager,
            reconnected_call_ids[-1],
            view=self._scalar_view(12),
        )
        self.assertEqual(self._shown_values(browser), {"val": "12"})

    def test_refresh_recovers_when_the_request_cannot_be_sent(self):
        browser, comm_manager = self._make_browser(connect=False)

        browser.refresh_namespace()
        process_events()
        self.assertEqual(self._pending_call_ids(comm_manager), [])
        self.assertEqual(len(self.status_service.transient_messages), 1)

        browser.spyder_comm.open()
        browser.refresh_namespace()
        process_events()
        call_ids = self._pending_call_ids(comm_manager)
        self.assertEqual(len(call_ids), 1)

        self._answer(browser, comm_manager, call_ids[-1], view=self._scalar_view(7))
        self.assertEqual(self._shown_values(browser), {"val": "7"})

    def test_a_refresh_asked_for_while_one_is_in_flight_runs_once_more(self):
        browser, comm_manager = self._make_browser()

        browser.refresh_namespace()
        browser.refresh_namespace()
        browser.refresh_namespace()
        process_events()
        first_pass = self._pending_call_ids(comm_manager)
        self.assertEqual(len(first_pass), 1)

        self._answer(browser, comm_manager, first_pass[-1], view=self._scalar_view(1))
        second_pass = self._pending_call_ids(comm_manager)
        self.assertEqual(len(second_pass), 2)

        self._answer(browser, comm_manager, second_pass[-1], view=self._scalar_view(2))
        self.assertEqual(len(self._pending_call_ids(comm_manager)), 2)
        self.assertEqual(self._shown_values(browser), {"val": "2"})
        self.assertEqual(self.status_service.transient_messages, [])

    def test_a_slow_refresh_is_left_to_wait_rather_than_abandoned(self):
        browser, comm_manager = self._make_browser()

        browser.refresh_namespace()
        slow_call_id = self._pending_call_ids(comm_manager)[-1]

        # The kernel is busy with the user's own cell. Time passing is not
        # evidence of anything, so nothing may give up on the request.
        for _ in range(6):
            process_events(0.05)
            browser.refresh_namespace()
        self.assertEqual(len(self._pending_call_ids(comm_manager)), 1)
        self.assertEqual(self.status_service.transient_messages, [])

        self._answer(browser, comm_manager, slow_call_id, view=self._scalar_view(5))
        self.assertEqual(self._shown_values(browser), {"val": "5"})
        self.assertEqual(self.status_service.transient_messages, [])


class TestPythonVariablesSharedClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def test_reuses_kernel_runtime_shared_client(self):
        class FakeSignal:
            def __init__(self):
                self._callbacks = []

            def connect(self, callback):
                self._callbacks.append(callback)

            def disconnect(self, callback):
                self._callbacks.remove(callback)

        class FakeChannel:
            def __init__(self):
                self.message_received = FakeSignal()

        class FakeKernelClient:
            def __init__(self):
                self.iopub_channel = FakeChannel()
                self.session = type("Session", (), {"session": "terminal-session"})()

        class FakeSpyderComm:
            def __init__(self, kernel_client, on_call_failed):
                self.kernel_client = kernel_client
                self.on_call_failed = on_call_failed

            def open(self):
                return None

            def wait_until_ready(self, timeout=5):
                return None

            def is_connected(self):
                return True

            def configure_namespace_view(self, settings):
                self.settings = settings

            def request_namespace_view(self, callback):
                callback({})
                return True

            def close(self):
                return None

        shared_client = FakeKernelClient()
        kernel_runtime_service = type(
            "KernelRuntimeService",
            (),
            {"kernel_client": lambda self: shared_client},
        )()

        with patch(
            "hyde.user_interface.plugins.python_variables_tool.SpyderFrontendComm",
            FakeSpyderComm,
        ):
            browser = PythonVariables(
                services={"kernel_runtime_service": kernel_runtime_service},
            )
        try:
            self.assertIs(browser.kernel_client, shared_client)
        finally:
            browser.shutdown()
            browser.deleteLater()


class TestPythonVariablesService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def test_namespace_service_reads_cached_view_without_creating_widget(self):
        class FakePlugin:
            def __init__(self):
                self.widget_instance = None
                self.ensure_calls = 0

            def ensure_mdi_widget(self, key):
                del key
                self.ensure_calls += 1
                return self.widget_instance

            def mdi_widget(self, key):
                del key
                return self.widget_instance

        plugin = FakePlugin()
        service = PythonVariablesService(plugin)
        published_view = {"arr": {"type": "ndarray", "view": "[1 2 3]"}}

        service.publish_namespace_view(published_view)
        snapshot = service.namespace_view()
        published_view["arr"]["view"] = "[1 9 3]"

        self.assertEqual(
            snapshot,
            {"arr": {"type": "ndarray", "view": "[1 2 3]"}},
        )
        self.assertEqual(plugin.ensure_calls, 0)
        self.assertIsNone(plugin.widget_instance)

    def test_namespace_service_subscribes_without_creating_widget(self):
        class FakePlugin:
            def __init__(self):
                self.widget_instance = None
                self.ensure_calls = 0

            def ensure_mdi_widget(self, key):
                del key
                self.ensure_calls += 1
                return self.widget_instance

            def mdi_widget(self, key):
                del key
                return self.widget_instance

        plugin = FakePlugin()
        service = PythonVariablesService(plugin)
        callback_payloads = []

        def callback(view):
            callback_payloads.append(view)

        self.assertTrue(service.connect_namespace_view_updated(callback))
        self.assertEqual(plugin.ensure_calls, 0)
        self.assertIsNone(plugin.widget_instance)

        service.publish_namespace_view(
            {"scalar": {"type": "int", "python_type": "int", "view": "7"}}
        )

        self.assertEqual(
            callback_payloads,
            [{"scalar": {"type": "int", "python_type": "int", "view": "7"}}],
        )
        self.assertEqual(plugin.ensure_calls, 0)
        self.assertTrue(service.disconnect_namespace_view_updated(callback))

    def test_namespace_view_isolated_from_nested_metadata_mutation(self):
        browser = PythonVariables.__new__(PythonVariables)
        QtWidgets.QWidget.__init__(browser)
        browser._last_view = {}
        browser._update_ui = Mock()
        browser.namespace_view_updated = type(
            "Signal", (), {"emit": lambda self, payload: None}
        )()
        shared_view = {"arr": {"type": "ndarray", "view": ["[1 2 3]"]}}

        browser._apply_namespace_view(shared_view)
        snapshot = browser.namespace_view()
        shared_view["arr"]["view"][0] = "[1 9 3]"

        self.assertEqual(snapshot["arr"]["view"], ["[1 2 3]"])


class FakeIOPubChannel(QtCore.QObject):
    message_received = QtCore.Signal(object)


class FakeNamespaceKernelClient:
    def __init__(self):
        self.iopub_channel = FakeIOPubChannel()


class FakeAnsweringSpyderComm:
    """A comm that answers a namespace-view request before it returns.

    `PythonVariables.__init__` opens a comm and asks for the namespace, so
    building the real widget needs an answer rather than a real kernel.
    """

    def __init__(self, kernel_client, on_call_failed):
        self.kernel_client = kernel_client
        self.on_call_failed = on_call_failed

    def open(self):
        return None

    def wait_until_ready(self, timeout=5):
        del timeout
        return None

    def is_connected(self):
        return True

    def configure_namespace_view(self, settings):
        self.settings = dict(settings)

    def request_namespace_view(self, callback):
        callback(
            {
                "arr": {
                    "type": "ndarray",
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "view": "[1 2 3]",
                },
                "scalar": {
                    "type": "int",
                    "python_type": "int",
                    "view": "7",
                },
                "text": {
                    "type": "str",
                    "python_type": "str",
                    "view": "'hello'",
                },
            }
        )
        return True

    def close(self):
        return None


def make_variables_plugin(qapp):
    """The real plugin, in a real MDI area, over a comm that answers at once."""
    mdi_area = QtWidgets.QMdiArea()
    mdi_area.show()
    qapp.processEvents()
    context = HydeMDIContext(mdi_area)

    plugin = PythonVariablesPlugin({})
    plugin.services = {
        "mdi_context": context,
        "kernel_runtime_service": type(
            "KernelRuntimeService",
            (),
            {"kernel_client": lambda _self: FakeNamespaceKernelClient()},
        )(),
    }
    context.add(
        "python_variables_tool",
        plugin.get_ui_contributions()[0],
        {"services": plugin.services},
    )
    return plugin, mdi_area, FakeAnsweringSpyderComm


class TestPythonVariablesWindowClose(unittest.TestCase):
    """A tool window that has been shut down must let go of its window.

    Tool windows persist by turning a close into a hide, so a shut-down widget
    that still insisted on that would leave a window the user cannot close and
    whose contents will never update again.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def test_a_shut_down_variables_tool_lets_its_window_close(self):
        plugin, mdi_area, fake_comm = make_variables_plugin(self.qapp)
        dummy_app = type("DummyApp", (), {"_subwindow_filters": []})()
        try:
            with patch(
                "hyde.user_interface.plugins.python_variables_tool.SpyderFrontendComm",
                fake_comm,
            ):
                widget = plugin.ensure_mdi_widget("python_variables_tool")
            subwindow = plugin.mdi_subwindow("python_variables_tool")
            HydeApp.configure_persistent_subwindow(dummy_app, subwindow)
            subwindow.show()
            self.qapp.processEvents()

            # While the tool is live its window persists: a close hides it.
            self.assertFalse(subwindow.close())
            self.qapp.processEvents()
            self.assertFalse(subwindow.isVisible())

            subwindow.show()
            self.qapp.processEvents()
            widget.shutdown()

            self.assertTrue(subwindow.close())
            self.qapp.processEvents()
            self.assertFalse(subwindow.isVisible())
        finally:
            plugin.destroy_mdi_widget("python_variables_tool")
            mdi_area.deleteLater()
            self.qapp.processEvents()


class TestPythonVariablesSessionPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def _make_plugin(self):
        return make_variables_plugin(self.qapp)

    def test_view_state_round_trips_through_widget_session_hooks(self):
        plugin, mdi_area, fake_comm = self._make_plugin()
        restored_plugin = None
        restored_mdi_area = None
        try:
            with patch(
                "hyde.user_interface.plugins.python_variables_tool.SpyderFrontendComm",
                fake_comm,
            ):
                widget = plugin.ensure_mdi_widget("python_variables_tool")
                subwindow = plugin.mdi_subwindow("python_variables_tool")
                subwindow.setGeometry(QtCore.QRect(20, 30, 340, 280))
                subwindow.show()
                self.qapp.processEvents()

                widget.ui.arraysCheckBox.setChecked(False)
                widget.ui.variablesCheckBox.setChecked(True)
                widget.ui.stringsCheckBox.setChecked(False)
                widget.ui.infoCheckBox.setChecked(False)
                self.qapp.processEvents()

                session = plugin.get_session_toml_data()

                restored_plugin, restored_mdi_area, _ = self._make_plugin()
                with patch(
                    "hyde.user_interface.plugins.python_variables_tool.SpyderFrontendComm",
                    fake_comm,
                ):
                    restored_plugin.on_project_loaded({"session": session})

                restored_widget = restored_plugin.mdi_widget("python_variables_tool")
                restored_subwindow = restored_plugin.mdi_subwindow("python_variables_tool")
                self.qapp.processEvents()

            self.assertEqual(
                session["python_variables_tool"],
                {
                    "arrays": False,
                    "variables": True,
                    "strings": False,
                    "info": False,
                },
            )
            self.assertEqual(
                restored_widget.get_session_toml_data(),
                session["python_variables_tool"],
            )
            self.assertIsNone(restored_widget.widget_ir)
            self.assertTrue(restored_subwindow.isVisible())
            self.assertEqual(current_names(restored_widget), ["scalar"])
            self.assertFalse(restored_widget.ui.infoCheckBox.isChecked())
            self.assertFalse(restored_widget.ui.infoPane.isVisible())
        finally:
            plugin.python_variables_service.destroy()
            mdi_area.deleteLater()
            if restored_plugin is not None:
                restored_plugin.python_variables_service.destroy()
            if restored_mdi_area is not None:
                restored_mdi_area.deleteLater()


if __name__ == "__main__":
    unittest.main()
