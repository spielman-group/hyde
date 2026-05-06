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
        self.assertEqual(tuple(figure.axes[0].get_xlim()), (-1.0, 5.0))

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
