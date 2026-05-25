import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import matplotlib

    matplotlib.use("Agg")
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

import hyde
from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import (
    figure_ir_from_live_state,
    runtime_graphics_export_formats,
)
from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugins.figure_control_dialog import Plugin as FigureControlPlugin
from hyde.user_interface.plugins.figure_interactive import Plugin as FigurePlugin
from hyde.user_interface.plugins.figure_interactive.window import FigureState, FigureWindow
from hyde.user_interface.plugins.remove_from_graph_dialog import Plugin as RemoveFromGraphPlugin
from hyde.user_interface.plugins.save_graphics_dialog import Plugin as SaveGraphicsPlugin
from hyde.user_interface.plugins.save_graphics_dialog.dialogs import (
    FigureGraphicsExportState,
    SaveGraphicsDialog,
)
from hyde.user_interface.shared.plugin import HydePluginManager


def make_plugin_host(plugin_manager):
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
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
    app.process_tree = object()
    app.show_plugin_window = lambda key: key
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
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
    state = FigureState()
    state.set_title(title)
    state.set_x_name("x")
    state.set_items(["trace_a", "trace_b"])
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
                "figure_ir": figure_ir_from_live_state(state.normalized_state()),
                "figure_defaults": None,
                "live_state": None,
                "trace_styles": None,
            },
        }
    )
    mdi_area.setActiveSubWindow(subwindow)
    return figure


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
            ],
        )
        self.assertEqual(len([action for action in actions if action.isSeparator()]), 1)
        self.assertTrue(actions[-2].isSeparator())
        self.assertEqual(actions[-1].text(), "Save Graphics...")

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
        class FigureContext:
            def figure_name(self):
                return "Figure9"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)
            exports_dir = os.path.join(project_dir, "exports")
            expected_path = os.path.join(exports_dir, "Figure9.pdf")

            dialog = SaveGraphicsDialog(
                FigureContext(),
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
        class FigureContext:
            def figure_name(self):
                return "Figure9"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                FigureContext(),
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
        class FigureContext:
            def figure_name(self):
                return "Figure9"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                FigureContext(),
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
        class FigureContext:
            def figure_name(self):
                return "Figure9"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                FigureContext(),
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
        class FigureContext:
            def figure_name(self):
                return "Figure9"

            def current_size_inches(self):
                return (5.0, 3.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                FigureContext(),
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
        class FigureContext:
            def figure_name(self):
                return "Figure9"

            def current_size_inches(self):
                return (5.0, 3.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                FigureContext(),
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
        class FigureContext:
            def figure_name(self):
                return "Figure9"

            def current_size_inches(self):
                return (5.0, 3.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                FigureContext(),
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

    def test_dialog_preview_matches_figure_graphics_export_state_for_current_selection(self):
        class FigureContext:
            def figure_name(self):
                return "Figure9"

            def current_size_inches(self):
                return (5.0, 3.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir, exist_ok=True)

            dialog = SaveGraphicsDialog(
                FigureContext(),
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

            state = FigureGraphicsExportState()
            state.set_figure_name(dialog.figure_name())
            state.set_output_path(dialog.selected_path())
            state.set_output_format(dialog.selected_format_key)
            state.set_dpi(dialog.selected_dpi())
            state.set_transparent(dialog.selected_transparent())
            state.set_size_inches(dialog.selected_size_override_inches())

            self.assertEqual(dialog.preview_string(), state.python_source(log=False))

    def test_do_it_exports_live_first_class_figure_to_default_pdf_target(self):
        class FigureContext:
            def figure_name(self):
                return "Figure9"

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
                FigureContext(),
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
        class FigureContext:
            def figure_name(self):
                return "FigureLiveKernel"

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
                FigureContext(),
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
