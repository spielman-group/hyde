import json
import os
import subprocess
import sys
import tempfile
import pathlib
import types
import unittest
from dataclasses import replace as dataclass_replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import matplotlib

    matplotlib.use("Agg")
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

import hyde
from qtutils.qt import QtGui, QtWidgets

from hyde.features.matplotlib_features import (
    graphics_export_formats,
)
from hyde.user_interface.main import HydeApp
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.plugins.figure_control_dialog import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_interactive import Plugin as FigurePlugin
from hyde.user_interface.plugins.figure_interactive.context import EditableFigureContext
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.plugins.save_graphics_dialog.clipboard import (
    clipboard_mime_data,
    clipboard_mime_type_for_format,
    graphics_clipboard_representations,
)
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow
from hyde.user_interface.plugins.remove_from_graph_dialog import Plugin as RemoveFromGraphPlugin
from hyde.user_interface.plugins.kernel_runtime import KernelRequest
from tests.kernel_fakes import KernelRequestRecorder
from hyde.user_interface.plugins.save_graphics_dialog import Plugin as SaveGraphicsPlugin
from hyde.user_interface.plugins.save_graphics_dialog.dialogs import (
    SaveGraphicsDialog,
)
from hyde.user_interface.shared.plugin import HydePluginManager


def make_plugin_host(plugin_manager):
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
    main_window.menuEdit = main_window.menuBar().addMenu("Edit")
    main_window.menuAnalysis = main_window.menuBar().addMenu("Analysis")
    main_window.menuWindow = main_window.menuBar().addMenu("Windows")
    main_window.menuFigure = QtWidgets.QMenu("Figure", main_window.menuBar())
    main_window.menuTable = QtWidgets.QMenu("Table", main_window.menuBar())
    main_window.menuBar().addMenu(main_window.menuFigure)
    main_window.menuBar().addMenu(main_window.menuTable)
    main_window.mdiArea = QtWidgets.QMdiArea()
    main_window.setCentralWidget(main_window.mdiArea)

    app = type("DummyApp", (), {})()
    app.ui = main_window
    app.plugin_manager = plugin_manager
    app.configure_persistent_subwindow = lambda subwindow: None
    app.emit_plugin_event = lambda name, data=None: (name, data)
    app.show_status_message = lambda label: label
    app.show_transient_status_message = lambda label, timeout_ms: label
    app.clear_status_message = lambda label: None
    app.process_tree = object()
    app.show_plugin_window = lambda key: key
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
    app.get_current_app_ir = lambda: HydeAppIR(current_project_dir=None)
    app.lookup_menu_action = lambda location, name, path=(): (
        None
        if getattr(app, "menu_context", None) is None
        else app.menu_context.lookup_action(location, name, path=path)
    )
    app.show_menu = lambda location: HydeApp.show_menu(app, location)
    app.hide_menu = lambda location: HydeApp.hide_menu(app, location)
    app.popup_menu = lambda location, global_pos: HydeApp.popup_menu(
        app, location, global_pos
    )
    app.get_current_project_dir = lambda: None
    app.get_shutting_down = lambda: False
    app.set_shutting_down = lambda value: value
    app.get_quit_command_sent = lambda: False
    app.set_quit_command_sent = lambda value: value
    app.begin_project_operation = lambda label: label
    app.project_target_needs_confirmation = lambda path: False
    app.confirm_overwrite_project = lambda path: False
    app.begin_shutdown_from_close_event = lambda: None
    app.finalize_quit = lambda: None
    app.on_kernel_ready = lambda: None
    app.on_kernel_crashed = lambda: None
    app.enter_no_project_state = lambda: None
    app.activate_project = lambda project_dir: project_dir
    app.on_project_state_result = lambda data: data
    app.request_gui_quit = lambda: None
    return app


def make_active_figure_window(mdi_area, services, *, title="Figure0"):
    figure_ir = (
        FigureIR()
        .with_title(title)
        .with_x_name("x")
        .with_items(["trace_a", "trace_b"])
    )
    figure = FigureWindow(figure_number=7, services=dict(services))
    subwindow = mdi_area.addSubWindow(figure)
    figure.bind_subwindow(subwindow)
    subwindow.show()
    figure.update_payload(
        {
            "figure_number": 7,
            "title": title,
            "snapshot": {
                "is_first_class": True,
                "figure_ir": figure_ir.normalized_state(),
                "figure_defaults": None,
                "live_state": None,
                "trace_styles": None,
            },
        }
    )
    mdi_area.setActiveSubWindow(subwindow)
    return figure


def make_save_graphics_context(*, title="Figure9", size_inches=(6.4, 4.8)):
    figure_ir = FigureIR().with_title(title)
    if size_inches is not None:
        figure_ir = figure_ir.with_figsize(*size_inches)
    figure = FigureWindow(figure_number=7, services={})
    figure.widget_ir = FigureIR(
        figure_state=figure_ir.normalized_state(),
        figure_number=figure.figure_number,
    )
    return EditableFigureContext(figure)


class RecordingEditableFigureContext(EditableFigureContext):
    def __init__(self, *, title="ExplicitContextFigure", size_inches=(8.0, 3.5)):
        figure_ir = FigureIR().with_title(title).with_figsize(*size_inches)
        figure = FigureWindow(figure_number=7, services={})
        figure.widget_ir = FigureIR(
            figure_state=figure_ir.normalized_state(),
            figure_number=figure.figure_number,
        )
        super().__init__(figure)
        self._recorded_figure_name = title
        self._recorded_size_inches = tuple(size_inches)
        self.calls = []

    def figure_name(self):
        self.calls.append("figure_name")
        return self._recorded_figure_name

    def current_size_inches(self):
        self.calls.append("current_size_inches")
        return self._recorded_size_inches


class FakeKernelRequests(KernelRequestRecorder):
    """Stands in for `python_execution_service`, and answers on demand.

    Copy needs two arrivals that no channel orders against each other -- the
    kernel's reply, and the rendered bytes -- so tests need to drive them
    separately and in either order.
    """

    def __init__(self):
        self.executed = []

    def execute_hidden(self, code, silent=True):
        self.executed.append(code)
        return True

    def render_ran(self):
        self.answer_last(KernelRequest.RAN)

    def render_raised(self, error="ValueError: no figure named Graph12"):
        self.answer_last(KernelRequest.RAISED, error)

    def kernel_went_away(self):
        self.answer_last(
            KernelRequest.ABANDONED, "The kernel is no longer available."
        )


def _one_pixel_png():
    import base64

    return base64.b64decode(_ONE_PIXEL_PNG_BASE64)


def copy_payload(*rendered, request_msg_id=None):
    """A kernel payload carrying one representation per `(format, bytes)` pair.

    Defaults to a lone PDF, which is what a forced vector copy sends.
    """
    import base64

    pairs = rendered or ((b"%PDF fake", "pdf"),)
    payload = {
        "representations": [
            {
                "output_format": output_format,
                "payload_base64": base64.b64encode(data).decode("ascii"),
            }
            for data, output_format in pairs
        ]
    }
    if request_msg_id is not None:
        payload["request_msg_id"] = request_msg_id
    return {"task": "COPY_TO_CLIPBOARD_REQUEST", "data": payload}


def settle_copy(plugin, kernel, output_format="pdf"):
    """Complete the copy in flight the way a real one completes.

    Copy refuses a second request while one is outstanding, so a test that
    triggers several in a row has to let each finish first.
    """
    kernel.render_ran()
    plugin.on_kernel_message(copy_payload((b"%PDF fake", output_format)))


_ONE_PIXEL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


def make_copy_plugin(messages=None):
    plugin = SaveGraphicsPlugin({})
    plugin.services = {
        "figure_context_service": types.SimpleNamespace(
            active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
        ),
        "python_execution_service": FakeKernelRequests(),
    }
    if messages is not None:
        plugin.services["status_message_service"] = types.SimpleNamespace(
            show_status_message=messages.append,
            show_transient_message=messages.append,
            clear_status_message=lambda label: None,
        )
    return plugin


def a_failure_was_reported(messages):
    """Did anything tell the user the copy did not work?

    Two voices reach the status bar: the request owner's "<operation> failed:
    <why>" for a render that raised or bytes that never came, and the plugin's
    own "Could not ..." for bytes it did receive and could not use. A test that
    looks for only one of them passes whenever the other is the one missing,
    which is the opposite of what it is asking.
    """
    return any(
        "failed" in str(message).lower() or "could not" in str(message).lower()
        for message in messages
    )


def let_the_payload_wait_expire(test, plugin, kernel):
    """The kernel says the render ran, and then no bytes ever follow.

    Drives the real bounded timer rather than calling a handler by name: the
    point under test is that something eventually gives up, not that a
    particular method exists to be called.
    """
    plugin.PAYLOAD_TIMEOUT_MS = 0
    kernel.render_ran()
    test.assertTrue(plugin.copy_in_flight())
    for _ in range(5):
        test.qapp.processEvents()


