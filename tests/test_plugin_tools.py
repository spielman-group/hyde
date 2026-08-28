import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from qtutils.qt import QtCore, QtGui, QtWidgets
from PyQt5.QtTest import QTest
from qtutils.outputbox import BLUE, GREEN, ORANGE, RED, WHITE

from hyde.user_interface.main import HydeApp, connect_logger_to_output_sink
from hyde.user_interface.base_hyde_widgets import HydeToolWidget
from hyde.user_interface.shared.plugin import (
    HydeMDIContext,
    HydeMenuContext,
    HydePlugin,
    HydePluginManager,
    HydeToolWindowService,
    HydeToolWindowPlugin,
    SETUP_PRIORITY_RUNTIME_START,
)
from hyde.user_interface.plugins.figure_interactive import Plugin as FigurePlugin
from hyde.user_interface.plugins.logging_tool import Plugin as LoggingPlugin
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow
from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.plugins.procedure_browser_tool import Plugin as ProcedureBrowserPlugin
from hyde.user_interface.plugins.python_variables_tool import Plugin as PythonVariablesPlugin
from hyde.user_interface.plugins.python_terminal_tool import Plugin as PythonTerminalPlugin
from hyde.user_interface.plugins.table_interactive import Plugin as TablePlugin
from hyde.user_interface.plugins.table_interactive.window import TableWidget
from hyde.user_interface.shared.project import resolve_requested_name


class RecordingMenu(QtWidgets.QMenu):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.popup_calls = []

    def exec_(self, pos, *args, **kwargs):
        self.popup_calls.append(QtCore.QPoint(pos))
        return None


def make_plugin_host(plugin_manager):
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
    main_window.menuEdit = main_window.menuBar().addMenu("Edit")
    main_window.menuAnalysis = main_window.menuBar().addMenu("Analysis")
    main_window.menuWindow = main_window.menuBar().addMenu("Windows")
    main_window.menuFigure = RecordingMenu("Figure", main_window.menuBar())
    main_window.menuTable = RecordingMenu("Table", main_window.menuBar())
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
    app.get_current_app_ir = lambda: HydeAppIR(current_project_dir=None)
    app.lookup_menu_action = lambda location, name, path=(): (
        None if getattr(app, "menu_context", None) is None
        else app.menu_context.lookup_action(location, name, path=path)
    )
    app.show_menu = lambda location: HydeApp.show_menu(app, location)
    app.hide_menu = lambda location: HydeApp.hide_menu(app, location)
    app.popup_menu = lambda location, global_pos: HydeApp.popup_menu(
        app, location, global_pos
    )
    app.get_current_project_dir = lambda: None
    app.get_procedures_init = lambda: None
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


class TestPluginTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def make_tool_window_plugin(self, mdi_key="real_window"):
        main_window = QtWidgets.QMainWindow()
        mdi_area = QtWidgets.QMdiArea()
        main_window.setCentralWidget(mdi_area)
        main_window.resize(800, 600)
        main_window.show()
        self.qapp.processEvents()

        context = HydeMDIContext(mdi_area)
        plugin = HydePlugin({})
        plugin.services = {"mdi_context": context}
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": mdi_key,
                "title": "Real Window",
                "factory": lambda parent=None, data=None: QtWidgets.QWidget(parent),
            },
            {"services": {}},
        )
        plugin.ensure_mdi_widget(mdi_key)
        subwindow = plugin.mdi_subwindow(mdi_key)
        return main_window, plugin, subwindow

    def rect_values(self, rect):
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    def subwindow_geometry(self, subwindow):
        return self.rect_values(subwindow.geometry())

    def test_plugin_manager_discovers_only_plugin_packages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir) / "sample_plugins"
            package_root.mkdir()
            (package_root / "__init__.py").write_text("", encoding="utf-8")

            plugin_dir = package_root / "alpha"
            plugin_dir.mkdir()
            (plugin_dir / "__init__.py").write_text(
                "class Plugin:\n"
                "    pass\n",
                encoding="utf-8",
            )

            helper_dir = package_root / "helper"
            helper_dir.mkdir()
            (helper_dir / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

            sys.path.insert(0, tmpdir)
            self.addCleanup(sys.path.remove, tmpdir)

            manager = HydePluginManager(
                plugin_package="sample_plugins",
                plugins_dir=str(package_root),
            )

            self.assertEqual(set(manager.discover_modules()), {"alpha"})

    def test_mdi_context_reuses_single_plugin_window(self):
        mdi_area = QtWidgets.QMdiArea()
        configured = []
        factory_calls = []

        def factory(parent=None, data=None):
            factory_calls.append((parent, dict(data)))
            widget = QtWidgets.QWidget(parent)
            widget.setObjectName("plugin-window")
            return widget

        context = HydeMDIContext(
            mdi_area,
            configure_subwindow=lambda subwindow: configured.append(subwindow),
        )
        context.add(
            "demo",
            {
                "context": "mdi",
                "key": "plugin_window",
                "title": "Plugin Window",
                "factory": factory,
            },
            {"services": {"execute_command": object()}},
        )

        first_widget = context.show("plugin_window")
        second_widget = context.show("plugin_window")

        self.assertIs(first_widget, second_widget)
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual(len(configured), 1)
        self.assertEqual(
            context.subwindow("plugin_window").windowTitle(),
            "Plugin Window",
        )
        self.assertEqual(
            context.subwindow("plugin_window").objectName(),
            "plugin_window",
        )

    def test_shared_tool_window_plugin_builds_menu_action_and_constructs_widget(self):
        class DemoToolWidget(HydeToolWidget):
            pass

        class DemoPlugin(HydeToolWindowPlugin):
            session_key = "demo_tool"
            window_title = "Demo Tool"
            menu_name = "Demo Tool"
            window_size = (320, 240)

            def create_tool_window_widget(self, parent=None):
                return DemoToolWidget(
                    parent=parent,
                    services=self.services,
                    session_key=self.session_key,
                )

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": DemoPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)

        HydeApp.setup_plugins(app)
        app.ui.show()
        self.qapp.processEvents()

        action = manager.services["lookup_menu_action"]("window", "Demo Tool")
        self.assertIsNotNone(action)
        self.assertIsNone(app.mdi_context.widget("demo_tool"))

        action.trigger()
        self.qapp.processEvents()

        widget = app.mdi_context.widget("demo_tool")
        subwindow = app.mdi_context.subwindow("demo_tool")
        self.assertIsInstance(widget, DemoToolWidget)
        self.assertEqual(widget.window_identifier(), "demo_tool")
        self.assertEqual(widget.session_key, "demo_tool")
        self.assertEqual(subwindow.objectName(), "demo_tool")
        self.assertEqual(subwindow.windowTitle(), "Demo Tool")
        self.assertEqual((subwindow.width(), subwindow.height()), (320, 240))
        self.assertTrue(subwindow.isVisible())

    def test_tool_window_session_helpers_use_subwindow_object_name_identity(self):
        _, plugin, subwindow = self.make_tool_window_plugin()
        subwindow.setGeometry(QtCore.QRect(11, 22, 333, 444))
        subwindow.show()
        self.qapp.processEvents()

        save_data = plugin.tool_window_save_data(
            "legacy_session_key",
            mdi_key="real_window",
        )

        self.assertEqual(
            set(save_data["tool_windows"]),
            {"real_window"},
        )
        self.assertEqual(
            save_data["tool_windows"]["real_window"],
            {
                "window_state": "visible",
                "geometry": [11, 22, 333, 444],
            },
        )

        subwindow.hide()
        self.qapp.processEvents()
        subwindow.setGeometry(QtCore.QRect(1, 2, 300, 200))
        restored = plugin.restore_tool_window(
            {
                "tool_windows": {
                    "real_window": {
                        "window_state": "visible",
                        "geometry": [11, 22, 333, 444],
                    }
                }
            },
            "legacy_session_key",
            mdi_key="real_window",
        )

        self.assertIs(restored, subwindow)
        self.assertTrue(subwindow.isVisible())
        self.assertEqual(self.subwindow_geometry(subwindow), [11, 22, 333, 444])

    def test_shared_tool_window_plugin_restores_generic_state_before_widget_state(self):
        class DemoToolWidget(HydeToolWidget):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.restore_snapshots = []

            def restore_session_toml_data(self, session):
                self.restore_snapshots.append(
                    {
                        "session": dict(session),
                        "geometry": [
                            self._subwindow.geometry().x(),
                            self._subwindow.geometry().y(),
                            self._subwindow.geometry().width(),
                            self._subwindow.geometry().height(),
                        ],
                    }
                )

        class DemoPlugin(HydeToolWindowPlugin):
            session_key = "demo_tool"
            window_title = "Demo Tool"
            menu_name = "Demo Tool"

            def create_tool_window_widget(self, parent=None):
                return DemoToolWidget(
                    parent=parent,
                    services=self.services,
                    session_key=self.session_key,
                )

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        plugin = DemoPlugin({})
        manager.plugins = {"demo": plugin}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)

        HydeApp.setup_plugins(app)
        app.ui.show()
        self.qapp.processEvents()

        widget = plugin.ensure_mdi_widget("demo_tool")
        subwindow = plugin.mdi_subwindow("demo_tool")
        subwindow.setGeometry(QtCore.QRect(1, 2, 100, 80))

        plugin.restore_tool_window_session(
            {
                "tool_windows": {
                    "demo_tool": {
                        "window_state": "visible",
                        "geometry": [15, 25, 210, 160],
                    }
                },
                "demo_tool": {"selected_path": "procedures/example.py"},
            }
        )

        self.assertEqual(
            widget.restore_snapshots,
            [
                {
                    "session": {"selected_path": "procedures/example.py"},
                    "geometry": [15, 25, 210, 160],
                }
            ],
        )

    def test_shared_tool_window_plugin_can_eagerly_create_hidden_widget(self):
        class DemoToolWidget(HydeToolWidget):
            pass

        class DemoPlugin(HydeToolWindowPlugin):
            session_key = "demo_tool"
            window_title = "Demo Tool"
            menu_name = "Demo Tool"
            creation_policy = "eager"

            def create_tool_window_widget(self, parent=None):
                return DemoToolWidget(
                    parent=parent,
                    services=self.services,
                    session_key=self.session_key,
                )

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": DemoPlugin({})}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        widget = app.mdi_context.widget("demo_tool")
        subwindow = app.mdi_context.subwindow("demo_tool")
        self.assertIsInstance(widget, DemoToolWidget)
        self.assertEqual(widget.session_key, "demo_tool")
        self.assertTrue(subwindow.isHidden())

    def test_shared_tool_window_plugin_can_drive_standard_persistent_lifecycle(self):
        class DemoToolWidget(HydeToolWidget):
            pass

        class DemoPlugin(HydeToolWindowPlugin):
            session_key = "demo_tool"
            window_title = "Demo Tool"
            menu_name = "Demo Tool"
            restore_on_project_loaded = True
            enable_action_with_project = True
            hide_on_enter_no_project = True
            ensure_widget_on_kernel_ready = True
            destroy_widget_on_kernel_crash = True

            def create_tool_window_widget(self, parent=None):
                return DemoToolWidget(
                    parent=parent,
                    services=self.services,
                    session_key=self.session_key,
                )

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": DemoPlugin({})}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)
        app.ui.show()
        self.qapp.processEvents()

        plugin = manager.plugins["demo"]
        action = manager.services["lookup_menu_action"]("window", "Demo Tool")
        handlers = plugin.get_event_handlers()

        self.assertEqual(
            set(handlers),
            {
                "project_loaded",
                "project_activated",
                "enter_no_project_state",
                "kernel_ready",
                "kernel_crashed",
            },
        )
        self.assertIsNone(plugin.mdi_widget("demo_tool"))

        plugin.on_kernel_ready({})
        subwindow = plugin.mdi_subwindow("demo_tool")
        self.assertIsNotNone(subwindow)

        plugin.on_enter_no_project_state({})
        self.assertFalse(action.isEnabled())
        self.assertTrue(subwindow.isHidden())

        plugin.on_project_activated({})
        self.assertTrue(action.isEnabled())

        plugin.on_project_loaded(
            {
                "session": {
                    "tool_windows": {
                        "demo_tool": {
                            "window_state": "visible",
                            "geometry": [15, 25, 210, 160],
                        }
                    }
                }
            }
        )
        self.assertTrue(subwindow.isVisible())
        self.assertEqual(self.subwindow_geometry(subwindow), [15, 25, 210, 160])

        plugin.on_kernel_crashed({})
        self.assertIsNone(plugin.mdi_widget("demo_tool"))
        self.assertIsNone(plugin.mdi_subwindow("demo_tool"))

    def test_shared_tool_window_service_can_target_container_or_mounted_child(self):
        class DemoToolWidget(HydeToolWidget):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.mount_child_widget(QtWidgets.QLabel("Mounted child"))

        class DemoContainerService(HydeToolWindowService):
            pass

        class DemoChildService(HydeToolWindowService):
            use_mounted_child = True

        class DemoPlugin(HydeToolWindowPlugin):
            session_key = "demo_tool"
            window_title = "Demo Tool"
            menu_name = "Demo Tool"

            def __init__(self, initial_settings):
                super().__init__(initial_settings)
                self.container_service = DemoContainerService(self)
                self.child_service = DemoChildService(self)

            def create_tool_window_widget(self, parent=None):
                return DemoToolWidget(
                    parent=parent,
                    services=self.services,
                    session_key=self.session_key,
                )

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": DemoPlugin({})}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        plugin = manager.plugins["demo"]
        container = plugin.container_service.ensure_widget()
        child = plugin.child_service.widget()

        self.assertIsInstance(container, DemoToolWidget)
        self.assertIs(child, container.mounted_child)
        self.assertIs(plugin.child_service.subwindow(), plugin.mdi_subwindow("demo_tool"))

        plugin.child_service.destroy()

        self.assertIsNone(plugin.mdi_widget("demo_tool"))
        self.assertIsNone(plugin.mdi_subwindow("demo_tool"))

    def test_python_terminal_plugin_mounts_console_inside_hyde_tool_widget(self):
        class FakeTerminalWidget(QtWidgets.QWidget):
            executed = QtCore.Signal(object)

            def __init__(
                self,
                kernel_client,
                history_sink=None,
                initial_history=None,
                *args,
                **kwargs,
            ):
                super().__init__(*args, **kwargs)
                self.kernel_client = kernel_client
                self.history_sink = history_sink
                self.initial_history = list(initial_history or [])

            def restore_history_entries(self, entries):
                self.initial_history = list(entries or [])

            def shutdown(self):
                self.kernel_client = None

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"python_terminal_tool": PythonTerminalPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)
        manager.services = {"kernel_runtime_service": object()}

        with patch(
            "hyde.user_interface.plugins.python_terminal_tool.PythonTerminal",
            FakeTerminalWidget,
        ):
            HydeApp.setup_plugins(app)
            plugin = manager.plugins["python_terminal_tool"]
            plugin.on_kernel_ready({})

        container = plugin.mdi_widget("python_terminal_tool")
        terminal = manager.services["visible_terminal_service"].widget()

        self.assertEqual(container.window_identifier(), "python_terminal_tool")
        self.assertIsInstance(terminal, FakeTerminalWidget)
        self.assertIs(container.mounted_child, terminal)
        self.assertIs(terminal.parentWidget(), container.ui.content_widget)
        self.assertEqual(container.ui.content_layout.count(), 1)

    def test_python_terminal_plugin_notifies_visible_command_service(self):
        class FakeKernelRuntimeService:
            def __init__(self):
                self.client = object()

            def kernel_client(self):
                return self.client

        class FakeTerminalWidget(QtWidgets.QWidget):
            executed = QtCore.Signal(object)

            def __init__(
                self,
                kernel_client,
                history_sink=None,
                initial_history=None,
                *args,
                **kwargs,
            ):
                super().__init__(*args, **kwargs)
                self.kernel_client = kernel_client
                self.history_sink = history_sink
                self.initial_history = list(initial_history or [])

            def restore_history_entries(self, entries):
                self.initial_history = list(entries or [])

            def shutdown(self):
                self.kernel_client = None

        class RecordingVisibleCommandService:
            def __init__(self):
                self.messages = []

            def on_command_executed(self, message):
                self.messages.append(message)

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"python_terminal_tool": PythonTerminalPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)
        visible_command_service = RecordingVisibleCommandService()
        app.build_plugin_services = lambda: {
            **HydeApp.build_plugin_services(app),
            "kernel_runtime_service": FakeKernelRuntimeService(),
            "visible_command_notification_service": visible_command_service,
        }

        with patch(
            "hyde.user_interface.plugins.python_terminal_tool.PythonTerminal",
            FakeTerminalWidget,
        ):
            HydeApp.setup_plugins(app)
            plugin = manager.plugins["python_terminal_tool"]
            plugin.on_kernel_ready({})
            terminal = manager.services["visible_terminal_service"].widget()
            message = {"content": {"status": "ok"}}
            terminal.executed.emit(message)

        self.assertEqual(visible_command_service.messages, [message])

    def test_python_variables_plugin_keeps_namespace_service_on_its_container(self):
        class FakeChannel(QtCore.QObject):
            message_received = QtCore.Signal(object)

        class FakeKernelClient:
            def __init__(self):
                self.iopub_channel = FakeChannel()

        class FakeSpyderComm:
            def __init__(self, kernel_client):
                self.kernel_client = kernel_client

            def open(self):
                return None

            def wait_until_ready(self, timeout=5):
                del timeout
                return None

            def configure_namespace_view(self, settings):
                self.settings = dict(settings)

            def request_namespace_view(self, callback):
                callback(
                    {
                        "scalar": {
                            "type": "int",
                            "python_type": "int",
                            "view": "7",
                        }
                    }
                )

            def close(self):
                return None

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"python_variables_tool": PythonVariablesPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)
        shared_client = FakeKernelClient()
        kernel_runtime_service = type(
            "KernelRuntimeService",
            (),
            {"kernel_client": lambda _self: shared_client},
        )()
        app.build_plugin_services = lambda: {
            **HydeApp.build_plugin_services(app),
            "kernel_runtime_service": kernel_runtime_service,
        }

        with patch(
            "hyde.user_interface.plugins.python_variables_tool.SpyderFrontendComm",
            FakeSpyderComm,
        ):
            HydeApp.setup_plugins(app)
            action = manager.services["lookup_menu_action"](
                "window",
                "Python Variables",
            )
            action.trigger()
            self.qapp.processEvents()

            plugin = manager.plugins["python_variables_tool"]
            widget = plugin.mdi_widget("python_variables_tool")
            subwindow = plugin.mdi_subwindow("python_variables_tool")

        self.assertIs(plugin.python_variables_service.widget(), widget)
        self.assertEqual(
            plugin.python_variables_service.namespace_view(),
            {
                "scalar": {
                    "type": "int",
                    "python_type": "int",
                    "view": "7",
                }
            },
        )
        self.assertIs(
            widget.service("kernel_runtime_service"),
            kernel_runtime_service,
        )
        self.assertIsNotNone(widget.ui.treeView)
        self.assertEqual(widget.window_identifier(), "python_variables_tool")
        self.assertEqual(widget.session_key, "python_variables_tool")
        self.assertEqual(subwindow.objectName(), "python_variables_tool")
        self.assertEqual(subwindow.windowTitle(), "Python Variables")

    def test_python_variables_service_stays_lazy_until_window_is_opened(self):
        class FakeChannel(QtCore.QObject):
            message_received = QtCore.Signal(object)

        class FakeKernelClient:
            def __init__(self):
                self.iopub_channel = FakeChannel()

        class FakeSpyderComm:
            def __init__(self, kernel_client):
                self.kernel_client = kernel_client

            def open(self):
                return None

            def wait_until_ready(self, timeout=5):
                del timeout
                return None

            def configure_namespace_view(self, settings):
                self.settings = dict(settings)

            def request_namespace_view(self, callback):
                callback(
                    {
                        "scalar": {
                            "type": "int",
                            "python_type": "int",
                            "view": "7",
                        }
                    }
                )

            def close(self):
                return None

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"python_variables_tool": PythonVariablesPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)
        shared_client = FakeKernelClient()
        kernel_runtime_service = type(
            "KernelRuntimeService",
            (),
            {"kernel_client": lambda _self: shared_client},
        )()
        app.build_plugin_services = lambda: {
            **HydeApp.build_plugin_services(app),
            "kernel_runtime_service": kernel_runtime_service,
        }

        with patch(
            "hyde.user_interface.plugins.python_variables_tool.SpyderFrontendComm",
            FakeSpyderComm,
        ):
            HydeApp.setup_plugins(app)
            plugin = manager.plugins["python_variables_tool"]
            service = plugin.python_variables_service
            callback_payloads = []

            self.assertTrue(service.connect_namespace_view_updated(callback_payloads.append))
            self.assertEqual(service.namespace_view(), {})
            self.assertIsNone(plugin.mdi_widget("python_variables_tool"))

            action = manager.services["lookup_menu_action"](
                "window",
                "Python Variables",
            )
            action.trigger()
            self.qapp.processEvents()

        self.assertEqual(
            callback_payloads,
            [
                {
                    "scalar": {
                        "type": "int",
                        "python_type": "int",
                        "view": "7",
                    }
                }
            ],
        )
        self.assertIsNotNone(plugin.mdi_widget("python_variables_tool"))
        self.assertEqual(
            service.namespace_view(),
            {
                "scalar": {
                    "type": "int",
                    "python_type": "int",
                    "view": "7",
                }
            },
        )

    def test_python_terminal_service_restores_and_captures_history_through_container(self):
        class FakeTerminalWidget(QtWidgets.QWidget):
            executed = QtCore.Signal(object)

            def __init__(
                self,
                kernel_client,
                history_sink=None,
                initial_history=None,
                *args,
                **kwargs,
            ):
                super().__init__(*args, **kwargs)
                self.kernel_client = kernel_client
                self.history_sink = history_sink
                self.history_snapshots = [list(initial_history or [])]

            def execute(self, source=None, hidden=False, interactive=False):
                del interactive
                if (
                    not hidden
                    and self.history_sink is not None
                    and isinstance(source, str)
                    and source.strip()
                ):
                    self.history_sink(source)

            def restore_history_entries(self, entries):
                self.history_snapshots.append(list(entries or []))

            def shutdown(self):
                self.kernel_client = None

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"python_terminal_tool": PythonTerminalPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)

        with patch(
            "hyde.user_interface.plugins.python_terminal_tool.PythonTerminal",
            FakeTerminalWidget,
        ):
            HydeApp.setup_plugins(app)
            service = manager.services["visible_terminal_service"]
            service.restore_history_entries(["a = 1"])

            terminal = service.widget()
            service.execute_visible("b = 2")

        self.assertEqual(service.history_entries(), ["a = 1", "b = 2"])
        self.assertEqual(
            terminal.history_snapshots,
            [["a = 1"], ["a = 1"]],
        )

    def test_python_terminal_kernel_ready_creates_container_and_terminal_widget(self):
        class FakeKernelRuntimeService:
            def __init__(self):
                self.client = object()

            def kernel_client(self):
                return self.client

        class FakeTerminalWidget(QtWidgets.QWidget):
            executed = QtCore.Signal(object)

            def __init__(
                self,
                kernel_client,
                history_sink=None,
                initial_history=None,
                *args,
                **kwargs,
            ):
                super().__init__(*args, **kwargs)
                self.kernel_client = kernel_client
                self.history_sink = history_sink
                self.initial_history = list(initial_history or [])

            def restore_history_entries(self, entries):
                self.initial_history = list(entries or [])

            def shutdown(self):
                self.kernel_client = None

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"python_terminal_tool": PythonTerminalPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)

        with patch(
            "hyde.user_interface.plugins.python_terminal_tool.PythonTerminal",
            FakeTerminalWidget,
        ):
            HydeApp.setup_plugins(app)
            plugin = manager.plugins["python_terminal_tool"]
            plugin.services["kernel_runtime_service"] = FakeKernelRuntimeService()

            self.assertIsNone(plugin.mdi_widget("python_terminal_tool"))
            self.assertIsNone(manager.services["visible_terminal_service"].widget())

            plugin.on_kernel_ready({})

        container = plugin.mdi_widget("python_terminal_tool")
        terminal = manager.services["visible_terminal_service"].widget()

        self.assertIs(container.mounted_child, terminal)
        self.assertIs(terminal.kernel_client, plugin.services["kernel_runtime_service"].client)

    def test_python_terminal_kernel_crash_teardown_destroys_container_and_terminal(self):
        class FakeTerminalWidget(QtWidgets.QWidget):
            executed = QtCore.Signal(object)

            def __init__(
                self,
                kernel_client,
                history_sink=None,
                initial_history=None,
                *args,
                **kwargs,
            ):
                del kernel_client, history_sink, initial_history
                super().__init__(*args, **kwargs)
                self.shutdown_calls = 0

            def restore_history_entries(self, entries):
                del entries

            def shutdown(self):
                self.shutdown_calls += 1

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"python_terminal_tool": PythonTerminalPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)

        with patch(
            "hyde.user_interface.plugins.python_terminal_tool.PythonTerminal",
            FakeTerminalWidget,
        ):
            HydeApp.setup_plugins(app)
            plugin = manager.plugins["python_terminal_tool"]
            plugin.on_kernel_ready({})
            terminal = manager.services["visible_terminal_service"].widget()

            plugin.on_kernel_crashed({})

        self.assertEqual(terminal.shutdown_calls, 1)
        self.assertIsNone(plugin.mdi_widget("python_terminal_tool"))
        self.assertIsNone(plugin.mdi_subwindow("python_terminal_tool"))
        self.assertIsNone(manager.services["visible_terminal_service"].widget())
        self.assertIsNone(manager.services["visible_terminal_service"].subwindow())

    def test_procedure_browser_uses_shared_tool_window_shell(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"procedure_browser_tool": ProcedureBrowserPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)

        HydeApp.setup_plugins(app)

        plugin = manager.plugins["procedure_browser_tool"]
        widget = plugin.mdi_widget("procedure_browser_tool")
        subwindow = plugin.mdi_subwindow("procedure_browser_tool")

        self.assertIsInstance(widget, HydeToolWidget)
        self.assertEqual(widget.window_identifier(), "procedure_browser_tool")
        self.assertIsNotNone(widget)
        self.assertTrue(subwindow.isHidden())

        subwindow.show()
        self.qapp.processEvents()

        closed = subwindow.close()
        self.qapp.processEvents()

        self.assertFalse(closed)
        self.assertIs(plugin.mdi_widget("procedure_browser_tool"), widget)
        self.assertTrue(subwindow.isHidden())

    def test_procedure_browser_updates_state_and_opens_python_files(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"procedure_browser_tool": ProcedureBrowserPlugin({})}
        app = make_plugin_host(manager)
        app.show_plugin_window = lambda key: HydeApp.show_plugin_window(app, key)

        HydeApp.setup_plugins(app)

        plugin = manager.plugins["procedure_browser_tool"]
        action = manager.services["lookup_menu_action"]("window", "Procedures")
        widget = plugin.mdi_widget("procedure_browser_tool")

        plugin.on_enter_no_project_state({})
        self.assertFalse(action.isEnabled())
        self.assertIsNone(widget.procedures_dir)
        self.assertEqual(widget.model.rootPath(), "")

        with tempfile.TemporaryDirectory() as tmpdir:
            procedures_dir = Path(tmpdir)
            procedure_path = procedures_dir / "example.py"
            procedure_path.write_text("print('hello')\n", encoding="utf-8")

            plugin.on_project_activated({"procedures_dir": str(procedures_dir)})
            self.qapp.processEvents()

            self.assertTrue(action.isEnabled())
            self.assertEqual(widget.procedures_dir, str(procedures_dir))
            self.assertEqual(widget.model.rootPath(), str(procedures_dir))
            self.assertEqual(
                widget.model.filePath(widget.tree_view.rootIndex()),
                str(procedures_dir),
            )

            with patch(
                "hyde.user_interface.plugins.procedure_browser_tool.QDesktopServices.openUrl"
            ) as open_url:
                widget.tree_view.doubleClicked.emit(
                    widget.model.index(str(procedure_path))
                )
                self.qapp.processEvents()

            open_url.assert_called_once()
            self.assertEqual(
                open_url.call_args[0][0].toLocalFile(),
                str(procedure_path),
            )

    def test_tool_window_session_helpers_capture_hidden_minimized_and_maximized(self):
        _, plugin, subwindow = self.make_tool_window_plugin()
        normal_geometry = [12, 18, 230, 140]

        subwindow.showNormal()
        subwindow.setGeometry(QtCore.QRect(*normal_geometry))
        subwindow.hide()
        self.qapp.processEvents()
        hidden_state = plugin.tool_window_save_data(
            "legacy_session_key",
            mdi_key="real_window",
        )["tool_windows"]["real_window"]
        self.assertEqual(hidden_state["window_state"], "hidden")
        self.assertEqual(hidden_state["geometry"], normal_geometry)
        self.assertNotIn("geometry_minimized", hidden_state)

        subwindow.showNormal()
        subwindow.setGeometry(QtCore.QRect(*normal_geometry))
        subwindow.showMaximized()
        self.qapp.processEvents()
        maximized_state = plugin.tool_window_save_data(
            "legacy_session_key",
            mdi_key="real_window",
        )["tool_windows"]["real_window"]
        self.assertEqual(maximized_state["window_state"], "maximized")
        self.assertEqual(maximized_state["geometry"], normal_geometry)
        self.assertNotIn("geometry_minimized", maximized_state)

        subwindow.showNormal()
        subwindow.setGeometry(QtCore.QRect(*normal_geometry))
        subwindow.showMinimized()
        self.qapp.processEvents()
        minimized_state = plugin.tool_window_save_data(
            "legacy_session_key",
            mdi_key="real_window",
        )["tool_windows"]["real_window"]
        self.assertEqual(minimized_state["window_state"], "minimized")
        self.assertEqual(minimized_state["geometry"], normal_geometry)
        self.assertNotIn("geometry_minimized", minimized_state)

    def test_restore_tool_window_accepts_hidden_visible_minimized_and_maximized(self):
        restore_cases = [
            (
                "hidden",
                {
                    "window_state": "hidden",
                    "geometry": [10, 20, 230, 140],
                },
            ),
            (
                "visible",
                {
                    "window_state": "visible",
                    "geometry": [30, 40, 240, 150],
                },
            ),
            (
                "maximized",
                {
                    "window_state": "maximized",
                    "geometry": [50, 60, 250, 160],
                },
            ),
            (
                "minimized",
                {
                    "window_state": "minimized",
                    "geometry": [70, 80, 260, 170],
                },
            ),
        ]

        for window_state, saved_state in restore_cases:
            with self.subTest(window_state=window_state):
                _, plugin, subwindow = self.make_tool_window_plugin()
                subwindow.setGeometry(QtCore.QRect(1, 2, 300, 200))
                subwindow.show()
                self.qapp.processEvents()

                restored = plugin.restore_tool_window(
                    {"tool_windows": {"real_window": saved_state}},
                    "legacy_session_key",
                    mdi_key="real_window",
                )

                self.assertIs(restored, subwindow)
                self.qapp.processEvents()
                if window_state == "hidden":
                    self.assertTrue(subwindow.isHidden())
                    self.assertEqual(self.subwindow_geometry(subwindow), saved_state["geometry"])
                elif window_state == "visible":
                    self.assertTrue(subwindow.isVisible())
                    self.assertFalse(subwindow.isMinimized())
                    self.assertFalse(subwindow.isMaximized())
                    self.assertEqual(self.subwindow_geometry(subwindow), saved_state["geometry"])
                elif window_state == "maximized":
                    self.assertTrue(subwindow.isMaximized())
                    subwindow.showNormal()
                    self.qapp.processEvents()
                    self.assertEqual(self.subwindow_geometry(subwindow), saved_state["geometry"])
                else:
                    self.assertTrue(subwindow.isMinimized())
                    subwindow.showNormal()
                    self.qapp.processEvents()
                    self.assertEqual(self.subwindow_geometry(subwindow), saved_state["geometry"])

    def test_restore_tool_window_hides_invalid_state_and_logs_warning(self):
        invalid_sessions = [
            (
                "invalid window_state",
                {
                    "window_state": "floating",
                    "geometry": [1, 2, 200, 100],
                },
                "window_state",
            ),
            (
                "missing window_state",
                {
                    "geometry": [1, 2, 200, 100],
                },
                "window_state",
            ),
            (
                "invalid geometry",
                {
                    "window_state": "visible",
                    "geometry": [1, 2, 0, 100],
                },
                "geometry",
            ),
            (
                "missing geometry",
                {
                    "window_state": "visible",
                },
                "geometry",
            ),
        ]

        for label, saved_state, expected_text in invalid_sessions:
            with self.subTest(case=label):
                _, plugin, subwindow = self.make_tool_window_plugin()
                subwindow.setGeometry(QtCore.QRect(1, 2, 300, 200))
                subwindow.show()
                self.qapp.processEvents()

                with self.assertLogs(
                    "hyde.user_interface.shared.plugin",
                    level="WARNING",
                ) as logs:
                    restored = plugin.restore_tool_window(
                        {"tool_windows": {"real_window": saved_state}},
                        "legacy_session_key",
                        mdi_key="real_window",
                    )

                self.assertIs(restored, subwindow)
                self.assertTrue(subwindow.isHidden())
                self.assertIn("real_window", "\n".join(logs.output))
                self.assertIn(expected_text, "\n".join(logs.output))

    def test_blank_object_name_falls_back_to_mdi_key_for_shared_identity_helper(self):
        _, plugin, subwindow = self.make_tool_window_plugin()
        subwindow.setObjectName("   ")

        save_data = plugin.tool_window_save_data(
            "legacy_session_key",
            mdi_key="real_window",
        )

        self.assertEqual(
            str(subwindow.objectName() or "").strip() or "real_window",
            "real_window",
        )
        self.assertEqual(set(save_data["tool_windows"]), {"real_window"})

    def test_configure_persistent_subwindow_uses_blank_icon_instead_of_app_icon(self):
        dummy_app = type("DummyApp", (), {"_subwindow_filters": []})()
        subwindow = QtWidgets.QMdiSubWindow()
        app_icon = QtGui.QIcon(QtGui.QPixmap(2, 2))
        QtWidgets.QApplication.setWindowIcon(app_icon)

        HydeApp.configure_persistent_subwindow(dummy_app, subwindow)

        self.assertEqual(subwindow.windowIcon().availableSizes(), [QtCore.QSize(1, 1)])
        self.assertNotEqual(
            subwindow.windowIcon().availableSizes(),
            app_icon.availableSizes(),
        )

    def test_setup_plugins_collects_services_and_renders_menu_actions(self):
        class DemoPlugin(HydePlugin):
            def __init__(self):
                super().__init__({})
                self.setup_services = None
                self.bound_action = None

            def get_services(self):
                return {"plugin_service": "demo"}

            def get_menu_contributions(self):
                return [
                    {
                        "location": "window",
                        "group": "plugin",
                        "order": 10,
                        "name": "Plugin Tool",
                        "action": lambda: None,
                    }
                ]

            def setup(self, data=None):
                del data
                self.setup_services = self.services
                self.bound_action = self.bind_menu_action(
                    "bound_action", "window", "Plugin Tool"
                )

        plugin = DemoPlugin()
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": plugin}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertNotIn("execute_command", manager.services)
        self.assertNotIn("queue_background_command", manager.services)
        self.assertNotIn("frontend_kernel_service", manager.services)
        self.assertIn("emit_plugin_event", manager.services)
        self.assertIn("process_tree", manager.services)
        self.assertIn("on_kernel_ready", manager.services)
        self.assertIn("lookup_menu_action", manager.services)
        self.assertEqual(manager.services["plugin_service"], "demo")
        self.assertIs(manager.services["process_tree"], app.process_tree)
        self.assertIs(plugin.setup_services, manager.services)
        self.assertIs(plugin.bound_action, app.ui.menuWindow.actions()[0])
        self.assertIs(
            manager.services["lookup_menu_action"]("window", "Plugin Tool"),
            app.ui.menuWindow.actions()[0],
        )
        self.assertEqual(
            [action.text() for action in app.ui.menuWindow.actions()],
            ["Plugin Tool"],
        )

    def test_setup_plugins_runs_runtime_start_after_all_plugin_setup(self):
        events = []
        test_case = self

        class RuntimeOutputService:
            def port(self):
                events.append("port")
                test_case.assertIn("logging_setup", events)
                test_case.assertIn("runtime_setup", events)
                return 12345

        class LoggingLikePlugin(HydePlugin):
            def __init__(self):
                super().__init__({})
                self.runtime_output_service = RuntimeOutputService()

            def get_services(self):
                return {"runtime_output_service": self.runtime_output_service}

            def setup(self, data=None):
                del data
                events.append("logging_setup")

        class RuntimeLikePlugin(HydePlugin):
            def get_setup_activities(self):
                return super().get_setup_activities() + [
                    {
                        "name": "start_runtime",
                        "priority": SETUP_PRIORITY_RUNTIME_START,
                        "action": self.start_runtime,
                    },
                ]

            def setup(self, data=None):
                del data
                events.append("runtime_setup")

            def start_runtime(self, data=None):
                del data
                events.append("runtime_start")
                self.services["runtime_output_service"].port()

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {
            "runtime": RuntimeLikePlugin({}),
            "logging": LoggingLikePlugin(),
        }
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertEqual(
            events,
            ["logging_setup", "runtime_setup", "runtime_start", "port"],
        )

    def test_logging_window_preserves_runtime_output_service_across_visibility_changes(self):
        class FakeOutputBox:
            def __init__(self, layout):
                self.port = 43210
                self.writes = []
                layout.addWidget(QtWidgets.QLabel("fake output"))

            def write(self, text, color=None):
                self.writes.append((text, color))

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"logging_tool": LoggingPlugin({})}
        app = make_plugin_host(manager)

        with patch(
            "hyde.user_interface.plugins.logging_tool.OutputBox",
            FakeOutputBox,
        ):
            HydeApp.setup_plugins(app)
        app.ui.show()
        self.qapp.processEvents()

        service = manager.services["runtime_output_service"]
        action = manager.services["lookup_menu_action"]("window", "Logging")
        widget = service.widget()
        subwindow = service.subwindow()
        show_calls = []
        original_show_window = manager.services["show_window"]

        def recording_show_window(key):
            show_calls.append(key)
            return original_show_window(key)

        manager.services["show_window"] = recording_show_window

        self.assertIs(service.ensure_widget(), widget)
        self.assertEqual(service.port(), widget.output_box.port)
        self.assertEqual(widget.window_identifier(), "logging_tool")
        self.assertEqual(widget.session_key, "logging_tool")
        self.assertFalse(subwindow.isVisible())

        action.trigger()
        self.qapp.processEvents()
        self.assertEqual(show_calls, ["logging_tool"])
        self.assertIs(service.widget(), widget)

        subwindow.close()
        self.qapp.processEvents()
        self.assertTrue(subwindow.isHidden())
        self.assertIs(service.widget(), widget)

    def test_logging_window_runtime_output_service_writes_through_sink_boundary(self):
        class FakeOutputBox:
            def __init__(self, layout):
                self.port = 43210
                self.writes = []
                layout.addWidget(QtWidgets.QLabel("fake output"))

            def write(self, text, color=None):
                self.writes.append((text, color))

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"logging_tool": LoggingPlugin({})}
        app = make_plugin_host(manager)

        with patch(
            "hyde.user_interface.plugins.logging_tool.OutputBox",
            FakeOutputBox,
        ):
            HydeApp.setup_plugins(app)
        app.ui.show()
        self.qapp.processEvents()

        service = manager.services["runtime_output_service"]

        service.write("runtime line\n", color="amber")

        self.assertEqual(service.port(), 43210)
        self.assertEqual(
            service.widget().output_box.writes,
            [("runtime line\n", "amber")],
        )

    def test_connect_logger_to_output_sink_formats_messages_through_sink_boundary(self):
        class RecordingSink:
            def __init__(self):
                self.writes = []

            def write(self, text, color=None):
                self.writes.append((text, color))

        logger_name = "hyde.tests.logging_sink"
        sink = RecordingSink()
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers = []
        self.addCleanup(setattr, logger, "handlers", [])

        handler = connect_logger_to_output_sink(logger_name, sink)
        self.addCleanup(logger.removeHandler, handler)

        logger.info("plain line")
        logger.warning("warn line")
        logger.info("[Hyde state] Demo\nstate:\n{'a': 1}\npython:\nprint('x')")

        self.assertEqual(
            sink.writes[0][1],
            WHITE,
        )
        self.assertTrue(
            sink.writes[0][0].endswith("INFO hyde.tests.logging_sink: plain line\n")
        )
        self.assertEqual(sink.writes[1][1], RED)
        self.assertTrue(
            sink.writes[1][0].endswith("WARNING hyde.tests.logging_sink: warn line\n")
        )
        self.assertEqual(
            [color for _, color in sink.writes[2:7]],
            [ORANGE, ORANGE, GREEN, ORANGE, BLUE],
        )
        self.assertTrue(
            sink.writes[2][0].endswith(
                "INFO hyde.tests.logging_sink: [Hyde state] Demo\n"
            )
        )
        self.assertEqual(
            [text for text, _ in sink.writes[3:7]],
            [
                "state:\n",
                "{'a': 1}\n",
                "python:\n",
                "print('x')\n",
            ],
        )

    def test_setup_plugins_registers_contextual_menu_locations_and_visibility_services(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertIn("figure", app.menu_context.locations)
        self.assertIn("table", app.menu_context.locations)
        self.assertIn("show_menu", manager.services)
        self.assertIn("hide_menu", manager.services)
        self.assertFalse(app.ui.menuFigure.menuAction().isVisible())
        self.assertFalse(app.ui.menuTable.menuAction().isVisible())
        self.assertEqual(
            [action.text() for action in app.ui.menuBar().actions()],
            ["File", "Edit",
                "Analysis", "Windows", "Figure", "Table"],
        )

        manager.services["show_menu"]("figure")
        self.assertTrue(app.ui.menuFigure.menuAction().isVisible())

        manager.services["hide_menu"]("figure")
        self.assertFalse(app.ui.menuFigure.menuAction().isVisible())

    def test_menu_context_builds_fresh_popup_menu_from_registry(self):
        triggered = []
        main_window = QtWidgets.QMainWindow()
        persistent_menu = RecordingMenu("Figure", main_window)
        context = HydeMenuContext()
        context.register_location("figure", persistent_menu)
        context.contributions = [
            (
                "demo",
                {
                    "location": "figure",
                    "group": "demo",
                    "order": 10,
                    "name": "Figure Action",
                    "action": lambda: triggered.append("figure"),
                },
            )
        ]

        context.render()
        popup_menu = context.build_popup_menu("figure", parent=main_window)

        self.assertIsNotNone(popup_menu)
        self.assertIsNot(popup_menu, persistent_menu)
        self.assertEqual(
            [action.text() for action in popup_menu.actions()],
            ["Figure Action"],
        )

        popup_menu.actions()[0].trigger()
        self.assertEqual(triggered, ["figure"])

    def test_callable_enabled_gates_menu_action_from_a_live_precondition(self):
        # Menus render once at startup, so a static `enabled` flag can only ever
        # describe the state at launch. Figure actions need to reflect whether a
        # figure is active right now.
        figure_active = [False]
        main_window = QtWidgets.QMainWindow()
        persistent_menu = RecordingMenu("Figure", main_window)
        context = HydeMenuContext()
        context.register_location("figure", persistent_menu)
        context.contributions = [
            (
                "demo",
                {
                    "location": "figure",
                    "name": "Needs Figure",
                    "action": lambda: None,
                    "enabled": lambda: figure_active[0],
                },
            )
        ]
        context.render()

        action = context.lookup_action("figure", "Needs Figure")
        self.assertIsNotNone(action)
        self.assertFalse(action.isEnabled())

        figure_active[0] = True
        context.refresh_enabled_states()
        self.assertTrue(action.isEnabled())

        figure_active[0] = False
        context.refresh_enabled_states()
        self.assertFalse(action.isEnabled())

    def test_static_and_absent_enabled_values_keep_working(self):
        main_window = QtWidgets.QMainWindow()
        persistent_menu = RecordingMenu("Figure", main_window)
        context = HydeMenuContext()
        context.register_location("figure", persistent_menu)
        context.contributions = [
            ("demo", {"location": "figure", "name": "Default", "action": lambda: None}),
            ("demo", {"location": "figure", "name": "On", "action": lambda: None, "enabled": True}),
            ("demo", {"location": "figure", "name": "Off", "action": lambda: None, "enabled": False}),
        ]
        context.render()
        context.refresh_enabled_states()

        states = {
            name: context.lookup_action("figure", name).isEnabled()
            for name in ("Default", "On", "Off")
        }
        self.assertEqual({"Default": True, "On": True, "Off": False}, states)

    def test_menu_about_to_show_refreshes_enabled_states(self):
        # The menu bar is rendered once, so opening a menu is the moment its
        # items must re-check their preconditions.
        figure_active = [False]
        main_window = QtWidgets.QMainWindow()
        persistent_menu = RecordingMenu("Figure", main_window)
        context = HydeMenuContext()
        context.register_location("figure", persistent_menu)
        context.contributions = [
            (
                "demo",
                {
                    "location": "figure",
                    "name": "Needs Figure",
                    "action": lambda: None,
                    "enabled": lambda: figure_active[0],
                },
            )
        ]
        context.render()
        action = context.lookup_action("figure", "Needs Figure")

        figure_active[0] = True
        persistent_menu.aboutToShow.emit()
        self.assertTrue(action.isEnabled())

    def test_popup_menu_reflects_the_current_precondition(self):
        # build_popup_menu re-renders the tree, so context menus need no extra
        # refresh hook -- but they must evaluate the callable, not skip it.
        figure_active = [False]
        main_window = QtWidgets.QMainWindow()
        persistent_menu = RecordingMenu("Figure", main_window)
        context = HydeMenuContext()
        context.register_location("figure", persistent_menu)
        context.contributions = [
            (
                "demo",
                {
                    "location": "figure",
                    "name": "Needs Figure",
                    "action": lambda: None,
                    "enabled": lambda: figure_active[0],
                },
            )
        ]
        context.render()

        disabled_popup = context.build_popup_menu("figure", parent=main_window)
        self.assertFalse(disabled_popup.actions()[0].isEnabled())

        figure_active[0] = True
        enabled_popup = context.build_popup_menu("figure", parent=main_window)
        self.assertTrue(enabled_popup.actions()[0].isEnabled())

    def test_disabled_action_does_not_fire_on_its_shortcut(self):
        # Correct enablement is what gates the keyboard, so there is no separate
        # shortcut-gating path to maintain.
        fired = []
        allowed = [False]
        main_window = QtWidgets.QMainWindow()
        main_window.show()
        persistent_menu = RecordingMenu("Edit", main_window)
        context = HydeMenuContext()
        context.register_location("edit", persistent_menu)
        context.contributions = [
            (
                "demo",
                {
                    "location": "edit",
                    "name": "Copy",
                    "action": lambda: fired.append("copy"),
                    "shortcut": QtGui.QKeySequence.Copy,
                    "enabled": lambda: allowed[0],
                },
            )
        ]
        context.render()
        main_window.addAction(context.lookup_action("edit", "Copy"))
        try:
            context.refresh_enabled_states()
            QTest.keyClick(main_window, QtCore.Qt.Key_C, QtCore.Qt.ControlModifier)
            QtWidgets.QApplication.instance().processEvents()
            self.assertEqual([], fired)

            allowed[0] = True
            context.refresh_enabled_states()
            QTest.keyClick(main_window, QtCore.Qt.Key_C, QtCore.Qt.ControlModifier)
            QtWidgets.QApplication.instance().processEvents()
            self.assertEqual(["copy"], fired)
        finally:
            main_window.close()

    def test_setup_plugins_renders_contextual_menu_contributions_and_uses_fresh_popup_menu(self):
        triggered = []

        class DemoPlugin(HydePlugin):
            def get_menu_contributions(self):
                return [
                    {
                        "location": "figure",
                        "group": "demo",
                        "order": 10,
                        "name": "Figure Action",
                        "action": lambda: triggered.append("figure"),
                    },
                    {
                        "location": "table",
                        "group": "demo",
                        "order": 20,
                        "name": "Table Action",
                        "action": lambda: triggered.append("table"),
                    },
                ]

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": DemoPlugin({})}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertEqual(
            [action.text() for action in app.ui.menuFigure.actions()],
            ["Figure Action"],
        )
        self.assertEqual(
            [action.text() for action in app.ui.menuTable.actions()],
            ["Table Action"],
        )

        manager.services["lookup_menu_action"]("figure", "Figure Action").trigger()
        manager.services["lookup_menu_action"]("table", "Table Action").trigger()
        self.assertEqual(triggered, ["figure", "table"])

        popup_pos = QtCore.QPoint(12, 34)
        manager.services["popup_menu"]("figure", popup_pos)
        self.assertEqual(app.ui.menuFigure.popup_calls, [])

    def test_figure_window_shows_empty_shared_contextual_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"figure_interactive": FigurePlugin({})}
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        mdi_area = app.ui.mdiArea
        other = mdi_area.addSubWindow(QtWidgets.QLabel("other"))
        other.show()
        widget = FigureWindow(
            figure_number=1,
            services=manager.services,
        )
        subwindow = mdi_area.addSubWindow(widget)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        self.assertEqual(app.ui.menuFigure.actions(), [])

        mdi_area.setActiveSubWindow(subwindow)
        self.qapp.processEvents()
        self.assertTrue(app.ui.menuFigure.menuAction().isVisible())
        self.assertFalse(app.ui.menuTable.menuAction().isVisible())

        mdi_area.setActiveSubWindow(other)
        self.qapp.processEvents()
        self.assertFalse(app.ui.menuFigure.menuAction().isVisible())

        popup_pos = QtCore.QPoint(20, 30)
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse,
            QtCore.QPoint(5, 5),
            popup_pos,
        )

        widget.contextMenuEvent(event)

        self.assertEqual(app.ui.menuFigure.popup_calls, [])
        self.assertIs(mdi_area.activeSubWindow(), subwindow)

    def test_table_widget_shows_shared_contextual_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"table_interactive": TablePlugin({})}
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        mdi_area = app.ui.mdiArea
        other = mdi_area.addSubWindow(QtWidgets.QLabel("other"))
        other.show()
        widget = TableWidget(
            "Table0",
            ["a"],
            services=manager.services,
        )
        subwindow = mdi_area.addSubWindow(widget)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        mdi_area.setActiveSubWindow(subwindow)
        self.qapp.processEvents()
        self.assertTrue(app.ui.menuTable.menuAction().isVisible())
        self.assertFalse(app.ui.menuFigure.menuAction().isVisible())

        mdi_area.setActiveSubWindow(other)
        self.qapp.processEvents()
        self.assertFalse(app.ui.menuTable.menuAction().isVisible())

        popup_pos = QtCore.QPoint(10, 12)
        expected_global = widget.ui.tableView.viewport().mapToGlobal(popup_pos)

        widget._show_context_menu(popup_pos)

        self.assertEqual(app.ui.menuTable.popup_calls, [])
        self.assertIs(mdi_area.activeSubWindow(), subwindow)

    def test_table_plugin_registers_delete_action_with_shared_table_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"table_interactive": TablePlugin({})}
        app = make_plugin_host(manager)
        HydeApp.setup_plugins(app)

        mdi_area = app.ui.mdiArea
        widget = TableWidget("Table0", ["a"], services=manager.services)
        called = []
        widget.request_delete_selected_data = lambda: called.append("delete") or True
        subwindow = mdi_area.addSubWindow(widget)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        mdi_area.setActiveSubWindow(subwindow)

        manager.services["lookup_menu_action"]("table", "Delete Selected Data").trigger()

        self.assertEqual(called, ["delete"])

    def test_hyde_plugin_can_setup_configured_window_macros_menu(self):
        executed = []

        class DemoPlugin(HydePlugin):
            window_macros_menu_title = "Demo Macros"
            window_macros_empty_label = "No Saved Demo Macros"
            window_macros_new_action_name = "New Demo..."
            window_macros_new_action_attr = "_new_demo_action"
            window_macros_attr = "demo_macros"

            def __init__(self, initial_settings):
                super().__init__(initial_settings)
                self.demo_macros = [{"name": "Macro0", "args": ["x", "y"]}]
                self._new_demo_action = None
                self._macro_menu = None

            def get_menu_contributions(self):
                return [
                    {
                        "location": "window",
                        "group": "demo",
                        "order": 40,
                        "name": "New Demo...",
                        "action": self.show_new_demo_dialog,
                    }
                ]

            def setup(self, data=None):
                del data
                self.setup_configured_window_macros_menu()

            def show_new_demo_dialog(self, checked=False):
                del checked

        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": DemoPlugin({})}
        app = make_plugin_host(manager)
        app.get_current_project_dir = lambda: "/tmp/demo.hy"
        app.get_current_app_ir = lambda: HydeAppIR(current_project_dir="/tmp/demo.hy")
        app.build_plugin_services = lambda: {
            **HydeApp.build_plugin_services(app),
            "python_execution_service": type(
                "ExecutionService",
                (),
                {"execute_visible": lambda _self, code: executed.append(code) or True},
            )(),
        }

        HydeApp.setup_plugins(app)

        plugin = manager.plugins["demo"]
        self.assertIsNotNone(plugin._new_demo_action)
        self.assertIsNotNone(plugin._macro_menu)
        self.assertEqual(plugin._macro_menu.title(), "Demo Macros")
        self.assertEqual(
            [action.text() for action in plugin._macro_menu.actions()],
            ["Macro0"],
        )
        self.assertTrue(plugin._macro_menu.isEnabled())
        self.assertTrue(plugin._new_demo_action.isEnabled())

        plugin._macro_menu.actions()[0].trigger()

        app_ir = app.get_current_app_ir()
        macro_ir = app_ir.with_callable_invocation("Macro0", ("x", "y"))
        self.assertEqual(
            executed,
            [app_ir.current_diff(macro_ir).python_source()],
        )

    def test_rebuild_window_macros_menu_populates_actions_with_tuple_args(self):
        plugin = HydePlugin({})
        plugin.services = {"get_current_project_dir": lambda: "/tmp/demo.hy"}
        plugin._new_macro_action = QtWidgets.QAction("New Macro")
        menu = QtWidgets.QMenu("Macros")
        triggered = []

        plugin.rebuild_window_macros_menu(
            menu=menu,
            macros=[{"name": "Macro0", "args": ["x", "y"]}],
            empty_label="No Saved Macros",
            new_action_attr="_new_macro_action",
            on_trigger=lambda name, args: triggered.append((name, args)),
        )

        self.assertTrue(menu.isEnabled())
        self.assertTrue(plugin._new_macro_action.isEnabled())
        self.assertEqual([action.text() for action in menu.actions()], ["Macro0"])

        menu.actions()[0].trigger()

        self.assertEqual(triggered, [("Macro0", ("x", "y"))])

    def test_resolve_requested_name_accepts_requested_name_or_falls_forward(self):
        self.assertEqual(
            resolve_requested_name("Table", {"Table0", "Table1"}, requested_name="Table7"),
            "Table7",
        )
        self.assertEqual(
            resolve_requested_name("Table", {"Table0", "Table1"}, requested_name="Table0"),
            "Table2",
        )
        self.assertEqual(
            resolve_requested_name("Figure", {"Figure0"}, requested_name=None),
            "Figure1",
        )

    def test_resolve_requested_name_supports_omit_zero_suffixing(self):
        self.assertEqual(
            resolve_requested_name(
                "fit_signal",
                {"fit_signal", "fit_signal_1"},
                requested_name=None,
                omit_zero=True,
            ),
            "fit_signal_2",
        )
        self.assertEqual(
            resolve_requested_name(
                "fit_signal",
                {"fit_signal", "fit_signal_1"},
                requested_name="fit_signal_7",
                omit_zero=True,
            ),
            "fit_signal_7",
        )
        self.assertEqual(
            resolve_requested_name(
                "fit_signal",
                {"fit_signal", "fit_signal_1"},
                requested_name="fit_signal",
                omit_zero=True,
            ),
            "fit_signal_2",
        )

if __name__ == "__main__":
    unittest.main()
