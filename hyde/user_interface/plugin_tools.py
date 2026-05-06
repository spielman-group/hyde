import importlib
import logging
import os

from labscript_utils.plugins import (
    DEFAULT_PRIORITY,
    BasePlugin,
    MenuContext,
    PluginManager,
)
from qtutils.qt import QtCore, QtGui

from hyde.user_interface.base import RuntimeCommandState


class _NullConfig:
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
            config=_NullConfig(),
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

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})
        self.on_setup_complete(data)

    def on_setup_complete(self, data=None):
        del data

    def service(self, key, default=None):
        return self.services.get(key, default)

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

    def _execute_macro(self, macro_name, macro_args):
        state = RuntimeCommandState()
        state.set_callable_invocation(macro_name, macro_args)
        self.service("python_execution_service").execute_visible(
            state.python_source()
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
        return {
            "tool_windows": {
                session_key: capture_subwindow_state(subwindow),
            }
        }

    def restore_tool_window(self, session, session_key, mdi_key=None, ensure=False):
        key = mdi_key or session_key
        if ensure:
            self.ensure_mdi_widget(key)
        subwindow = self.mdi_subwindow(key)
        if subwindow is None:
            return None
        restore_subwindow_state(
            subwindow,
            session.get("tool_windows", {}).get(session_key, {}),
        )
        return subwindow


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
                group_orders[key][group] = len(group_orders[key])

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
    return {
        "visible": bool(subwindow.isVisible()),
        "geometry": capture_subwindow_geometry(subwindow),
    }


def restore_subwindow_state(subwindow, info):
    geometry = info.get("geometry")
    if geometry:
        subwindow.setGeometry(QtCore.QRect(*geometry))
    subwindow.setVisible(bool(info.get("visible", False)))


def capture_subwindow_geometry(subwindow):
    geometry = subwindow.geometry()
    if subwindow.isMinimized():
        normal_geometry = subwindow.normalGeometry()
        if normal_geometry.isValid() and not normal_geometry.isNull():
            geometry = normal_geometry
    return [
        geometry.x(),
        geometry.y(),
        geometry.width(),
        geometry.height(),
    ]


def capture_saveable_window_state(subwindow):
    return "minimized" if subwindow.isMinimized() else None


def apply_saveable_window_state(subwindow, window_state):
    if subwindow is None or window_state != "minimized":
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