class TestFigureCopyCommand(unittest.TestCase):
    """Copy lowers to a Hyde helper because the clipboard is GUI-owned.

    Plain matplotlib cannot express "put this on the clipboard", so this is the
    one place IR-CONTROL.md's carve-out for Hyde helpers in emitted Python
    applies. DPI is passed as the 'figure' sentinel so the kernel resolves it
    against the live figure rather than the GUI mirroring kernel state.
    """

    def test_copy_lowers_to_a_hyde_clipboard_call_on_the_looked_up_figure(self):
        source = FigureIR(figure_name="Graph12").with_copy_graphics(output_formats=('pdf',)).python_source(log=False)

        self.assertEqual(
            source.splitlines(),
            [
                "fig = hyde.get_figure('Graph12')",
                "hyde.copy_figure(fig, formats=('pdf',), dpi='figure')",
            ],
        )

    def test_copy_defaults_to_pdf_and_carries_the_requested_format(self):
        for output_format in ("pdf", "png", "svg"):
            with self.subTest(output_format=output_format):
                source = (
                    FigureIR(figure_name="Graph12")
                    .with_copy_graphics(output_formats=(output_format,))
                    .python_source(log=False)
                )
                self.assertIn(f"formats=({output_format!r},)", source)

    def test_copy_always_resolves_a_figure_name_to_look_up(self):
        # The emitted Python has to name a figure for hyde.get_figure, so an
        # absent name falls back to the default the save path uses too.
        source = FigureIR().with_copy_graphics(output_formats=('pdf',)).python_source(log=False)

        self.assertRegex(source.splitlines()[0], r"^fig = hyde\.get_figure\('.+'\)$")

    def test_copy_carries_no_output_path(self):
        # Copy has no export target; a state carrying one is a save state that
        # took the wrong branch.
        with self.assertRaises(ValueError):
            dataclass_replace(
                FigureIR(figure_name="Graph12").with_copy_graphics(output_formats=('pdf',)),
                output_path="/tmp/Graph12.pdf",
            ).validate()

    def test_copy_emits_the_dpi_sentinel_that_the_kernel_resolves(self):
        # The IR defers DPI; the sentinel is matplotlib's, and it belongs in
        # the emitted call rather than in the IR's dpi field.
        source = FigureIR(figure_name="Graph12").with_copy_graphics().python_source(log=False)

        self.assertIn("dpi='figure'", source)

    def test_copy_ignores_the_output_options_a_save_would_honour(self):
        # A figure IR that has been used for a save carries a DPI, a
        # transparency and a size; copying it must not smuggle them into the
        # clipboard call.
        source = (
            FigureIR(
                figure_name="Graph12",
                dpi=450,
                transparent=True,
                size_inches=(6.0, 4.0),
            )
            .with_copy_graphics(output_formats=('pdf', 'png'))
            .python_source(log=False)
        )

        self.assertEqual(
            source.splitlines(),
            [
                "fig = hyde.get_figure('Graph12')",
                "hyde.copy_figure(fig, formats=('pdf', 'png'), dpi='figure')",
            ],
        )

    def test_save_rejects_a_deferred_dpi(self):
        # Deferring DPI to the live figure is a copy's contract. A save lowers
        # to savefig, which is given a concrete number.
        with self.assertRaises(ValueError):
            FigureIR(figure_name="Graph12").with_save_graphics(
                "/tmp/Graph12.pdf", dpi=None
            ).validate()

    def test_copy_does_not_emit_savefig_or_touch_figure_size(self):
        source = FigureIR(figure_name="Graph12").with_copy_graphics(output_formats=('pdf',)).python_source(log=False)

        self.assertNotIn("savefig", source)
        self.assertNotIn("set_size_inches", source)


class TestFigureExportFormatValidation(unittest.TestCase):
    """One format list serves both export commands, so each has to police it.

    A save writes one file and a clipboard holds several representations of one
    content, so the same field means "exactly one" on one command and "at least
    one" on the other. Nothing else can tell a caller that the second format it
    asked a save for will be dropped.
    """

    def save(self, path="/tmp/Graph12.pdf", **kwargs):
        return FigureIR(figure_name="Graph12").with_save_graphics(path, **kwargs)

    def copy(self, **kwargs):
        return FigureIR(figure_name="Graph12").with_copy_graphics(**kwargs)

    def test_save_emits_the_one_format_it_was_given(self):
        for output_format in ("pdf", "png", "svg", "jpg"):
            with self.subTest(output_format=output_format):
                source = self.save(
                    f"/tmp/Graph12.{output_format}", output_formats=(output_format,)
                ).python_source(log=False)

                self.assertIn(f"format={output_format!r}", source)

    def test_save_rejects_more_than_one_format(self):
        # Accepted before the two format fields were merged: the extra formats
        # sat in the field only copy read, and the savefig dropped them.
        with self.assertRaises(ValueError):
            self.save(output_formats=("pdf", "png")).validate()

    def test_save_rejects_no_format_at_all(self):
        for empty in ((), ("",), ("  ",)):
            with self.subTest(output_formats=empty):
                with self.assertRaises(ValueError):
                    self.save(output_formats=empty).validate()

    def test_save_takes_a_bare_format_name_as_one_format(self):
        # Not as a sequence of one-character formats.
        source = self.save("/tmp/Graph12.png", output_formats="png").python_source(log=False)

        self.assertIn("format='png'", source)

    def test_copy_accepts_one_format_or_several(self):
        for output_formats in (("pdf",), ("pdf", "png"), ("pdf", "png", "svg")):
            with self.subTest(output_formats=output_formats):
                source = self.copy(output_formats=output_formats).python_source(log=False)

                self.assertIn(f"formats={tuple(output_formats)!r}", source)

    def test_copy_rejects_no_format_at_all(self):
        for empty in ((), ("",), ("  ",)):
            with self.subTest(output_formats=empty):
                with self.assertRaises(ValueError):
                    self.copy(output_formats=empty).validate()

    def test_formats_are_normalized_before_they_reach_the_emitted_call(self):
        source = self.copy(output_formats=(" PDF ", "PNG")).python_source(log=False)

        self.assertIn("formats=('pdf', 'png')", source)

    def test_a_diff_still_emits_the_command_it_was_built_from(self):
        # The diff carries the whole export state, formats included; a diff
        # that dropped them would emit a copy of the wrong thing, or none.
        base = FigureIR().with_title("Graph12").with_items(["trace_a"])

        self.assertEqual(
            base.current_diff(self.copy(output_formats=("pdf", "png"))).python_source(log=False),
            "fig = hyde.get_figure('Graph12')\n"
            "hyde.copy_figure(fig, formats=('pdf', 'png'), dpi='figure')",
        )
        self.assertEqual(
            base.current_diff(
                self.save("/tmp/Graph12.png", output_formats=("png",), dpi=450, transparent=True)
            ).python_source(log=False),
            "fig = hyde.get_figure('Graph12')\n"
            "fig.savefig('/tmp/Graph12.png', format='png', dpi=450, transparent=True)",
        )

    def test_the_debug_report_names_the_formats_the_command_will_emit(self):
        # The report exists so a human can read what an IR is about to do; a
        # format it will not honour, or a missing one, makes it a lying report.
        self.assertEqual(
            self.copy(output_formats=("pdf", "png")).debug_state()["output_formats"],
            ("pdf", "png"),
        )
        self.assertEqual(
            self.save(output_formats=("png",)).debug_state()["output_formats"],
            ("png",),
        )
        self.assertEqual(
            FigureIR()
            .with_title("Graph12")
            .with_items(["trace_a"])
            .current_diff(self.copy(output_formats=("pdf", "png")))
            .debug_state()["output_formats"],
            ("pdf", "png"),
        )


