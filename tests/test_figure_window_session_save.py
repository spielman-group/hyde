import unittest

from qtutils.qt import QtWidgets

from hyde.user_interface.base_hyde_widgets import HydeToolWidget
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow


class TestFigureWindowSessionSave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _live_state_with_title(self, title):
        return (
            FigureIR()
            .with_title(title)
            .with_x_name("delay")
            .with_items(["fit_delay", "raw_delay"])
            .normalized_state()
        )

    def _live_state_with_title_and_figsize(self, title, figsize):
        return (
            FigureIR()
            .with_title(title)
            .with_x_name("delay")
            .with_items(["fit_delay", "raw_delay"])
            .with_figsize(*figsize)
            .normalized_state()
        )

    def test_figure_window_inherits_shared_shell(self):
        self.assertTrue(issubclass(FigureWindow, HydeToolWidget))

    def test_figure_window_names_and_parameterises_a_macro_from_the_figures_ir(self):
        widget = FigureWindow(figure_number=1)
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {"figure_ir": self._live_state_with_title("Figure0")},
                }
            )

            self.assertEqual(widget.saveable_default_macro_name(), "Figure0")
            self.assertEqual(
                widget.tracked_namespace_names(),
                ("delay", "fit_delay", "raw_delay"),
            )
            macro = widget.macro_definition_source("Graph0", handle="Figure0")
            self.assertIn("def Graph0(delay, fit_delay, raw_delay):", macro)
            self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", macro)
            self.assertIn("fig.show()", macro)
            self.assertNotIn("fig.canvas.draw_idle()", macro)
            self.assertNotIn("return fig", macro)
        finally:
            widget.force_close()

    def test_figure_window_macro_omits_a_style_the_kernel_reports_as_a_default(self):
        """A figure's macro must not freeze the rcParams it happened to inherit.

        A colour that came from the kernel's defaults is not something the user
        chose, so restating it in the macro would pin the figure to whatever
        style was in force the day it was saved.
        """
        figure_ir = self._live_state_with_title("Figure0")
        figure_ir["layout"]["subplots"][0]["traces"][0]["kwargs"]["color"] = "#123456"
        chosen = FigureWindow(figure_number=1)
        inherited = FigureWindow(figure_number=2)
        try:
            chosen.update_payload(
                {"figure_number": 1, "snapshot": {"figure_ir": figure_ir}}
            )
            inherited.update_payload(
                {
                    "figure_number": 2,
                    "snapshot": {
                        "figure_ir": figure_ir,
                        "figure_defaults": {
                            "trace_styles": {"subplot0": {"trace0": {"color": "#123456"}}}
                        },
                    },
                }
            )

            self.assertIn(
                "color='#123456'",
                chosen.macro_definition_source("Graph0", handle="Figure0"),
            )
            self.assertNotIn(
                "color='#123456'",
                inherited.macro_definition_source("Graph0", handle="Figure0"),
            )
        finally:
            chosen.force_close()
            inherited.force_close()

    def test_figure_window_tracks_live_figure_ir_in_widget_ir_from_backend_payloads(self):
        widget = FigureWindow(figure_number=1)
        first_ir = self._live_state_with_title("Figure0")
        second_ir = self._live_state_with_title("Figure1")
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {
                        "figure_ir": first_ir,
                        "live_state": None,
                    },
                }
            )
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {
                        "figure_ir": second_ir,
                        "live_state": None,
                    },
                }
            )

            self.assertIsInstance(widget.widget_ir, FigureIR)
            self.assertEqual(
                widget.widget_ir.normalized_state()["settings"]["title"],
                "Figure1",
            )
        finally:
            widget.force_close()

    def test_figure_window_falls_back_to_the_recorded_call_when_hyde_has_no_ir(self):
        """A figure Hyde could not describe still has the call that made it."""
        widget = FigureWindow(figure_number=1)
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {
                        "default_macro_name": "Figure0",
                        "call_source": "fig = plt.figure('Figure0')",
                        "figure_ir": None,
                        "is_first_class": True,
                    },
                }
            )

            self.assertEqual(widget.tracked_namespace_names(), ())
            self.assertEqual(widget.session_restore_arguments(), ())
            self.assertEqual(
                widget.macro_definition_source("Graph0", handle="Figure0"),
                "@hyde.figure\n"
                "def Graph0():\n"
                "    fig = plt.figure('Figure0')\n"
                "    return fig\n",
            )
            self.assertIn(
                "@hyde.figure(register=False)",
                widget.session_restore_definition_source("Figure0"),
            )
        finally:
            widget.force_close()

    def test_figure_window_macro_source_includes_window_pos_metadata(self):
        widget = FigureWindow(figure_number=1)
        subwindow = QtWidgets.QMdiSubWindow()
        subwindow.setWidget(widget)
        widget.bind_subwindow(subwindow)
        subwindow.setGeometry(10, 20, 300, 240)
        figure_ir = self._live_state_with_title("Figure0")
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
        figure_ir = self._live_state_with_title("Graph0")
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
            self.assertEqual(
                subwindow.windowTitle(),
                "Graph0: fit_delay: fit_delay vs delay, raw_delay: raw_delay vs delay",
            )
            self.assertEqual(widget.window_handle(), "Figure7")
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
        figure_ir = self._live_state_with_title_and_figsize("Figure0", (5.0, 3.0))
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

            self.assertEqual(subwindow.windowTitle(), "Figure0 [Unsupported Feature]")
            self.assertIn("unsupported trace source", widget.warning_label.text().lower())
            self.assertFalse(widget.warning_label.isHidden())
        finally:
            widget.close()

    def test_unsupported_figure_window_still_generates_supported_subset_restore_source(self):
        widget = FigureWindow(figure_number=1)
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setObjectName("Figure7")
        widget.bind_subwindow(subwindow)
        figure_ir = self._live_state_with_title("Figure0")
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "title": "Figure0",
                    "snapshot": {
                        "default_macro_name": "Figure0",
                        "call_source": None,
                        "save_error": "unsupported trace source",
                        "figure_ir": figure_ir,
                        "live_state": None,
                        "is_first_class": True,
                    },
                }
            )

            macro = widget.macro_source("Figure0")
            source = widget.session_restore_source()

            self.assertEqual(
                subwindow.windowTitle(),
                "Figure0: fit_delay: fit_delay vs delay, raw_delay: raw_delay vs delay [Unsupported Feature]",
            )
            self.assertIn("fig = plt.figure('Figure7')", macro)
            self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", macro)
            self.assertIn("fig = plt.figure('Figure7')", source)
            self.assertIn("ax.plot(delay, raw_delay, label='raw_delay')", source)
        finally:
            widget.force_close()
            mdi_area.close()

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

            self.assertEqual(subwindow.windowTitle(), "Graph0 [Unsupported Feature]")
            self.assertIn("unsupported trace source", widget.warning_label.text().lower())
            self.assertFalse(widget.warning_label.isHidden())
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
        figure_ir = self._live_state_with_title("Figure0")
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
        figure_ir = self._live_state_with_title("Graph0")
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
