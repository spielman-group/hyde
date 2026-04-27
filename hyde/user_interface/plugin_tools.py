import importlib
import logging
import os

from labscript_utils.plugins import PluginManager
from qtutils.qt import QtCore


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