class TestFigureCopyEndToEnd(unittest.TestCase):
    """The whole path: menu action -> emitted Python -> kernel render ->
    bytes handed to the GUI -> clipboard."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_copy_action_emits_the_copy_command_for_the_active_figure(self):
        kernel = FakeKernelRequests()
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
            ),
            "python_execution_service": kernel,
        }

        self.assertTrue(plugin.copy_active_figure())
        self.assertEqual(
            kernel.executed,
            [
                "fig = hyde.get_figure('Graph12')\n"
                "hyde.copy_figure(fig, formats=('pdf', 'png'), dpi='figure')"
            ],
        )

    def test_copy_action_does_nothing_without_an_active_figure(self):
        kernel = FakeKernelRequests()
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: None
            ),
            "python_execution_service": kernel,
        }

        self.assertFalse(plugin.copy_active_figure())
        self.assertEqual([], kernel.executed)

    def test_rendered_bytes_from_the_kernel_reach_the_clipboard_as_pdf(self):
        import base64

        plugin = make_copy_plugin()
        plugin.copy_active_figure(representation="vector")
        rendered = b"%PDF-1.4 fake pdf bytes"

        plugin.on_kernel_message(copy_payload((rendered, "pdf")))

        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        self.assertIn("application/pdf", mime_data.formats())
        self.assertEqual(rendered, bytes(mime_data.data("application/pdf")))

    def test_unrelated_kernel_messages_leave_the_clipboard_alone(self):
        QtWidgets.QApplication.clipboard().setText("untouched")
        plugin = SaveGraphicsPlugin({})
        plugin.services = {}

        plugin.on_kernel_message({"task": "SOMETHING_ELSE", "data": {}})

        self.assertEqual("untouched", QtWidgets.QApplication.clipboard().text())

    def test_kernel_render_produces_pdf_bytes_without_disturbing_the_figure(self):
        # hyde.copy_figure runs in the kernel against the live figure. Copying
        # must not change the figure the user is looking at.
        import base64
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import hyde

        captured = []
        figure = plt.figure(figsize=(5.0, 3.0))
        figure.add_subplot(111).plot([0, 1], [1, 2])
        original_size = tuple(figure.get_size_inches())
        original_dpi = figure.dpi
        try:
            with patch(
                "hyde.execution.ipc.signal_copy_to_clipboard",
                side_effect=captured.append,
            ):
                self.assertTrue(hyde.copy_figure(figure, formats=("pdf", "png")))

            self.assertEqual(1, len(captured))
            representations = captured[0]
            self.assertEqual(
                ["pdf", "png"],
                [item["output_format"] for item in representations],
            )
            self.assertTrue(
                base64.b64decode(representations[0]["payload_base64"]).startswith(b"%PDF")
            )
            self.assertEqual(original_size, tuple(figure.get_size_inches()))
            self.assertEqual(original_dpi, figure.dpi)
        finally:
            plt.close(figure)

    def test_each_representation_renders_through_a_format_the_table_lists(self):
        # The table, not the installed matplotlib: the runtime-sourced version of
        # this check is
        # `TestGeneratedGraphicsFormatTable.test_copy_offers_only_formats_the_installed_matplotlib_can_export`.
        exportable = {item.key for item in graphics_export_formats()}

        for item in graphics_clipboard_representations():
            with self.subTest(representation=item.key):
                for candidate in item.output_formats:
                    self.assertIn(candidate, exportable)
                    self.assertIsNotNone(clipboard_mime_type_for_format(candidate))

    def test_a_format_with_no_clipboard_representation_yields_no_payload(self):
        self.assertIsNone(clipboard_mime_data([("raw", b"junk")]))
        self.assertIsNone(clipboard_mime_type_for_format("rgba"))


class TestEditMenuCopy(unittest.TestCase):
    """Edit is a shell-owned menu location, like File and Figure.

    It exists so table copy and terminal copy can later contribute into it
    without renegotiating who owns the menu.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _host_with_figure(self, figure_context):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        self.save_graphics = SaveGraphicsPlugin({})
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": self.save_graphics,
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        for plugin in manager.plugins.values():
            services = getattr(plugin, "services", None)
            if isinstance(services, dict):
                services["figure_context_service"] = types.SimpleNamespace(
                    active_editable_figure=lambda: figure_context[0]
                )
                services["python_execution_service"] = self.kernel
        return app

    def setUp(self):
        self.kernel = FakeKernelRequests()

    def test_edit_menu_exists_and_carries_copy_with_the_platform_shortcut(self):
        figure_context = [None]
        app = self._host_with_figure(figure_context)

        self.assertTrue(hasattr(app.ui, "menuEdit"))
        self.assertEqual("Edit", app.ui.menuEdit.title())

        copy_action = app.menu_context.lookup_action("edit", "Copy")
        self.assertIsNotNone(copy_action)
        self.assertEqual(
            QtGui.QKeySequence(QtGui.QKeySequence.Copy).toString(),
            copy_action.shortcut().toString(),
        )

    def test_edit_menu_appears_after_file_in_the_menu_bar(self):
        app = self._host_with_figure([None])
        titles = [
            action.menu().title()
            for action in app.ui.menuBar().actions()
            if action.menu() is not None
        ]

        self.assertEqual(titles[:2], ["File", "Edit"])

    def test_edit_copy_needs_an_active_figure(self):
        figure_context = [None]
        app = self._host_with_figure(figure_context)
        copy_action = app.menu_context.lookup_action("edit", "Copy")

        app.menu_context.refresh_enabled_states()
        self.assertFalse(copy_action.isEnabled())

        figure_context[0] = make_save_graphics_context(title="Graph12")
        app.menu_context.refresh_enabled_states()
        self.assertTrue(copy_action.isEnabled())

    def test_edit_copy_emits_the_same_command_as_the_figure_menu_entry(self):
        figure_context = [make_save_graphics_context(title="Graph12")]
        app = self._host_with_figure(figure_context)
        app.menu_context.refresh_enabled_states()

        app.menu_context.lookup_action("edit", "Copy").trigger()
        from_edit = list(self.kernel.executed)
        settle_copy(self.save_graphics, self.kernel)

        self.kernel.executed.clear()
        app.menu_context.lookup_action("figure", "Copy").trigger()
        from_figure = list(self.kernel.executed)

        self.assertEqual(
            [
                "fig = hyde.get_figure('Graph12')\n"
                "hyde.copy_figure(fig, formats=('pdf', 'png'), dpi='figure')"
            ],
            from_edit,
        )
        self.assertEqual(from_edit, from_figure)


class TestCopyPgfAsText(unittest.TestCase):
    """PGF is LaTeX source, so it goes on the clipboard as text.

    It is the one offered format with no image reading, which is also why it is
    excluded from the PNG companion representation: attaching an image to a
    text copy would mean pasting into a word processor silently yields a
    picture instead of the source that was asked for.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_pgf_reaches_the_clipboard_as_latex_source(self):
        import base64

        plugin = make_copy_plugin()
        plugin.copy_active_figure(representation="latex")
        latex = b"\\begingroup%\n\\makeatletter%\n\\begin{pgfpicture}%"

        plugin.on_kernel_message(copy_payload((latex, "pgf")))

        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        self.assertTrue(mime_data.hasText())
        self.assertIn("pgfpicture", mime_data.text())

    def test_pgf_payload_carries_no_image_representation(self):
        payload = clipboard_mime_data([("pgf", b"\\begin{pgfpicture}")])

        self.assertTrue(payload.mime_data.hasText())
        for image_type in ("image/png", "application/pdf", "image/svg+xml"):
            self.assertNotIn(image_type, payload.mime_data.formats())


class TestClipboardPayloadRepresentations(unittest.TestCase):
    """A clipboard payload carries several representations of one content."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_an_image_copy_carries_both_its_own_format_and_png(self):
        png = _one_pixel_png()
        payload = clipboard_mime_data([("pdf", b"%PDF-1.4 fake"), ('png', png)])

        self.assertIn("application/pdf", payload.mime_data.formats())
        self.assertIn("image/png", payload.mime_data.formats())
        self.assertEqual(b"%PDF-1.4 fake", bytes(payload.mime_data.data("application/pdf")))
        self.assertEqual(png, bytes(payload.mime_data.data("image/png")))

    def test_a_png_copy_does_not_duplicate_itself(self):
        png = _one_pixel_png()
        payload = clipboard_mime_data([("png", png), ('png', png)])

        self.assertEqual(
            ["image/png"],
            [f for f in payload.mime_data.formats() if f.startswith("image/")],
        )

    def test_a_copy_carries_an_image_the_platform_can_republish(self):
        """MIME types reach other Qt applications; everything else reads the
        platform's own pasteboard.

        Bytes under an unrecognised MIME type land there as a private flavour
        that nothing can paste, so a copy that only set bytes put nothing
        usable on the clipboard at all.
        """
        png = _one_pixel_png()
        for output_format, rendered, companion in (
            ("pdf", b"%PDF-1.4 fake", png),
            ("svg", b"<svg/>", png),
            ("png", png, None),
        ):
            with self.subTest(output_format=output_format):
                payload = clipboard_mime_data(
                    [(output_format, rendered), ('png', companion)]
                )
                self.assertTrue(
                    payload.mime_data.hasImage(),
                    f"a {output_format} copy cannot be pasted outside Qt",
                )

    def test_a_pgf_copy_carries_no_image_the_platform_could_paste(self):
        payload = clipboard_mime_data([("pgf", b"\\begin{pgfpicture}")])

        self.assertFalse(payload.mime_data.hasImage())
        self.assertTrue(payload.mime_data.hasText())

    def test_a_pdf_copy_is_pasteable_by_a_png_only_consumer(self):
        plugin = make_copy_plugin()
        plugin.copy_active_figure(representation="vector")
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": copy_payload(
                    (b"%PDF-1.4 fake", "pdf"), (_one_pixel_png(), "png")
                )["data"],
            }
        )

        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        self.assertTrue(mime_data.hasImage())
        self.assertIn("image/png", mime_data.formats())
        self.assertIn("application/pdf", mime_data.formats())


