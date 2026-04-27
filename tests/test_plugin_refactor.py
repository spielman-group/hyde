import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from labscript_utils.plugins import BasePlugin
from qtutils.qt import QtWidgets

from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugin_tools import HydeMDIContext, HydePluginManager
from hyde.user_interface.project_state import read_session, write_session


class TestHydePluginManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_discover_modules_loads_packages_with_plugin_class_without_config(self):
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
            (helper_dir / "__init__.py").write_text(
                "VALUE = 1\n",
                encoding="utf-8",
            )

            sys.path.insert(0, tmpdir)
            self.addCleanup(sys.path.remove, tmpdir)

            manager = HydePluginManager(
                plugin_package="sample_plugins",
                plugins_dir=str(package_root),
            )

            modules = manager.discover_modules()

        self.assertEqual(set(modules), {"alpha"})

    def test_mdi_context_creates_singleton_window_from_plugin_contribution(self):
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
        self.assertEqual(context.subwindow("plugin_window").windowTitle(), "Plugin Window")

    def test_setup_plugins_builds_shared_services_before_plugin_setup_complete(self):
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

        main_window = QtWidgets.QMainWindow()
        main_window.setMenuBar(QtWidgets.QMenuBar())
        menu_file = main_window.menuBar().addMenu("File")
        menu_window = main_window.menuBar().addMenu("Window")
        mdi_area = QtWidgets.QMdiArea()
        main_window.setCentralWidget(mdi_area)

        app = type("DummyApp", (), {})()
        app.ui = main_window
        app.plugin_manager = manager
        app.configure_persistent_subwindow = lambda subwindow: None
        app.execute_command = lambda code, visible=True: (code, visible)
        app.queue_background_command = lambda code, silent=True: (code, silent)
        app.open_table = lambda *args, **kwargs: (args, kwargs)
        app.request_quit = lambda checked=False: checked
        app.choose_new_project = lambda checked=False: checked
        app.choose_project = lambda checked=False: checked
        app.choose_heal_project = lambda checked=False: checked
        app.save_project = lambda checked=False: checked
        app.save_project_as = lambda checked=False: checked
        app.save_project_copy = lambda checked=False: checked
        app.show_new_table_dialog = lambda checked=False: checked
        app.show_plugin_window = lambda key: key
        app.on_visible_command_executed = lambda message: message
        app.request_window_macros = lambda kind="table": kind
        app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
        app._register_plugin_window = lambda key, widget, subwindow: HydeApp._register_plugin_window(
            app, key, widget, subwindow
        )
        app._bind_plugin_action_aliases = lambda: HydeApp._bind_plugin_action_aliases(app)
        app._find_menu_action = lambda menu, text: HydeApp._find_menu_action(app, menu, text)
        app.ui.menuFile = menu_file
        app.ui.menuWindow = menu_window
        app.ui.mdiArea = mdi_area

        HydeApp.setup_plugins(app)

        self.assertIn("execute_command", manager.services)
        self.assertEqual(manager.services["plugin_service"], "demo")
        self.assertIs(plugin.setup_data["services"], manager.services)
        self.assertEqual([action.text() for action in menu_window.actions()], ["Plugin Tool"])

    def test_real_user_interface_plugins_populate_file_and_window_menus(self):
        manager = HydePluginManager(
            plugin_package="hyde.user_interface",
            plugins_dir=str(Path(__file__).resolve().parents[1] / "hyde" / "user_interface"),
        )
        manager.discover_modules()
        manager.instantiate_plugins()

        main_window = QtWidgets.QMainWindow()
        main_window.setMenuBar(QtWidgets.QMenuBar())
        menu_file = main_window.menuBar().addMenu("File")
        menu_window = main_window.menuBar().addMenu("Window")
        mdi_area = QtWidgets.QMdiArea()
        main_window.setCentralWidget(mdi_area)

        app = type("DummyApp", (), {})()
        app.ui = main_window
        app.plugin_manager = manager
        app.configure_persistent_subwindow = lambda subwindow: None
        app.execute_command = lambda code, visible=True: (code, visible)
        app.queue_background_command = lambda code, silent=True: (code, silent)
        app.open_table = lambda *args, **kwargs: (args, kwargs)
        app.request_quit = lambda checked=False: checked
        app.choose_new_project = lambda checked=False: checked
        app.choose_project = lambda checked=False: checked
        app.choose_heal_project = lambda checked=False: checked
        app.save_project = lambda checked=False: checked
        app.save_project_as = lambda checked=False: checked
        app.save_project_copy = lambda checked=False: checked
        app.show_command_window = lambda checked=False: checked
        app.show_logging_window = lambda checked=False: checked
        app.show_procedures_window = lambda checked=False: checked
        app.show_data_browser = lambda checked=False: checked
        app.show_new_table_dialog = lambda checked=False: checked
        app.show_plugin_window = lambda key: key
        app.on_visible_command_executed = lambda message: message
        app.request_window_macros = lambda kind="table": kind
        app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
        app._register_plugin_window = lambda key, widget, subwindow: HydeApp._register_plugin_window(
            app, key, widget, subwindow
        )
        app._bind_plugin_action_aliases = lambda: HydeApp._bind_plugin_action_aliases(app)
        app._find_menu_action = lambda menu, text: HydeApp._find_menu_action(app, menu, text)
        app.ui.menuFile = menu_file
        app.ui.menuWindow = menu_window
        app.ui.mdiArea = mdi_area

        HydeApp.setup_plugins(app)

        file_texts = [action.text() for action in menu_file.actions() if action.text()]
        window_texts = [action.text() for action in menu_window.actions() if action.text()]

        self.assertIn("New...", file_texts)
        self.assertIn("Load...", file_texts)
        self.assertIn("Save", file_texts)
        self.assertIn("Quit", file_texts)
        self.assertIn("Command Window", window_texts)
        self.assertIn("Logging", window_texts)
        self.assertIn("Procedures", window_texts)
        self.assertIn("Data Browser", window_texts)

    def test_project_session_round_trip_uses_plugin_event_handlers(self):
        class SessionPlugin(BasePlugin):
            def __init__(self):
                super().__init__({})
                self.loaded_session = None

            def get_event_handlers(self):
                return {
                    "request_project_save": self.on_request_project_save,
                    "project_loaded": self.on_project_loaded,
                }

            def on_request_project_save(self, data):
                data["session"]["plugin_state"] = {"value": 7}

            def on_project_loaded(self, data):
                self.loaded_session = dict(data["session"])

        plugin = SessionPlugin()
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"session": plugin}

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "plugin_session.hy")
            os.makedirs(project_dir)
            os.makedirs(os.path.join(project_dir, "terminal"))

            main_window = QtWidgets.QMainWindow()
            mdi_area = QtWidgets.QMdiArea()
            main_window.setCentralWidget(mdi_area)

            app = type("DummyApp", (), {})()
            app.ui = main_window
            app.plugin_manager = manager
            app.emit_plugin_event = lambda name, data=None: HydeApp.emit_plugin_event(app, name, data)
            app.current_project_dir = project_dir
            app.command_window = type(
                "HistorySink",
                (),
                {
                    "history_entries": lambda self: [],
                    "restore_history_entries": lambda self, entries: setattr(self, "entries", list(entries)),
                },
            )()
            app.tables = {}
            app.active_table_handle = None
            app.table_counter = 0

            write_session(app, project_dir)
            session = read_session(project_dir)
            self.assertEqual(session["plugin_state"]["value"], 7)

            HydeApp.restore_project_session(app)

        self.assertIsNotNone(plugin.loaded_session)
        self.assertEqual(plugin.loaded_session["plugin_state"]["value"], 7)


if __name__ == "__main__":
    unittest.main()
