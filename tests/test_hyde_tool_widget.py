import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec
from hyde.user_interface.shared.plugin import HydeMDIContext
from hyde.user_interface.base_hyde_widgets import (
    HydeDialogWidget,
    HydeDialog,
    HydeFileDialog,
    HydeFileWidget,
    HydeToolWidget,
)
from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugins.figure_interactive.window import FigureIR
import hyde.user_interface as ui_package
from hyde.user_interface.shared.core import HydeIR
from hyde.user_interface.shared.figure import FigureDialogIR, HydeFigureDialogWidget


class DemoToolWidget(HydeToolWidget):
    pass


class DemoDialogWidget(HydeDialogWidget):
    pass


class DemoDialog(HydeDialog):
    pass


class HookedDialogWidget(HydeDialogWidget):
    def __init__(self, *args, **kwargs):
        self.do_it_calls = 0
        self.payload = "print('dialog payload')"
        self.preview_text = "Equation preview"
        super().__init__(*args, **kwargs)
        self.mount_content_widget(QtWidgets.QLabel("Upper content"))
        self.set_preview_string(self.payload, display_text=self.preview_text)
        self.refresh_shell()

    def handle_do_it(self):
        self.do_it_calls += 1


class DispatchingDialogWidget(HydeDialogWidget):
    def __init__(self, *args, **kwargs):
        self.payload = "print('dispatch payload')"
        self.preview_text = "Displayed preview"
        super().__init__(*args, **kwargs)
        self.mount_content_widget(QtWidgets.QLabel("Upper content"))
        self.set_preview_string(self.payload, display_text=self.preview_text)
        self.refresh_shell()


class VisibleDispatchDialogWidget(DispatchingDialogWidget):
    def do_it_dispatch_mode(self):
        return "visible"


class HelpFileDialogWidget(HydeDialogWidget):
    help_filename = "dialog_help.txt"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mount_content_widget(QtWidgets.QLabel("Upper content"))
        self.refresh_shell()


class DemoFigureDialogWidget(HydeFigureDialogWidget):
    figure_patch_command_name = "demo_figure_edit"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mount_content_widget(QtWidgets.QLabel("Upper content"))
        self.refresh_shell()