class TestCopyFeedback(unittest.TestCase):
    """Copy is asynchronous and its whole effect is invisible until you paste
    somewhere else, so it has to say what happened."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _plugin_with_status(self):
        messages = []
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
            ),
            "python_execution_service": FakeKernelRequests(),
            "status_message_service": types.SimpleNamespace(
                show_status_message=lambda text: messages.append(text),
                show_transient_message=lambda text: messages.append(text),
                clear_status_message=lambda label: messages.append(None),
            ),
        }
        return plugin, messages

    def test_a_completed_copy_confirms_which_representation_reached_the_clipboard(self):
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure(representation="image")
        plugin.on_kernel_message(copy_payload((_one_pixel_png(), "png")))

        self.assertIn("Copied figure to the clipboard as Image.", messages)

    def test_a_copy_names_only_the_representations_the_clipboard_took(self):
        """A payload can offer more than the clipboard ends up carrying.

        LaTeX source is exclusive -- an image alongside it would mean pasting
        into a word processor silently yields a picture instead of the source --
        so a payload carrying text as well places only the text. Naming the
        rest promises a paste that cannot happen.
        """
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure()
        plugin.on_kernel_message(
            copy_payload(
                (b"%PDF-1.4 fake", "pdf"),
                (_one_pixel_png(), "png"),
                (b"\\begin{pgfpicture}", "pgf"),
            )
        )

        self.assertIn("Copied figure to the clipboard as LaTeX.", messages)
        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        self.assertTrue(mime_data.hasText())
        self.assertFalse(mime_data.hasImage())

    def test_a_plain_copy_names_both_the_drawing_and_the_picture_it_placed(self):
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure()
        plugin.on_kernel_message(
            copy_payload((b"%PDF-1.4 fake", "pdf"), (_one_pixel_png(), "png"))
        )

        self.assertIn("Copied figure to the clipboard as Vector, Image.", messages)
        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        self.assertIn("application/pdf", mime_data.formats())
        self.assertTrue(mime_data.hasImage())

    def test_a_picture_that_will_not_decode_is_not_reported_as_copied(self):
        """Image bytes Qt cannot decode reach nobody: no image flavour is
        published for the platform to paste, and the raw bytes another Qt
        application would read are not a picture. A copy that placed only those
        has copied nothing."""
        plugin, messages = self._plugin_with_status()
        QtWidgets.QApplication.clipboard().setText("untouched")
        plugin.copy_active_figure(representation="image")
        plugin.on_kernel_message(copy_payload((b"\x89PNG fake", "png")))

        self.assertFalse(any("Copied" in str(m) for m in messages), messages)
        self.assertTrue(a_failure_was_reported(messages), messages)
        self.assertEqual("untouched", QtWidgets.QApplication.clipboard().text())

    def test_a_copy_whose_picture_will_not_decode_still_names_the_vector(self):
        """The vector did reach the clipboard, so this is not a failed copy --
        but the picture did not, and a message naming it would send someone to
        paste into an application that gets nothing."""
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure()
        plugin.on_kernel_message(
            copy_payload((b"%PDF-1.4 fake", "pdf"), (b"\x89PNG fake", "png"))
        )

        self.assertIn("Copied figure to the clipboard as Vector.", messages)
        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        self.assertIn("application/pdf", mime_data.formats())
        self.assertFalse(mime_data.hasImage())

    def test_a_copy_waits_for_a_busy_kernel_rather_than_reporting_failure(self):
        """The user's own long cell holds the kernel; the copy is queued, not late."""
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure(representation="vector")

        self.assertTrue(plugin.copy_in_flight())
        self.assertFalse(a_failure_was_reported(messages), messages)

    def test_a_copy_with_no_usable_format_says_so_rather_than_doing_nothing(self):
        """A copy that never reaches the kernel is invisible unless it reports.

        Every other refusal says why. This one returned quietly, so the action
        was indistinguishable from a copy that had worked.
        """
        plugin, messages = self._plugin_with_status()

        self.assertFalse(plugin.copy_active_figure(representation="no-such-thing"))

        self.assertEqual([], plugin.services["python_execution_service"].executed)
        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(a_failure_was_reported(messages), messages)

    def test_a_rendered_copy_whose_data_never_arrives_reports_failure(self):
        plugin, messages = self._plugin_with_status()
        kernel = plugin.services["python_execution_service"]
        plugin.copy_active_figure(representation="vector")

        let_the_payload_wait_expire(self, plugin, kernel)

        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(a_failure_was_reported(messages), messages)
        self.assertTrue(
            any("never arrived" in str(m) for m in messages), messages
        )
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_the_cursor_is_never_left_busy_after_a_completed_copy(self):
        import base64

        plugin, _ = self._plugin_with_status()
        # Take the slow path: the cursor a lingering copy puts up, held long
        # enough that only completing the copy can take it down again.
        plugin.BUSY_CURSOR_DELAY_MS = 0
        plugin.BUSY_CURSOR_HOLD_MS = 60000
        plugin.copy_active_figure(representation="vector")
        for _ in range(3):
            self.qapp.processEvents()
        self.assertIsNotNone(QtWidgets.QApplication.overrideCursor())
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {
                    "payload_base64": base64.b64encode(b"%PDF fake").decode("ascii"),
                    "output_format": "pdf",
                    "is_text": False,
                },
            }
        )

        self.assertIsNone(QtWidgets.QApplication.overrideCursor())
        self.assertFalse(plugin.copy_in_flight())

    def test_a_failed_render_does_not_confirm_success(self):
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure(representation="vector")
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {"payload_base64": "", "output_format": "pdf", "is_text": False},
            }
        )

        self.assertFalse(any("Copied" in str(m) for m in messages), messages)
        self.assertTrue(a_failure_was_reported(messages), messages)

    def test_copy_works_without_a_status_service(self):
        kernel = FakeKernelRequests()
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
            ),
            "python_execution_service": kernel,
        }

        self.assertTrue(plugin.copy_active_figure())
        kernel.render_raised()
        self.assertFalse(plugin.copy_in_flight())
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())


