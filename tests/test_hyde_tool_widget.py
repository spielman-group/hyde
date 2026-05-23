import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import FigureIRCodec, figure_ir_from_live_state
from hyde.user_interface.shared.plugin import HydeMDIContext
from hyde.user_interface.base_hyde_widgets import (
    HydeDialogWidget,
    HydeDialog,
    HydeToolWidget,
)
from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugins.figure_interactive.window import FigureState
from hyde.user_interface.shared.figure import HydeFigureDialogWidget


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


class FakeFigureSession:
    def __init__(self, opening_state, *, current_state=None, trace_records=()):
        self.figure_number = 7
        self._opening_state = copy.deepcopy(opening_state)
        self._current_state = copy.deepcopy(
            opening_state if current_state is None else current_state
        )
        self._trace_records = copy.deepcopy(tuple(trace_records))

    def opening_effective_state(self):
        return copy.deepcopy(self._opening_state)

    def current_effective_state(self):
        return copy.deepcopy(self._current_state)

    def set_current_effective_state(self, state):
        self._current_state = copy.deepcopy(state)

    def supported_trace_records(self):
        return copy.deepcopy(self._trace_records)


class FakeFigureContext:
    def __init__(self, session, *, figure_name="Figure0"):
        self.figure_number = int(session.figure_number)
        self._session = session
        self._figure_name = str(figure_name)
        self.open_session_calls = 0

    def open_session(self):
        self.open_session_calls += 1
        return self._session

    def figure_name(self):
        return self._figure_name


def make_demo_figure_ir(title="Figure0", items=("trace_a",)):
    state = FigureState()
    state.set_title(title)
    state.set_x_name("x")
    state.set_items(list(items))
    return FigureIRCodec.validate_state(figure_ir_from_live_state(state.normalized_state()))


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

        self.assertIs(content.parentWidget(), dialog.shell_ui.content_widget)
        self.assertEqual(dialog.shell_ui.content_layout.count(), 1)
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

    def test_figure_dialog_base_advances_live_patch_state_and_rolls_back_on_cancel(self):
        execution_service = RecordingExecutionService()
        opening_state = make_demo_figure_ir()
        updated_state = copy.deepcopy(opening_state)
        updated_state["layout"]["subplots"][0]["axes"]["x"]["label"]["text"] = "Delay"
        session = FakeFigureSession(
            opening_state,
            current_state=updated_state,
            trace_records=(
                {
                    "subplot_id": "subplot_1",
                    "trace_id": "trace_1",
                    "label": "trace_a",
                    "x_name": "x",
                    "y_name": "trace_a",
                },
            ),
        )
        figure_context = FakeFigureContext(session)
        dialog = DemoFigureDialogWidget(
            figure_context=figure_context,
            services={"python_execution_service": execution_service},
        )

        try:
            expected_patch = dialog.figure_patch_source(
                opening_state,
                updated_state,
            )

            self.assertIs(dialog.figure_context, figure_context)
            self.assertIs(dialog.figure_session(), session)
            self.assertEqual(figure_context.open_session_calls, 1)
            self.assertEqual(
                dialog.supported_trace_records()[0]["trace_id"],
                "trace_1",
            )

            dialog.refresh_figure_preview()

            self.assertEqual(dialog.preview_string(), expected_patch)
            self.assertEqual(dialog.lower_text_edit.toPlainText(), expected_patch)
            self.assertTrue(dialog.apply_current_figure_patch(mode="live_update"))
            self.assertEqual(
                execution_service.hidden_calls[-1],
                (expected_patch, True),
            )
            self.assertEqual(dialog.preview_string(), "")

            dialog.reject()
        finally:
            dialog.close()

        rollback_patch = dialog.figure_patch_source(updated_state, opening_state)
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
            self.assertIsNone(dialog.figure_session())
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
