import unittest
import types
from unittest.mock import patch
import sys

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

import hyde

from qtutils.qt import QtCore, QtWidgets

from hyde.matplotlib_backend import FigureCanvasHyde, FigureManagerHyde, figure_snapshot_payload
from hyde.project_tools import (
    HYDE_MATPLOTLIB_BACKEND,
    configure_gui_matplotlib_backend,
    is_excluded,
)
from hyde.user_interface.plugins.figure import FigureFeatureService, FigureWorkspaceService
from hyde.user_interface.plugins.figure.window import FigureState, FigureWindow


class FakeNamespaceViewService:
    def __init__(self, view=None):
        self._view = dict(view or {})
        self._callbacks = []
        self.connected = False

    def namespace_view(self):
        return dict(self._view)

    def connect_namespace_view_updated(self, callback):
        self.connected = True
        self._callbacks.append(callback)

    def disconnect_namespace_view_updated(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, view):
        self._view = dict(view)
        for callback in list(self._callbacks):
            callback(dict(self._view))


class TestFigureCodec(unittest.TestCase):
    def test_figure_state_generates_object_oriented_matplotlib_code(self):
        state = FigureState()
        state.set_title("DelayGraph")
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])

        source = state.python_source()

        self.assertIn("def _hyde_figure(delay, fit_delay, raw_delay):", source)
        self.assertIn("_hyde_figure(delay, fit_delay, raw_delay)", source)
        self.assertIn("del _hyde_figure", source)
        self.assertIn("fig = plt.figure('DelayGraph')", source)
        self.assertIn("ax = fig.add_subplot(111)", source)
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", source)
        self.assertIn("ax.plot(delay, raw_delay, label='raw_delay')", source)
        self.assertIn("ax.legend()", source)
        self.assertIn("fig.show()", source)

    def test_figure_state_generates_decorated_macro_source(self):
        state = FigureState()
        state.set_title("DelayGraph")
        state.set_x_name("delay")
        state.set_items(["fit_delay"])

        macro = state.macro_source("Graph0")

        self.assertIn("@hyde.figure", macro)
        self.assertIn("def Graph0(delay, fit_delay):", macro)
        self.assertIn("fig = plt.figure('DelayGraph')", macro)
        self.assertIn("ax = fig.add_subplot(111)", macro)
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", macro)

    def test_figure_codec_generates_track_command(self):
        state = FigureState()
        state.set_title("DelayGraph")
        state.set_items(["fit_delay"])

        source = state.source_for_command(
            "track",
            figure_number=3,
            tracked_state=state.normalized_state(),
        )

        self.assertTrue(source.startswith("hyde.track_figure(3, {"))
        self.assertIn("'title': 'DelayGraph'", source)
        self.assertIn("'items': ['fit_delay']", source)


class TestFigurePluginDispatch(unittest.TestCase):
    def test_new_figure_dialog_dispatches_muted_command(self):
        executed = []
        pending_states = []

        plugin = type("FakePlugin", (), {})()
        plugin.workspace = type(
            "FakeWorkspace",
            (),
            {
                "next_generated_title": lambda self: "Figure0",
                "register_pending_open": (
                    lambda self, restore=None, live_state=None: (
                        pending_states.append(live_state) or "open-token"
                    )
                ),
            },
        )()
        plugin.services = {
            "execute_command": lambda code, visible=True: executed.append((code, visible))
        }

        service = FigureFeatureService(plugin)

        class FakeDialog:
            def __init__(self, objects_metadata, preselection=None, parent=None):
                del objects_metadata, preselection, parent

            def exec_(self):
                return True

            def normalized_state(self):
                return {"feature": "figure", "settings": {"title": None}, "items": ["arr"]}

        with patch("hyde.user_interface.plugins.figure.NewFigureDialog", FakeDialog):
            self.assertTrue(service.show_new_figure_dialog({"arr": {}}, parent=None))

        self.assertEqual(len(executed), 1)
        self.assertFalse(executed[0][1])
        self.assertIn("fig = plt.figure('Figure0')", executed[0][0])
        self.assertIn("fig._hyde_open_token = 'open-token'", executed[0][0])
        self.assertEqual(pending_states[0]["settings"]["title"], "Figure0")


