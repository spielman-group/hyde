import importlib
import logging
import os

from labscript_utils.plugins import (
    DEFAULT_PRIORITY,
    DEFAULT_SETUP_PRIORITY,
    BasePlugin,
    MenuContext,
    PluginManager,
)
from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.user_interface.base_hyde_widgets import HydeToolWidget
LOGGER = logging.getLogger(__name__)
SETUP_PRIORITY_BIND_SERVICES = DEFAULT_SETUP_PRIORITY
SETUP_PRIORITY_PLUGIN_SETUP = DEFAULT_SETUP_PRIORITY + 10
# Side-effectful runtime startup must wait until all plugins have received
# services and completed ordinary setup, including output-window creation.
SETUP_PRIORITY_RUNTIME_START = DEFAULT_SETUP_PRIORITY + 20
_TOOL_WINDOW_STATES = frozenset({"hidden", "visible", "minimized", "maximized"})


class NullConfig:
    def has_section(self, section):
        del section
        return True

    def add_section(self, section):
        del section

    def items(self, section):
        del section
        return []

    def set(self, section, name, value):
        del section, name, value

    def getboolean(self, section, name):
        del section, name
        return True


class HydePluginManager(PluginManager):
    """Plugin manager with unconditional discovery for Hyde UI packages."""

    def __init__(self, plugin_package, plugins_dir, logger=None):
        super().__init__(
            plugin_package=plugin_package,
            plugins_dir=plugins_dir,
            config=NullConfig(),
            config_section="hyde/user_interface",
            default_plugins=(),
            logger=logger or logging.getLogger(__name__),
        )

    def discover_modules(self):
        modules = {}
        for module_name in os.listdir(self.plugins_dir):
            module_path = os.path.join(self.plugins_dir, module_name)
            if not os.path.isdir(module_path) or module_name == "__pycache__":
                continue
            try:
                module = importlib.import_module(f"{self.plugin_package}.{module_name}")
            except Exception:
                self.logger.exception(
                    "Could not import plugin '%s'. Skipping." % module_name
                )
                continue
            if not hasattr(module, "Plugin"):
                continue
            modules[module_name] = module

        self.modules = modules
        return modules


