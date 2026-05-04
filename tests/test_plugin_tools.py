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

from labscript_utils.plugins import BasePlugin
from qtutils.qt import QtWidgets

from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugin_tools import (
    HydeMDIContext,
    HydeMenuContext,
    HydePluginManager,
)
from hyde.user_interface.main.project_state import read_session, write_session


def make_plugin_host(plugin_manager):
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
    main_window.menuWindow = main_window.menuBar().addMenu("Window")
    main_window.mdiArea = QtWidgets.QMdiArea()
    main_window.setCentralWidget(main_window.mdiArea)

    app = type("DummyApp", (), {})()
    app.ui = main_window
    app.plugin_manager = plugin_manager
    app.configure_persistent_subwindow = lambda subwindow: None
    app.execute_command = lambda code, visible=True: (code, visible)
    app.queue_background_command = lambda code, silent=True: (code, silent)
    app.show_plugin_window = lambda key: key
    app.on_visible_command_executed = lambda message: message
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
    app.lookup_menu_action = lambda location, name, path=(): (
        None if getattr(app, "menu_context", None) is None
        else app.menu_context.lookup_action(location, name, path=path)
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
    app.reload_procedures = lambda: None
    return app


class TestPluginTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

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

    def test_hyde_menu_context_retains_actions_for_lookup(self):
        main_window = QtWidgets.QMainWindow()
        main_window.setMenuBar(QtWidgets.QMenuBar())
        file_menu = main_window.menuBar().addMenu("File")

        context = HydeMenuContext()
        context.register_location("file", file_menu)
        context.add(
            "demo",
            {
                "location": "file",
                "group": "project",
                "order": 10,
                "name": "Open Demo",
                "action": lambda: None,
            },
            {},
        )
        context.render()

        action = context.lookup_action("file", "Open Demo")
        self.assertIs(action, file_menu.actions()[0])

    def test_setup_plugins_collects_services_and_renders_menu_actions(self):
        class DemoPlugin(BasePlugin):
            def __init__(self):
                super().__init__({})
                self.setup_data = None

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

            def plugin_setup_complete(self, data=None):
                self.setup_data = dict(data or {})

        plugin = DemoPlugin()
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"demo": plugin}
        app = make_plugin_host(manager)

        HydeApp.setup_plugins(app)

        self.assertIn("execute_command", manager.services)
        self.assertIn("lookup_menu_action", manager.services)
        self.assertEqual(manager.services["plugin_service"], "demo")
        self.assertIs(plugin.setup_data["services"], manager.services)
        self.assertIs(
            manager.services["lookup_menu_action"]("window", "Plugin Tool"),
            app.ui.menuWindow.actions()[0],
        )
        self.assertEqual(
            [action.text() for action in app.ui.menuWindow.actions()],
            ["Plugin Tool"],
        )

    def test_builtin_plugins_populate_file_and_window_menus(self):
        class FakeOutputBox:
            def __init__(self, layout):
                del layout
                self.port = 12345

        manager = HydePluginManager(
            plugin_package="hyde.user_interface.plugins",
            plugins_dir=str(
                Path(__file__).resolve().parents[1]
                / "hyde"
                / "user_interface"
                / "plugins"
            ),
        )
        manager.discover_modules()
        manager.instantiate_plugins()
        app = make_plugin_host(manager)

        with patch(
            "hyde.user_interface.plugins.remote_requests.RemoteRequestServer",
            lambda *args, **kwargs: object(),
        ):
            with patch(
                "hyde.user_interface.plugins.logging_window.OutputBox",
                FakeOutputBox,
            ):
                HydeApp.setup_plugins(app)

        file_texts = [action.text() for action in app.ui.menuFile.actions() if action.text()]
        window_texts = [
            action.text() for action in app.ui.menuWindow.actions() if action.text()
        ]

        self.assertIn("New...", file_texts)
        self.assertIn("Load...", file_texts)
        self.assertIn("Save", file_texts)
        self.assertIn("Quit", file_texts)
        self.assertIn("Command Window", window_texts)
        self.assertIn("Logging", window_texts)
        self.assertIn("Procedures", window_texts)
        self.assertIn("Data Browser", window_texts)

    def test_project_session_round_trip_uses_plugin_save_and_load_hooks(self):
        class SessionPlugin(BasePlugin):
            def __init__(self):
                super().__init__({})
                self.loaded_session = None

            def get_save_data(self):
                return {"plugin_state": {"value": 7}}

            def get_event_handlers(self):
                return {"project_loaded": self.on_project_loaded}

            def on_project_loaded(self, data):
                self.loaded_session = dict(data["session"])

        plugin = SessionPlugin()
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"session": plugin}

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "plugin_session.hy")
            os.makedirs(project_dir)
            os.makedirs(os.path.join(project_dir, "terminal"))

            app = make_plugin_host(manager)
            app.emit_plugin_event = lambda name, data=None: HydeApp.emit_plugin_event(
                app, name, data
            )
            app.plugin_service = lambda key: manager.services.get(key)
            app.current_project_dir = project_dir

            write_session(app, project_dir)
            session = read_session(project_dir)
            self.assertEqual(session["plugin_state"]["value"], 7)

            HydeApp.restore_project_session(app)

        self.assertIsNotNone(plugin.loaded_session)
        self.assertEqual(plugin.loaded_session["plugin_state"]["value"], 7)


if __name__ == "__main__":
    unittest.main()
