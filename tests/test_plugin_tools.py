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
from hyde.user_interface.plugins.figure import Plugin as FigurePlugin
from hyde.user_interface.plugins.figure.window import FigureWindow
from hyde.user_interface.plugins.table import Plugin as TablePlugin
from hyde.user_interface.plugins.table.window import TableWidget
from hyde.user_interface.window_naming import next_numbered_name


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
    app.on_visible_command_executed = lambda message: message
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
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
            ["File", "Windows", "Figure", "Table"],
        )

        manager.services["show_menu"]("figure")
        self.assertTrue(app.ui.menuFigure.menuAction().isVisible())

        manager.services["hide_menu"]("figure")
        self.assertFalse(app.ui.menuFigure.menuAction().isVisible())

    def test_setup_plugins_renders_contextual_menu_contributions_and_reuses_menu_for_popup(self):
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
        self.assertEqual(app.ui.menuFigure.popup_calls, [popup_pos])

    def test_figure_window_shows_empty_shared_contextual_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"figure": FigurePlugin({})}
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

        self.assertEqual(app.ui.menuFigure.popup_calls, [popup_pos])
        self.assertIs(mdi_area.activeSubWindow(), subwindow)

    def test_table_widget_shows_shared_contextual_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"table": TablePlugin({})}
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

        self.assertEqual(app.ui.menuTable.popup_calls, [expected_global])
        self.assertIs(mdi_area.activeSubWindow(), subwindow)

    def test_table_plugin_registers_delete_action_with_shared_table_menu(self):
        manager = HydePluginManager(plugin_package="unused", plugins_dir="unused")
        manager.plugins = {"table": TablePlugin({})}
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