class TestCopySettlesOnEveryPath(unittest.TestCase):
    """A copy request must settle however it ends.

    Every exit leaves the busy timer and the timeout timer armed until it does,
    so an unsettled request shows a wait cursor for an operation that already
    failed.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_a_reply_naming_an_unpasteable_format_settles_the_request(self):
        import base64

        messages = []
        plugin = make_copy_plugin(messages)
        plugin.copy_active_figure(representation="vector")
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {
                    "payload_base64": base64.b64encode(b"junk").decode("ascii"),
                    "output_format": "raw",
                    "is_text": False,
                },
            }
        )

        self.assertFalse(plugin.copy_in_flight())
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())
        self.assertTrue(a_failure_was_reported(messages), messages)

    def test_undecodable_payload_settles_the_request(self):
        messages = []
        plugin = make_copy_plugin(messages)
        plugin.copy_active_figure(representation="vector")
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {"payload_base64": "!!not base64!!", "output_format": "pdf"},
            }
        )

        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(a_failure_was_reported(messages), messages)

    def test_data_arriving_after_a_failure_does_not_overwrite_it(self):
        messages = []
        plugin = make_copy_plugin(messages)
        kernel = plugin.services["python_execution_service"]
        QtWidgets.QApplication.clipboard().setText("untouched")
        plugin.copy_active_figure(representation="vector")
        let_the_payload_wait_expire(self, plugin, kernel)
        self.assertTrue(a_failure_was_reported(messages), messages)

        plugin.on_kernel_message(copy_payload((b"%PDF late", "pdf")))

        self.assertFalse(any("Copied" in str(m) for m in messages), messages)
        self.assertEqual("untouched", QtWidgets.QApplication.clipboard().text())


class TestCopyLifecycleAcrossTwoChannels(unittest.TestCase):
    """A copy is answered twice, by routes nothing orders against each other.

    The kernel's execute_reply says the render ran; the rendered bytes come
    back on the parent-message channel. Either can arrive first, and only one
    of them carries a reason when things go wrong.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _copy_in_flight(self, representation="vector"):
        messages = []
        plugin = make_copy_plugin(messages)
        kernel = plugin.services["python_execution_service"]
        self.assertTrue(plugin.copy_active_figure(representation=representation))
        return plugin, kernel, messages

    def test_a_copy_in_progress_holds_the_status_bar_but_its_outcome_does_not(self):
        """A finished operation should not sit in the status bar indefinitely.

        The copy in flight is the only thing still telling the user anything --
        the wait cursor has already lowered itself -- so that message stays.
        """
        shown = []
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
            ),
            "python_execution_service": FakeKernelRequests(),
            "status_message_service": types.SimpleNamespace(
                show_status_message=lambda text: shown.append(("holds", text)),
                show_transient_message=lambda text: shown.append(("fades", text)),
                clear_status_message=lambda label: None,
            ),
        }

        plugin.copy_active_figure(representation="vector")
        self.assertEqual([("holds", "Copying figure as Vector...")], shown)

        plugin.on_kernel_message(copy_payload())
        self.assertEqual("fades", shown[-1][0])
        self.assertIn("Copied figure", shown[-1][1])

    def test_rendered_bytes_reach_the_clipboard_through_kernel_dispatch(self):
        """The plugin has to be wired to kernel messages, not merely able to
        handle one.

        Calling on_kernel_message directly proves nothing about whether
        anything ever calls it.
        """
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        save_graphics = SaveGraphicsPlugin({})
        manager.plugins = {"save_graphics_dialog": save_graphics}
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        app.emit_plugin_event = lambda name, data=None: HydeApp.emit_plugin_event(
            app, name, data
        )
        kernel = FakeKernelRequests()
        save_graphics.services["figure_context_service"] = types.SimpleNamespace(
            active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
        )
        save_graphics.services["python_execution_service"] = kernel

        QtWidgets.QApplication.clipboard().setText("untouched")
        self.assertTrue(save_graphics.copy_active_figure(representation="vector"))
        kernel.render_ran()

        app.emit_plugin_event(
            "kernel_message",
            copy_payload((b"%PDF real", "pdf"), request_msg_id=kernel.kernel_requests[-1][0].msg_id),
        )

        self.assertFalse(save_graphics.copy_in_flight())
        mime = QtWidgets.QApplication.clipboard().mimeData()
        self.assertTrue(mime.hasFormat("application/pdf"))

    def test_a_vector_copy_is_published_under_the_platform_identifier(self):
        """Qt maps a MIME type it does not recognise onto a private pasteboard
        flavour, so vector bytes were on the clipboard and invisible outside
        Qt."""
        from hyde.user_interface.plugins.save_graphics_dialog.clipboard_platform import (
            register_clipboard_converters,
        )

        converters = register_clipboard_converters()
        if not converters:
            self.skipTest("this platform's clipboard needs no MIME translation")
        converter = converters[0]

        self.assertEqual("com.adobe.pdf", converter.utiForMime("application/pdf"))
        self.assertEqual("application/pdf", converter.mimeForUti("com.adobe.pdf"))
        self.assertTrue(converter.canConvert("application/pdf", "com.adobe.pdf"))
        self.assertFalse(converter.canConvert("application/pdf", "public.png"))
        self.assertEqual("", converter.utiForMime("image/png"))

    def test_registering_clipboard_converters_keeps_them_alive(self):
        """Qt unregisters a converter when it is destroyed, so something has to
        own it; dropping it presents as vector paste working sometimes."""
        import gc

        from hyde.user_interface.plugins.save_graphics_dialog.clipboard_platform import (
            register_clipboard_converters,
            registered_clipboard_converters,
        )

        first = register_clipboard_converters()
        if not first:
            self.skipTest("this platform's clipboard needs no MIME translation")
        gc.collect()

        self.assertEqual(first, register_clipboard_converters())
        self.assertEqual(first, registered_clipboard_converters())

    def test_a_plain_copy_carries_a_vector_and_a_raster_together(self):
        """The receiving application picks; the user does not have to know."""
        plugin, kernel, _ = self._copy_in_flight(representation=None)

        self.assertEqual(
            [
                "fig = hyde.get_figure('Graph12')\n"
                "hyde.copy_figure(fig, formats=('pdf', 'png'), dpi='figure')"
            ],
            kernel.executed,
        )

    def test_forcing_vector_carries_no_raster_to_fall_back_on(self):
        """The point of forcing: an application that would have settled for the
        raster gets nothing to settle for."""
        plugin, kernel, _ = self._copy_in_flight(representation="vector")
        self.assertIn("formats=('pdf',)", kernel.executed[0])

        plugin.on_kernel_message(copy_payload((b"%PDF-1.4 fake", "pdf")))
        mime = QtWidgets.QApplication.clipboard().mimeData()

        self.assertIn("application/pdf", mime.formats())
        self.assertNotIn("image/png", mime.formats())
        self.assertFalse(mime.hasImage())

    def test_forcing_image_carries_no_vector(self):
        plugin, kernel, _ = self._copy_in_flight(representation="image")
        self.assertIn("formats=('png',)", kernel.executed[0])

        plugin.on_kernel_message(copy_payload((_one_pixel_png(), "png")))
        mime = QtWidgets.QApplication.clipboard().mimeData()

        self.assertNotIn("application/pdf", mime.formats())
        self.assertTrue(mime.hasImage())

    def test_only_the_format_this_platform_publishes_is_rendered(self):
        """A vector representation offers candidates; rendering every one would
        render figures nothing on this machine can paste."""
        plugin, kernel, _ = self._copy_in_flight(representation="vector")
        requested = kernel.executed[0]

        self.assertEqual(
            1,
            sum(requested.count(f"'{candidate}'") for candidate in ("pdf", "svg")),
            f"expected one vector format in {requested!r}",
        )

    def test_a_second_copy_is_refused_while_one_is_in_flight(self):
        plugin, kernel, messages = self._copy_in_flight()

        self.assertFalse(plugin.copy_active_figure(representation="image"))
        self.assertEqual(1, len(kernel.executed))
        self.assertTrue(
            any("already in progress" in str(m).lower() for m in messages), messages
        )

    def test_a_copy_can_be_started_again_once_the_last_one_settled(self):
        plugin, kernel, _ = self._copy_in_flight()
        plugin.on_kernel_message(copy_payload())

        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(plugin.copy_active_figure(representation="image"))
        self.assertEqual(2, len(kernel.executed))

    def test_a_render_that_raises_reports_what_the_kernel_said(self):
        """Hidden execution failures used to be invisible; the reply carries them."""
        plugin, kernel, messages = self._copy_in_flight()
        kernel.render_raised("ValueError: no figure named Graph12")

        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(
            any("no figure named Graph12" in str(m) for m in messages), messages
        )
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_a_copy_fails_when_the_kernel_goes_away(self):
        plugin, kernel, messages = self._copy_in_flight()
        kernel.kernel_went_away()

        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(a_failure_was_reported(messages), messages)
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_data_arriving_before_the_reply_still_reaches_the_clipboard(self):
        plugin, kernel, messages = self._copy_in_flight()
        QtWidgets.QApplication.clipboard().setText("untouched")

        plugin.on_kernel_message(copy_payload((b"%PDF early", "pdf")))
        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(any("Copied" in str(m) for m in messages), messages)

        # The reply lands afterwards against a copy that is already settled.
        kernel.render_ran()
        self.assertFalse(plugin.copy_in_flight())
        self.assertFalse(a_failure_was_reported(messages), messages)

    def test_data_left_over_from_an_abandoned_copy_is_not_taken_for_a_new_one(self):
        """The bytes name the request that produced them."""
        plugin, kernel, messages = self._copy_in_flight()
        stale = kernel.kernel_requests[-1][0].msg_id
        let_the_payload_wait_expire(self, plugin, kernel)
        self.assertFalse(plugin.copy_in_flight())

        QtWidgets.QApplication.clipboard().setText("untouched")
        self.assertTrue(plugin.copy_active_figure(representation="image"))
        plugin.on_kernel_message(copy_payload((b"%PDF stale", "pdf"), request_msg_id=stale))

        self.assertTrue(plugin.copy_in_flight())
        self.assertEqual("untouched", QtWidgets.QApplication.clipboard().text())

        current = kernel.kernel_requests[-1][0].msg_id
        plugin.on_kernel_message(
            copy_payload((_one_pixel_png(), "png"), request_msg_id=current)
        )
        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(any("Copied" in str(m) for m in messages), messages)

    def test_data_that_cannot_name_its_request_is_still_accepted(self):
        """An absent name means the kernel could not tell us, not that it is stale."""
        plugin, _, messages = self._copy_in_flight()
        plugin.on_kernel_message(copy_payload())

        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(any("Copied" in str(m) for m in messages), messages)

    def test_the_wait_cursor_is_released_while_the_copy_is_still_waiting(self):
        """A minute-long wait cursor reads as a hung application.

        The cursor says something started, not how long it will take, so it
        lowers itself while the copy carries on waiting for the kernel.
        """
        messages = []
        plugin = make_copy_plugin(messages)
        plugin.BUSY_CURSOR_DELAY_MS = 0
        plugin.BUSY_CURSOR_HOLD_MS = 0
        self.assertTrue(plugin.copy_active_figure(representation="vector"))
        for _ in range(5):
            self.qapp.processEvents()

        self.assertIsNone(QtWidgets.QApplication.overrideCursor())
        self.assertTrue(plugin.copy_in_flight())


def module_names_under(package_dir, package_name):
    """Importable module names for the Python files under a package directory."""
    names = set()
    for path in package_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(package_dir).with_suffix("").parts
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        names.add(".".join((package_name,) + parts))
    return sorted(names)


