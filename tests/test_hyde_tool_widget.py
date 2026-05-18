import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtWidgets

from hyde.user_interface.plugin_tools import HydeMDIContext
from hyde.user_interface.hyde_tool_widget import HydeToolWidget
from hyde.user_interface.main import HydeApp


class DemoToolWidget(HydeToolWidget):
    pass


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
