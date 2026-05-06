import unittest

import hyde

try:
    import matplotlib
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

from hyde.matplotlib_backend import apply_figure_action
from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.user_interface.plugins.figure.window import FigureState, FigureWindow


class TestFigureCommActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from qtutils.qt import QtWidgets
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("Qt is required") from exc
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def tearDown(self):
        pyplot = getattr(matplotlib, "pyplot", None)
        if pyplot is not None:
            pyplot.close("all")

    def _live_state_with_title(self, title):
        state = FigureState()
        state.set_title(title)
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])
        return state.normalized_state()

    def _configure_pyplot(self):
        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as pyplot

        return pyplot

    def test_first_class_figure_keeps_kernel_owned_defaults_snapshot(self):
        plt = self._configure_pyplot()

        with matplotlib.rc_context({"lines.linewidth": 3.25}):
            @hyde.figure
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])

        defaults = figure._hyde_defaults
        self.assertEqual(
            defaults["layout"]["subplots"][0]["traces"][0]["kwargs"]["linewidth"],
            3.25,
        )
        self.assertEqual(
            defaults["trace_styles"]["subplot0"]["trace0"]["linewidth"],
            3.25,
        )

    def test_apply_figure_action_updates_ir_and_live_axis_limits(self):
        plt = self._configure_pyplot()

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
                "type": "set_axis_limits",
                "subplot_id": "subplot0",
                "axis": "x",
                "min": -1,
                "max": 5,
            },
        )

        subplot = figure._hyde_ir["layout"]["subplots"][0]
        self.assertEqual(subplot["x_limits"], (-1, 5))
        self.assertEqual(subplot["axes"]["x"]["range"]["limits"], (-1.0, 5.0))
        self.assertEqual(tuple(figure.axes[0].get_xlim()), (-1.0, 5.0))

    def test_apply_figure_action_updates_ir_and_live_trace_style_for_broader_line2d_kwargs(self):
        plt = self._configure_pyplot()

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
                    "visible": False,
                    "alpha": 0.25,
                    "drawstyle": "steps-mid",
                    "color": "green",
                    "linestyle": "None",
                    "linewidth": 3.5,
                    "marker": "s",
                    "markersize": 7.0,
                    "markerfacecolor": "red",
                    "markeredgecolor": "black",
                    "markeredgewidth": 2.0,
                },
            },
        )

        trace_kwargs = figure._hyde_ir["layout"]["subplots"][0]["traces"][0]["kwargs"]
        self.assertFalse(trace_kwargs["visible"])
        self.assertEqual(trace_kwargs["alpha"], 0.25)
        self.assertEqual(trace_kwargs["drawstyle"], "steps-mid")
        self.assertEqual(trace_kwargs["linestyle"], "None")
        self.assertEqual(trace_kwargs["linewidth"], 3.5)
        self.assertEqual(trace_kwargs["marker"], "s")
        self.assertEqual(trace_kwargs["markersize"], 7.0)
        self.assertEqual(trace_kwargs["markerfacecolor"], "red")
        self.assertEqual(trace_kwargs["markeredgecolor"], "black")
        self.assertEqual(trace_kwargs["markeredgewidth"], 2.0)

        line = figure.axes[0].lines[0]
        self.assertFalse(line.get_visible())
        self.assertEqual(line.get_alpha(), 0.25)
        self.assertEqual(line.get_drawstyle(), "steps-mid")
        self.assertEqual(line.get_color(), "green")
        self.assertEqual(line.get_linestyle(), "None")
        self.assertEqual(line.get_linewidth(), 3.5)
        self.assertEqual(line.get_marker(), "s")
        self.assertEqual(line.get_markersize(), 7.0)
        self.assertEqual(line.get_markerfacecolor(), "red")
        self.assertEqual(line.get_markeredgecolor(), "black")
        self.assertEqual(line.get_markeredgewidth(), 2.0)

    def test_apply_figure_action_updates_ir_and_live_axis_semantics(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([1, 2, 4, 8], [1, -1, 2, -2])

        apply_figure_action(
            figure,
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
        apply_figure_action(
            figure,
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
        apply_figure_action(
            figure,
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
        apply_figure_action(
            figure,
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
                        "limits": (-2.5, 2.5),
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

        subplot = figure._hyde_ir["layout"]["subplots"][0]
        self.assertEqual(subplot["axes"]["x"]["label"]["side"], "top")
        self.assertEqual(subplot["axes"]["y"]["label"]["side"], "right")
        self.assertFalse(subplot["axes"]["y"]["label"]["visible"])
        self.assertFalse(subplot["axis_sides"]["bottom"]["spine_visible"])
        self.assertEqual(subplot["axis_sides"]["right"]["tick_label_color"], "#00aa00")

        axis = figure.axes[0]
        self.assertEqual(axis.get_xscale(), "log")
        self.assertEqual(axis.xaxis.get_label_position(), "top")
        self.assertEqual(axis.get_xlabel(), "Delay")
        self.assertEqual(axis.xaxis.label.get_color(), "#aa5500")
        self.assertEqual(axis.xaxis.label._linespacing, 1.6)
        self.assertEqual(axis.xaxis.labelpad, 14.0)
        self.assertAlmostEqual(axis.xaxis.label.get_position()[0], 0.35)
        self.assertEqual(axis.yaxis.get_label_position(), "right")
        self.assertEqual(axis.get_ylabel(), "Signal")
        self.assertFalse(axis.yaxis.label.get_visible())
        self.assertEqual(tuple(axis.get_xlim()), (1.0, 8.0))
        self.assertEqual(tuple(axis.get_ylim()), (-2.5, 2.5))
        self.assertFalse(axis.spines["bottom"].get_visible())
        self.assertTrue(axis.spines["top"].get_visible())
        self.assertTrue(any(line.get_visible() for line in axis.get_xgridlines()))
        right_tick = axis.yaxis.get_major_ticks()[0]
        self.assertTrue(right_tick.label2.get_visible())
        self.assertEqual(right_tick.label2.get_color(), "#00aa00")
        self.assertEqual(right_tick.label2.get_rotation(), 35.0)
        self.assertEqual(len(axis.lines), 2)
        zero_line = axis.lines[1]
        self.assertEqual(list(zero_line.get_ydata()), [0, 0])
        self.assertEqual(zero_line.get_linestyle(), "--")
        self.assertEqual(zero_line.get_linewidth(), 2.0)

    def test_apply_figure_action_allows_hiding_side_with_label_text_on_same_side(self):
        plt = self._configure_pyplot()

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
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {
                    "label": {
                        "text": "asdf",
                        "visible": True,
                        "side": "bottom",
                    },
                },
            },
        )
        apply_figure_action(
            figure,
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

        subplot = figure._hyde_ir["layout"]["subplots"][0]
        self.assertEqual(subplot["axes"]["x"]["label"]["text"], "asdf")
        self.assertFalse(subplot["axis_sides"]["bottom"]["spine_visible"])
        self.assertFalse(subplot["axis_sides"]["bottom"]["ticks_visible"])
        self.assertFalse(subplot["axis_sides"]["bottom"]["tick_labels_visible"])

        axis = figure.axes[0]
        tick = axis.xaxis.get_major_ticks()[0]
        self.assertEqual(axis.get_xlabel(), "asdf")
        self.assertFalse(axis.spines["bottom"].get_visible())
        self.assertFalse(tick.tick1line.get_visible())
        self.assertFalse(tick.label1.get_visible())

    def test_apply_figure_action_resolves_partial_axis_ranges_and_side_state(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        x_values = [1, 2, 4, 8]
        y_values = [-3, -1, 2, -2]
        figure = Graph0(x_values, y_values)

        apply_figure_action(
            figure,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "bottom",
                "state": {
                    "draw_between": (0.1, 0.9),
                },
            },
        )
        apply_figure_action(
            figure,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "top",
                "state": {
                    "draw_on_top": True,
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
                    "range": {
                        "limits": (0.0, 8.0),
                        "limit_mode": {"min": "manual", "max": "auto"},
                        "autoscale": "data",
                    },
                },
            },
        )
        apply_figure_action(
            figure,
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

        expected_figure = plt.figure("Expected")
        expected_axis = expected_figure.add_subplot(111)
        expected_axis.plot(x_values, y_values, label="y")
        expected_axis.autoscale(enable=True, axis="x")
        expected_axis.set_xlim(left=0.0)
        expected_xlim = tuple(expected_axis.get_xlim())
        expected_axis.autoscale(enable=True, axis="y")
        expected_axis.set_ylim(top=3.0)
        expected_ylim = tuple(expected_axis.get_ylim())

        subplot = figure._hyde_ir["layout"]["subplots"][0]
        self.assertEqual(
            subplot["axes"]["x"]["range"]["limit_mode"],
            {"min": "manual", "max": "auto"},
        )
        self.assertEqual(
            subplot["axes"]["y"]["range"]["limit_mode"],
            {"min": "auto", "max": "manual"},
        )
        self.assertEqual(subplot["axis_sides"]["bottom"]["draw_between"], (0.1, 0.9))
        self.assertTrue(subplot["axis_sides"]["top"]["draw_on_top"])

        axis = figure.axes[0]
        self.assertEqual(tuple(axis.get_xlim()), expected_xlim)
        self.assertEqual(tuple(axis.get_ylim()), expected_ylim)
        expected_bounds = (
            expected_xlim[0] + (expected_xlim[1] - expected_xlim[0]) * 0.1,
            expected_xlim[0] + (expected_xlim[1] - expected_xlim[0]) * 0.9,
        )
        self.assertEqual(axis.spines["bottom"].get_bounds(), expected_bounds)
        self.assertFalse(axis.get_axisbelow())

    def test_apply_figure_action_regenerates_live_figure_from_ir(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])
        figure.clear()

        apply_figure_action(figure, {"type": "regenerate_from_ir"})

        self.assertEqual(len(figure.axes), 1)
        self.assertEqual(len(figure.axes[0].lines), 1)
        self.assertEqual(figure.axes[0].lines[0].get_label(), "y")

    def test_apply_figure_action_refreshes_from_live_state(self):
        plt = self._configure_pyplot()
        main_namespace = __import__("sys").modules["__main__"].__dict__
        previous_values = {
            name: main_namespace.get(name)
            for name in ("delay", "fit_delay")
        }
        try:
            main_namespace["delay"] = [0, 1, 2]
            main_namespace["fit_delay"] = [1, 4, 9]

            figure = plt.figure("Graph0")
            axis = figure.add_subplot(111)
            axis.plot(main_namespace["delay"], main_namespace["fit_delay"], label="fit_delay")

            state = FigureState()
            state.set_title("Graph0")
            state.set_x_name("delay")
            state.set_items(["fit_delay"])
            figure._hyde_live_state = state.normalized_state()

            main_namespace["fit_delay"] = [2, 5, 10]
            apply_figure_action(figure, {"type": "refresh_from_live_state"})

            self.assertEqual(
                list(figure.axes[0].lines[0].get_ydata()),
                [2, 5, 10],
            )
        finally:
            for name, value in previous_values.items():
                if value is None:
                    main_namespace.pop(name, None)
                else:
                    main_namespace[name] = value

    def test_figure_window_requests_resize_and_regenerate_actions(self):
        sent = []
        window = FigureWindow(
            figure_number=7,
            services={
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )
        try:
            figure_ir = figure_ir_from_live_state(self._live_state_with_title("Figure0"))
            window.update_payload(
                {
                    "figure_number": 7,
                    "title": "Figure0",
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "live_state": None,
                    },
                }
            )

            self.assertTrue(window.request_resize_redraw(width=800, height=600))
            self.assertTrue(window.request_regenerate_from_ir())

            self.assertEqual(
                sent,
                [
                    (7, {"type": "resize_redraw", "width": 800, "height": 600}),
                    (7, {"type": "regenerate_from_ir"}),
                ],
            )
        finally:
            window.close()

    def test_figure_window_requests_refresh_from_live_state_action(self):
        sent = []
        window = FigureWindow(
            figure_number=7,
            services={
                "send_figure_action": lambda figure_number, action: (
                    sent.append((figure_number, action)) or True
                ),
            },
        )
        try:
            window.set_live_state(self._live_state_with_title("Figure0"))

            self.assertTrue(window.request_refresh_from_live_state())
            self.assertEqual(sent, [(7, {"type": "refresh_from_live_state"})])
        finally:
            window.close()

    def test_refresh_figure_regenerates_first_class_figure_from_ir(self):
        plt = self._configure_pyplot()
        main_namespace = __import__("sys").modules["__main__"].__dict__
        previous_values = {
            name: main_namespace.get(name)
            for name in ("delay", "fit_delay")
        }
        try:
            main_namespace["delay"] = [0, 1, 2]
            main_namespace["fit_delay"] = [1, 4, 9]

            @hyde.figure
            def Graph0(delay, fit_delay):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(delay, fit_delay, label="fit_delay")
                return fig

            figure = Graph0(main_namespace["delay"], main_namespace["fit_delay"])
            main_namespace["fit_delay"] = [2, 5, 10]

            hyde.refresh_figure(figure)

            self.assertEqual(
                list(figure.axes[0].lines[0].get_ydata()),
                [2, 5, 10],
            )
        finally:
            for name, value in previous_values.items():
                if value is None:
                    main_namespace.pop(name, None)
                else:
                    main_namespace[name] = value


if __name__ == "__main__":
    unittest.main()
