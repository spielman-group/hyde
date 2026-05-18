from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.hyde_tool_widget import HydeToolWidget
from hyde.user_interface.plugin_tools import (
    build_window_function_source,
    build_window_restore_source,
    capture_saveable_window_state,
    capture_subwindow_geometry,
)


def _freeze_namespace_tracking_value(value):
    if isinstance(value, dict):
        return tuple(
            (str(key), _freeze_namespace_tracking_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_namespace_tracking_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_namespace_tracking_value(item) for item in value))
    return value


def _tracked_namespace_signature(view, names):
    tracked = []
    view = dict(view or {})
    for name in names:
        metadata = dict(view.get(name, {}) or {})
        tracked.append((name, _freeze_namespace_tracking_value(metadata)))
    return tuple(tracked)


class HydeInteractiveWidget(HydeToolWidget):
    def __init__(
        self,
        *,
        services=None,
        initial_window_name=None,
        window_identifier=None,
        parent=None,
    ):
        super().__init__(
            services=services,
            window_identifier=(
                window_identifier
                if window_identifier is not None
                else initial_window_name
            ),
            parent=parent,
        )
        self._last_normal_geometry = None

    def close_policy(self):
        return "close"

    def bind_subwindow(self, subwindow, stable_name=None):
        previous_subwindow = self._subwindow
        resolved_name = (
            stable_name
            or self.read_subwindow_identifier(subwindow)
            or self.window_identifier()
        )
        if previous_subwindow is not None and previous_subwindow is not subwindow:
            previous_subwindow.removeEventFilter(self)
        super().bind_subwindow(subwindow, window_identifier=resolved_name)
        if previous_subwindow is not subwindow:
            subwindow.installEventFilter(self)
        if self.window_identifier() is not None:
            self.on_stable_name_bound(self.window_identifier())
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
        return self.window_identifier()

    def formatted_window_title(self, title_suffix=None, warning_text=None):
        stable_name = str(self.window_handle())
        suffix_text = (
            str(title_suffix).strip()
            if title_suffix is not None
            else ""
        )
        base_title = stable_name if not suffix_text else f"{stable_name}: {suffix_text}"
        warning = str(warning_text).strip() if warning_text is not None else ""
        if warning:
            return f"{base_title} [{warning}]"
        return base_title

    def prepare_saveable_state(self):
        capture_layout_state = getattr(self, "capture_layout_state", None)
        if callable(capture_layout_state):
            capture_layout_state()

    def tracked_namespace_signature(self, view, names):
        return _tracked_namespace_signature(view, names)

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
        return self.window_identifier() or self.saveable_default_macro_name()

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
