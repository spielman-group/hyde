import importlib
import logging
import os
import weakref

from labscript_utils.plugins import DEFAULT_PRIORITY, MenuContext, PluginManager
from qtutils.qt import QtCore


_MENU_ACTIONS_BY_ID = {}


def _menu_entry(menu, create=False):
    menu_id = id(menu)
    entry = _MENU_ACTIONS_BY_ID.get(menu_id)
    if entry is not None:
        menu_ref, actions = entry
        if menu_ref() is menu:
            return actions
        _MENU_ACTIONS_BY_ID.pop(menu_id, None)
    if not create:
        return None
    actions = {}
    _MENU_ACTIONS_BY_ID[menu_id] = (weakref.ref(menu), actions)
    return actions


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


class HydeMenuContext(MenuContext):
    """Hyde-local menu context that retains rendered QAction objects."""

    def __init__(self, icon_factory=None, logger=None):
        super().__init__(icon_factory=icon_factory, logger=logger)
        self._actions = {}

    def register_location(self, name, menu):
        super().register_location(name, menu)
        _menu_entry(menu, create=True)

    def lookup_action(self, location, name, path=()):
        if isinstance(path, str):
            path = (path,)
        else:
            path = tuple(path)
        return self._actions.get((location, path, name))

    def _register_action(self, location, path, menu, name, action):
        self._actions[(location, path, name)] = action
        actions = _menu_entry(menu, create=True)
        actions[name] = action

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

            path = contribution.get("path", ())
            if isinstance(path, str):
                path = (path,)
            else:
                path = tuple(path)

            key = (location, path)
            group = contribution.get("group", None)
            if key not in group_orders:
                group_orders[key] = {}
            if group not in group_orders[key]:
                group_orders[key][group] = len(group_orders[key])

            grouped.setdefault(key, []).append((plugin_name, contribution))

        menus = {}
        for name, menu in self.locations.items():
            menus[(name, ())] = menu
            _menu_entry(menu, create=True).clear()

        for key in sorted(grouped):
            location, path = key
            parent_path = ()
            for submenu_name in path:
                submenu_path = parent_path + (submenu_name,)
                submenu_key = (location, submenu_path)
                if submenu_key not in menus:
                    submenu = menus[(location, parent_path)].addMenu(submenu_name)
                    menus[submenu_key] = submenu
                    _menu_entry(submenu, create=True).clear()
                parent_path = submenu_path
            menu = menus[(location, path)]

            contributions = sorted(
                grouped[key],
                key=lambda item: (
                    group_orders[key][item[1].get("group", None)],
                    item[1].get("order", DEFAULT_PRIORITY),
                    item[0],
                    item[1]["name"],
                ),
            )

            previous_group = None
            for index, (plugin_name, contribution) in enumerate(contributions):
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

                self._register_action(location, path, menu, name, action)


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
        self._contributions.get(key)
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
        "geometry": [
            subwindow.geometry().x(),
            subwindow.geometry().y(),
            subwindow.geometry().width(),
            subwindow.geometry().height(),
        ],
    }


def restore_subwindow_state(subwindow, info):
    geometry = info.get("geometry")
    if geometry:
        subwindow.setGeometry(QtCore.QRect(*geometry))
    subwindow.setVisible(bool(info.get("visible", False)))
