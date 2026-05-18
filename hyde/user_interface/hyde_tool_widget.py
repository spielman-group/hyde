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
    ui_filename = "hyde_window_widget.ui"

    def __init__(
        self,
        services=None,
        session_key=None,
        window_identifier=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.services = dict(services or {})
        self._window_identifier = self._normalize_window_identifier(
            window_identifier if window_identifier is not None else session_key
        )
        self.session_key = self._window_identifier
        self.mounted_child = None
        self._subwindow = None
        self._shutdown_requested = False
        self._persistent_close_filter = _PersistentToolWindowFilter(self)

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), self.ui_filename)
        self.ui = loader.load(ui_path, self)

    def _normalize_window_identifier(self, value):
        if value is None:
            return None
        return str(value)

    def set_window_identifier(self, value):
        self._window_identifier = self._normalize_window_identifier(value)
        self.session_key = self._window_identifier
        return self._window_identifier

    @staticmethod
    def read_subwindow_identifier(subwindow, fallback=None):
        if subwindow is None:
            return None if fallback is None else str(fallback)
        object_name = str(subwindow.objectName() or "").strip()
        if object_name:
            return object_name
        return None if fallback is None else str(fallback)

    @staticmethod
    def bind_subwindow_identifier(subwindow, identifier):
        bound_identifier = str(identifier)
        subwindow.setObjectName(bound_identifier)
        return bound_identifier

    def window_identifier(self):
        return self.read_subwindow_identifier(
            self._subwindow,
            fallback=self._window_identifier,
        )

    def service(self, key, default=None):
        return self.services.get(key, default)

    def close_policy(self):
        return "hide"

    def allows_subwindow_close(self):
        if self._shutdown_requested:
            return True
        get_shutting_down = self.service("get_shutting_down")
        if callable(get_shutting_down) and get_shutting_down():
            # App shutdown is the one close path that should tear down the
            # mounted tool instead of preserving it for later reuse.
            self.shutdown()
            return True
        return self.close_policy() == "close"

    def mount_child_widget(self, child):
        if self.mounted_child is child:
            return child
        if self.mounted_child is not None:
            self.ui.content_layout.removeWidget(self.mounted_child)
            self.mounted_child.setParent(None)
        self.ui.content_layout.addWidget(child)
        self.mounted_child = child
        return child

    def bind_subwindow(self, subwindow, *, window_identifier=None):
        if self._subwindow is subwindow:
            return subwindow
        if self._subwindow is not None:
            self._subwindow.removeEventFilter(self._persistent_close_filter)
        if window_identifier is not None:
            self.set_window_identifier(window_identifier)
        self._subwindow = subwindow
        if self._subwindow is not None:
            bound_identifier = self.window_identifier()
            if bound_identifier is not None:
                bound_identifier = self.bind_subwindow_identifier(
                    self._subwindow,
                    bound_identifier,
                )
                self.set_window_identifier(bound_identifier)
            self._subwindow.installEventFilter(self._persistent_close_filter)
        return subwindow

    def shutdown(self):
        self._shutdown_requested = True
        child = self.mounted_child
        if child is not None and hasattr(child, "shutdown"):
            child.shutdown()
        if self._subwindow is not None:
            self._subwindow.removeEventFilter(self._persistent_close_filter)
