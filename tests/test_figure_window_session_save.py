import unittest

from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import figure_ir_from_live_state
from hyde.user_interface.hyde_tool_widget import HydeToolWidget
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

    def test_figure_window_inherits_shared_shell(self):
        self.assertTrue(issubclass(FigureWindow, HydeToolWidget))

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

    def test_snapshot_state_preserves_figure_defaults_metadata(self):
        snapshot = FigureSnapshotState()
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("Figure0"))
        figure_defaults = {
            "settings": {"title": None, "figsize": (6.4, 4.8)},
            "trace_styles": {"subplot0": {"trace0": {"color": "#123456"}}},
        }

        snapshot.update(
            default_macro_name=None,
            call_source=None,
            tracked_names=None,
            figure_ir=figure_ir,
            figure_defaults=figure_defaults,
            live_state=None,
        )

        self.assertEqual(
            snapshot.figure_defaults()["trace_styles"]["subplot0"]["trace0"]["color"],
            "#123456",
        )

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
            self.assertIn("fig = plt.figure('Figure1')", macro)
        finally:
            widget.close()

    def test_figure_window_session_restore_source_uses_subwindow_object_name_as_stable_identity(self):
        widget = FigureWindow(figure_number=1)
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setObjectName("Figure7")
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("Graph0"))
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Graph0",
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "live_state": None,
                    },
                }
            )
            subwindow.show()
            self.qapp.processEvents()
            subwindow.showMinimized()
            self.qapp.processEvents()

            source = widget.session_restore_source()

            self.assertIn(
                "@hyde.figure(window_pos=(10, 20), window_state='minimized', register=False)",
                source,
            )
            self.assertIn("def Figure7(delay, fit_delay, raw_delay):", source)
            self.assertIn("Figure7(delay, fit_delay, raw_delay)", source)
            self.assertIn("fig = plt.figure('Figure7')", source)
            self.assertIn(
                "ax.plot(delay, fit_delay, label='fit_delay')",
                source,
            )
            self.assertNotIn("hidden=", source)
            self.assertNotIn("visible=", source)
        finally:
            widget.force_close()
            mdi_area.close()

    def test_figure_window_uses_subwindow_object_name_as_stable_identity(self):
        widget = FigureWindow(figure_number=1)
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setObjectName("Figure7")
        try:
            widget.bind_subwindow(subwindow)

            self.assertEqual(widget.window_handle(), "Figure7")
        finally:
            widget.force_close()
            mdi_area.close()

    def test_figure_window_canonicalizes_spaced_default_figure_name(self):
        widget = FigureWindow(figure_number=1)
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        try:
            widget.bind_subwindow(subwindow, stable_name="Figure 1")

            self.assertEqual(widget.window_handle(), "Figure1")
            self.assertEqual(subwindow.objectName(), "Figure1")
        finally:
            widget.force_close()
            mdi_area.close()

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

            self.assertIn("fig = plt.figure('Figure1', figsize=(5.0, 3.0))", macro)
            self.assertIn("fig = plt.figure('Figure1', figsize=(5.0, 3.0))", source)
        finally:
            widget.close()

    def test_figure_window_title_warns_when_macro_source_is_incomplete(self):
        widget = FigureWindow(figure_number=1)
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(widget)
        subwindow.setObjectName("Figure7")
        widget.bind_subwindow(subwindow)
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Figure0",
                    "snapshot": {
                        "default_macro_name": "Figure0",
                        "call_source": None,
                        "save_error": "unsupported trace source",
                        "figure_ir": None,
                        "live_state": None,
                        "is_first_class": True,
                    },
                }
            )

            self.assertEqual(subwindow.windowTitle(), "Figure7 [Macro Incomplete]")
        finally:
            widget.close()

    def test_figure_window_uses_stable_name_when_payload_title_is_missing(self):
        widget = FigureWindow(figure_number=1)
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setObjectName("Figure7")
        widget.bind_subwindow(subwindow)
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": None,
                    "snapshot": {
                        "default_macro_name": "Graph0",
                        "call_source": None,
                        "save_error": "unsupported trace source",
                        "figure_ir": None,
                        "live_state": None,
                        "is_first_class": True,
                    },
                }
            )

            self.assertEqual(subwindow.windowTitle(), "Figure7 [Macro Incomplete]")
        finally:
            widget.force_close()
            mdi_area.close()

    def test_figure_window_session_restore_source_includes_minimized_metadata_only(self):
        widget = FigureWindow(figure_number=1)
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
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
            subwindow.show()
            self.qapp.processEvents()
            subwindow.showMinimized()
            self.qapp.processEvents()

            macro = widget.macro_source("Figure0")
            source = widget.session_restore_source()

            self.assertIn("@hyde.figure(window_pos=(10, 20))", macro)
            self.assertNotIn("window_state=", macro)
            self.assertIn(
                "@hyde.figure(window_pos=(10, 20), window_state='minimized', register=False)",
                source,
            )
            self.assertNotIn("geometry_minimized", source)
        finally:
            widget.force_close()
            mdi_area.close()

    def test_figure_window_session_restore_source_preserves_maximized_metadata(self):
        widget = FigureWindow(figure_number=1)
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setObjectName("Figure7")
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("Graph0"))
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Graph0",
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "live_state": None,
                    },
                }
            )
            subwindow.show()
            self.qapp.processEvents()
            subwindow.showMaximized()
            self.qapp.processEvents()

            source = widget.session_restore_source()

            self.assertIn(
                "@hyde.figure(window_pos=(10, 20), window_state='maximized', register=False)",
                source,
            )
            self.assertIn("def Figure7(delay, fit_delay, raw_delay):", source)
            self.assertIn("fig = plt.figure('Figure7')", source)
        finally:
            widget.force_close()
            mdi_area.close()
