import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtWidgets

from hyde.user_interface.shared.plugin import HydeMDIContext
from hyde.user_interface.base_hyde_widgets import (
    HydeDialogWidget,
    HydePromptDialog,
    HydeToolWidget,
)
from hyde.user_interface.main import HydeApp


class DemoToolWidget(HydeToolWidget):
    pass


class DemoDialogWidget(HydeDialogWidget):
    pass


class DemoPromptDialog(HydePromptDialog):
    pass


class HookedDialogWidget(HydeDialogWidget):
    def __init__(self, *args, **kwargs):
        self.do_it_calls = 0
        self.help_calls = 0
        self.payload = "print('dialog payload')"
        super().__init__(*args, **kwargs)
        self.mount_content_widget(QtWidgets.QLabel("Upper content"))
        self.refresh_shell()

    def canonical_text_payload(self):
        return self.payload

    def can_send_to_cmd_line(self):
        return True

    def can_show_help(self):
        return True

    def handle_do_it(self):
        self.do_it_calls += 1

    def handle_help(self):
        self.help_calls += 1


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

    def test_prompt_dialog_base_stores_services_without_tool_shell(self):
        service = object()
        import hyde.user_interface.plugins.save_window_dialog  # noqa: F401

        dialog = DemoPromptDialog(services={"demo_service": service})
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
        self.assertFalse(dialog.to_cmd_line_button.isEnabled())
        self.assertTrue(dialog.to_cmd_line_button.isVisibleTo(dialog))
        self.assertFalse(dialog.help_button.isEnabled())
        self.assertTrue(dialog.help_button.isVisibleTo(dialog))
        self.assertGreater(dialog.shell_ui.left_button_layout.count(), 0)
        self.assertGreater(dialog.shell_ui.right_button_layout.count(), 0)

    def test_tool_dialog_shell_uses_hooks_for_canonical_text_actions(self):
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
        dialog.help_button.click()

        self.assertEqual(dialog.lower_text_edit.toPlainText(), dialog.payload)
        self.assertEqual(clipboard.text(), dialog.payload)
        self.assertEqual(terminal_service.executed, [dialog.payload])
        self.assertEqual(dialog.do_it_calls, 1)
        self.assertEqual(dialog.help_calls, 1)
        self.assertTrue(dialog.to_cmd_line_button.isEnabled())
        self.assertTrue(dialog.to_clip_button.isEnabled())
        self.assertTrue(dialog.help_button.isEnabled())

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