class ShutdownAwareToolWidget(HydeToolWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        super().shutdown()


class CloseAwareToolWidget(HydeToolWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.close_events = 0

    def closeEvent(self, event):
        self.close_events += 1
        super().closeEvent(event)


class CloseByPolicyToolWidget(CloseAwareToolWidget):
    def close_policy(self):
        return "close"


class ShutdownAwareChild(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


class RecordingVisibleTerminalService:
    def __init__(self):
        self.executed = []

    def execute_visible(self, code):
        self.executed.append(code)


class RecordingExecutionService:
    def __init__(self):
        self.hidden_calls = []
        self.visible_calls = []

    def execute_hidden(self, code, silent=True):
        self.hidden_calls.append((code, silent))
        return True

    def execute_visible(self, code):
        self.visible_calls.append(code)
        return True


class DemoCommandIR(HydeIR):
    def __init__(self, path=None):
        self.path = None if path is None else os.path.abspath(path)

    def set_path(self, path):
        self.path = os.path.abspath(path)
        return self

    def debug_state(self):
        return {"settings": {"path": self.path}}

    def validate(self):
        if not self.path:
            raise ValueError("path is required")
        return self

    def _python_source(self):
        return f"emit({self.path!r})"


class DemoFileDialog(HydeFileDialog):
    selection_mode = "directory"
    require_existing = True
    allowed_suffixes = (".hy",)
    name_filters = ("Demo Packages (*.hy)",)

    def build_preview_state(self, selected_path):
        state = DemoCommandIR()
        state.set_path(selected_path)
        return state


class ConfirmingFileDialog(DemoFileDialog):
    confirm_overwrite = True


class ExtendedDemoFileDialog(DemoFileDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra_controls = QtWidgets.QLabel("Extra controls")
        self.mount_content_widget(self.extra_controls, row=1)


class SuggestedPathFileDialog(HydeFileDialog):
    def __init__(self, suggested_path, *args, **kwargs):
        self._suggested_path = suggested_path
        super().__init__(*args, **kwargs)

    def suggested_path(self):
        return self._suggested_path

    def build_preview_state(self, selected_path):
        state = DemoCommandIR()
        state.set_path(selected_path)
        return state


class CreatingSuggestedPathFileDialog(SuggestedPathFileDialog):
    create_suggested_directory = True


class FakeFigureWindow:
    def __init__(self, figure_ir):
        self.figure_number = 7
        self.widget_ir = copy.deepcopy(figure_ir)


class FakeFigureContext:
    def __init__(self, figure_ir, *, figure_name="Figure0"):
        self.figure_number = 7
        self._figure_window = FakeFigureWindow(figure_ir)
        self._figure_name = str(figure_name)

    def figure_name(self):
        return self._figure_name


def make_demo_figure_ir(title="Figure0", items=("trace_a",)):
    return FigureIRCodec.validate_state(
        FigureIR()
        .with_title(title)
        .with_x_name("x")
        .with_items(list(items))
        .normalized_state()
    )


class TestHydeToolWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_default_shell_stores_common_window_identifier_and_services(self):
        service = object()

        widget = DemoToolWidget(
            services={"demo_service": service},
            window_identifier="demo_tool",
        )

        self.assertEqual(widget.window_identifier(), "demo_tool")
        self.assertEqual(widget.session_key, "demo_tool")
        self.assertIs(widget.service("demo_service"), service)
        self.assertEqual(widget.service("missing", "fallback"), "fallback")
        self.assertIsNotNone(widget.ui)

    def test_dialog_base_stores_services(self):
        service = object()

        dialog = DemoDialogWidget(services={"demo_service": service})

        self.assertIs(dialog.service("demo_service"), service)
        self.assertEqual(dialog.service("missing", "fallback"), "fallback")

    def test_ir_python_source_can_skip_state_debug_logging_for_preview(self):
        state = DemoCommandIR()
        state.set_path("/tmp/demo.hy")

        with patch(
            "hyde.user_interface.shared.core.log_hyde_state_debug"
        ) as log_debug:
            preview_source = state.python_source(log=False)
            committed_source = state.python_source()

        self.assertEqual(preview_source, "emit('/tmp/demo.hy')")
        self.assertEqual(committed_source, preview_source)
        log_debug.assert_called_once()

    def test_user_interface_package_exports_only_current_ir_contract(self):
        self.assertIn("HydeIR", ui_package.__all__)
        self.assertIn("HydeIRDiff", ui_package.__all__)
        self.assertNotIn("HydeGuiState", ui_package.__all__)

    def test_dialog_base_stores_services_without_tool_shell(self):
        service = object()
        import hyde.user_interface.plugins.save_window_dialog  # noqa: F401

        dialog = DemoDialog(services={"demo_service": service})
        dialog.load_ui(
            "save_window_dialog.ui",
            module_name="hyde.user_interface.plugins.save_window_dialog",
        )

        self.assertIs(dialog.service("demo_service"), service)
        self.assertEqual(dialog.service("missing", "fallback"), "fallback")
        self.assertFalse(hasattr(dialog, "shell_ui"))
        self.assertIsNotNone(dialog.ui.saveButton)

    def test_tool_dialog_shell_exposes_content_mount_preview_and_fixed_footer(self):
        dialog = DemoDialogWidget()
        content = QtWidgets.QLabel("Upper content")

        dialog.mount_content_widget(content)
        dialog.refresh_shell()
        dialog.show()
        self.qapp.processEvents()

        self.assertTrue(content.isVisibleTo(dialog))
        self.assertLess(content.geometry().top(), dialog.lower_text_edit.geometry().top())
        self.assertTrue(dialog.lower_text_edit.isReadOnly())
        self.assertEqual(dialog.do_it_button.text(), "Do It")
        self.assertEqual(dialog.to_cmd_line_button.text(), "To Cmd Line")
        self.assertEqual(dialog.to_clip_button.text(), "To Clip")
        self.assertEqual(dialog.help_button.text(), "Help")
        self.assertEqual(dialog.cancel_button.text(), "Cancel")
        self.assertFalse(dialog.do_it_button.isEnabled())
        self.assertFalse(dialog.to_cmd_line_button.isEnabled())
        self.assertTrue(dialog.to_cmd_line_button.isVisibleTo(dialog))
        self.assertFalse(dialog.help_button.isEnabled())
        self.assertTrue(dialog.help_button.isVisibleTo(dialog))
        self.assertGreater(dialog.shell_ui.left_button_layout.count(), 0)
        self.assertGreater(dialog.shell_ui.right_button_layout.count(), 0)

    def test_tool_dialog_shell_supports_stacked_content_rows_and_row_replacement(self):
        dialog = DemoDialogWidget()
        top = QtWidgets.QLabel("Top row")
        lower = QtWidgets.QLabel("Lower row")
        replacement = QtWidgets.QLabel("Replacement top row")

        dialog.mount_content_widget(top)
        dialog.mount_content_widget(lower, row=1)
        dialog.mount_content_widget(replacement)
        dialog.show()
        self.qapp.processEvents()

        self.assertTrue(replacement.isVisibleTo(dialog))
        self.assertTrue(lower.isVisibleTo(dialog))
        self.assertFalse(top.isVisibleTo(dialog))
        self.assertLess(replacement.geometry().top(), lower.geometry().top())
        self.assertLess(lower.geometry().top(), dialog.lower_text_edit.geometry().top())
        self.assertTrue(dialog.lower_text_edit.isVisibleTo(dialog))
        self.assertTrue(dialog.cancel_button.isVisibleTo(dialog))

    def test_tool_dialog_load_ui_can_mount_into_later_content_row(self):
        dialog = DemoDialogWidget()
        top = QtWidgets.QLabel("Top row")

        dialog.mount_content_widget(top)
        loaded = dialog.load_ui(
            "hyde_window_widget.ui",
            module_name="hyde.user_interface",
            row=1,
        )
        dialog.show()
        self.qapp.processEvents()

        self.assertIs(dialog.ui, loaded)
        self.assertTrue(top.isVisibleTo(dialog))
        self.assertTrue(loaded.isVisibleTo(dialog))
        self.assertLess(top.geometry().top(), loaded.geometry().top())
        self.assertLess(loaded.geometry().top(), dialog.lower_text_edit.geometry().top())

    def test_tool_dialog_shell_uses_preview_string_backing_for_base_footer_actions(self):
        clipboard = QtWidgets.QApplication.clipboard()
        terminal_service = RecordingVisibleTerminalService()
        dialog = HookedDialogWidget(
            services={"visible_terminal_service": terminal_service}
        )

        dialog.show()
        self.qapp.processEvents()
        dialog.do_it_button.click()
        dialog.to_clip_button.click()
        dialog.to_cmd_line_button.click()

        self.assertEqual(dialog.lower_text_edit.toPlainText(), dialog.preview_text)
        self.assertEqual(dialog.preview_string(), dialog.payload)
        self.assertEqual(clipboard.text(), dialog.payload)
        self.assertEqual(terminal_service.executed, [dialog.payload])
        self.assertEqual(dialog.do_it_calls, 1)
        self.assertTrue(dialog.to_cmd_line_button.isEnabled())
        self.assertTrue(dialog.to_clip_button.isEnabled())
        self.assertFalse(dialog.help_button.isEnabled())

    def test_dialog_base_return_triggers_default_do_it_action(self):
        dialog = HookedDialogWidget()

        dialog.show()
        self.qapp.processEvents()

        QtWidgets.QApplication.sendEvent(
            dialog,
            QtGui.QKeyEvent(
                QtCore.QEvent.KeyPress,
                QtCore.Qt.Key_Return,
                QtCore.Qt.NoModifier,
            ),
        )
        self.qapp.processEvents()

        self.assertEqual(dialog.do_it_calls, 1)

    def test_tool_dialog_shell_can_show_message_without_enabling_footer_payload_actions(self):
        terminal_service = RecordingVisibleTerminalService()
        dialog = DemoDialogWidget(services={"visible_terminal_service": terminal_service})
        dialog.mount_content_widget(QtWidgets.QLabel("Upper content"))
        dialog.set_preview_message("Validation failed")
        dialog.refresh_shell()

        self.assertEqual(dialog.preview_string(), "")
        self.assertEqual(dialog.lower_text_edit.toPlainText(), "Validation failed")
        self.assertFalse(dialog.to_cmd_line_button.isEnabled())
        self.assertFalse(dialog.to_clip_button.isEnabled())

    def test_dialog_base_do_it_dispatches_hidden_canonical_payload_and_accepts(self):
        execution_service = RecordingExecutionService()
        dialog = DispatchingDialogWidget(
            services={"python_execution_service": execution_service}
        )

        dialog.show()
        self.qapp.processEvents()
        dialog.do_it_button.click()

        self.assertEqual(dialog.lower_text_edit.toPlainText(), dialog.preview_text)
        self.assertEqual(
            execution_service.hidden_calls,
            [(dialog.payload, True)],
        )
        self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_dialog_base_do_it_can_dispatch_visible_payload(self):
        execution_service = RecordingExecutionService()
        dialog = VisibleDispatchDialogWidget(
            services={"python_execution_service": execution_service}
        )

        dialog.show()
        self.qapp.processEvents()
        dialog.do_it_button.click()

        self.assertEqual(execution_service.visible_calls, [dialog.payload])
        self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_dialog_base_help_opens_declared_module_relative_file(self):
        dialog = HelpFileDialogWidget()
        with tempfile.TemporaryDirectory() as tmpdir:
            help_path = os.path.join(tmpdir, "dialog_help.txt")
            with open(help_path, "w", encoding="utf-8") as handle:
                handle.write("dialog help")
            module_file = os.path.join(tmpdir, "dialog_owner.py")

            with patch.object(
                sys.modules[type(dialog).__module__],
                "__file__",
                module_file,
            ), patch(
                "hyde.user_interface.base_hyde_widgets.QDesktopServices.openUrl"
            ) as open_url:
                dialog.refresh_shell()

                self.assertTrue(dialog.help_button.isEnabled())
                dialog.help_button.click()

        opened_url = open_url.call_args.args[0]
        self.assertEqual(opened_url.toLocalFile(), help_path)

    def test_file_widget_applies_declarative_selection_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)
            image_path = os.path.join(tmpdir, "plot.png")
            with open(image_path, "w", encoding="utf-8") as handle:
                handle.write("png")

            directory_widget = HydeFileWidget(
                selection_mode="directory",
                require_existing=True,
                allowed_suffixes=(".hy",),
                initial_path=project_dir,
            )
            file_widget = HydeFileWidget(
                selection_mode="file",
                require_existing=True,
                allowed_suffixes=(".png", ".svg"),
                name_filters=("Images (*.png *.svg)",),
                initial_path=image_path,
            )

            self.qapp.processEvents()

            self.assertTrue(
                directory_widget.testOption(
                    QtWidgets.QFileDialog.DontUseNativeDialog
                )
            )
            self.assertEqual(
                directory_widget.fileMode(),
                QtWidgets.QFileDialog.Directory,
            )
            self.assertTrue(
                directory_widget.testOption(
                    QtWidgets.QFileDialog.ShowDirsOnly
                )
            )
            self.assertEqual(directory_widget.selected_path(), os.path.abspath(project_dir))
            self.assertIsNone(directory_widget.validation_error())

            directory_widget.set_selected_path(os.path.join(tmpdir, "wrong_target"))
            self.qapp.processEvents()
            self.assertIn(".hy", directory_widget.validation_error())

            self.assertEqual(
                file_widget.fileMode(),
                QtWidgets.QFileDialog.ExistingFile,
            )
            self.assertEqual(file_widget.nameFilters(), ["Images (*.png *.svg)"])
            self.assertEqual(file_widget.selected_path(), os.path.abspath(image_path))
            self.assertIsNone(file_widget.validation_error())

            file_widget.set_selected_path(os.path.join(tmpdir, "missing.png"))
            self.qapp.processEvents()
            self.assertIn("does not exist", file_widget.validation_error())

    def test_file_widget_defaults_to_file_selection_mode(self):
        widget = HydeFileWidget()

        self.assertEqual(
            widget.fileMode(),
            QtWidgets.QFileDialog.AnyFile,
        )
        self.assertEqual(
            widget.acceptMode(),
            QtWidgets.QFileDialog.AcceptOpen,
        )
        self.assertFalse(
            widget.testOption(QtWidgets.QFileDialog.ShowDirsOnly)
        )
        self.assertTrue(
            widget.testOption(QtWidgets.QFileDialog.DontConfirmOverwrite)
        )

    def test_embedded_file_widget_suppresses_qfiledialog_accept_behavior(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)
            widget = HydeFileWidget(
                selection_mode="directory",
                require_existing=True,
                initial_path=project_dir,
            )

            self.qapp.processEvents()
            widget.accept()

            self.assertEqual(widget.result(), 0)
            self.assertEqual(widget.selected_path(), os.path.abspath(project_dir))

    def test_escape_in_embedded_file_widget_rejects_outer_dialog(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)
            dialog = DemoFileDialog()

            dialog.file_widget.set_selected_path(project_dir)
            dialog.show()
            self.assertIsNotNone(dialog.file_widget.file_name_edit)
            dialog.file_widget.file_name_edit.setFocus()
            self.qapp.processEvents()

            self.assertTrue(dialog.isVisible())

            QtWidgets.QApplication.sendEvent(
                dialog.file_widget.file_name_edit,
                QtGui.QKeyEvent(
                    QtCore.QEvent.KeyPress,
                    QtCore.Qt.Key_Escape,
                    QtCore.Qt.NoModifier,
                ),
            )
            self.qapp.processEvents()

            self.assertFalse(dialog.isVisible())
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Rejected)

    def test_return_in_embedded_file_widget_triggers_outer_dialog_do_it(self):
        execution_service = RecordingExecutionService()
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)
            dialog = DemoFileDialog(
                services={"python_execution_service": execution_service}
            )

            dialog.file_widget.set_selected_path(project_dir)
            dialog.show()
            self.assertIsNotNone(dialog.file_widget.file_name_edit)
            dialog.file_widget.file_name_edit.setFocus()
            self.qapp.processEvents()

            QtWidgets.QApplication.sendEvent(
                dialog.file_widget.file_name_edit,
                QtGui.QKeyEvent(
                    QtCore.QEvent.KeyPress,
                    QtCore.Qt.Key_Return,
                    QtCore.Qt.NoModifier,
                ),
            )
            self.qapp.processEvents()

            self.assertEqual(
                execution_service.hidden_calls,
                [(f"emit({os.path.abspath(project_dir)!r})", True)],
            )
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_file_dialog_mounts_chooser_and_dispatches_hidden_preview_payload(self):
        execution_service = RecordingExecutionService()
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)
            dialog = DemoFileDialog(
                services={"python_execution_service": execution_service}
            )

            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.do_it_button.click()

            expected_payload = f"emit({os.path.abspath(project_dir)!r})"
            self.assertIs(dialog.mounted_child, dialog.file_widget)
            self.assertEqual(
                dialog.file_widget.selectedNameFilter(),
                "Demo Packages (*.hy)",
            )
            self.assertEqual(dialog.preview_string(), expected_payload)
            self.assertEqual(dialog.lower_text_edit.toPlainText(), expected_payload)
            self.assertEqual(execution_service.hidden_calls, [(expected_payload, True)])
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_file_dialog_subclass_can_add_extra_content_below_embedded_chooser(self):
        execution_service = RecordingExecutionService()
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)
            dialog = ExtendedDemoFileDialog(
                services={"python_execution_service": execution_service}
            )

            dialog.show()
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.do_it_button.click()

            expected_payload = f"emit({os.path.abspath(project_dir)!r})"
            self.assertTrue(dialog.file_widget.isVisibleTo(dialog))
            self.assertTrue(dialog.extra_controls.isVisibleTo(dialog))
            self.assertLess(
                dialog.file_widget.geometry().top(),
                dialog.extra_controls.geometry().top(),
            )
            self.assertLess(
                dialog.extra_controls.geometry().top(),
                dialog.lower_text_edit.geometry().top(),
            )
            self.assertEqual(dialog.preview_string(), expected_payload)
            self.assertEqual(execution_service.hidden_calls, [(expected_payload, True)])
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_file_dialog_routes_valid_preview_payload_through_footer_actions(self):
        clipboard = QtWidgets.QApplication.clipboard()
        terminal_service = RecordingVisibleTerminalService()
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)
            dialog = DemoFileDialog(
                services={"visible_terminal_service": terminal_service}
            )

            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.to_clip_button.click()
            dialog.to_cmd_line_button.click()

            expected_payload = f"emit({os.path.abspath(project_dir)!r})"
            self.assertEqual(dialog.preview_string(), expected_payload)
            self.assertEqual(dialog.lower_text_edit.toPlainText(), expected_payload)
            self.assertTrue(dialog.do_it_button.isEnabled())
            self.assertTrue(dialog.to_clip_button.isEnabled())
            self.assertTrue(dialog.to_cmd_line_button.isEnabled())
            self.assertEqual(clipboard.text(), expected_payload)
            self.assertEqual(terminal_service.executed, [expected_payload])

    def test_file_dialog_optional_overwrite_confirmation_gates_dispatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "demo.hy")
            os.makedirs(project_dir)

            execution_service = RecordingExecutionService()
            dialog = ConfirmingFileDialog(
                services={"python_execution_service": execution_service}
            )
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()

            with patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.No,
            ) as question:
                dialog.do_it_button.click()

            question.assert_called_once()
            self.assertEqual(execution_service.hidden_calls, [])
            self.assertEqual(dialog.result(), 0)

            execution_service = RecordingExecutionService()
            dialog = ConfirmingFileDialog(
                services={"python_execution_service": execution_service}
            )
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()

            with patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.Yes,
            ) as question:
                dialog.do_it_button.click()

            question.assert_called_once()
            self.assertEqual(
                execution_service.hidden_calls,
                [(f"emit({os.path.abspath(project_dir)!r})", True)],
            )
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_file_dialog_invalid_selection_shows_message_and_disables_payload_actions(self):
        terminal_service = RecordingVisibleTerminalService()
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_project_dir = os.path.join(tmpdir, "missing.hy")
            dialog = DemoFileDialog(
                services={"visible_terminal_service": terminal_service}
            )

            dialog.file_widget.set_selected_path(missing_project_dir)
            self.qapp.processEvents()

            self.assertEqual(dialog.preview_string(), "")
            self.assertIn("does not exist", dialog.lower_text_edit.toPlainText())
            self.assertFalse(dialog.do_it_button.isEnabled())
            self.assertFalse(dialog.to_clip_button.isEnabled())
            self.assertFalse(dialog.to_cmd_line_button.isEnabled())

    def test_file_dialog_can_optionally_create_directory_for_suggested_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            suggested_path = os.path.join(tmpdir, "exports", "figure.pdf")
            self.assertFalse(os.path.exists(os.path.dirname(suggested_path)))

            dialog = CreatingSuggestedPathFileDialog(suggested_path)
            self.qapp.processEvents()

            self.assertTrue(os.path.isdir(os.path.dirname(suggested_path)))
            self.assertEqual(dialog.selected_path(), os.path.abspath(suggested_path))
            self.assertEqual(
                dialog.preview_string(),
                f"emit({os.path.abspath(suggested_path)!r})",
            )

    def test_figure_dialog_base_advances_live_patch_state_and_rolls_back_on_cancel(self):
        execution_service = RecordingExecutionService()
        opening_state = make_demo_figure_ir()
        updated_state = copy.deepcopy(opening_state)
        updated_state["layout"]["subplots"][0]["axes"]["x"]["label"]["text"] = "Delay"
        figure_context = FakeFigureContext(FigureIR(figure_state=opening_state))
        dialog = DemoFigureDialogWidget(
            figure_context=figure_context,
            services={"python_execution_service": execution_service},
        )
        dialog.live_update_always_enabled = True

        try:
            dialog.current_figure_ir = FigureIR(figure_state=updated_state)
            patch_state = dialog.figure_patch_state(
                dialog.widget_ir.opening_figure_ir,
                dialog.widget_ir.current_figure_ir,
            )
            expected_patch = patch_state.python_source(log=False)

            self.assertIs(dialog.figure_context, figure_context)
            self.assertIsInstance(dialog.widget_ir, FigureDialogIR)
            self.assertNotIn("initial_ir", vars(dialog))
            self.assertNotIn("current_ir", vars(dialog))
            self.assertEqual(
                dialog.supported_trace_records()[0]["trace_id"],
                "trace0",
            )

            dialog.refresh_figure_preview()

            self.assertEqual(dialog.preview_string(), expected_patch)
            self.assertEqual(dialog.lower_text_edit.toPlainText(), expected_patch)
            self.assertTrue(dialog.apply_live_update_figure_patch(mode="live_update"))
            self.assertEqual(
                execution_service.hidden_calls[-1],
                (expected_patch, True),
            )
            self.assertEqual(dialog.preview_string(), expected_patch)

            dialog.current_figure_ir = copy.deepcopy(dialog.widget_ir.opening_figure_ir)
            self.assertTrue(dialog.apply_live_update_figure_patch(mode="live_update"))
            self.assertEqual(dialog.preview_string(), "")

            dialog.reject()
        finally:
            dialog.close()

        rollback_patch = dialog.figure_patch_state(
            FigureIR(figure_state=updated_state),
            FigureIR(figure_state=opening_state),
        ).python_source(log=False)
        self.assertEqual(
            execution_service.hidden_calls,
            [
                (expected_patch, True),
                (rollback_patch, True),
            ],
        )

    def test_figure_dialog_base_supports_unattached_dialogs(self):
        dialog = DemoFigureDialogWidget()
        try:
            dialog.refresh_figure_preview()

            self.assertIsNone(dialog.figure_context)
            self.assertIsNone(dialog.current_figure_ir)
            self.assertEqual(dialog.supported_trace_records(), ())
            self.assertEqual(dialog.preview_string(), "")
            self.assertEqual(dialog.lower_text_edit.toPlainText(), "")
        finally:
            dialog.close()

    def test_bind_subwindow_uses_window_identifier_as_default_object_name(self):
        mdi_area = QtWidgets.QMdiArea()
        widget = DemoToolWidget(window_identifier="demo_tool")
        subwindow = mdi_area.addSubWindow(widget)

        widget.bind_subwindow(subwindow)

        self.assertEqual(widget.window_identifier(), "demo_tool")
        self.assertEqual(subwindow.objectName(), "demo_tool")

    def test_default_shell_mounts_child_widget(self):
        widget = DemoToolWidget()
        child = QtWidgets.QLabel("Mounted child")

        mounted = widget.mount_child_widget(child)

        self.assertIs(mounted, child)
        self.assertIs(widget.mounted_child, child)
        self.assertIs(child.parentWidget(), widget.ui.content_widget)
        self.assertEqual(widget.ui.content_layout.count(), 1)

    def test_mdi_close_hides_persistent_tool_widget(self):
        mdi_area = QtWidgets.QMdiArea()
        context = HydeMDIContext(mdi_area)
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": "demo_tool",
                "title": "Demo Tool",
                "factory": lambda parent=None, data=None: DemoToolWidget(
                    parent=parent,
                    session_key="demo_tool",
                ),
            },
            {},
        )

        widget = context.show("demo_tool")
        subwindow = context.subwindow("demo_tool")
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()

        self.assertIs(context.widget("demo_tool"), widget)
        self.assertTrue(subwindow.isHidden())

    def test_app_configured_user_close_hides_without_triggering_widget_close(self):
        dummy_app = type("DummyApp", (), {"_subwindow_filters": []})()
        mdi_area = QtWidgets.QMdiArea()
        context = HydeMDIContext(
            mdi_area,
            configure_subwindow=lambda subwindow: HydeApp.configure_persistent_subwindow(
                dummy_app,
                subwindow,
            ),
        )
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": "demo_tool",
                "title": "Demo Tool",
                "factory": lambda parent=None, data=None: DemoToolWidget(
                    parent=parent,
                    session_key="demo_tool",
                    services={"get_shutting_down": lambda: False},
                ),
            },
            {},
        )

        widget = context.show("demo_tool")
        subwindow = context.subwindow("demo_tool")
        self.qapp.processEvents()

        closed = subwindow.close()
        self.qapp.processEvents()

        self.assertFalse(closed)
        self.assertIs(context.widget("demo_tool"), widget)
        self.assertTrue(subwindow.isHidden())

    def test_app_configured_shutdown_close_runs_mounted_child_shutdown(self):
        shutting_down = {"value": False}
        dummy_app = type("DummyApp", (), {"_subwindow_filters": []})()
        mdi_area = QtWidgets.QMdiArea()
        context = HydeMDIContext(
            mdi_area,
            configure_subwindow=lambda subwindow: HydeApp.configure_persistent_subwindow(
                dummy_app,
                subwindow,
            ),
        )
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": "demo_tool",
                "title": "Demo Tool",
                "factory": lambda parent=None, data=None: DemoToolWidget(
                    parent=parent,
                    session_key="demo_tool",
                    services={
                        "get_shutting_down": lambda: shutting_down["value"],
                    },
                ),
            },
            {},
        )

        widget = context.show("demo_tool")
        subwindow = context.subwindow("demo_tool")
        child = ShutdownAwareChild()
        widget.mount_child_widget(child)
        self.qapp.processEvents()

        shutting_down["value"] = True
        closed = subwindow.close()
        self.qapp.processEvents()

        self.assertTrue(closed)
        self.assertEqual(child.shutdown_calls, 1)

    def test_app_configured_close_after_widget_shutdown_is_accepted(self):
        dummy_app = type("DummyApp", (), {"_subwindow_filters": []})()
        mdi_area = QtWidgets.QMdiArea()
        context = HydeMDIContext(
            mdi_area,
            configure_subwindow=lambda subwindow: HydeApp.configure_persistent_subwindow(
                dummy_app,
                subwindow,
            ),
        )
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": "demo_tool",
                "title": "Demo Tool",
                "factory": lambda parent=None, data=None: CloseAwareToolWidget(
                    parent=parent,
                    session_key="demo_tool",
                ),
            },
            {},
        )

        widget = context.show("demo_tool")
        subwindow = context.subwindow("demo_tool")
        self.qapp.processEvents()

        widget.shutdown()
        closed = subwindow.close()
        self.qapp.processEvents()

        self.assertTrue(closed)
        self.assertEqual(widget.close_events, 1)

    def test_close_policy_can_allow_non_persistent_close_without_shutdown(self):
        dummy_app = type("DummyApp", (), {"_subwindow_filters": []})()
        mdi_area = QtWidgets.QMdiArea()
        context = HydeMDIContext(
            mdi_area,
            configure_subwindow=lambda subwindow: HydeApp.configure_persistent_subwindow(
                dummy_app,
                subwindow,
            ),
        )
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": "demo_tool",
                "title": "Demo Tool",
                "factory": lambda parent=None, data=None: CloseByPolicyToolWidget(
                    parent=parent,
                    window_identifier="demo_tool",
                ),
            },
            {},
        )

        widget = context.show("demo_tool")
        subwindow = context.subwindow("demo_tool")
        self.qapp.processEvents()

        closed = subwindow.close()
        self.qapp.processEvents()

        self.assertTrue(closed)
        self.assertEqual(widget.close_events, 1)

    def test_destroy_calls_shutdown_hook_once(self):
        mdi_area = QtWidgets.QMdiArea()
        context = HydeMDIContext(mdi_area)
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": "demo_tool",
                "title": "Demo Tool",
                "factory": lambda parent=None, data=None: ShutdownAwareToolWidget(
                    parent=parent,
                    session_key="demo_tool",
                ),
            },
            {},
        )

        widget = context.show("demo_tool")

        destroyed_widget, destroyed_subwindow = context.destroy("demo_tool")

        self.assertIs(destroyed_widget, widget)
        self.assertIsNotNone(destroyed_subwindow)
        self.assertEqual(widget.shutdown_calls, 1)
        self.assertIsNone(context.widget("demo_tool"))
        self.assertIsNone(context.subwindow("demo_tool"))
