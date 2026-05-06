import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.user_interface.main import HydeApp
from hyde.user_interface.plugin_tools import (
    HydeMDIContext,
    HydePlugin,
    HydePluginManager,
)
from hyde.user_interface.window_naming import next_numbered_name


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
    app.emit_plugin_event = lambda name, data=None: (name, data)
    app.process_tree = object()
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
    app.finalize_quit = lambda: None
    app.reload_procedures = lambda: None
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

            def on_setup_complete(self, data=None):
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

    def test_next_numbered_name_is_shared_counter_based_naming_helper(self):
        name, next_counter = next_numbered_name("Table", {"Table0", "Table1"}, 0)
        self.assertEqual(name, "Table2")
        self.assertEqual(next_counter, 3)

        name, next_counter = next_numbered_name("Figure", {"Figure0"}, 0)
        self.assertEqual(name, "Figure1")
        self.assertEqual(next_counter, 2)

if __name__ == "__main__":
    unittest.main()
