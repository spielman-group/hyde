import unittest

import hyde

try:
    import matplotlib
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

from hyde.matplotlib_backend import apply_figure_action
from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.user_interface.plugins.figure_interactive.window import FigureState, FigureWindow


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

    def test_apply_figure_action_rejects_routine_semantic_edit_actions(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        with self.assertRaisesRegex(ValueError, "Unsupported figure action"):
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

    def test_apply_figure_action_regenerates_live_figure_from_ir(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])
        figure._hyde_ir["layout"]["subplots"][0]["legend"] = True
        figure.clear()

        apply_figure_action(figure, {"type": "regenerate_from_ir"})

        self.assertEqual(len(figure.axes), 1)
        self.assertEqual(len(figure.axes[0].lines), 1)
        self.assertEqual(figure.axes[0].lines[0].get_label(), "y")
        self.assertIsNotNone(figure.axes[0].get_legend())
        self.assertEqual(
            [text.get_text() for text in figure.axes[0].get_legend().texts],
            ["y"],
        )

    def test_figure_window_requests_resize_and_regenerate_actions(self):
        sent = []
        window = FigureWindow(
            figure_number=7,
            services={
                "get_shutting_down": lambda: True,
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: (
                                sent.append((figure_number, dict(action or {})))
                                or True
                            )
                        )
                    },
                )(),
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
            window.force_close()

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

            del main_namespace["delay"]
            hyde.refresh_figure(figure)

            self.assertEqual(len(figure.axes[0].lines), 0)
        finally:
            for name, value in previous_values.items():
                if value is None:
                    main_namespace.pop(name, None)
                else:
                    main_namespace[name] = value


if __name__ == "__main__":
    unittest.main()
