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

from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.matplotlib_backend import (
    FigureCanvasHyde,
    FigureManagerHyde,
    _figure_defaults_snapshot,
    apply_figure_action,
    figure_snapshot_payload,
)
from hyde.features.matplotlib_features import FigureIRCodec, figure_ir_from_live_state
from hyde.project_tools import (
    HYDE_MATPLOTLIB_BACKEND,
    configure_gui_matplotlib_backend,
    is_excluded,
)
from hyde.user_interface.shared.plugin import HydePlugin
from hyde.user_interface.plugins.figure import (
    FigureContextService,
    FigureFeatureService,
    FigureWorkspaceService,
    Plugin,
)
from hyde.user_interface.plugins.figure.dialogs import NewFigureDialog
from hyde.user_interface.plugins.figure.window import (
    FigureState,
    FigureWindow,
)


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


class FakeExecutionService:
    def __init__(self, hidden_calls=None, visible_calls=None):
        self.hidden_calls = hidden_calls if hidden_calls is not None else []
        self.visible_calls = visible_calls if visible_calls is not None else []

    def execute_hidden(self, code, silent=True):
        self.hidden_calls.append((code, silent))
        return True

    def execute_visible(self, code):
        self.visible_calls.append(code)
        return True


class TestFigureCodec(unittest.TestCase):
    def test_figure_state_generates_first_class_figure_builder_code(self):
        state = FigureState()
        state.set_title("DelayGraph")
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])

        source = state.python_source()

        self.assertIn("@hyde.figure(register=False)", source)
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

    def test_figure_state_generates_empty_figure_builder_code(self):
        state = FigureState()
        state.set_title("EmptyFigure")
        state.set_x_name("delay")

        source = state.python_source()

        self.assertIn("@hyde.figure(register=False)", source)
        self.assertIn("def _hyde_figure():", source)
        self.assertIn("_hyde_figure()", source)
        self.assertIn("fig = plt.figure('EmptyFigure')", source)
        self.assertIn("ax = fig.add_subplot(111)", source)
        self.assertNotIn("ax.plot(", source)
        self.assertNotIn("delay", source)
        self.assertIn("fig.show()", source)

    def test_figure_codec_rejects_removed_track_command(self):
        state = FigureState()
        state.set_title("DelayGraph")
        state.set_items(["fit_delay"])

        with self.assertRaises(ValueError):
            state.source_for_command(
                "track",
                figure_number=3,
                tracked_state=state.normalized_state(),
            )


class TestFigurePluginDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_new_figure_dialog_dispatches_muted_command(self):
        executed = []

        plugin = type("FakePlugin", (), {})()
        plugin.workspace = type(
            "FakeWorkspace",
            (),
            {"next_generated_title": lambda self: "Figure0"},
        )()
        plugin.services = {
            "python_execution_service": FakeExecutionService(executed),
        }

        service = FigureFeatureService(plugin)

        class FakeDialog:
            def __init__(self, objects_metadata, preselection=None, parent=None):
                del objects_metadata, preselection, parent

            def exec_(self):
                return True

            def get_command(self, default_title=None):
                del default_title
                return (
                    "@hyde.figure(register=False)\n"
                    "def _hyde_figure(arr):\n"
                    "    fig = plt.figure('Figure0')\n"
                    "    ax = fig.add_subplot(111)\n"
                    "    ax.set_title('Figure0')\n"
                    "    ax.plot(arr, label='arr')\n"
                    "    fig.show()\n\n"
                    "_hyde_figure(arr)\n"
                    "del _hyde_figure"
                )

        with patch("hyde.user_interface.plugins.figure.NewFigureDialog", FakeDialog):
            self.assertTrue(service.show_new_figure_dialog({"arr": {}}, parent=None))

        self.assertEqual(len(executed), 1)
        self.assertTrue(executed[0][1])
        self.assertIn("@hyde.figure(register=False)", executed[0][0])
        self.assertIn("def _hyde_figure(arr):", executed[0][0])
        self.assertIn("_hyde_figure(arr)", executed[0][0])
        self.assertIn("fig = plt.figure('Figure0')", executed[0][0])

    def test_new_figure_dialog_dispatches_requested_figure_size(self):
        executed = []

        plugin = type("FakePlugin", (), {})()
        plugin.workspace = type(
            "FakeWorkspace",
            (),
            {"next_generated_title": lambda self: "Figure0"},
        )()
        plugin.services = {
            "python_execution_service": FakeExecutionService(executed),
        }

        service = FigureFeatureService(plugin)

        class FakeDialog:
            def __init__(self, objects_metadata, preselection=None, parent=None):
                del objects_metadata, preselection, parent

            def exec_(self):
                return True

            def get_command(self, default_title=None):
                del default_title
                return (
                    "@hyde.figure(register=False)\n"
                    "def _hyde_figure(arr):\n"
                    "    fig = plt.figure('Figure0', figsize=(5.0, 3.0))\n"
                    "    ax = fig.add_subplot(111)\n"
                    "    ax.set_title('Figure0')\n"
                    "    ax.plot(arr, label='arr')\n"
                    "    fig.show()\n\n"
                    "_hyde_figure(arr)\n"
                    "del _hyde_figure"
                )

        with patch("hyde.user_interface.plugins.figure.NewFigureDialog", FakeDialog):
            self.assertTrue(service.show_new_figure_dialog({"arr": {}}, parent=None))

        self.assertEqual(len(executed), 1)
        self.assertIn("@hyde.figure(register=False)", executed[0][0])
        self.assertIn("fig = plt.figure('Figure0', figsize=(5.0, 3.0))", executed[0][0])

    def test_new_figure_dialog_defaults_to_reasonable_figure_size(self):
        dialog = NewFigureDialog({"arr": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "f"}})
        try:
            state = dialog.normalized_state()
            self.assertEqual(dialog.ui.widthSpinBox.value(), 5.0)
            self.assertEqual(dialog.ui.heightSpinBox.value(), 3.0)
            self.assertEqual(dialog.ui.widthSpinBox.prefix(), "x: ")
            self.assertEqual(dialog.ui.heightSpinBox.prefix(), "y: ")
            self.assertEqual(state["settings"]["figsize"], (5.0, 3.0))
        finally:
            dialog.close()

    def test_new_figure_dialog_dispatches_empty_figure_when_no_data_selected(self):
        executed = []

        plugin = type("FakePlugin", (), {})()
        plugin.workspace = type(
            "FakeWorkspace",
            (),
            {"next_generated_title": lambda self: "Figure0"},
        )()
        plugin.services = {
            "python_execution_service": FakeExecutionService(executed),
        }

        service = FigureFeatureService(plugin)

        class FakeDialog:
            def __init__(self, objects_metadata, preselection=None, parent=None):
                del objects_metadata, preselection, parent

            def exec_(self):
                return True

            def get_command(self, default_title=None):
                del default_title
                return (
                    "@hyde.figure(register=False)\n"
                    "def _hyde_figure():\n"
                    "    fig = plt.figure('Figure0')\n"
                    "    ax = fig.add_subplot(111)\n"
                    "    fig.show()\n\n"
                    "_hyde_figure()\n"
                    "del _hyde_figure"
                )

        with patch("hyde.user_interface.plugins.figure.NewFigureDialog", FakeDialog):
            self.assertTrue(service.show_new_figure_dialog({}, parent=None))

        self.assertEqual(len(executed), 1)
        self.assertIn("def _hyde_figure():", executed[0][0])
        self.assertIn("ax = fig.add_subplot(111)", executed[0][0])
        self.assertNotIn("ax.plot(", executed[0][0])

    def test_figure_macro_dispatch_uses_shared_callable_invocation(self):
        executed = []
        plugin = HydePlugin({})
        plugin.services = {
            "python_execution_service": FakeExecutionService(
                hidden_calls=[],
                visible_calls=executed,
            )
        }

        Plugin._execute_macro(plugin, "Figure0", ("x", "y"))

        self.assertEqual(executed, ["Figure0(x, y)"])