class HydePlugin(BasePlugin):
    """Hyde-local plugin base with shared service and menu-action helpers."""

    window_macros_menu_title = None
    window_macros_empty_label = None
    window_macros_new_action_name = None
    window_macros_new_action_attr = None
    window_macros_attr = None
    window_macros_menu_attr = "_macro_menu"

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}

    def get_setup_activities(self):
        return [
            {
                "name": "bind_services",
                "priority": SETUP_PRIORITY_BIND_SERVICES,
                "action": self.bind_services,
            },
            {
                "name": "setup",
                "priority": SETUP_PRIORITY_PLUGIN_SETUP,
                "action": self.setup,
            },
        ]

    def bind_services(self, data=None):
        data = data or {}
        self.services = data.get("services", {})

    def setup(self, data=None):
        del data

    def service(self, key, default=None):
        return self.services.get(key, default)

    def current_app_ir(self):
        from hyde.user_interface.plugins.file.dialogs import HydeAppIR

        get_current_app_ir = self.services.get("get_current_app_ir")
        if callable(get_current_app_ir):
            app_ir = get_current_app_ir()
            if isinstance(app_ir, HydeAppIR):
                return app_ir
        get_current_project_dir = self.services.get("get_current_project_dir")
        current_project_dir = (
            get_current_project_dir() if callable(get_current_project_dir) else None
        )
        return HydeAppIR(current_project_dir=current_project_dir)

    def get_session_toml_data(self):
        return {}

    def get_session_restore_source(self):
        return ""

    def menu_action(self, location, name, path=()):
        lookup_menu_action = self.service("lookup_menu_action")
        if lookup_menu_action is None:
            return None
        return lookup_menu_action(location, name, path=path)

    def bind_menu_action(self, attr_name, location, name, path=()):
        action = self.menu_action(location, name, path=path)
        setattr(self, attr_name, action)
        return action

    def set_bound_action_enabled(self, attr_name, enabled):
        action = getattr(self, attr_name, None)
        if action is not None:
            action.setEnabled(bool(enabled))

    def rebuild_window_macros_menu(
        self,
        *,
        menu,
        macros,
        empty_label,
        new_action_attr,
        on_trigger,
    ):
        menu.clear()
        get_current_project_dir = self.service("get_current_project_dir")
        has_project = (
            False
            if get_current_project_dir is None
            else get_current_project_dir() is not None
        )
        self.set_bound_action_enabled(new_action_attr, has_project)
        if not has_project:
            menu.setEnabled(False)
            return
        if not macros:
            placeholder = menu.addAction(empty_label)
            placeholder.setEnabled(False)
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        for macro in macros:
            macro_name = macro["name"]
            macro_args = tuple(macro.get("args", ()))
            action = menu.addAction(macro_name)
            action.triggered.connect(
                lambda checked=False, name=macro_name, args=macro_args: (
                    on_trigger(name, args)
                )
            )

    def setup_configured_window_macros_menu(self):
        menu_title = self.window_macros_menu_title
        if not menu_title:
            return None
        if self.window_macros_new_action_attr and self.window_macros_new_action_name:
            self.bind_menu_action(
                self.window_macros_new_action_attr,
                "window",
                self.window_macros_new_action_name,
            )
        menu_attr = self.window_macros_menu_attr
        menu = getattr(self, menu_attr, None)
        if menu is None:
            ui = self.services["ui"]
            menu = QtWidgets.QMenu(menu_title, ui.menuWindow)
            ui.menuWindow.addMenu(menu)
            setattr(self, menu_attr, menu)
            menu.aboutToShow.connect(self.rebuild_configured_window_macros_menu)
        self.rebuild_configured_window_macros_menu()
        return menu

    def rebuild_configured_window_macros_menu(self):
        menu = getattr(self, self.window_macros_menu_attr, None)
        if menu is None:
            return None
        macros = []
        if self.window_macros_attr:
            macros = getattr(self, self.window_macros_attr, [])
        self.rebuild_window_macros_menu(
            menu=menu,
            macros=macros,
            empty_label=self.window_macros_empty_label,
            new_action_attr=self.window_macros_new_action_attr,
            on_trigger=self._execute_macro,
        )
        return menu

    def _execute_macro(self, macro_name, macro_args):
        app_ir = self.current_app_ir()
        macro_ir = app_ir.with_callable_invocation(macro_name, macro_args)
        self.service("python_execution_service").execute_visible(
            app_ir.current_diff(macro_ir).python_source()
        )

    def mdi_context(self):
        return self.service("mdi_context")

    def ensure_mdi_widget(self, key):
        return self.mdi_context().ensure_widget(key)

    def mdi_widget(self, key):
        return self.mdi_context().widget(key)

    def mdi_subwindow(self, key):
        return self.mdi_context().subwindow(key)

    def destroy_mdi_widget(self, key):
        return self.mdi_context().destroy(key)

    def hide_mdi_subwindow(self, key):
        subwindow = self.mdi_subwindow(key)
        if subwindow is not None:
            subwindow.hide()
        return subwindow

    def tool_window_save_data(self, session_key, mdi_key=None):
        subwindow = self.mdi_subwindow(mdi_key or session_key)
        if subwindow is None:
            return {}
        object_name = HydeToolWidget.read_subwindow_identifier(
            subwindow,
            fallback=mdi_key or session_key,
        )
        return {
            "tool_windows": {
                object_name: capture_subwindow_state(subwindow),
            }
        }

    def restore_tool_window(self, session, session_key, mdi_key=None):
        key = mdi_key or session_key
        subwindow = self.mdi_subwindow(key)
        if subwindow is None:
            return None
        object_name = HydeToolWidget.read_subwindow_identifier(
            subwindow,
            fallback=key,
        )
        tool_windows = session.get("tool_windows", {})
        info = tool_windows.get(session_key, tool_windows.get(object_name, {}))
        presentation_deferred = False
        deferred_getter = self.service(
            "get_session_restore_presentation_deferred"
        )
        if deferred_getter is not None:
            presentation_deferred = bool(deferred_getter())
        if presentation_deferred:
            restored = stage_subwindow_state(
                subwindow,
                info,
                session_key=object_name,
            )
            if restored:
                register_tool_window = self.service(
                    "register_session_restore_tool_window"
                )
                if register_tool_window is not None:
                    register_tool_window(object_name, subwindow, info)
            return subwindow
        restore_subwindow_state(
            subwindow,
            info,
            session_key=object_name,
        )
        return subwindow


