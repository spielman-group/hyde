import os

from qtutils import UiLoader
from qtutils.qt import QtCore, QtWidgets


class _PersistentToolWindowFilter(QtCore.QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget

    def eventFilter(self, watched, event):
        if event.type() != QtCore.QEvent.Close:
            return super().eventFilter(watched, event)
        if self.widget.allows_subwindow_close():
            return super().eventFilter(watched, event)
        watched.hide()
        event.ignore()
        return True


class HydeToolWidget(QtWidgets.QWidget):
    ui_filename = "hyde_tool_widget.ui"

    def __init__(self, services=None, session_key=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services = dict(services or {})
        self.session_key = session_key
        self.mounted_child = None
        self._subwindow = None
        self._shutdown_requested = False
        self._persistent_close_filter = _PersistentToolWindowFilter(self)

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), self.ui_filename)
        self.ui = loader.load(ui_path, self)

    def service(self, key, default=None):
        return self.services.get(key, default)

    def allows_subwindow_close(self):
        if self._shutdown_requested:
            return True
        get_shutting_down = self.service("get_shutting_down")
        if callable(get_shutting_down) and get_shutting_down():
            # App shutdown is the one close path that should tear down the
            # mounted tool instead of preserving it for later reuse.
            self.shutdown()
            return True
        return False

    def mount_child_widget(self, child):
        if self.mounted_child is child:
            return child
        if self.mounted_child is not None:
            self.ui.content_layout.removeWidget(self.mounted_child)
            self.mounted_child.setParent(None)
        self.ui.content_layout.addWidget(child)
        self.mounted_child = child
        return child

    def bind_subwindow(self, subwindow):
        if self._subwindow is subwindow:
            return subwindow
        if self._subwindow is not None:
            self._subwindow.removeEventFilter(self._persistent_close_filter)
        self._subwindow = subwindow
        if self._subwindow is not None:
            self._subwindow.installEventFilter(self._persistent_close_filter)
        return subwindow

    def shutdown(self):
        self._shutdown_requested = True
        child = self.mounted_child
        if child is not None and hasattr(child, "shutdown"):
            child.shutdown()
        if self._subwindow is not None:
            self._subwindow.removeEventFilter(self._persistent_close_filter)
