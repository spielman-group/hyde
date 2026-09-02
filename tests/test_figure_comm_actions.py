import unittest
from unittest.mock import patch

import numpy as np

import hyde

try:
    import matplotlib
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

from hyde.matplotlib_backend import apply_figure_action, figure_snapshot_payload
from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow
from hyde.user_interface.shared.core import log_hyde_dispatch_debug


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
        return figure_ir_from_live_state(
            {
                "feature": "figure_command",
                "settings": {
                    "command": "create",
                    "title": title,
                    "x_name": "delay",
                    "subplot_code": "111",
                    "figsize": None,
                },
                "items": ["fit_delay", "raw_delay"],
                "ui": {},
            }
        )

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

    def _saved_recreation_macro(self, plt):
        """Hyde's own saved macro for a figure built at the prompt.

        Taking the macro from Hyde rather than writing one that resembles it
        is the whole point: what breaks a re-run is a line Hyde emits.
        """

        @hyde.figure(register=False)
        def Graph0(y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(y, label="y")
            fig.show()
            return fig

        figure = Graph0([1.0, 4.0, 9.0])
        payload = figure_snapshot_payload(figure, figure.canvas.manager.num)
        source = FigureIR(
            figure_state=payload["figure_ir"],
            figure_defaults=payload["figure_defaults"],
        ).recreation_function_source("Graph0", register=False)
        plt.close("all")
        namespace = {"hyde": hyde, "plt": plt, "np": np}
        exec(compile(source, "<session.py>", "exec"), namespace)
        return namespace["Graph0"]

    def test_a_saved_recreation_macro_can_be_run_again(self):
        """Re-running is what a recreation macro is for.

        `plt.figure(label)` hands back the figure that already exists rather
        than constructing one, so a macro that runs a second time replaces
        that figure's contents instead of drawing over them. Its `fig.show()`
        pushes the result straight through the open comm, so a figure Hyde
        can no longer describe raises inside the macro.
        """
        plt = self._configure_pyplot()
        pushed = []

        class RecordingComm:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            def on_msg(self, callback):
                del callback

            def on_close(self, callback):
                del callback

            def send(self, payload):
                pushed.append(payload)

            def close(self):
                return None

        with patch("hyde.matplotlib_backend.Comm", RecordingComm):
            macro = self._saved_recreation_macro(plt)
            first = macro([1.0, 4.0, 9.0])
            again = macro([2.0, 5.0, 10.0])

        self.assertIs(again, first)
        self.assertEqual("Graph0", again.get_label())
        self.assertEqual(1, len(again.axes), "re-running stacked another axes")
        self.assertEqual(
            [2.0, 5.0, 10.0],
            list(again.axes[0].lines[0].get_ydata()),
        )
        drawn = [payload for payload in pushed if payload["event"] == "draw"]
        self.assertTrue(drawn, "the re-run pushed no drawing to Hyde")
        self.assertIsNone(drawn[-1]["snapshot"]["save_error"])

    def test_a_re_run_figure_can_still_be_saved_as_a_macro(self):
        """A figure Hyde cannot snapshot is a figure the user cannot save.

        Nothing pushes a snapshot while the figure window is closed, so a
        re-run that leaves the figure undescribable surfaces only when the
        user next saves the project.
        """
        plt = self._configure_pyplot()
        macro = self._saved_recreation_macro(plt)

        macro([1.0, 4.0, 9.0])
        again = macro([2.0, 5.0, 10.0])
        payload = figure_snapshot_payload(again, again.canvas.manager.num)

        self.assertTrue(payload["is_first_class"])
        self.assertIsNone(payload["save_error"])
        subplots = payload["figure_ir"]["layout"]["subplots"]
        self.assertEqual(1, len(subplots))
        self.assertEqual(1, len(subplots[0]["traces"]))

    def test_a_macro_may_draw_on_another_figure_while_building_its_own(self):
        """Drawing on a figure is not the same as building it."""
        plt = self._configure_pyplot()

        @hyde.figure(register=False)
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            fig.clear()
            fig.add_subplot(111).plot(x, y)
            return fig

        neighbour = Graph0([0, 1, 2], [1, 4, 9])

        @hyde.figure(register=False)
        def Graph1(x, y):
            plt.figure("Graph0").axes[0].plot(x, y)
            fig = plt.figure("Graph1")
            fig.clear()
            fig.add_subplot(111).plot(x, y)
            return fig

        built = Graph1([0, 1, 2], [3, 6, 9])

        self.assertEqual("Graph1", built.get_label())
        self.assertIsNot(built, neighbour)

    def test_a_figure_built_without_hydes_backend_says_so(self):
        """"must create exactly one figure" sends the reader to the wrong place.

        A plain matplotlib figure means the process is on another backend, and
        the function plainly did create a figure.
        """
        from matplotlib.figure import Figure

        from hyde.matplotlib_backend import (
            begin_figure_build_session,
            end_figure_build_session,
            finalize_figure_build_session,
        )

        def build():
            return None

        session = begin_figure_build_session(build, (), {})
        end_figure_build_session(session)
        with self.assertRaises(ValueError) as caught:
            finalize_figure_build_session(session, Figure())

        self.assertIn("backend is not active", str(caught.exception))

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

    def test_apply_figure_action_rejects_regenerate_from_ir_after_refresh_moves_to_command_path(self):
        plt = self._configure_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])
        with self.assertRaisesRegex(ValueError, "Unsupported figure action"):
            apply_figure_action(figure, {"type": "regenerate_from_ir"})

    def test_figure_window_routes_resize_as_action_and_regenerate_as_hidden_python(self):
        sent = []
        hidden = []
        window = FigureWindow(
            figure_number=7,
            services={
                "get_shutting_down": lambda: True,
                "python_execution_service": type(
                    "PythonExecutionService",
                    (),
                    {
                        "execute_hidden": (
                            lambda _self, code, silent=True: (
                                log_hyde_dispatch_debug("hidden", code) or
                                hidden.append((code, silent)) or True
                            )
                        )
                    },
                )(),
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
            figure_ir = self._live_state_with_title("Figure0")
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
            with self.assertLogs("hyde", level="DEBUG") as logs:
                self.assertTrue(window.request_regenerate_from_ir())

            self.assertEqual(sent, [(7, {"type": "resize_redraw", "width": 800, "height": 600})])
            self.assertEqual(len(hidden), 1)
            self.assertTrue(hidden[0][1])
            self.assertEqual(
                hidden[0][0],
                FigureIR()
                .with_refresh_figure("Figure0", use_bound_values=True)
                .python_source(log=False),
            )
            output = "\n".join(logs.output)
            self.assertIn("[Hyde state] TransportDispatchState", output)
            self.assertIn("'mode': 'hidden'", output)
            self.assertIn("python:\n", output)
            self.assertIn("hyde.refresh_figure(fig, use_bound_values=True)", output)
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