class HydeToolWindowPlugin(HydePlugin):
    """Shared plugin plumbing for ordinary persistent tool windows."""

    session_key = None
    window_title = None
    menu_name = None
    window_size = None
    menu_group = "tool_windows"
    menu_order = DEFAULT_PRIORITY
    creation_policy = "lazy"
    restore_on_project_loaded = False
    enable_action_with_project = False
    hide_on_enter_no_project = False
    ensure_widget_on_kernel_ready = False
    destroy_widget_on_kernel_crash = False

    def create_tool_window_widget(self, parent=None):
        raise NotImplementedError

    def _tool_window_factory(self, parent=None, data=None):
        del data
        return self.create_tool_window_widget(parent=parent)

    def get_ui_contributions(self):
        key = self.session_key
        title = self.window_title or self.menu_name or key
        contribution = {
            "context": "mdi",
            "key": key,
            "title": title,
            "factory": self._tool_window_factory,
        }
        if self.window_size is not None:
            contribution["size"] = self.window_size
        return [contribution]

    def get_menu_contributions(self):
        title = self.window_title or self.menu_name or self.session_key
        menu_name = self.menu_name or title
        return [
            {
                "location": "window",
                "group": self.menu_group,
                "order": self.menu_order,
                "name": menu_name,
                "action": self.show_window,
            }
        ]

    def setup(self, data=None):
        del data
        title = self.window_title or self.menu_name or self.session_key
        menu_name = self.menu_name or title
        self.bind_menu_action("_action", "window", menu_name)
        if self.creation_policy == "eager":
            self.ensure_mdi_widget(self.session_key)
            self.hide_mdi_subwindow(self.session_key)

    def show_window(self, checked=False):
        del checked
        self.service("show_window")(self.session_key)

    def get_event_handlers(self):
        handlers = {}
        if self.restore_on_project_loaded:
            handlers["project_loaded"] = self.on_project_loaded
        if self.enable_action_with_project or self.hide_on_enter_no_project:
            handlers["enter_no_project_state"] = self.on_enter_no_project_state
        if self.enable_action_with_project:
            handlers["project_activated"] = self.on_project_activated
        if self.ensure_widget_on_kernel_ready:
            handlers["kernel_ready"] = self.on_kernel_ready
        if self.destroy_widget_on_kernel_crash:
            handlers["kernel_crashed"] = self.on_kernel_crashed
        return handlers

    def on_project_loaded(self, data):
        self.restore_tool_window_session(data["session"])

    def on_enter_no_project_state(self, data):
        del data
        if self.enable_action_with_project:
            self.set_bound_action_enabled("_action", False)
        if self.hide_on_enter_no_project:
            self.hide_mdi_subwindow(self.session_key)

    def on_project_activated(self, data):
        del data
        if self.enable_action_with_project:
            self.set_bound_action_enabled("_action", True)

    def on_kernel_ready(self, data):
        del data
        if self.ensure_widget_on_kernel_ready:
            self.ensure_mdi_widget(self.session_key)

    def on_kernel_crashed(self, data):
        del data
        if self.destroy_widget_on_kernel_crash:
            self.destroy_mdi_widget(self.session_key)

    def get_session_toml_data(self):
        session = self.tool_window_save_data(self.session_key)
        widget = self.mdi_widget(self.session_key)
        if widget is None:
            return session
        getter = getattr(widget, "get_session_toml_data", None)
        widget_session = getter() if callable(getter) else {}
        if widget_session:
            session[self.session_key] = widget_session
        return session

    def restore_tool_window_session(self, session):
        widget = self.ensure_mdi_widget(self.session_key)
        self.restore_tool_window(session, self.session_key)
        restorer = getattr(widget, "restore_session_toml_data", None)
        if callable(restorer):
            restorer(dict(session.get(self.session_key, {}) or {}))
        return widget


