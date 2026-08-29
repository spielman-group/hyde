import os
import tempfile
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
    runtime_graphics_export_formats,
)
from hyde.user_interface.main import HydeApp
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.plugins.figure_control_dialog import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_interactive import Plugin as FigurePlugin
from hyde.user_interface.plugins.figure_interactive.context import EditableFigureContext
from hyde.features.matplotlib_ir import FigureIR
from hyde.features.matplotlib_features import (
    clipboard_mime_type_for_format,
    graphics_clipboard_formats,
)
from hyde.user_interface.plugins.save_graphics_dialog.clipboard import clipboard_mime_data
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow
from hyde.user_interface.plugins.remove_from_graph_dialog import Plugin as RemoveFromGraphPlugin
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
    app.clear_status_message = lambda: None
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


class TestFigureCopyCommand(unittest.TestCase):
    """Copy lowers to a Hyde helper because the clipboard is GUI-owned.

    Plain matplotlib cannot express "put this on the clipboard", so this is the
    one place IR-CONTROL.md's carve-out for Hyde helpers in emitted Python
    applies. DPI is passed as the 'figure' sentinel so the kernel resolves it
    against the live figure rather than the GUI mirroring kernel state.
    """

    def test_copy_lowers_to_a_hyde_clipboard_call_on_the_looked_up_figure(self):
        source = FigureIR(figure_name="Graph12").with_copy_graphics().python_source(log=False)

        self.assertEqual(
            source.splitlines(),
            [
                "fig = hyde.get_figure('Graph12')",
                "hyde.copy_figure(fig, format='pdf', dpi='figure')",
            ],
        )

    def test_copy_defaults_to_pdf_and_carries_the_requested_format(self):
        for output_format in ("pdf", "png", "svg"):
            with self.subTest(output_format=output_format):
                source = (
                    FigureIR(figure_name="Graph12")
                    .with_copy_graphics(output_format=output_format)
                    .python_source(log=False)
                )
                self.assertIn(f"format={output_format!r}", source)

    def test_copy_always_resolves_a_figure_name_to_look_up(self):
        # The emitted Python has to name a figure for hyde.get_figure, so an
        # absent name falls back to the default the save path uses too.
        source = FigureIR().with_copy_graphics().python_source(log=False)

        self.assertRegex(source.splitlines()[0], r"^fig = hyde\.get_figure\('.+'\)$")

    def test_copy_state_without_a_figure_name_fails_validation(self):
        with self.assertRaises(ValueError):
            dataclass_replace(
                FigureIR(figure_name="Graph12").with_copy_graphics(), figure_name=None
            ).validate()

    def test_copy_carries_no_output_path(self):
        # Copy has no export target; a state carrying one is a save state that
        # took the wrong branch.
        with self.assertRaises(ValueError):
            dataclass_replace(
                FigureIR(figure_name="Graph12").with_copy_graphics(),
                output_path="/tmp/Graph12.pdf",
            ).validate()

    def test_save_still_rejects_the_figure_dpi_sentinel(self):
        # The sentinel is valid only where the kernel is meant to resolve it.
        with self.assertRaises(ValueError):
            FigureIR(figure_name="Graph12").with_save_graphics(
                "/tmp/Graph12.pdf", dpi="figure"
            ).validate()

    def test_copy_does_not_emit_savefig_or_touch_figure_size(self):
        source = FigureIR(figure_name="Graph12").with_copy_graphics().python_source(log=False)

        self.assertNotIn("savefig", source)
        self.assertNotIn("set_size_inches", source)


