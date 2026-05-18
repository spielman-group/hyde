from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.plugin_tools import (
    build_window_function_source,
    build_window_restore_source,
    capture_saveable_window_state,
    capture_subwindow_geometry,
)
from hyde.user_interface.window_naming import (
    bind_stable_window_name,
    stable_window_name,
)


class HydeInteractiveWidget(QtWidgets.QWidget):
    def __init__(self, *, services=None, initial_window_name=None, parent=None):
        super().__init__(parent)
        self.services = dict(services or {})
        self._subwindow = None
        self._initial_window_name = (
            None if initial_window_name is None else str(initial_window_name)
        )
        self._last_normal_geometry = None

    def service(self, key, default=None):
        return self.services.get(key, default)

    def bind_subwindow(self, subwindow, stable_name=None):
        self._subwindow = subwindow
        resolved_name = (
            stable_name
            or stable_window_name(subwindow)
            or self._initial_window_name
        )
        if resolved_name is not None:
            bind_stable_window_name(subwindow, resolved_name)
            self.on_stable_name_bound(resolved_name)
        self._initial_window_name = None
        subwindow.installEventFilter(self)
        self._remember_subwindow_geometry()
        return subwindow

    def on_stable_name_bound(self, stable_name):
        del stable_name

    def _remember_subwindow_geometry(self):
        if self._subwindow is None or self._subwindow.isMinimized():
            return
        self._last_normal_geometry = tuple(capture_subwindow_geometry(self._subwindow))

    def capture_geometry(self):
        if self._subwindow is None:
            return None
        if self._subwindow.isMinimized() and self._last_normal_geometry is not None:
            return list(self._last_normal_geometry)
        return capture_subwindow_geometry(self._subwindow)

    def activate_popup_menu(self, location, global_pos):
        mdi_area = self.service("mdi_area")
        if mdi_area is not None and self._subwindow is not None:
            mdi_area.setActiveSubWindow(self._subwindow)
        popup_menu = self.service("popup_menu")
        if popup_menu is None:
            return False
        popup_menu(location, global_pos)
        return True

    def window_state(self):
        return capture_saveable_window_state(self._subwindow)

    def window_handle(self):
        return stable_window_name(self._subwindow)

    def prepare_saveable_state(self):
        capture_layout_state = getattr(self, "capture_layout_state", None)
        if callable(capture_layout_state):
            capture_layout_state()

    def saveable_default_macro_name(self):
        raise NotImplementedError

    def saveable_decorator_name(self):
        raise NotImplementedError

    def macro_definition_source(self, macro_name, *, handle):
        del macro_name, handle
        raise NotImplementedError

    def session_restore_definition_source(self, handle):
        del handle
        raise NotImplementedError

    def session_restore_arguments(self):
        return ()

    def macro_window_metadata(self, geometry, window_state):
        del geometry
        return {"window_state": window_state}

    def session_restore_window_metadata(self, geometry, window_state):
        del geometry
        return {"window_state": window_state}

    def default_macro_name(self):
        return self.window_handle() or self.saveable_default_macro_name()

    def macro_source(self, macro_name):
        self.prepare_saveable_state()
        return build_window_function_source(
            self.macro_definition_source(
                macro_name,
                handle=self.window_handle(),
            ),
            decorator_name=self.saveable_decorator_name(),
            **self.macro_window_metadata(
                self.capture_geometry(),
                self.window_state(),
            ),
        )

    def session_restore_source(self):
        self.prepare_saveable_state()
        handle = self.window_handle()
        if handle is None:
            return None
        metadata = self.session_restore_window_metadata(
            self.capture_geometry(),
            self.window_state(),
        )
        if metadata is None:
            return None
        return build_window_restore_source(
            self.session_restore_definition_source(handle),
            handle=handle,
            arguments=self.session_restore_arguments(),
            decorator_name=self.saveable_decorator_name(),
            **metadata,
        )

    def is_close_complete(self):
        return False

    def complete_interactive_close(self, event):
        return QtWidgets.QWidget.closeEvent(self, event)

    def finalize_interactive_close(self, event):
        raise NotImplementedError

    def _prompt_to_save_on_close(self):
        save_window_dialog_service = self.service("save_window_dialog_service")
        get_procedures_init = self.service("get_procedures_init")
        reload_procedures = self.service("reload_procedures")
        if (
            save_window_dialog_service is None
            or get_procedures_init is None
            or reload_procedures is None
        ):
            return True
        procedures_init = get_procedures_init()
        if not procedures_init:
            return True
        self.prepare_saveable_state()
        return bool(
            save_window_dialog_service.prompt_to_save_window_macro(
                saveable=self,
                parent=self.service("ui", self),
                procedures_init=procedures_init,
                reload_procedures=reload_procedures,
            )
        )

    def eventFilter(self, watched, event):
        subwindow = getattr(self, "_subwindow", None)
        if (
            watched is subwindow
            and event.type() in (QtCore.QEvent.Move, QtCore.QEvent.Resize)
        ):
            self._remember_subwindow_geometry()
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        if self.is_close_complete():
            self.complete_interactive_close(event)
            return
        get_shutting_down = self.service("get_shutting_down")
        if get_shutting_down is not None and get_shutting_down():
            self.finalize_interactive_close(event)
            return
        if QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier:
            self.finalize_interactive_close(event)
            return
        if not self._prompt_to_save_on_close():
            event.ignore()
            return
        self.finalize_interactive_close(event)