class HydeToolWindowService:
    """Shared MDI-backed service helpers for persistent tool windows."""

    use_mounted_child = False

    def __init__(self, plugin, window_key=None):
        self.plugin = plugin
        self.window_key = (
            window_key
            if window_key is not None
            else getattr(plugin, "session_key", None)
        )

    def _service_widget(self, widget):
        if widget is None or not self.use_mounted_child:
            return widget
        return getattr(widget, "mounted_child", None)

    def ensure_widget(self):
        return self._service_widget(self.plugin.ensure_mdi_widget(self.window_key))

    def widget(self):
        return self._service_widget(self.plugin.mdi_widget(self.window_key))

    def subwindow(self):
        return self.plugin.mdi_subwindow(self.window_key)

    def destroy(self):
        return self.plugin.destroy_mdi_widget(self.window_key)


class HydeMenuContext(MenuContext):
    """Hyde-local menu context that retains rendered QAction objects."""

    def __init__(self, icon_factory=None, logger=None):
        super().__init__(icon_factory=icon_factory, logger=logger)
        self._actions = {}
        self._grouped_contributions = {}
        self._group_orders = {}

    def lookup_action(self, location, name, path=()):
        if isinstance(path, str):
            path = (path,)
        else:
            path = tuple(path)
        return self._actions.get((location, path, name))

    def _register_action(self, location, path, name, action):
        self._actions[(location, path, name)] = action

    def _normalized_path(self, path):
        if isinstance(path, str):
            return (path,)
        return tuple(path)

    def _sorted_contributions(self, location, path):
        key = (location, self._normalized_path(path))
        contributions = self._grouped_contributions.get(key, [])
        group_orders = self._group_orders.get(key, {})
        return sorted(
            contributions,
            key=lambda item: (
                group_orders[item[1].get("group", None)],
                item[1].get("order", DEFAULT_PRIORITY),
                item[0],
                item[1]["name"],
            ),
        )

    def _render_menu_tree(self, location, root_menu, register_actions):
        menus = {(location, ()): root_menu}
        paths = {
            path
            for current_location, path in self._grouped_contributions
            if current_location == location
        }
        for path in sorted(paths):
            parent_path = ()
            for submenu_name in path:
                submenu_path = parent_path + (submenu_name,)
                submenu_key = (location, submenu_path)
                if submenu_key not in menus:
                    submenu = menus[(location, parent_path)].addMenu(submenu_name)
                    menus[submenu_key] = submenu
                parent_path = submenu_path

        for path in sorted(paths):
            menu = menus[(location, path)]
            previous_group = None
            for index, (plugin_name, contribution) in enumerate(
                self._sorted_contributions(location, path)
            ):
                group = contribution.get("group", None)
                if index and group != previous_group:
                    menu.addSeparator()
                previous_group = group

                name = contribution["name"]
                icon = contribution.get("icon", None)
                if icon is not None and self.icon_factory is not None:
                    action = menu.addAction(self.icon_factory(icon), name)
                else:
                    action = menu.addAction(name)

                callback = contribution.get("action", None)
                if callback is not None:
                    action.triggered.connect(callback)

                shortcut = contribution.get("shortcut", None)
                if shortcut is not None and hasattr(action, "setShortcut"):
                    action.setShortcut(shortcut)

                checkable = contribution.get("checkable", False)
                if hasattr(action, "setCheckable"):
                    action.setCheckable(checkable)

                enabled = contribution.get("enabled", True)
                if hasattr(action, "setEnabled"):
                    action.setEnabled(enabled)

                if register_actions:
                    self._register_action(location, path, name, action)

    def build_popup_menu(self, location, parent=None):
        if location not in self.locations:
            return None
        base_menu = self.locations[location]
        popup_menu = base_menu.__class__(base_menu.title(), parent or base_menu.parent())
        self._render_menu_tree(location, popup_menu, register_actions=False)
        return popup_menu

    def render(self):
        self._actions = {}
        grouped = {}
        group_orders = {}

        for plugin_name, contribution in self.contributions:
            if not isinstance(contribution, dict):
                self.logger.error(
                    "Menu contribution from plugin '%s' is not a dictionary. "
                    "Skipping." % plugin_name
                )
                continue
            if "location" not in contribution:
                self.logger.error(
                    "Menu contribution from plugin '%s' missing location. "
                    "Skipping." % plugin_name
                )
                continue
            if "name" not in contribution:
                self.logger.error(
                    "Menu contribution from plugin '%s' missing name. "
                    "Skipping." % plugin_name
                )
                continue

            location = contribution["location"]
            if location not in self.locations:
                self.logger.error(
                    "Menu contribution from plugin '%s' requested unknown "
                    "location '%s'. Skipping." % (plugin_name, location)
                )
                continue

            path = self._normalized_path(contribution.get("path", ()))

            key = (location, path)
            group = contribution.get("group", None)
            if key not in group_orders:
                group_orders[key] = {}
            if group not in group_orders[key]:
                explicit_group_order = contribution.get("group_order", None)
                if explicit_group_order is None:
                    group_orders[key][group] = len(group_orders[key])
                else:
                    group_orders[key][group] = int(explicit_group_order)

            grouped.setdefault(key, []).append((plugin_name, contribution))

        self._grouped_contributions = grouped
        self._group_orders = group_orders

        for name, menu in self.locations.items():
            menu.clear()
            self._render_menu_tree(name, menu, register_actions=True)