class TestFigureCopyEndToEnd(unittest.TestCase):
    """The whole path: menu action -> emitted Python -> kernel render ->
    bytes handed to the GUI -> clipboard."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_copy_action_emits_the_copy_command_for_the_active_figure(self):
        executed = []
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
            ),
            "python_execution_service": types.SimpleNamespace(
                execute_hidden=lambda code, silent=True: executed.append(code)
            ),
        }

        self.assertTrue(plugin.copy_active_figure())
        self.assertEqual(
            executed,
            [
                "fig = hyde.get_figure('Graph12')\n"
                "hyde.copy_figure(fig, format='pdf', dpi='figure')"
            ],
        )

    def test_copy_action_does_nothing_without_an_active_figure(self):
        executed = []
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: None
            ),
            "python_execution_service": types.SimpleNamespace(
                execute_hidden=lambda code, silent=True: executed.append(code)
            ),
        }

        self.assertFalse(plugin.copy_active_figure())
        self.assertEqual([], executed)

    def test_rendered_bytes_from_the_kernel_reach_the_clipboard_as_pdf(self):
        import base64

        plugin = SaveGraphicsPlugin({})
        plugin.services = {}
        rendered = b"%PDF-1.4 fake pdf bytes"

        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {
                    "payload_base64": base64.b64encode(rendered).decode("ascii"),
                    "output_format": "pdf",
                    "is_text": False,
                },
            }
        )

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
                side_effect=lambda payload, **kw: captured.append((payload, kw)),
            ):
                self.assertTrue(hyde.copy_figure(figure, format="pdf"))

            self.assertEqual(1, len(captured))
            payload, kwargs = captured[0]
            self.assertEqual("pdf", kwargs["output_format"])
            self.assertFalse(kwargs["is_text"])
            self.assertTrue(base64.b64decode(payload).startswith(b"%PDF"))
            self.assertEqual(original_size, tuple(figure.get_size_inches()))
            self.assertEqual(original_dpi, figure.dpi)
        finally:
            plt.close(figure)

    def test_clipboard_capable_formats_exclude_the_unpasteable_ones(self):
        keys = [item.key for item in graphics_clipboard_formats()]

        self.assertEqual(["pdf", "png"], keys[:2])
        for excluded in ("raw", "rgba", "svgz"):
            self.assertNotIn(excluded, keys)
        for expected in ("pdf", "png", "svg", "pgf", "jpeg", "tiff"):
            self.assertIn(expected, keys)

    def test_a_format_with_no_clipboard_representation_yields_no_payload(self):
        self.assertIsNone(clipboard_mime_data(b"junk", output_format="raw"))
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
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": SaveGraphicsPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        for plugin in manager.plugins.values():
            services = getattr(plugin, "services", None)
            if isinstance(services, dict):
                services["figure_context_service"] = types.SimpleNamespace(
                    active_editable_figure=lambda: figure_context[0]
                )
                services["python_execution_service"] = types.SimpleNamespace(
                    execute_hidden=lambda code, silent=True: self.executed.append(code)
                )
        return app

    def setUp(self):
        self.executed = []

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
        from_edit = list(self.executed)

        self.executed.clear()
        app.menu_context.lookup_action("figure", "Copy").trigger()
        from_figure = list(self.executed)

        self.assertEqual(
            [
                "fig = hyde.get_figure('Graph12')\n"
                "hyde.copy_figure(fig, format='pdf', dpi='figure')"
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

        plugin = SaveGraphicsPlugin({})
        plugin.services = {}
        latex = b"\\begingroup%\n\\makeatletter%\n\\begin{pgfpicture}%"

        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {
                    "payload_base64": base64.b64encode(latex).decode("ascii"),
                    "output_format": "pgf",
                    "is_text": True,
                },
            }
        )

        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        self.assertTrue(mime_data.hasText())
        self.assertIn("pgfpicture", mime_data.text())

    def test_pgf_payload_carries_no_image_representation(self):
        payload = clipboard_mime_data(b"\\begin{pgfpicture}", output_format="pgf", is_text=True)

        self.assertTrue(payload.hasText())
        for image_type in ("image/png", "application/pdf", "image/svg+xml"):
            self.assertNotIn(image_type, payload.formats())

    def test_the_kernel_marks_pgf_as_text_and_other_formats_as_not(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import hyde

        figure = plt.figure(figsize=(3.0, 2.0))
        figure.add_subplot(111).plot([0, 1], [1, 2])
        try:
            for output_format, expected_text in (("pgf", True), ("png", False), ("pdf", False)):
                with self.subTest(output_format=output_format):
                    captured = []
                    with patch(
                        "hyde.execution.ipc.signal_copy_to_clipboard",
                        side_effect=lambda payload, **kw: captured.append(kw),
                    ):
                        hyde.copy_figure(figure, format=output_format)
                    self.assertEqual(expected_text, captured[0]["is_text"])
        finally:
            plt.close(figure)


class TestPngCompanionRepresentation(unittest.TestCase):
    """A clipboard payload can carry several representations of one content.

    Without a PNG alongside the requested format, a PDF copy appears to do
    nothing in the many applications that do not accept PDF from the clipboard.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_an_image_copy_carries_both_its_own_format_and_png(self):
        payload = clipboard_mime_data(
            b"%PDF-1.4 fake",
            output_format="pdf",
            companion_png=b"\x89PNG\r\n\x1a\n fake",
        )

        self.assertIn("application/pdf", payload.formats())
        self.assertIn("image/png", payload.formats())
        self.assertEqual(b"%PDF-1.4 fake", bytes(payload.data("application/pdf")))
        self.assertEqual(b"\x89PNG\r\n\x1a\n fake", bytes(payload.data("image/png")))

    def test_a_png_copy_does_not_duplicate_itself(self):
        payload = clipboard_mime_data(
            b"\x89PNG fake", output_format="png", companion_png=b"\x89PNG fake"
        )

        self.assertEqual(["image/png"], [f for f in payload.formats() if f.startswith("image/")])

    def test_pgf_is_excluded_from_the_companion(self):
        # Attaching an image to a text copy would mean pasting into a word
        # processor silently yields a picture instead of the LaTeX source.
        payload = clipboard_mime_data(
            b"\\begin{pgfpicture}",
            output_format="pgf",
            is_text=True,
            companion_png=b"\x89PNG fake",
        )

        self.assertTrue(payload.hasText())
        self.assertNotIn("image/png", payload.formats())

    def test_the_kernel_renders_a_companion_png_for_image_formats_only(self):
        import base64
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import hyde

        figure = plt.figure(figsize=(3.0, 2.0))
        figure.add_subplot(111).plot([0, 1], [1, 2])
        try:
            for output_format, expect_companion in (
                ("pdf", True),
                ("svg", True),
                ("png", False),
                ("pgf", False),
            ):
                with self.subTest(output_format=output_format):
                    captured = []
                    with patch(
                        "hyde.execution.ipc.signal_copy_to_clipboard",
                        side_effect=lambda payload, **kw: captured.append(kw),
                    ):
                        hyde.copy_figure(figure, format=output_format)
                    companion = captured[0].get("companion_png_base64")
                    if expect_companion:
                        self.assertTrue(companion, f"{output_format} should carry a PNG")
                        self.assertTrue(base64.b64decode(companion).startswith(b"\x89PNG"))
                    else:
                        self.assertFalse(companion, f"{output_format} should carry no PNG")
        finally:
            plt.close(figure)

    def test_a_pdf_copy_is_pasteable_by_a_png_only_consumer(self):
        import base64

        plugin = SaveGraphicsPlugin({})
        plugin.services = {}
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {
                    "payload_base64": base64.b64encode(b"%PDF-1.4 fake").decode("ascii"),
                    "output_format": "pdf",
                    "is_text": False,
                    "companion_png_base64": base64.b64encode(b"\x89PNG fake").decode("ascii"),
                },
            }
        )

        mime_data = QtWidgets.QApplication.clipboard().mimeData()
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
            "python_execution_service": types.SimpleNamespace(
                execute_hidden=lambda code, silent=True: None
            ),
            "status_message_service": types.SimpleNamespace(
                show_status_message=lambda text: messages.append(text),
                clear_status_message=lambda: messages.append(None),
            ),
        }
        return plugin, messages

    def test_a_completed_copy_confirms_which_format_reached_the_clipboard(self):
        import base64

        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure(output_format="png")
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {
                    "payload_base64": base64.b64encode(b"\x89PNG fake").decode("ascii"),
                    "output_format": "png",
                    "is_text": False,
                },
            }
        )

        self.assertTrue(any("PNG" in str(m) for m in messages), messages)
        self.assertTrue(any("clipboard" in str(m).lower() for m in messages), messages)

    def test_a_copy_that_never_completes_reports_failure_and_restores_the_cursor(self):
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure(output_format="pdf")

        self.assertTrue(plugin.copy_in_flight())
        plugin.on_copy_timeout()

        self.assertFalse(plugin.copy_in_flight())
        self.assertTrue(any("could not" in str(m).lower() for m in messages), messages)
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_the_cursor_is_never_left_busy_after_a_completed_copy(self):
        import base64

        plugin, _ = self._plugin_with_status()
        plugin.copy_active_figure(output_format="pdf")
        plugin.show_busy_cursor()
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

    def test_a_fast_copy_shows_no_busy_cursor(self):
        import base64

        plugin, _ = self._plugin_with_status()
        plugin.copy_active_figure(output_format="pdf")
        # Completion before the delay elapses, so the cursor was never shown.
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

    def test_a_failed_render_does_not_confirm_success(self):
        plugin, messages = self._plugin_with_status()
        plugin.copy_active_figure(output_format="pdf")
        plugin.on_kernel_message(
            {
                "task": "COPY_TO_CLIPBOARD_REQUEST",
                "data": {"payload_base64": "", "output_format": "pdf", "is_text": False},
            }
        )

        self.assertFalse(any("Copied" in str(m) for m in messages), messages)
        self.assertTrue(any("could not" in str(m).lower() for m in messages), messages)

    def test_copy_works_without_a_status_service(self):
        plugin = SaveGraphicsPlugin({})
        plugin.services = {
            "figure_context_service": types.SimpleNamespace(
                active_editable_figure=lambda: make_save_graphics_context(title="Graph12")
            ),
            "python_execution_service": types.SimpleNamespace(
                execute_hidden=lambda code, silent=True: None
            ),
        }

        self.assertTrue(plugin.copy_active_figure())
        plugin.on_copy_timeout()
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())


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
        self.executed = []

    def _host(self, figure_context):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": SaveGraphicsPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        for plugin in manager.plugins.values():
            services = getattr(plugin, "services", None)
            if isinstance(services, dict):
                services["figure_context_service"] = types.SimpleNamespace(
                    active_editable_figure=lambda: figure_context[0]
                )
                services["python_execution_service"] = types.SimpleNamespace(
                    execute_hidden=lambda code, silent=True: self.executed.append(code)
                )
        return app

    def _submenu_labels(self, menu):
        for action in menu.actions():
            submenu = action.menu()
            if submenu is not None and submenu.title() == "Copy As":
                return [entry.text() for entry in submenu.actions() if not entry.isSeparator()]
        return None

    def test_copy_as_lists_the_clipboard_capable_formats_in_save_dialog_order(self):
        app = self._host([None])
        expected = [item.display_label for item in graphics_clipboard_formats()]

        self.assertEqual(expected, self._submenu_labels(app.ui.menuEdit))

    def test_copy_as_omits_formats_with_no_clipboard_representation(self):
        app = self._host([None])
        labels = self._submenu_labels(app.ui.menuEdit)

        for excluded in ("RAW", "RGBA", "SVGZ"):
            self.assertNotIn(excluded, labels)
        for expected in ("PDF", "PNG", "SVG", "PGF", "JPEG", "TIFF"):
            self.assertIn(expected, labels)

    def test_copy_as_appears_in_the_figure_context_menu(self):
        app = self._host([None])
        popup = app.menu_context.build_popup_menu("figure", parent=app.ui)

        self.assertEqual(
            [item.display_label for item in graphics_clipboard_formats()],
            self._submenu_labels(popup),
        )

    def test_each_copy_as_entry_emits_its_own_format(self):
        figure_context = [make_save_graphics_context(title="Graph12")]
        app = self._host(figure_context)
        app.menu_context.refresh_enabled_states()

        for item in graphics_clipboard_formats():
            with self.subTest(output_format=item.key):
                self.executed.clear()
                action = app.menu_context.lookup_action(
                    "edit", item.display_label, path=("Copy As",)
                )
                self.assertIsNotNone(action, f"missing Copy As entry for {item.key}")
                action.trigger()
                self.assertEqual(
                    [
                        "fig = hyde.get_figure('Graph12')\n"
                        f"hyde.copy_figure(fig, format={item.key!r}, dpi='figure')"
                    ],
                    self.executed,
                )

    def test_copy_as_entries_need_an_active_figure(self):
        figure_context = [None]
        app = self._host(figure_context)

        app.menu_context.refresh_enabled_states()
        action = app.menu_context.lookup_action("edit", "PNG", path=("Copy As",))
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
        manager.plugins = {
            "figure": FigurePlugin({}),
            "save_graphics_dialog": SaveGraphicsPlugin({}),
        }
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)
        figure = make_active_figure_window(app.ui.mdiArea, manager.services, title="Figure9")

        launched = {}

        def record_exec(dialog):
            launched["dialog"] = dialog
            return QtWidgets.QDialog.Accepted

        with patch(
            "hyde.user_interface.plugins.save_graphics_dialog.dialogs.SaveGraphicsDialog.exec_",
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

            expected_formats = runtime_graphics_export_formats()

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
                output_format=dialog.selected_format_key,
                dpi=dialog.selected_dpi(),
                transparent=dialog.selected_transparent(),
                size_inches=dialog.selected_size_override_inches(),
            )

            self.assertEqual(state.python_source(log=False), expected_state.python_source(log=False))
            self.assertEqual(dialog.widget_ir.python_source(log=False), expected_state.python_source(log=False))
            self.assertEqual(dialog.preview_string(), expected_state.python_source(log=False))

    def test_footer_actions_reuse_the_same_preview_backed_payload(self):
        class ExecutionService:
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

            dialog.to_clip_button.click()
            dialog.to_cmd_line_button.click()
            dialog.do_it_button.click()
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

    def test_do_it_exports_live_first_class_figure_to_default_pdf_target(self):
        class EvaluatingExecutionService:
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

            dialog.do_it_button.click()
            self.qapp.processEvents()

            output_path = os.path.join(project_dir, "exports", "Figure9.pdf")
            self.assertTrue(os.path.isfile(output_path))
            self.assertGreater(os.path.getsize(output_path), 0)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
            self.assertEqual(len(execution_service.hidden_calls), 1)
            self.assertIn(repr(output_path), execution_service.hidden_calls[0][0])

    def test_do_it_resolves_the_live_kernel_figure_at_export_time(self):
        class EvaluatingExecutionService:
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
                dialog.do_it_button.click()
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