_GUI_START_UP_PYPLOT_PROBE = r"""
import importlib
import json
import logging
import os
import sys

PYPLOT = "matplotlib.pyplot"
report = {"stages": [], "logged": [], "menus": {}, "plugins": [], "gui_modules": []}


def observe(stage):
    report["stages"].append([stage, PYPLOT in sys.modules])


class CaptureErrors(logging.Handler):
    # Every skip in the plugin framework is logged rather than raised: a plugin
    # that will not import, a contribution that raises, a location nothing
    # registered. Any of those would leave the menus half-built and the
    # observation below vacuous, so they are reported as failures too.
    def emit(self, record):
        report["logged"].append(record.name + ": " + record.getMessage())


logging.getLogger().addHandler(CaptureErrors(level=logging.ERROR))
logging.getLogger().setLevel(logging.ERROR)

observe("a clean interpreter")

from qtutils.qt import QtWidgets

import hyde.user_interface.main as gui_main
from hyde.user_interface.shared.plugin import HydePluginManager

observe("importing the GUI application")

qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

manager = HydePluginManager(
    plugin_package="hyde.user_interface.plugins",
    plugins_dir=os.path.join(os.path.dirname(gui_main.__file__), os.pardir, "plugins"),
)
manager.discover_modules()
manager.instantiate_plugins()
report["plugins"] = sorted(manager.plugins)
observe("importing and instantiating every GUI plugin")

window = QtWidgets.QMainWindow()
window.setMenuBar(QtWidgets.QMenuBar())
window.menuFile = window.menuBar().addMenu("File")
window.menuEdit = window.menuBar().addMenu("Edit")
window.menuAnalysis = window.menuBar().addMenu("Analysis")
window.menuWindow = window.menuBar().addMenu("Windows")
window.menuFigure = QtWidgets.QMenu("Figure", window.menuBar())
window.menuTable = QtWidgets.QMenu("Table", window.menuBar())
window.mdiArea = QtWidgets.QMdiArea()
window.setCentralWidget(window.mdiArea)


class StubApp:
    # Stands in for HydeApp so that HydeApp's own setup_plugins does the work.
    # Which menu locations exist, and which plugins render what into them, then
    # come from the product rather than from a list written here.
    def __init__(self):
        self.ui = window
        self.plugin_manager = manager

    def __getattr__(self, name):
        return lambda *args, **kwargs: None

    def build_plugin_services(self):
        return gui_main.HydeApp.build_plugin_services(self)

    def show_menu(self, location):
        return gui_main.HydeApp.show_menu(self, location)

    def hide_menu(self, location):
        return gui_main.HydeApp.hide_menu(self, location)


# Start-up launches the kernel once the menus are rendered. That is a different
# process, and spyder_kernels has pyplot imported there before Hyde runs at all,
# so this stops at the render.
manager.setup_complete = lambda data: None
app = StubApp()
gui_main.HydeApp.setup_plugins(app)
observe("building every start-up menu")

for location, menu in sorted(app.menu_context.locations.items()):
    entries = {}
    for action in menu.actions():
        submenu = action.menu()
        if submenu is None:
            entries.setdefault("", []).append(action.text())
        else:
            entries[submenu.title()] = [
                child.text() for child in submenu.actions() if not child.isSeparator()
            ]
    report["menus"][location] = entries

# The rest of the GUI process, whether or not start-up happens to reach it: a
# window built later resolves a backend just as ruinously as one built at
# start-up, and much of the GUI is imported lazily. The module list comes from
# the filesystem, so none of it is read out of the code being guarded, and an
# import that raises takes the whole probe down rather than being skipped.
import hyde.user_interface as gui_package

gui_dir = os.path.dirname(gui_package.__file__)
gui_modules = set()
for directory, subdirectories, filenames in os.walk(gui_dir):
    subdirectories[:] = [name for name in subdirectories if name != "__pycache__"]
    for filename in filenames:
        if not filename.endswith(".py"):
            continue
        relative = os.path.relpath(os.path.join(directory, filename), gui_dir)
        parts = relative[: -len(".py")].split(os.sep)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        gui_modules.add(".".join(["hyde", "user_interface"] + parts))
for module_name in sorted(gui_modules):
    importlib.import_module(module_name)
report["gui_modules"] = sorted(gui_modules)
observe("importing every other GUI module")

sys.stdout.write("PROBE_JSON " + json.dumps(report, default=str) + "\n")
"""


class TestGeneratedGraphicsFormatTable(unittest.TestCase):
    """Hyde ships a generated table of matplotlib's export formats rather than
    querying matplotlib at runtime, because that query imports pyplot and
    resolves an interactive backend, which the GUI process must not do.

    A generated artifact can go stale silently, so these are the trigger: they
    fail when the checked-in table and the installed matplotlib disagree.
    """

    def test_the_generated_table_matches_the_installed_matplotlib(self):
        from hyde.features.matplotlib_features import (
            GRAPHICS_EXPORT_FILETYPES,
            runtime_graphics_export_filetypes,
        )

        self.assertEqual(
            dict(GRAPHICS_EXPORT_FILETYPES),
            dict(runtime_graphics_export_filetypes()),
            "matplotlib's export formats have changed. Run "
            "scripts/regenerate_graphics_formats.py",
        )

    def test_copy_offers_only_formats_the_installed_matplotlib_can_export(self):
        # Asked of matplotlib rather than of the generated table, like the
        # sibling above: a table that still lists a format matplotlib has
        # dropped would vouch for a menu entry that renders nothing.
        from hyde.features.matplotlib_features import (
            runtime_graphics_export_filetypes,
        )

        exportable = set(runtime_graphics_export_filetypes())
        clipboard = {
            candidate
            for item in graphics_clipboard_representations()
            for candidate in item.output_formats
        }

        self.assertTrue(
            clipboard <= exportable,
            f"copy offers formats that cannot be exported: {sorted(clipboard - exportable)}",
        )

    def test_the_gui_start_up_never_imports_pyplot(self):
        """The whole reason the table is generated: importing pyplot resolves an
        interactive backend, and the GUI process must not.

        Observed in a subprocess because `sys.modules` in this process is no
        evidence. Test modules here import pyplot at module scope, so it is
        already present before the first test runs and a snapshot-and-compare
        guard would pass whatever the product did.

        Covers the GUI process only, up to the point its menus are built. The
        kernel is a separate process where `spyder_kernels` sets
        `IPKernelApp.matplotlib = "inline"`, so pyplot is pre-imported there and
        this rule was never about it.
        """
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        # Nothing may pre-decide the backend for the probe: MPLBACKEND changes
        # what importing pyplot does, and the point is to watch a GUI process
        # that has made no such arrangement.
        environment.pop("MPLBACKEND", None)
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(repo_root)]
            + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])
        )
        completed = subprocess.run(
            [sys.executable, "-c", _GUI_START_UP_PYPLOT_PROBE],
            cwd=str(repo_root),
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
        )
        transcript = (
            f"exit status {completed.returncode}\n"
            f"--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}"
        )
        reports = [
            line[len("PROBE_JSON ") :]
            for line in completed.stdout.splitlines()
            if line.startswith("PROBE_JSON ")
        ]
        self.assertEqual(
            1,
            len(reports),
            f"the start-up probe did not finish, so nothing was observed:\n{transcript}",
        )
        report = json.loads(reports[0])
        stages = [(stage, reached) for stage, reached in report["stages"]]

        self.assertEqual(
            ("a clean interpreter", False),
            stages[0],
            f"a fresh interpreter already has pyplot, so this observes nothing:\n{stages}",
        )
        self.assertEqual(
            [],
            [stage for stage, reached in stages if reached],
            "matplotlib.pyplot reached the GUI process, which resolves an "
            f"interactive backend there:\n{stages}",
        )

        # The observation only means something if the menus really got built.
        self.assertEqual([], report["logged"], f"the probe skipped work:\n{transcript}")
        plugins_dir = repo_root / "hyde" / "user_interface" / "plugins"
        self.assertEqual(
            sorted(
                entry.name
                for entry in plugins_dir.iterdir()
                if entry.is_dir() and entry.name != "__pycache__"
            ),
            report["plugins"],
            f"the probe did not load every plugin:\n{transcript}",
        )
        for location in ("edit", "figure"):
            self.assertTrue(
                report["menus"].get(location, {}).get("Copy As"),
                f"the {location} menu has no populated Copy As submenu, so "
                f"nothing built the copy menu:\n{report['menus']}",
            )
        self.assertEqual(
            module_names_under(
                repo_root / "hyde" / "user_interface", "hyde.user_interface"
            ),
            report["gui_modules"],
            f"the probe did not import every GUI module:\n{transcript}",
        )