class HydeMDIContext:
    """Register and lazily open plugin-owned MDI windows."""

    def __init__(self, mdi_area, configure_subwindow=None, created_callback=None):
        self.mdi_area = mdi_area
        self.configure_subwindow = configure_subwindow
        self.created_callback = created_callback
        self._contributions = {}
        self._widgets = {}
        self._subwindows = {}

    def add(self, plugin_name, contribution, data):
        key = contribution["key"]
        self._contributions[key] = {
            "plugin_name": plugin_name,
            "contribution": dict(contribution),
            "data": dict(data),
        }

    def ensure_widget(self, key):
        if key in self._widgets:
            return self._widgets[key]

        info = self._contributions[key]
        contribution = info["contribution"]
        widget = contribution["factory"](parent=self.mdi_area, data=info["data"])
        subwindow = self.mdi_area.addSubWindow(widget)
        HydeToolWidget.bind_subwindow_identifier(subwindow, key)
        bind_subwindow = getattr(widget, "bind_subwindow", None)
        if callable(bind_subwindow):
            bind_subwindow(subwindow)
        if self.configure_subwindow is not None:
            self.configure_subwindow(subwindow)
        title = contribution.get("title")
        if title:
            subwindow.setWindowTitle(title)
        size = contribution.get("size")
        if size:
            subwindow.resize(*size)

        self._widgets[key] = widget
        self._subwindows[key] = subwindow
        if self.created_callback is not None:
            self.created_callback(key, widget, subwindow)
        return widget

    def show(self, key):
        widget = self.ensure_widget(key)
        subwindow = self._subwindows[key]
        subwindow.show()
        subwindow.setFocus()
        subwindow.raise_()
        return widget

    def widget(self, key):
        return self._widgets.get(key)

    def subwindow(self, key):
        return self._subwindows.get(key)

    def destroy(self, key):
        widget = self._widgets.pop(key, None)
        subwindow = self._subwindows.pop(key, None)
        if widget is None:
            return None, None
        if subwindow is not None:
            self.mdi_area.removeSubWindow(widget)
        if hasattr(widget, "shutdown"):
            widget.shutdown()
        widget.deleteLater()
        if subwindow is not None:
            subwindow.deleteLater()
        if self.created_callback is not None:
            self.created_callback(key, None, None)
        return widget, subwindow

def capture_subwindow_state(subwindow):
    window_state = capture_subwindow_window_state(subwindow)
    return {
        "window_state": window_state,
        "geometry": capture_subwindow_geometry(subwindow),
    }


def restore_subwindow_state(subwindow, info, *, session_key="tool window"):
    normalized = normalize_subwindow_restore_info(
        subwindow,
        info,
        session_key=session_key,
    )
    if normalized is None:
        return False
    apply_staged_subwindow_restore(subwindow, normalized)
    apply_subwindow_presentation_state(subwindow, normalized)
    return True


def stage_subwindow_state(subwindow, info, *, session_key="tool window"):
    normalized = normalize_subwindow_restore_info(
        subwindow,
        info,
        session_key=session_key,
    )
    if normalized is None:
        return False
    apply_staged_subwindow_restore(subwindow, normalized)
    return True


def finalize_subwindow_state(subwindow, info, *, session_key="tool window"):
    normalized = normalize_subwindow_restore_info(
        subwindow,
        info,
        session_key=session_key,
    )
    if normalized is None:
        return False
    apply_subwindow_presentation_state(subwindow, normalized)
    return True