class TestFigureBackendSnapshot(unittest.TestCase):
    def tearDown(self):
        pyplot = getattr(matplotlib, "pyplot", None)
        if pyplot is not None:
            pyplot.close("all")

    def _configure_hyde_pyplot(self):
        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as pyplot

        return pyplot

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

    def test_figure_ir_trace_style_edit_preserves_broader_line2d_kwargs(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        updated = FigureIRCodec.update_state(
            figure_ir,
            {
                "type": "set_trace_style",
                "subplot_id": "subplot0",
                "trace_id": "trace0",
                "style": {
                    "visible": False,
                    "alpha": 0.25,
                    "linestyle": "None",
                    "linewidth": 3.5,
                    "drawstyle": "steps-mid",
                    "markersize": 7.0,
                    "markerfacecolor": "red",
                    "markeredgecolor": "black",
                    "markeredgewidth": 2.0,
                },
            },
        )

        trace_kwargs = updated["layout"]["subplots"][0]["traces"][0]["kwargs"]
        self.assertFalse(trace_kwargs["visible"])
        self.assertEqual(trace_kwargs["alpha"], 0.25)
        self.assertEqual(trace_kwargs["linestyle"], "None")
        self.assertEqual(trace_kwargs["linewidth"], 3.5)
        self.assertEqual(trace_kwargs["drawstyle"], "steps-mid")
        self.assertEqual(trace_kwargs["markersize"], 7.0)
        self.assertEqual(trace_kwargs["markerfacecolor"], "red")
        self.assertEqual(trace_kwargs["markeredgecolor"], "black")
        self.assertEqual(trace_kwargs["markeredgewidth"], 2.0)

        source = FigureIRCodec.state_to_python(updated)
        self.assertIn("visible=False", source)
        self.assertIn("alpha=0.25", source)
        self.assertIn("linestyle='None'", source)
        self.assertIn("linewidth=3.5", source)
        self.assertIn("drawstyle='steps-mid'", source)
        self.assertIn("markersize=7.0", source)
        self.assertIn("markerfacecolor='red'", source)
        self.assertIn("markeredgecolor='black'", source)
        self.assertIn("markeredgewidth=2.0", source)

    def test_figure_ir_axis_edit_surface_lowers_axis_state_to_python(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        with_bottom_hidden = FigureIRCodec.update_state(
            figure_ir,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "bottom",
                "state": {
                    "spine_visible": False,
                    "ticks_visible": False,
                    "tick_labels_visible": False,
                },
            },
        )
        with_x_axis = FigureIRCodec.update_state(
            with_bottom_hidden,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {
                    "scale_mode": "log2",
                    "range": {
                        "limits": (1.0, 8.0),
                        "limit_mode": {"min": "manual", "max": "manual"},
                        "autoscale": "data",
                    },
                    "label": {
                        "text": "Delay",
                        "visible": True,
                        "side": "top",
                        "position_mode": "manual",
                        "position": 0.35,
                        "offset": 14.0,
                        "line_spacing": 1.6,
                        "color": "#aa5500",
                    },
                    "ticks": {
                        "major": {
                            "mode": "manual",
                            "positions": [1.0, 2.0, 4.0, 8.0],
                            "labels": ["1", "2", "4", "8"],
                        },
                        "minor": {"visible": True},
                        "direction": "both",
                    },
                    "grid": {
                        "visible": True,
                        "linestyle": ":",
                        "linewidth": 1.25,
                        "color": "#123456",
                    },
                },
            },
        )
        with_right_side = FigureIRCodec.update_state(
            with_x_axis,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "right",
                "state": {
                    "spine_visible": True,
                    "ticks_visible": True,
                    "tick_labels_visible": True,
                    "tick_label_color": "#00aa00",
                    "tick_label_rotation": 35.0,
                },
            },
        )
        updated = FigureIRCodec.update_state(
            with_right_side,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "y",
                "state": {
                    "label": {
                        "text": "Signal",
                        "visible": False,
                        "side": "right",
                    },
                    "range": {
                        "limits": (-2.0, 12.0),
                        "limit_mode": {"min": "manual", "max": "manual"},
                        "autoscale": "data",
                    },
                    "zero_line": {
                        "visible": True,
                        "linestyle": "--",
                        "linewidth": 2.0,
                        "color": "#654321",
                    },
                },
            },
        )

        subplot = updated["layout"]["subplots"][0]
        self.assertEqual(subplot["axes"]["x"]["label"]["side"], "top")
        self.assertEqual(subplot["axes"]["y"]["label"]["side"], "right")
        self.assertFalse(subplot["axes"]["y"]["label"]["visible"])
        self.assertFalse(subplot["axis_sides"]["bottom"]["spine_visible"])
        self.assertFalse(subplot["axis_sides"]["top"]["ticks_visible"])
        self.assertEqual(subplot["axis_sides"]["right"]["tick_label_color"], "#00aa00")

        source = FigureIRCodec.state_to_python(updated)
        self.assertIn("import matplotlib.ticker as mticker", source)
        self.assertIn("ax.set_xscale('log', base=2)", source)
        self.assertIn("ax.set_xlim(1.0, 8.0)", source)
        self.assertIn("ax.xaxis.set_label_position('top')", source)
        self.assertIn("ax.set_xlabel('Delay')", source)
        self.assertIn("ax.xaxis.label.set_color('#aa5500')", source)
        self.assertIn("ax.xaxis.label.set_linespacing(1.6)", source)
        self.assertIn("ax.xaxis.set_label_coords(0.35, _hyde_x_label_coords[1])", source)
        self.assertIn("ax.xaxis.labelpad = 14.0", source)
        self.assertIn("ax.tick_params(axis='x', which='both', top=False, labeltop=False, bottom=False, labelbottom=False, direction='inout')", source)
        self.assertIn("ax.xaxis.set_major_locator(mticker.FixedLocator([1.0, 2.0, 4.0, 8.0]))", source)
        self.assertIn("ax.xaxis.set_major_formatter(mticker.FixedFormatter(['1', '2', '4', '8']))", source)
        self.assertIn("ax.grid(True, axis='x', which='major', linestyle=':', linewidth=1.25, color='#123456')", source)
        self.assertIn("ax.yaxis.set_label_position('right')", source)
        self.assertIn("ax.set_ylabel('Signal')", source)
        self.assertIn("ax.yaxis.label.set_visible(False)", source)
        self.assertIn("ax.set_ylim(-2.0, 12.0)", source)
        self.assertIn("for _hyde_tick in ax.yaxis.get_major_ticks() + ax.yaxis.get_minor_ticks():", source)
        self.assertIn("_hyde_tick.label2.set_color('#00aa00')", source)
        self.assertIn("_hyde_tick.label2.set_rotation(35.0)", source)
        self.assertIn("ax.axhline(0, linestyle='--', linewidth=2.0, color='#654321')", source)

    def test_figure_ir_lowers_partial_axis_ranges_and_resolved_side_state_to_python(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        with_top_layer = FigureIRCodec.update_state(
            figure_ir,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "top",
                "state": {
                    "draw_on_top": True,
                },
            },
        )
        updated = FigureIRCodec.update_state(
            with_top_layer,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {
                    "range": {
                        "limits": (0.0, 8.0),
                        "limit_mode": {"min": "manual", "max": "auto"},
                        "autoscale": "data",
                    },
                },
            },
        )
        updated = FigureIRCodec.update_state(
            updated,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "y",
                "state": {
                    "range": {
                        "limits": (-4.0, 3.0),
                        "limit_mode": {"min": "auto", "max": "manual"},
                        "autoscale": "data",
                    },
                },
            },
        )

        source = FigureIRCodec.state_to_python(updated)

        self.assertIn("ax.autoscale(enable=True, axis='x')", source)
        self.assertIn("ax.set_xlim(left=0.0)", source)
        self.assertIn("ax.autoscale(enable=True, axis='y')", source)
        self.assertIn("ax.set_ylim(top=3.0)", source)
        self.assertIn("ax.set_axisbelow(False)", source)
        self.assertNotIn("import matplotlib.transforms as mtransforms", source)
        self.assertNotIn("set_bounds(", source)
        self.assertNotIn("ax.set_position(", source)

    def test_figure_ir_lowers_subplot_margins_to_python(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        updated = FigureIRCodec.update_state(
            figure_ir,
            {
                "type": "set_subplot_margins",
                "subplot_id": "subplot0",
                "state": {
                    "left": 0.12,
                    "bottom": 0.2,
                    "right": 0.97,
                    "top": 0.98,
                },
            },
        )

        subplot = updated["layout"]["subplots"][0]
        self.assertEqual(
            subplot["margins"],
            {"left": 0.12, "bottom": 0.2, "right": 0.97, "top": 0.98},
        )

        source = FigureIRCodec.state_to_python(updated)

        self.assertIn(
            "fig.subplots_adjust(left=0.12, bottom=0.2, right=0.97, top=0.98)",
            source,
        )

    def test_default_diff_lowering_omits_blank_label_visibility_until_explicitly_hidden(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        defaults = _figure_defaults_snapshot(figure_ir)

        source = FigureIRCodec.state_to_python(
            figure_ir,
            context={"figure_defaults": defaults},
        )

        self.assertNotIn("label.set_visible(False)", source)

        hidden = FigureIRCodec.update_state(
            figure_ir,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {"label": {"visible": False}},
            },
        )
        hidden_source = FigureIRCodec.state_to_python(
            hidden,
            context={"figure_defaults": defaults},
        )

        self.assertIn("ax.xaxis.label.set_visible(False)", hidden_source)

    def test_set_axis_label_action_does_not_hide_blank_label_artist(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        cleared = FigureIRCodec.update_state(
            figure_ir,
            {
                "type": "set_axis_label",
                "subplot_id": "subplot0",
                "axis": "x",
                "label": "",
            },
        )

        self.assertIsNone(cleared["layout"]["subplots"][0]["axes"]["x"]["label"]["text"])
        self.assertTrue(cleared["layout"]["subplots"][0]["axes"]["x"]["label"]["visible"])

    def test_snapshot_payload_serializes_simple_single_axes_line_figure(self):
        figure = Figure()
        axes = figure.add_subplot(111)
        axes.set_title("DelayGraph")
        axes.plot([0, 1, 2], [1, 4, 9], label="fit_delay")

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["default_macro_name"], "Figure1")
        self.assertIsNone(payload["save_error"])
        self.assertIn("fig = plt.figure('Figure1')", payload["call_source"])
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

    def test_snapshot_payload_prefers_figure_ir_for_first_class_decorated_figure(self):
        plt = self._configure_hyde_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["tracked_names"], ["x", "y"])
        self.assertIsNone(payload["live_state"])
        self.assertEqual(payload["figure_ir"]["settings"]["title"], "Graph0")
        self.assertEqual(
            payload["resolved_axis_limits"]["subplot0"]["x"],
            tuple(float(value) for value in figure.axes[0].get_xlim()),
        )
        self.assertEqual(
            payload["resolved_axis_limits"]["subplot0"]["y"],
            tuple(float(value) for value in figure.axes[0].get_ylim()),
        )
        self.assertEqual(
            payload["trace_styles"]["subplot0"]["trace0"]["label"],
            "y",
        )
        self.assertEqual(
            payload["trace_styles"]["subplot0"]["trace0"]["linestyle"],
            "-",
        )
        self.assertIn("ax.plot(x, y, label='y')", payload["call_source"])
        self.assertEqual(
            [entry["op"] for entry in payload["command_log"]],
            ["add_subplot", "plot"],
        )
        subplot = payload["figure_ir"]["layout"]["subplots"][0]
        self.assertEqual(subplot["axes"]["x"]["label"]["side"], "bottom")
        self.assertEqual(subplot["axes"]["x"]["range"]["limit_mode"], {"min": "auto", "max": "auto"})
        self.assertEqual(
            sorted(subplot["axis_sides"]),
            ["bottom", "left", "right", "top"],
        )

    def test_snapshot_payload_keeps_build_time_defaults_when_rcparams_change_later(self):
        plt = self._configure_hyde_pyplot()

        with matplotlib.rc_context({"lines.linewidth": 3.25}):
            @hyde.figure
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])

        with matplotlib.rc_context({"lines.linewidth": 7.5}):
            payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(
            payload["figure_defaults"]["trace_styles"]["subplot0"]["trace0"]["linewidth"],
            3.25,
        )
        self.assertEqual(
            figure._hyde_defaults["trace_styles"]["subplot0"]["trace0"]["linewidth"],
            3.25,
        )
        self.assertNotIn("linewidth=3.25", payload["call_source"])

    def test_snapshot_payload_preserves_figsize_for_first_class_decorated_figure(self):
        plt = self._configure_hyde_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0", figsize=(5.0, 3.0))
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["figure_ir"]["settings"]["figsize"], (5.0, 3.0))
        self.assertIn("fig = plt.figure('Graph0', figsize=(5.0, 3.0))", payload["call_source"])

    def test_snapshot_payload_includes_kernel_defaults_and_omits_matching_default_output(self):
        plt = self._configure_hyde_pyplot()

        with matplotlib.rc_context(
            {
                "axes.labelpad": 9.0,
                "lines.linestyle": "--",
                "lines.linewidth": 3.25,
                "xtick.direction": "in",
                "ytick.direction": "in",
            }
        ):
            @hyde.figure
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])
            apply_figure_action(
                figure,
                {
                    "type": "set_trace_style",
                    "subplot_id": "subplot0",
                    "trace_id": "trace0",
                    "style": {
                        "linestyle": "--",
                        "linewidth": 3.25,
                    },
                },
            )
            apply_figure_action(
                figure,
                {
                    "type": "set_axis_state",
                    "subplot_id": "subplot0",
                    "axis": "x",
                    "state": {
                        "label": {
                            "offset": 9.0,
                        },
                        "ticks": {
                            "direction": "inside",
                        },
                    },
                },
            )

            payload = figure_snapshot_payload(figure, 1)

        defaults = payload["figure_defaults"]
        subplot_defaults = defaults["layout"]["subplots"][0]
        self.assertEqual(subplot_defaults["traces"][0]["kwargs"]["linestyle"], "--")
        self.assertEqual(subplot_defaults["traces"][0]["kwargs"]["linewidth"], 3.25)
        self.assertEqual(subplot_defaults["axes"]["x"]["label"]["offset"], 9.0)
        self.assertEqual(subplot_defaults["axes"]["x"]["ticks"]["direction"], "inside")
        self.assertEqual(defaults, figure._hyde_defaults)
        self.assertNotIn("linestyle='--'", payload["call_source"])
        self.assertNotIn("linewidth=3.25", payload["call_source"])
        self.assertNotIn("ax.tick_params(", payload["call_source"])
        self.assertNotIn("labelpad = 9.0", payload["call_source"])
        self.assertNotIn("ax.set_xlabel(None)", payload["call_source"])

    def test_snapshot_payload_includes_hyde_figure_metadata(self):
        plt = self._configure_hyde_pyplot()

        @hyde.figure(window_pos=(10, 20), window_state="minimized")
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])
        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(
            payload["hyde_metadata"],
            {"window_pos": (10, 20), "window_state": "minimized"},
        )

    def test_snapshot_payload_keeps_undecorated_hyde_backend_figures_second_class(self):
        plt = self._configure_hyde_pyplot()
        figure = plt.figure("Plain")
        axis = figure.add_subplot(111)
        axis.plot([0, 1, 2], [1, 4, 9], label="y")

        payload = figure_snapshot_payload(figure, 1)

        self.assertFalse(payload["is_first_class"])
        self.assertIsNone(payload.get("figure_ir"))
        self.assertIsNone(payload.get("command_log"))
        self.assertIn("ax.plot(np.array([1, 4, 9])", payload["call_source"])

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

    def test_manager_shows_undecorated_figure_in_terminal_without_comm(self):
        plt = self._configure_hyde_pyplot()
        figure = plt.figure("Plain")
        figure.add_subplot(111).plot([0, 1, 2], [1, 4, 9], label="y")
        manager = figure.canvas.manager

        with patch("hyde.matplotlib_backend.Comm") as comm_cls, patch(
            "hyde.matplotlib_backend._display_in_ipython_terminal"
        ) as display_terminal:
            manager.show()

        comm_cls.assert_not_called()
        display_terminal.assert_called_once_with(figure)

    def test_manager_opens_comm_for_decorated_figure_before_builder_returns(self):
        plt = self._configure_hyde_pyplot()

        with patch("hyde.matplotlib_backend.Comm") as comm_cls:
            fake_comm = comm_cls.return_value
            fake_comm.send.return_value = None
            fake_comm.close.return_value = None

            @hyde.figure(register=False)
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                fig.show()
                return fig

            Graph0([0, 1, 2], [1, 4, 9])

        comm_cls.assert_called()

    def test_manager_destroy_closes_comm_even_if_close_payload_send_fails(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)
        manager = FigureManagerHyde(canvas, 3)
        closed = []

        class FakeComm:
            def send(self, payload):
                del payload
                raise RuntimeError("boom")

            def close(self):
                closed.append(True)

        manager._comm = FakeComm()

        manager.destroy()

        self.assertEqual(closed, [True])

    def test_manager_destroy_logs_close_payload_send_failure(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)
        manager = FigureManagerHyde(canvas, 3)

        class FakeComm:
            def send(self, payload):
                del payload
                raise RuntimeError("boom")

            def close(self):
                return None

        manager._comm = FakeComm()

        with self.assertLogs("hyde", level="ERROR") as logs:
            manager.destroy()

        self.assertTrue(
            any("close payload" in message and "figure 3" in message for message in logs.output)
        )

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    class _FakeSaveWindowDialogService:
        def __init__(self, result=True):
            self.result = result
            self.calls = []

        def prompt_to_save_window_macro(self, **kwargs):
            self.calls.append(kwargs)
            return self.result

    def test_figure_window_refreshes_from_same_namespace_signal_as_tables(self):
        sent = []
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
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: (
                                sent.append((figure_number, action)) or True
                            )
                        )
                    },
                )(),
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

            self.assertEqual(sent, [(1, {"type": "refresh_from_live_state"})])
        finally:
            widget.close()

    def test_figure_window_detects_in_place_namespace_metadata_mutation(self):
        sent = []
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
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: (
                                sent.append((figure_number, action)) or True
                            )
                        )
                    },
                )(),
                "namespace_view_service": namespace_service,
            },
        )
        try:
            widget.set_live_state(self._live_state())
            sent.clear()
            shared_view[0] = "[10 40 90]"
            namespace_service.emit(
                {
                    "delay": {"type": "ndarray", "view": "[0 1 2]"},
                    "fit_delay": {"type": "ndarray", "view": shared_view},
                    "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
                }
            )

            self.assertEqual(sent, [(1, {"type": "refresh_from_live_state"})])
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
        sent = []
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
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: (
                                sent.append((figure_number, action)) or True
                            )
                        )
                    },
                )(),
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

            self.assertEqual(len(sent), 2)
            self.assertEqual(sent[1], (1, {"type": "refresh_from_live_state"}))
        finally:
            widget.close()

    def test_figure_window_context_menu_activates_bound_subwindow(self):
        popup_calls = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "mdi_area": mdi_area,
                "popup_menu": lambda location, global_pos: popup_calls.append(
                    (location, global_pos)
                ),
            },
        )
        other = QtWidgets.QWidget()
        other_subwindow = mdi_area.addSubWindow(other)
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        other_subwindow.show()
        subwindow.show()
        self.qapp.processEvents()
        mdi_area.setActiveSubWindow(other_subwindow)

        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse,
            QtCore.QPoint(5, 5),
            QtCore.QPoint(20, 30),
        )
        widget.contextMenuEvent(event)

        self.assertIs(mdi_area.activeSubWindow(), subwindow)
        self.assertEqual(popup_calls, [("figure", QtCore.QPoint(20, 30))])

        widget.force_close()
        other.close()

    def test_figure_window_close_honors_save_prompt_cancel(self):
        queued = []
        save_window_dialog_service = self._FakeSaveWindowDialogService(result=False)
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": save_window_dialog_service,
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()

        self.assertEqual(len(save_window_dialog_service.calls), 1)
        self.assertEqual(set(save_window_dialog_service.calls[0]), {"saveable"})
        self.assertEqual(queued, [])
        self.assertFalse(widget._closed)
        self.assertFalse(widget._kernel_close_in_progress)

        widget.force_close()

    def test_figure_window_close_waits_for_kernel_confirmation(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
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
        widget.close_from_kernel()
        self.qapp.processEvents()

        self.assertTrue(widget._closed)

    def test_figure_window_ignores_duplicate_close_while_waiting_for_kernel_confirmation(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()
        subwindow.close()
        self.qapp.processEvents()

        self.assertEqual(queued, [("plt.close(1)", True)])
        self.assertTrue(widget._kernel_close_in_progress)
        self.assertFalse(widget._closed)

        widget.close_from_kernel()
        self.qapp.processEvents()

    def test_figure_window_shutdown_close_bypasses_kernel_queue_and_closes_immediately(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
                "get_shutting_down": lambda: True,
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()

        self.assertEqual(queued, [])
        self.assertTrue(widget._closed)
        self.assertFalse(widget._kernel_close_in_progress)
        self.assertFalse(subwindow.isVisible())

    def test_figure_window_close_timeout_clears_in_flight_close(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
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

    def test_figure_window_close_timeout_logs_warning(self):
        widget = FigureWindow(figure_number=7)
        widget._kernel_close_in_progress = True

        with self.assertLogs("hyde", level="WARNING") as logs:
            widget._on_close_timeout()

        self.assertFalse(widget._kernel_close_in_progress)
        self.assertTrue(any("close confirmation timed out" in message for message in logs.output))

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
        available_size = QtCore.QSize(
            max(160, mdi_area.viewport().width() - max(0, frame_size.width())),
            max(120, mdi_area.viewport().height() - max(0, frame_size.height())),
        )
        if (
            expected_size.width() > available_size.width()
            or expected_size.height() > available_size.height()
        ):
            expected_size.scale(available_size, QtCore.Qt.KeepAspectRatio)
        contents_size = subwindow.contentsRect().size()

        self.assertEqual(contents_size.width(), expected_size.width())
        self.assertEqual(contents_size.height(), expected_size.height())
        self.assertLessEqual(subwindow.width(), mdi_area.viewport().width())
        self.assertLessEqual(subwindow.height(), mdi_area.viewport().height())
        main.close()

    def test_figure_window_does_not_resize_redraw_before_initial_size_is_applied(self):
        sent = []
        widget = FigureWindow(
            figure_number=1,
            services={
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: (
                                sent.append((figure_number, action)) or True
                            )
                        )
                    },
                )(),
            },
        )
        try:
            widget._on_resize_redraw_timeout()
            self.assertEqual(sent, [])

            widget._initial_size_applied = True
            widget.image_label.resize(320, 240)
            widget._on_resize_redraw_timeout()

            self.assertEqual(
                sent,
                [(1, {"type": "resize_redraw", "width": 320, "height": 240})],
            )
        finally:
            widget.close()

    def test_workspace_ignores_non_first_class_figure_payload(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)

        figure = workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": False,
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "live_state": self._live_state_with_title("FigureA"),
                },
            }
        )
        self.qapp.processEvents()

        self.assertIsNone(figure)
        self.assertEqual(workspace.figures, {})
        workspace.clear()
        mdi_area.close()

    def test_workspace_uses_snapshot_figure_ir_without_live_state_bridge(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                },
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertEqual(figure.window_handle(), "FigureA")
        self.assertEqual(figure.parentWidget().objectName(), "FigureA")
        self.assertEqual(figure.parentWidget().windowTitle(), "FigureA")
        self.assertEqual(figure.snapshot_state.figure_ir()["settings"]["title"], "FigureA")
        self.assertIsNone(figure.snapshot_state.live_state())
        workspace.clear()
        mdi_area.close()

    def test_workspace_requires_save_window_dialog_service_for_first_class_windows(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        with self.assertRaises(KeyError):
            workspace.open_or_update_figure(
                {
                    "figure_number": 1,
                    "title": "FigureA",
                    "snapshot": {
                        "is_first_class": True,
                        "default_macro_name": "FigureA",
                        "call_source": "fig = plt.figure('FigureA')",
                        "figure_size": (320, 240),
                        "figure_ir": figure_ir,
                    },
                }
            )

        mdi_area.close()

    def test_workspace_applies_snapshot_window_metadata_for_new_macro_window(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {
                        "window_pos": [30, 40],
                        "window_state": "minimized",
                    },
                },
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertEqual(figure.capture_geometry()[:2], [30, 40])
        self.assertTrue(figure.parentWidget().isMinimized())
        workspace.clear()
        mdi_area.close()

    def test_workspace_reapplies_window_pos_after_first_draw_initial_size(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {"window_pos": [120, 130]},
                },
            }
        )
        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {"window_pos": [120, 130]},
                },
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertEqual(figure.capture_geometry()[:2], [120, 130])
        workspace.clear()
        mdi_area.close()

    def test_workspace_applies_snapshot_minimized_metadata_for_new_macro_window(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "hyde_metadata": {"window_state": "minimized"},
            },
        }
        workspace.open_or_update_figure(payload)
        workspace.open_or_update_figure(
            {
                **payload,
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertTrue(figure.parentWidget().isMinimized())
        workspace.clear()
        mdi_area.close()

    def test_minimized_workspace_restore_keeps_first_draw_pixmap(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "hyde_metadata": {"window_state": "minimized"},
            },
        }
        workspace.open_or_update_figure(payload)
        workspace.open_or_update_figure(
            {
                **payload,
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertTrue(figure.parentWidget().isMinimized())
        self.assertIsNotNone(figure.image_label.pixmap())
        self.assertFalse(figure.image_label.pixmap().isNull())
        figure.parentWidget().showNormal()
        self.qapp.processEvents()
        self.assertFalse(figure.parentWidget().isMinimized())
        self.assertIsNotNone(figure.image_label.pixmap())
        self.assertFalse(figure.image_label.pixmap().isNull())
        workspace.clear()
        mdi_area.close()

    def test_workspace_applies_snapshot_maximized_metadata_for_new_macro_window(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {"window_state": "maximized"},
                },
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertTrue(figure.parentWidget().isMaximized())
        workspace.clear()
        mdi_area.close()

    def test_minimized_workspace_restore_returns_to_saved_normal_position(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {
                        "window_pos": [120, 130],
                        "window_state": "minimized",
                    },
                },
            }
        )
        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {
                        "window_pos": [120, 130],
                        "window_state": "minimized",
                    },
                },
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        subwindow = figure.parentWidget()
        self.assertTrue(subwindow.isMinimized())
        subwindow.showNormal()
        self.qapp.processEvents()

        self.assertEqual(figure.capture_geometry()[:2], [120, 130])
        workspace.clear()
        mdi_area.close()

    def test_plugin_session_toml_omits_figure_name_counters(self):
        plugin = Plugin({})
        plugin.services = {
            "python_execution_service": FakeExecutionService(),
        }
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin.services.update(
            {
                "mdi_area": mdi_area,
                "namespace_view_service": FakeNamespaceViewService(),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
                "get_shutting_down": lambda: False,
            }
        )
        figure = FigureWindow(figure_number=1)
        subwindow = mdi_area.addSubWindow(figure)
        figure.bind_subwindow(subwindow)
        subwindow.destroyed.connect(
            lambda *_, number=1, workspace=plugin.workspace: (
                workspace._remove_figure(number)
            )
        )
        subwindow.setGeometry(10, 20, 300, 220)
        plugin.workspace.figures[1] = figure
        figure.update_payload(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "live_state": None,
                },
            }
        )

        toml_data = plugin.get_session_toml_data()

        self.assertEqual(toml_data, {})
        figure.close()
        mdi_area.close()

    def test_closed_figures_are_absent_from_session_restore_source(self):
        plugin = Plugin({})
        plugin.services = {
            "python_execution_service": FakeExecutionService(),
        }
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin.services.update(
            {
                "mdi_area": mdi_area,
                "namespace_view_service": FakeNamespaceViewService(),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
                "get_shutting_down": lambda: False,
            }
        )
        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "live_state": None,
            },
        }
        figure = plugin.workspace.open_or_update_figure(payload)
        figure.parentWidget().setGeometry(10, 20, 300, 220)

        session_source = plugin.get_session_restore_source()

        self.assertIn("FigureA(delay, fit_delay, raw_delay)", session_source)
        self.assertIn("fig = plt.figure('FigureA')", session_source)

        plugin.workspace.close_figure(1)
        self.qapp.processEvents()

        self.assertEqual(plugin.get_session_restore_source(), "")
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
    def test_matplotlib_figure_and_axes_are_excluded_from_kernel_persistence(self):
        figure = Figure()
        axes = figure.add_subplot(111)

        self.assertTrue(is_excluded("fig", figure))
        self.assertTrue(is_excluded("ax", axes))


class TestFigureWindowBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _figure_ir(self, *, items=("trace_a", "trace_b")):
        state = FigureState()
        state.set_title("Figure0")
        state.set_x_name("x")
        state.set_items(list(items))
        return figure_ir_from_live_state(state.normalized_state())

    def test_figure_window_reports_supported_trace_records_from_snapshot_ir(self):
        widget = FigureWindow(figure_number=1)
        try:
            widget.update_payload(
                {
                    "snapshot": {
                        "figure_ir": self._figure_ir(),
                    }
                }
            )

            self.assertEqual(
                widget.supported_trace_records(),
                (
                    {
                        "subplot_id": "subplot0",
                        "trace_id": "trace0",
                        "label": "trace_a",
                        "x_name": "x",
                        "y_name": "trace_a",
                        "trace": {
                            "id": "trace0",
                            "kind": "line",
                            "kwargs": {"label": "trace_a"},
                            "x_source": {"kind": "name", "value": "x"},
                            "y_source": {"kind": "name", "value": "trace_a"},
                        },
                    },
                    {
                        "subplot_id": "subplot0",
                        "trace_id": "trace1",
                        "label": "trace_b",
                        "x_name": "x",
                        "y_name": "trace_b",
                        "trace": {
                            "id": "trace1",
                            "kind": "line",
                            "kwargs": {"label": "trace_b"},
                            "x_source": {"kind": "name", "value": "x"},
                            "y_source": {"kind": "name", "value": "trace_b"},
                        },
                    },
                ),
            )
            self.assertTrue(widget.has_supported_traces())
        finally:
            widget.close()

    def test_figure_window_reports_editable_readiness_from_ir_and_dispatch(self):
        widget = FigureWindow(
            figure_number=1,
            services={
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: True
                        )
                    },
                )(),
            },
        )
        try:
            self.assertFalse(widget.has_figure_ir())
            self.assertTrue(widget.can_request_figure_actions())
            self.assertFalse(widget.is_editable_figure_ready())

            widget.update_payload(
                {
                    "snapshot": {
                        "figure_ir": self._figure_ir(items=("trace_a",)),
                    }
                }
            )

            self.assertTrue(widget.has_figure_ir())
            self.assertTrue(widget.can_request_figure_actions())
            self.assertTrue(widget.is_editable_figure_ready())
        finally:
            widget.close()


class TestFigureContextService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _figure_ir(self):
        state = FigureState()
        state.set_title("Figure0")
        state.set_x_name("x")
        state.set_items(["trace_a"])
        return figure_ir_from_live_state(state.normalized_state())

    def test_active_editable_figure_returns_boundary_context(self):
        mdi_area = QtWidgets.QMdiArea()
        sent = []
        widget = FigureWindow(
            figure_number=1,
            services={
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: (
                                sent.append((int(figure_number), dict(action or {})))
                                or True
                            )
                        )
                    },
                )(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.show()
        mdi_area.setActiveSubWindow(subwindow)
        widget.update_payload({"snapshot": {"figure_ir": self._figure_ir()}})

        service = FigureContextService(type("Plugin", (), {"services": {"mdi_area": mdi_area}})())
        try:
            context = service.active_editable_figure()

            self.assertIsNotNone(context)
            self.assertEqual(context.figure_number, 1)
            self.assertEqual(context.supported_trace_records(), widget.supported_trace_records())
            self.assertTrue(context.request_figure_action({"type": "refresh_from_live_state"}))
            self.assertEqual(
                sent,
                [(1, {"type": "refresh_from_live_state"})],
            )
        finally:
            widget.close()


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