class TestFigureBackendSnapshot(unittest.TestCase):
    def _live_state(self):
        state = FigureState()
        state.set_title("DelayGraph")
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])
        return state.normalized_state()

    def _live_state_with_title(self, title):
        state = FigureState()
        state.set_title(title)
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])
        return state.normalized_state()

    def test_snapshot_payload_serializes_simple_single_axes_line_figure(self):
        figure = Figure()
        axes = figure.add_subplot(111)
        axes.set_title("DelayGraph")
        axes.plot([0, 1, 2], [1, 4, 9], label="fit_delay")

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["default_macro_name"], "Figure 1")
        self.assertIsNone(payload["save_error"])
        self.assertIn("fig = plt.figure('Figure 1')", payload["call_source"])
        self.assertIn("ax = fig.add_subplot(111)", payload["call_source"])
        self.assertIn("ax.plot(np.array([1, 4, 9])", payload["call_source"])
        self.assertEqual(
            payload["figure_size"],
            tuple(int(value * figure.dpi) for value in figure.get_size_inches()),
        )

    def test_snapshot_payload_prefers_hyde_live_state_when_available(self):
        figure = Figure()
        figure._hyde_live_state = self._live_state()

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["tracked_names"], ["delay", "fit_delay", "raw_delay"])
        self.assertEqual(payload["live_state"]["settings"]["title"], "DelayGraph")
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", payload["call_source"])

    def test_snapshot_payload_infers_live_state_for_simple_terminal_figure(self):
        figure = Figure()
        axes = figure.add_subplot(111)
        axes.set_title("DelayGraph")
        main_namespace = sys.modules["__main__"].__dict__
        previous_values = {
            name: main_namespace.get(name)
            for name in ("delay", "fit_delay")
        }
        try:
            main_namespace["delay"] = [0, 1, 2]
            main_namespace["fit_delay"] = [1, 4, 9]
            axes.plot(main_namespace["delay"], main_namespace["fit_delay"], label="fit_delay")

            payload = figure_snapshot_payload(figure, 1)

            self.assertEqual(payload["tracked_names"], ["fit_delay"])
            self.assertEqual(payload["live_state"]["settings"]["title"], "DelayGraph")
            self.assertIn("ax.plot(fit_delay, label='fit_delay')", payload["call_source"])
        finally:
            for name, value in previous_values.items():
                if value is None:
                    main_namespace.pop(name, None)
                else:
                    main_namespace[name] = value

    def test_manager_initialization_does_not_push_draw_before_backend_is_ready(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)

        with patch("hyde.matplotlib_backend.Comm") as comm_cls:
            manager = FigureManagerHyde(canvas, 3)

        self.assertIs(canvas.manager, manager)
        self.assertEqual(manager.num, 3)
        self.assertTrue(manager._ready_to_push)
        comm_cls.assert_not_called()

    def test_set_window_title_does_not_push_draw(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)
        manager = FigureManagerHyde(canvas, 3)

        with patch.object(manager, "_push_draw") as push_draw:
            manager.set_window_title("Retitled")

        push_draw.assert_not_called()
        self.assertEqual(figure.get_label(), "Retitled")

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_figure_window_session_state_captures_geometry_and_recreation_source(self):
        widget = FigureWindow(figure_number=1)
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(widget)
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        widget.snapshot_state.update(
            default_macro_name="Figure0",
            call_source="fig = plt.figure('Figure0')\nax = fig.add_subplot(111)",
            save_error=None,
            figure_size=(640, 480),
        )

        saved = widget.session_save_data()

        self.assertEqual(saved["title"], "Figure0")
        self.assertEqual(saved["geometry"], [10, 20, 300, 240])
        self.assertIn("fig = plt.figure('Figure0')", saved["call_source"])

    def test_figure_window_refreshes_from_same_namespace_signal_as_tables(self):
        queued = []
        namespace_service = FakeNamespaceViewService(
            {
                "delay": {"type": "ndarray", "view": "[0 1 2]"},
                "fit_delay": {"type": "ndarray", "view": "[1 4 9]"},
                "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
            }
        )
        widget = FigureWindow(
            figure_number=1,
            services={
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.set_live_state(self._live_state())

            namespace_service.emit(
                {
                    "delay": {"type": "ndarray", "view": "[0 1 2]"},
                    "fit_delay": {"type": "ndarray", "view": "[10 40 90]"},
                    "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
                }
            )

            self.assertEqual(queued, [("hyde.refresh_figure(1)", True)])
        finally:
            widget.close()

    def test_figure_window_detects_in_place_namespace_metadata_mutation(self):
        queued = []
        shared_view = ["[1 4 9]"]
        namespace_service = FakeNamespaceViewService(
            {
                "delay": {"type": "ndarray", "view": "[0 1 2]"},
                "fit_delay": {"type": "ndarray", "view": shared_view},
                "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
            }
        )
        widget = FigureWindow(
            figure_number=1,
            services={
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.set_live_state(self._live_state())
            queued.clear()
            shared_view[0] = "[10 40 90]"
            namespace_service.emit(
                {
                    "delay": {"type": "ndarray", "view": "[0 1 2]"},
                    "fit_delay": {"type": "ndarray", "view": shared_view},
                    "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
                }
            )

            self.assertEqual(queued, [("hyde.refresh_figure(1)", True)])
        finally:
            widget.close()

    def test_figure_window_subscribes_to_namespace_updates(self):
        namespace_service = FakeNamespaceViewService()
        widget = FigureWindow(
            figure_number=1,
            services={"namespace_view_service": namespace_service},
        )
        try:
            self.assertTrue(namespace_service.connected)
        finally:
            widget.close()

    def test_figure_window_refresh_recovers_after_timed_out_request(self):
        queued = []
        namespace_service = FakeNamespaceViewService(
            {
                "delay": {"type": "ndarray", "view": "[0 1 2]"},
                "fit_delay": {"type": "ndarray", "view": "[1 4 9]"},
                "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
            }
        )
        widget = FigureWindow(
            figure_number=1,
            services={
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.set_live_state(self._live_state())
            widget.refresh_figure()
            self.assertTrue(widget._refresh_in_flight)

            widget._on_refresh_timeout()
            self.assertFalse(widget._refresh_in_flight)

            namespace_service.emit(
                {
                    "delay": {"type": "ndarray", "view": "[0 1 2]"},
                    "fit_delay": {"type": "ndarray", "view": "[10 40 90]"},
                    "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
                }
            )

            self.assertEqual(len(queued), 2)
            self.assertEqual(queued[1], ("hyde.refresh_figure(1)", True))
        finally:
            widget.close()

    def test_figure_window_close_waits_for_kernel_confirmation(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "request_save_figure_macro": lambda saveable: True,
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()

        self.assertFalse(widget._closed)
        self.assertTrue(widget._kernel_close_in_progress)
        self.assertEqual(queued, [("plt.close(1)", True)])

        widget.close_from_kernel()
        self.qapp.processEvents()

        self.assertTrue(widget._closed)

    def test_figure_window_close_timeout_clears_in_flight_close(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "queue_background_command": lambda code, silent=True: (
                    queued.append((code, silent)) or True
                ),
                "request_save_figure_macro": lambda saveable: True,
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()
        self.assertTrue(widget._kernel_close_in_progress)

        widget._on_close_timeout()
        self.assertFalse(widget._kernel_close_in_progress)
        self.assertFalse(widget._closed)

        subwindow.close()
        self.qapp.processEvents()
        self.assertEqual(queued, [("plt.close(1)", True), ("plt.close(1)", True)])
        widget.close_from_kernel()
        self.qapp.processEvents()

    def test_figure_window_uses_snapshot_size_for_initial_subwindow_geometry(self):
        main = QtWidgets.QMainWindow()
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(320, 240)
        main.setCentralWidget(mdi_area)
        main.show()
        self.qapp.processEvents()

        widget = FigureWindow(figure_number=1)
        subwindow = mdi_area.addSubWindow(widget)
        widget.bind_subwindow(subwindow)
        widget.snapshot_state.update(
            default_macro_name="Figure0",
            call_source="fig = plt.figure('Figure0')",
            save_error=None,
            figure_size=(640, 480),
        )

        widget._apply_initial_subwindow_size()

        frame_size = subwindow.size() - subwindow.contentsRect().size()
        expected_size = QtCore.QSize(640, 480)
        expected_size.scale(
            QtCore.QSize(
                max(160, mdi_area.viewport().width() - max(0, frame_size.width())),
                max(120, mdi_area.viewport().height() - max(0, frame_size.height())),
            ),
            QtCore.Qt.KeepAspectRatio,
        )
        contents_size = subwindow.contentsRect().size()

        self.assertEqual(contents_size.width(), expected_size.width())
        self.assertEqual(contents_size.height(), expected_size.height())
        self.assertLessEqual(subwindow.width(), mdi_area.viewport().width())
        self.assertLessEqual(subwindow.height(), mdi_area.viewport().height())
        main.close()

    def test_workspace_matches_pending_state_by_open_token_not_arrival_order(self):
        tracked = []
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "queue_background_command": lambda code, silent=True: True,
            "request_save_figure_macro": lambda saveable: True,
            "get_shutting_down": lambda: False,
        }
        plugin.request_save_figure_macro = lambda saveable: True
        plugin.track_live_figure = (
            lambda figure_number, state: tracked.append(
                (figure_number, state["settings"]["title"])
            )
        )
        workspace = FigureWorkspaceService(plugin)
        token_a = workspace.register_pending_open(
            restore={"geometry": [10, 20, 300, 220], "hidden": False},
            live_state=self._live_state_with_title("FigureA"),
        )
        token_b = workspace.register_pending_open(
            restore={"geometry": [30, 40, 280, 180], "hidden": True},
            live_state=self._live_state_with_title("FigureB"),
        )

        workspace.open_or_update_figure(
            {
                "figure_number": 2,
                "title": "FigureB",
                "snapshot": {
                    "open_token": token_b,
                    "call_source": "fig = plt.figure('FigureB')",
                    "figure_size": (320, 240),
                },
            }
        )
        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "open_token": token_a,
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                },
            }
        )
        self.qapp.processEvents()

        figure_b = workspace.figures[2]
        figure_a = workspace.figures[1]
        self.assertEqual(figure_b.snapshot_state.live_state()["settings"]["title"], "FigureB")
        self.assertEqual(figure_a.snapshot_state.live_state()["settings"]["title"], "FigureA")
        self.assertEqual(figure_b.capture_geometry(), [30, 40, 280, 180])
        self.assertEqual(figure_a.capture_geometry(), [10, 20, 300, 220])
        self.assertEqual(tracked, [(2, "FigureB"), (1, "FigureA")])
        workspace.clear()
        mdi_area.close()


class TestBackendBootstrap(unittest.TestCase):
    def test_configure_gui_matplotlib_backend_forces_module_backend_only(self):
        fake_matplotlib = types.ModuleType("matplotlib")
        calls = []

        def fake_use(backend, *args, **kwargs):
            del args, kwargs
            calls.append(backend)

        fake_matplotlib.use = fake_use
        fake_matplotlib.get_backend = lambda: "MacOSX"

        with patch.dict(sys.modules, {"matplotlib": fake_matplotlib}, clear=False):
            sys.modules.pop("matplotlib.pyplot", None)
            configure_gui_matplotlib_backend()

            self.assertEqual(calls, [HYDE_MATPLOTLIB_BACKEND])


class TestMatplotlibPersistenceExclusion(unittest.TestCase):
    def test_matplotlib_figure_and_axes_are_not_excluded_from_kernel_persistence(self):
        figure = Figure()
        axes = figure.add_subplot(111)

        self.assertFalse(is_excluded("fig", figure))
        self.assertFalse(is_excluded("ax", axes))


class TestFigureRefreshHelpers(unittest.TestCase):
    def test_refresh_figure_reapplies_live_state_without_accumulating_lines(self):
        state = FigureState()
        state.set_title("DelayGraph")
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])
        normalized_state = state.normalized_state()

        figure = Figure()
        FigureCanvasHyde(figure)

        main_namespace = sys.modules["__main__"].__dict__
        previous_values = {
            name: main_namespace.get(name)
            for name in ("delay", "fit_delay", "raw_delay")
        }
        try:
            main_namespace["delay"] = [0, 1, 2]
            main_namespace["fit_delay"] = [1, 4, 9]
            main_namespace["raw_delay"] = [1, 2, 3]

            hyde.track_figure(figure, normalized_state)
            hyde.refresh_figure(figure)

            axis = figure.axes[0]
            self.assertEqual(len(axis.lines), 2)
            self.assertEqual(list(axis.lines[0].get_ydata()), [1, 4, 9])

            main_namespace["fit_delay"] = [2, 5, 10]
            hyde.refresh_figure(figure)

            axis = figure.axes[0]
            self.assertEqual(len(axis.lines), 2)
            self.assertEqual(list(axis.lines[0].get_ydata()), [2, 5, 10])
        finally:
            for name, value in previous_values.items():
                if value is None:
                    main_namespace.pop(name, None)
                else:
                    main_namespace[name] = value


if __name__ == "__main__":
    unittest.main()