def capture_subwindow_geometry(subwindow):
    was_hidden = subwindow.isHidden()
    was_minimized = subwindow.isMinimized()
    was_maximized = subwindow.isMaximized()
    if was_minimized or was_maximized:
        subwindow.showNormal()
    geometry = qrect_to_list(subwindow.geometry())
    if was_maximized:
        subwindow.showMaximized()
    elif was_minimized:
        subwindow.showMinimized()
    if was_hidden:
        subwindow.hide()
    return geometry


def capture_subwindow_window_state(subwindow):
    if subwindow.isHidden():
        return "hidden"
    if subwindow.isMinimized():
        return "minimized"
    if subwindow.isMaximized():
        return "maximized"
    return "visible"


def coerce_geometry(geometry):
    if not isinstance(geometry, (list, tuple)) or len(geometry) != 4:
        return None
    try:
        x, y, width, height = [int(value) for value in geometry]
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return QtCore.QRect(x, y, width, height)


def hide_subwindow_with_warning(subwindow, session_key, detail):
    subwindow.hide()
    LOGGER.warning("%s: %s.", session_key, detail)


def normalize_subwindow_restore_info(subwindow, info, *, session_key):
    if not isinstance(info, dict):
        info = {}

    window_state = info.get("window_state")
    if window_state not in _TOOL_WINDOW_STATES:
        hide_subwindow_with_warning(
            subwindow,
            session_key,
            "invalid or missing tool-window window_state",
        )
        return None

    geometry = coerce_geometry(info.get("geometry"))
    if geometry is None:
        hide_subwindow_with_warning(
            subwindow,
            session_key,
            "invalid or missing tool-window geometry",
        )
        return None

    return {
        "window_state": window_state,
        "geometry": geometry,
    }


def apply_staged_subwindow_restore(subwindow, info):
    if info["window_state"] == "hidden":
        subwindow.hide()
        subwindow.setGeometry(info["geometry"])
        return
    subwindow.showNormal()
    subwindow.setGeometry(info["geometry"])


def apply_subwindow_presentation_state(subwindow, info):
    window_state = info["window_state"]
    if window_state == "hidden":
        subwindow.hide()
        return
    if window_state == "maximized":
        subwindow.showMaximized()
        return
    if window_state == "minimized":
        subwindow.showMinimized()


def qrect_to_list(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def capture_saveable_window_state(subwindow):
    if subwindow is None:
        return None
    if subwindow.isMinimized():
        return "minimized"
    if subwindow.isMaximized():
        return "maximized"
    return None


def apply_saveable_window_state(subwindow, window_state):
    if subwindow is None:
        return
    if window_state == "maximized":
        subwindow.showMaximized()
        return
    if window_state != "minimized":
        return
    subwindow.showMinimized()


def with_window_metadata(
    macro_source,
    *,
    decorator_name,
    register=None,
    window_pos=None,
    window_state=None,
):
    if not macro_source:
        return macro_source
    decorator_args = []
    if window_pos and len(window_pos) == 2:
        decorator_args.append(f"window_pos=({int(window_pos[0])}, {int(window_pos[1])})")
    if window_state:
        decorator_args.append(f"window_state={window_state!r}")
    if register is False:
        decorator_args.append("register=False")
    if not decorator_args:
        return macro_source
    lines = macro_source.splitlines()
    if not lines:
        return macro_source
    lines[0] = f"{decorator_name}({', '.join(decorator_args)})"
    return "\n".join(lines)


def build_window_function_source(
    function_source,
    *,
    decorator_name,
    register=None,
    window_pos=None,
    window_state=None,
):
    return with_window_metadata(
        function_source,
        decorator_name=decorator_name,
        register=register,
        window_pos=window_pos,
        window_state=window_state,
    )


def build_window_restore_source(
    function_source,
    *,
    handle,
    arguments,
    decorator_name,
    register=False,
    window_pos=None,
    window_state=None,
):
    wrapped_source = build_window_function_source(
        function_source,
        decorator_name=decorator_name,
        register=register,
        window_pos=window_pos,
        window_state=window_state,
    )
    invocation_arguments = ", ".join(arguments or ())
    return f"{wrapped_source}\n\n{handle}({invocation_arguments})\n"


def blank_window_icon():
    pixmap = QtGui.QPixmap(1, 1)
    pixmap.fill(QtCore.Qt.transparent)
    return QtGui.QIcon(pixmap)