class TestCopyAsSubmenu(unittest.TestCase):
    """Copy As offers the clipboard-capable subset of what Save offers.

    Curation is not preference here: `raw` and `rgba` are raw buffers with no
    MIME type and `svgz` is gzipped SVG nothing pastes, so a menu entry for any
    of them would be a broken action.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def setUp(self):
        self.kernel = FakeKernelRequests()

    def _host(self, figure_context):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        self.save_graphics = SaveGraphicsPlugin({})
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": self.save_graphics,
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        for plugin in manager.plugins.values():
            services = getattr(plugin, "services", None)
            if isinstance(services, dict):
                services["figure_context_service"] = types.SimpleNamespace(
                    active_editable_figure=lambda: figure_context[0]
                )
                services["python_execution_service"] = self.kernel
        return app

    def _submenu_labels(self, menu):
        for action in menu.actions():
            submenu = action.menu()
            if submenu is not None and submenu.title() == "Copy As":
                return [entry.text() for entry in submenu.actions() if not entry.isSeparator()]
        return None

    def test_copy_as_offers_the_three_representations_a_clipboard_distinguishes(self):
        """A clipboard carries representations, not file formats.

        Every raster encoding pastes identically, because the platform
        republishes the image rather than the encoding, so offering a dozen of
        them was offering choices with no consequence.
        """
        app = self._host([None])

        self.assertEqual(
            ["Vector", "Image", "LaTeX"], self._submenu_labels(app.ui.menuEdit)
        )

    def test_copy_as_appears_in_the_figure_context_menu(self):
        app = self._host([None])
        popup = app.menu_context.build_popup_menu("figure", parent=app.ui)

        self.assertEqual(["Vector", "Image", "LaTeX"], self._submenu_labels(popup))

    def test_each_copy_as_entry_emits_its_own_format(self):
        figure_context = [make_save_graphics_context(title="Graph12")]
        app = self._host(figure_context)
        app.menu_context.refresh_enabled_states()

        for item in graphics_clipboard_representations():
            with self.subTest(representation=item.key):
                self.kernel.executed.clear()
                action = app.menu_context.lookup_action(
                    "edit", item.display_label, path=("Copy As",)
                )
                self.assertIsNotNone(action, f"missing Copy As entry for {item.key}")
                action.trigger()
                self.assertEqual(
                    [
                        "fig = hyde.get_figure('Graph12')\n"
                        f"hyde.copy_figure(fig, formats=({item.output_formats[0]!r},), dpi='figure')"
                    ],
                    self.kernel.executed,
                )
                settle_copy(self.save_graphics, self.kernel, item.output_formats[0])

    def test_copy_as_entries_need_an_active_figure(self):
        figure_context = [None]
        app = self._host(figure_context)

        app.menu_context.refresh_enabled_states()
        action = app.menu_context.lookup_action("edit", "Image", path=("Copy As",))
        self.assertFalse(action.isEnabled())

        figure_context[0] = make_save_graphics_context(title="Graph12")
        app.menu_context.refresh_enabled_states()
        self.assertTrue(action.isEnabled())


class TestSaveGraphicsPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_plugin_registers_save_graphics_in_new_figure_menu_section(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": SaveGraphicsPlugin({}),
            "figure_control_dialog": FigureControlPlugin({}),
            "remove_from_graph_dialog": RemoveFromGraphPlugin({}),
        }
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        actions = app.ui.menuFigure.actions()

        self.assertEqual(
            [action.text() for action in actions if not action.isSeparator()],
            [
                "Remove from Graph...",
                "Modify Data Appearance...",
                "Modify Axis...",
                "Save Graphics...",
                "Copy",
                "Copy As",
            ],
        )
        self.assertEqual(len([action for action in actions if action.isSeparator()]), 1)
        self.assertEqual(
            [action.text() for action in actions[-3:]],
            ["Save Graphics...", "Copy", "Copy As"],
        )

    def test_figure_actions_are_disabled_without_an_active_figure(self):
        # These actions need a first-class figure. Before menu preconditions
        # were live they stayed permanently enabled and silently did nothing.
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": SaveGraphicsPlugin({}),
            "figure_control_dialog": FigureControlPlugin({}),
            "remove_from_graph_dialog": RemoveFromGraphPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        figure_context = [None]
        for plugin in manager.plugins.values():
            services = getattr(plugin, "services", None)
            if isinstance(services, dict):
                services["figure_context_service"] = types.SimpleNamespace(
                    active_editable_figure=lambda: figure_context[0]
                )

        app.menu_context.refresh_enabled_states()
        without_figure = {
            action.text(): action.isEnabled()
            for action in app.ui.menuFigure.actions()
            if not action.isSeparator()
        }

        figure_context[0] = make_save_graphics_context(title="Figure9")
        app.menu_context.refresh_enabled_states()
        with_figure = {
            action.text(): action.isEnabled()
            for action in app.ui.menuFigure.actions()
            if not action.isSeparator()
        }

        for name in (
            "Save Graphics...",
            "Modify Axis...",
            "Modify Data Appearance...",
            "Remove from Graph...",
        ):
            with self.subTest(action=name):
                self.assertFalse(without_figure[name], f"{name} should need a figure")
                self.assertTrue(with_figure[name], f"{name} should enable with a figure")

    def test_save_graphics_action_opens_dialog_for_active_figure(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        self.save_graphics = SaveGraphicsPlugin({})
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": self.save_graphics,
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        figure = make_active_figure_window(app.ui.mdiArea, manager.services, title="Figure9")

        launched = {}

        def record_exec(dialog):
            launched["dialog"] = dialog
            return QtWidgets.QDialog.Accepted

        with patch(
            "hyde.user_interface.plugins.save_graphics_dialog.dialogs.SaveGraphicsDialog.exec",
            new=record_exec,
        ):
            action = manager.services["lookup_menu_action"]("figure", "Save Graphics...")
            self.assertIsNotNone(action)
            action.trigger()

        dialog = launched["dialog"]
        self.assertEqual(dialog.windowTitle(), "Save Graphics")
        self.assertEqual(dialog.figure_context.figure_name(), "Figure9")
        self.assertIs(app.ui.mdiArea.activeSubWindow().widget(), figure)

    def test_dialog_defaults_to_project_exports_directory_with_pdf_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)
            exports_dir = os.path.join(project_dir, "exports")
            expected_path = os.path.join(exports_dir, "Figure9.pdf")

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9"),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            self.assertTrue(os.path.isdir(exports_dir))
            self.assertEqual(dialog.windowTitle(), "Save Graphics")
            self.assertEqual(dialog.selected_path(), expected_path)
            self.assertTrue(dialog.file_widget.isVisibleTo(dialog))
            self.assertNotIn("import hyde", dialog.preview_string())
            self.assertIn("fig = hyde.get_figure('Figure9')", dialog.preview_string())
            self.assertIn(repr(expected_path), dialog.preview_string())
            self.assertIn("format='pdf'", dialog.preview_string())

    def test_dialog_lists_runtime_formats_and_defaults_to_first_available_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9"),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            expected_formats = graphics_export_formats()

            self.assertEqual(
                [
                    dialog.format_list_widget.item(index).text()
                    for index in range(dialog.format_list_widget.count())
                ],
                [item.display_label for item in expected_formats],
            )
            self.assertEqual(dialog.selected_format_key, expected_formats[0].key)
            self.assertEqual(
                dialog.selected_path(),
                os.path.join(
                    project_dir,
                    "exports",
                    f"Figure9{expected_formats[0].preferred_suffix}",
                ),
            )
            self.assertEqual(
                dialog.file_widget.selectedNameFilter(),
                expected_formats[0].name_filter,
            )
            self.assertIn(
                f"format={expected_formats[0].key!r}",
                dialog.preview_string(),
            )

    def test_selecting_new_format_updates_file_target_filter_and_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9"),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            png_row = next(
                index
                for index in range(dialog.format_list_widget.count())
                if dialog.format_list_widget.item(index).text() == "PNG"
            )

            dialog.format_list_widget.setCurrentRow(png_row)
            self.qapp.processEvents()

            self.assertEqual(dialog.selected_format_key, "png")
            self.assertEqual(
                dialog.selected_path(),
                os.path.join(project_dir, "exports", "Figure9.png"),
            )
            self.assertEqual(
                dialog.file_widget.selectedNameFilter(),
                "PNG Files (*.png)",
            )
            self.assertIn(
                repr(os.path.join(project_dir, "exports", "Figure9.png")),
                dialog.preview_string(),
            )
            self.assertIn("format='png'", dialog.preview_string())

    def test_format_change_preserves_deliberate_user_entered_suffix_variant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9"),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            jpg_row = next(
                index
                for index in range(dialog.format_list_widget.count())
                if dialog.format_list_widget.item(index).text() == "JPG"
            )
            png_row = next(
                index
                for index in range(dialog.format_list_widget.count())
                if dialog.format_list_widget.item(index).text() == "PNG"
            )

            dialog.format_list_widget.setCurrentRow(jpg_row)
            self.qapp.processEvents()
            dialog.file_widget.set_selected_path(
                os.path.join(project_dir, "exports", "Figure9.jpeg")
            )
            self.qapp.processEvents()

            dialog.format_list_widget.setCurrentRow(png_row)
            self.qapp.processEvents()

            self.assertEqual(
                dialog.selected_path(),
                os.path.join(project_dir, "exports", "Figure9.jpeg"),
            )
            self.assertEqual(
                dialog.file_widget.selectedNameFilter(),
                "PNG Files (*.png)",
            )
            self.assertIn("format='png'", dialog.preview_string())
            self.assertIn(
                repr(os.path.join(project_dir, "exports", "Figure9.jpeg")),
                dialog.preview_string(),
            )

    def test_dialog_exposes_output_options_and_same_size_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9", size_inches=(5.0, 3.0)),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            self.assertTrue(dialog.options_panel.isVisibleTo(dialog))
            self.assertEqual(dialog.dpi_spin_box.value(), 300)
            self.assertFalse(dialog.transparent_checkbox.isChecked())
            self.assertTrue(dialog.same_size_radio.isChecked())
            self.assertFalse(dialog.width_spin_box.isEnabled())
            self.assertFalse(dialog.height_spin_box.isEnabled())
            self.assertEqual(dialog.width_spin_box.value(), 5.0)
            self.assertEqual(dialog.height_spin_box.value(), 3.0)
            self.assertIn("dpi=300", dialog.preview_string())
            self.assertIn("transparent=False", dialog.preview_string())
            self.assertNotIn("set_size_inches(", dialog.preview_string())

    def test_switching_to_custom_size_updates_preview_without_preserving_hidden_draft(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9", size_inches=(5.0, 3.0)),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            dialog.custom_size_radio.setChecked(True)
            self.qapp.processEvents()
            dialog.width_spin_box.setValue(7.5)
            dialog.height_spin_box.setValue(4.5)
            self.qapp.processEvents()

            self.assertTrue(dialog.width_spin_box.isEnabled())
            self.assertTrue(dialog.height_spin_box.isEnabled())
            self.assertIn("fig.set_size_inches(7.5, 4.5, forward=False)", dialog.preview_string())

            dialog.same_size_radio.setChecked(True)
            self.qapp.processEvents()
            self.assertFalse(dialog.width_spin_box.isEnabled())
            self.assertFalse(dialog.height_spin_box.isEnabled())
            self.assertEqual(dialog.width_spin_box.value(), 5.0)
            self.assertEqual(dialog.height_spin_box.value(), 3.0)
            self.assertNotIn("fig.set_size_inches(7.5, 4.5, forward=False)", dialog.preview_string())

            dialog.custom_size_radio.setChecked(True)
            self.qapp.processEvents()
            self.assertEqual(dialog.width_spin_box.value(), 5.0)
            self.assertEqual(dialog.height_spin_box.value(), 3.0)
            self.assertNotIn("fig.set_size_inches(7.5, 4.5, forward=False)", dialog.preview_string())

    def test_transparent_toggle_disables_for_jpg_and_format_change_keeps_custom_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9", size_inches=(5.0, 3.0)),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            dialog.custom_size_radio.setChecked(True)
            self.qapp.processEvents()
            dialog.width_spin_box.setValue(6.0)
            dialog.height_spin_box.setValue(4.0)
            dialog.transparent_checkbox.setChecked(True)
            dialog.dpi_spin_box.setValue(450)
            self.qapp.processEvents()

            jpg_row = next(
                index
                for index in range(dialog.format_list_widget.count())
                if dialog.format_list_widget.item(index).text() == "JPG"
            )
            dialog.format_list_widget.setCurrentRow(jpg_row)
            self.qapp.processEvents()

            self.assertFalse(dialog.transparent_checkbox.isEnabled())
            self.assertFalse(dialog.transparent_checkbox.isChecked())
            self.assertEqual(dialog.width_spin_box.value(), 6.0)
            self.assertEqual(dialog.height_spin_box.value(), 4.0)
            self.assertIn("format='jpg'", dialog.preview_string())
            self.assertIn("dpi=450", dialog.preview_string())
            self.assertIn("transparent=False", dialog.preview_string())
            self.assertIn("fig.set_size_inches(6.0, 4.0, forward=False)", dialog.preview_string())

    def test_dialog_preview_matches_figure_ir_for_current_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9", size_inches=(5.0, 3.0)),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            dialog.custom_size_radio.setChecked(True)
            dialog.width_spin_box.setValue(6.0)
            dialog.height_spin_box.setValue(4.0)
            dialog.transparent_checkbox.setChecked(True)
            dialog.dpi_spin_box.setValue(450)
            self.qapp.processEvents()

            state = dialog.build_preview_state(dialog.selected_path())
            self.assertIsInstance(state, FigureIR)
            self.assertIsInstance(dialog.widget_ir, FigureIR)
            expected_state = FigureIR(figure_name=dialog.figure_name()).with_save_graphics(
                dialog.selected_path(),
                output_formats=(dialog.selected_format_key,),
                dpi=dialog.selected_dpi(),
                transparent=dialog.selected_transparent(),
                size_inches=dialog.selected_size_override_inches(),
            )

            self.assertEqual(state.python_source(log=False), expected_state.python_source(log=False))
            self.assertEqual(dialog.widget_ir.python_source(log=False), expected_state.python_source(log=False))
            self.assertEqual(dialog.preview_string(), expected_state.python_source(log=False))

    def test_footer_actions_reuse_the_same_preview_backed_payload(self):
        class ExecutionService(KernelRequestRecorder):
            def __init__(self):
                self.hidden_calls = []
                self.visible_calls = []

            def execute_hidden(self, code, silent=True):
                self.hidden_calls.append((str(code), bool(silent)))
                return True

            def execute_visible(self, code):
                self.visible_calls.append(str(code))
                return True

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)
            execution_service = ExecutionService()
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.clear()

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9", size_inches=(5.0, 3.0)),
                services={
                    "get_current_project_dir": lambda: project_dir,
                    "python_execution_service": execution_service,
                    "visible_terminal_service": execution_service,
                },
            )
            dialog.show()
            self.qapp.processEvents()

            dialog.custom_size_radio.setChecked(True)
            dialog.width_spin_box.setValue(6.0)
            dialog.height_spin_box.setValue(4.0)
            dialog.transparent_checkbox.setChecked(True)
            dialog.dpi_spin_box.setValue(450)
            self.qapp.processEvents()

            expected_payload = dialog.widget_ir.python_source(log=False)
            self.assertEqual(dialog.preview_string(), expected_payload)

            dialog.copy_button.click()
            dialog.to_ipython_button.click()
            dialog.ok_button.click()
            self.qapp.processEvents()

            self.assertEqual(clipboard.text(), expected_payload)
            self.assertEqual(execution_service.visible_calls, [expected_payload])
            self.assertEqual(execution_service.hidden_calls, [(expected_payload, True)])

    def test_dialog_uses_editable_context_current_size_for_same_size_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9", size_inches=(7.5, 4.25)),
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            self.assertTrue(dialog.same_size_radio.isChecked())
            self.assertEqual(dialog.width_spin_box.value(), 7.5)
            self.assertEqual(dialog.height_spin_box.value(), 4.25)
            self.assertNotIn("set_size_inches(", dialog.preview_string())

    def test_dialog_uses_editable_context_for_default_target_size_and_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)
            figure_context = RecordingEditableFigureContext()

            dialog = SaveGraphicsDialog(
                figure_context,
                services={"get_current_project_dir": lambda: project_dir},
            )
            dialog.show()
            self.qapp.processEvents()

            self.assertIn("current_size_inches", figure_context.calls)
            self.assertIn("figure_name", figure_context.calls)
            self.assertEqual(
                dialog.selected_path(),
                os.path.join(project_dir, "exports", "ExplicitContextFigure.pdf"),
            )
            self.assertEqual(dialog.width_spin_box.value(), 8.0)
            self.assertEqual(dialog.height_spin_box.value(), 3.5)
            self.assertIn(
                "fig = hyde.get_figure('ExplicitContextFigure')",
                dialog.preview_string(),
            )

    def test_ok_exports_live_first_class_figure_to_default_pdf_target(self):
        class EvaluatingExecutionService(KernelRequestRecorder):
            def __init__(self):
                self.hidden_calls = []

            def execute_hidden(self, code, silent=True):
                self.hidden_calls.append((str(code), bool(silent)))
                exec(str(code), {"__builtins__": __builtins__, "hyde": hyde}, {})
                return True

        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as live_pyplot

        @hyde.figure(register=False)
        def Figure9(x, trace_a, trace_b):
            fig = live_pyplot.figure("Figure9")
            ax = fig.add_subplot(111)
            ax.plot(x, trace_a, label="trace_a")
            ax.plot(x, trace_b, label="trace_b")
            return fig

        Figure9([0, 1, 2], [1, 4, 9], [9, 4, 1])

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)
            execution_service = EvaluatingExecutionService()
            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="Figure9"),
                services={
                    "get_current_project_dir": lambda: project_dir,
                    "python_execution_service": execution_service,
                },
            )
            dialog.show()
            self.qapp.processEvents()

            dialog.ok_button.click()
            self.qapp.processEvents()

            output_path = os.path.join(project_dir, "exports", "Figure9.pdf")
            self.assertTrue(os.path.isfile(output_path))
            self.assertGreater(os.path.getsize(output_path), 0)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
            self.assertEqual(len(execution_service.hidden_calls), 1)
            self.assertIn(repr(output_path), execution_service.hidden_calls[0][0])

    def test_ok_resolves_the_live_kernel_figure_at_export_time(self):
        class EvaluatingExecutionService(KernelRequestRecorder):
            def __init__(self):
                self.hidden_calls = []

            def execute_hidden(self, code, silent=True):
                self.hidden_calls.append((str(code), bool(silent)))
                exec(str(code), {"__builtins__": __builtins__, "hyde": hyde}, {})
                return True

        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as live_pyplot

        @hyde.figure(register=False)
        def FigureLiveKernel(x, trace_a, trace_b):
            fig = live_pyplot.figure("FigureLiveKernel")
            ax = fig.add_subplot(111)
            ax.plot(x, trace_a, label="trace_a")
            ax.plot(x, trace_b, label="trace_b")
            return fig

        FigureLiveKernel([0, 1, 2], [1, 4, 9], [9, 4, 1])

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)
            execution_service = EvaluatingExecutionService()
            dialog = SaveGraphicsDialog(
                make_save_graphics_context(title="FigureLiveKernel"),
                services={
                    "get_current_project_dir": lambda: project_dir,
                    "python_execution_service": execution_service,
                },
            )
            dialog.show()
            self.qapp.processEvents()

            live_figure = hyde.get_figure("FigureLiveKernel")
            live_figure.axes[0].plot([0, 1, 2], [2, 2, 2], label="late_trace")
            observed = {}
            original_savefig = live_figure.savefig

            def record_live_savefig(path, *args, **kwargs):
                observed["path"] = path
                observed["line_count"] = len(live_figure.axes[0].lines)
                observed["kwargs"] = dict(kwargs)
                return None

            live_figure.savefig = record_live_savefig
            try:
                dialog.ok_button.click()
                self.qapp.processEvents()
            finally:
                live_figure.savefig = original_savefig

            self.assertEqual(observed["line_count"], 3)
            self.assertEqual(
                observed["path"],
                os.path.join(project_dir, "exports", "FigureLiveKernel.pdf"),
            )
            self.assertEqual(observed["kwargs"]["format"], "pdf")
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
            self.assertEqual(len(execution_service.hidden_calls), 1)
