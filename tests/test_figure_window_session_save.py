import unittest

from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.user_interface.plugins.figure.window import (
    FigureSnapshotState,
    FigureState,
    FigureWindow,
)


class TestFigureWindowSessionSave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _live_state_with_title(self, title):
        state = FigureState()
        state.set_title(title)
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])
        return state.normalized_state()

    def _live_state_with_title_and_figsize(self, title, figsize):
        state = FigureState()
        state.set_title(title)
        state.set_x_name("delay")
        state.set_items(["fit_delay", "raw_delay"])
        state.set_figsize(*figsize)
        return state.normalized_state()

    def test_snapshot_state_derives_recreation_source_from_figure_ir(self):
        snapshot = FigureSnapshotState()
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("Figure0"))

        snapshot.update(
            default_macro_name=None,
            call_source=None,
            tracked_names=None,
            figure_ir=figure_ir,
            live_state=None,
        )

        self.assertEqual(snapshot.default_macro_name(), "Figure0")
        self.assertEqual(snapshot.tracked_names(), ("delay", "fit_delay", "raw_delay"))
        self.assertIn("fig = plt.figure('Figure0')", snapshot.call_source())
        macro = snapshot.macro_source("Graph0")
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", macro)
        self.assertIn("fig.show()", macro)
        self.assertNotIn("fig.canvas.draw_idle()", macro)
        self.assertNotIn("return fig", macro)

    def test_figure_window_macro_source_includes_window_pos_metadata(self):
        widget = FigureWindow(figure_number=1)
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(widget)
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("Figure0"))
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Figure0",
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "live_state": None,
                        "hyde_metadata": {},
                    },
                }
            )

            macro = widget.macro_source("Graph0")

            self.assertIn("@hyde.figure(window_pos=(10, 20))", macro)
            self.assertIn("fig = plt.figure('Figure0')", macro)
        finally:
            widget.close()

    def test_figure_window_session_restore_source_uses_figure_ir_without_live_state(self):
        widget = FigureWindow(figure_number=1)
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(widget)
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("Figure0"))
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Figure0",
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "live_state": None,
                    },
                }
            )

            source = widget.session_restore_source()

            self.assertIn("@hyde.figure(window_pos=(10, 20), register=False)", source)
            self.assertIn("def Figure0(delay, fit_delay, raw_delay):", source)
            self.assertIn("Figure0(delay, fit_delay, raw_delay)", source)
            self.assertIn("fig = plt.figure('Figure0')", source)
            self.assertIn(
                "ax.plot(delay, fit_delay, label='fit_delay')",
                source,
            )
        finally:
            widget.close()

    def test_figure_window_sources_preserve_figsize_from_figure_ir(self):
        widget = FigureWindow(figure_number=1)
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(widget)
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        figure_ir = figure_ir_from_live_state(
            self._live_state_with_title_and_figsize("Figure0", (5.0, 3.0))
        )
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Figure0",
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "live_state": None,
                    },
                }
            )

            macro = widget.macro_source("Figure0")
            source = widget.session_restore_source()

            self.assertIn("fig = plt.figure('Figure0', figsize=(5.0, 3.0))", macro)
            self.assertIn("fig = plt.figure('Figure0', figsize=(5.0, 3.0))", source)
        finally:
            widget.close()

    def test_session_restore_source_reuses_same_function_source_as_macro_save(self):
        widget = FigureWindow(figure_number=1)
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(widget)
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        figure_ir = figure_ir_from_live_state(
            self._live_state_with_title_and_figsize("Figure0", (5.0, 3.0))
        )
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Figure0",
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "live_state": None,
                    },
                }
            )

            macro_lines = widget.macro_source("Figure0").splitlines()
            session_lines = widget.session_restore_source().splitlines()

            self.assertEqual(
                session_lines[:-2],
                [
                    "@hyde.figure(window_pos=(10, 20), register=False)",
                    *macro_lines[1:],
                ],
            )
            self.assertEqual(session_lines[-1], "Figure0(delay, fit_delay, raw_delay)")
        finally:
            widget.close()
