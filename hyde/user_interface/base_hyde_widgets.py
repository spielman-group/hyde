import os
import sys

from qtutils import UiLoader
from qtutils.qt import QtCore, QtWidgets


def load_ui_for_owner(owner, ui_filename, *, module_name=None):
    resolved_module_name = module_name or type(owner).__module__
    module = sys.modules[resolved_module_name]
    module_file = module.__file__
    ui_path = os.path.join(os.path.dirname(module_file), ui_filename)
    loader = UiLoader()
    return loader.load(ui_path, owner)


class PersistentToolWindowFilter(QtCore.QObject):
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
        self._persistent_close_filter = PersistentToolWindowFilter(self)
        self.ui = load_ui_for_owner(
            self,
            self.ui_filename,
            module_name="hyde.user_interface",
        )

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


class HydeDialog(QtWidgets.QDialog):
    def __init__(self, *args, services=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.services = dict(services or {})
        self.ui = None
        self.setModal(True)

    def service(self, key, default=None):
        return self.services.get(key, default)

    def load_ui(self, ui_filename, *, module_name=None):
        self.ui = load_ui_for_owner(self, ui_filename, module_name=module_name)
        return self.ui


class HydeDialogWidget(HydeDialog):
    ui_filename = "hyde_dialog_widget.ui"

    def __init__(self, *args, services=None, **kwargs):
        super().__init__(*args, services=services, **kwargs)
        self.shell_ui = load_ui_for_owner(
            self,
            self.ui_filename,
            module_name="hyde.user_interface",
        )
        self.mounted_child = None
        self.lower_text_edit.setReadOnly(True)
        self.do_it_button.clicked.connect(self.handle_do_it)
        self.to_cmd_line_button.clicked.connect(self.send_to_cmd_line)
        self.to_clip_button.clicked.connect(self.copy_to_clip)
        self.help_button.clicked.connect(self.handle_help)
        self.cancel_button.clicked.connect(self.reject)
        self.refresh_shell()

    def mount_content_widget(self, child):
        if self.mounted_child is child:
            return child
        if self.mounted_child is not None:
            self.content_layout.removeWidget(self.mounted_child)
            self.mounted_child.setParent(None)
        self.content_layout.addWidget(child)
        self.mounted_child = child
        return child

    def load_ui(self, ui_filename, *, module_name=None):
        content = load_ui_for_owner(
            QtWidgets.QWidget(self),
            ui_filename,
            module_name=module_name,
        )
        self.ui = content
        self.mount_content_widget(content)
        return content

    def canonical_text_payload(self):
        return ""

    def can_do_it(self):
        return True

    def can_send_to_cmd_line(self):
        return False

    def can_show_help(self):
        return False

    def handle_do_it(self):
        self.accept()

    def handle_help(self):
        return None

    def copy_to_clip(self):
        payload = self.canonical_text_payload() or ""
        if not payload:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(payload)

    def send_to_cmd_line(self):
        payload = self.canonical_text_payload() or ""
        if not payload:
            return
        visible_terminal_service = self.service("visible_terminal_service")
        if visible_terminal_service is None:
            return
        visible_terminal_service.execute_visible(payload)

    def refresh_shell(self):
        payload = self.canonical_text_payload() or ""
        self.lower_text_edit.setPlainText(payload)
        self.do_it_button.setEnabled(self.can_do_it())
        self.to_cmd_line_button.setEnabled(bool(payload) and self.can_send_to_cmd_line())
        self.to_clip_button.setEnabled(bool(payload))
        self.help_button.setEnabled(self.can_show_help())


def active_interactive_window(services, interactive_type=None):
    mdi_area = None if services is None else services.get("mdi_area")
    if mdi_area is None:
        return None
    subwindow = mdi_area.activeSubWindow()
    widget = None if subwindow is None else subwindow.widget()
    if not isinstance(widget, HydeInteractiveWidget):
        return None
    if interactive_type is not None and not isinstance(widget, interactive_type):
        return None
    return widget


def freeze_namespace_tracking_value(value):
    if isinstance(value, dict):
        return tuple(
            (str(key), freeze_namespace_tracking_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_namespace_tracking_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(freeze_namespace_tracking_value(item) for item in value))
    return value


def tracked_namespace_signature(view, names):
    tracked = []
    view = dict(view or {})
    for name in names:
        metadata = dict(view.get(name, {}) or {})
        tracked.append((name, freeze_namespace_tracking_value(metadata)))
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
        self._tracked_namespace_state = ()

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
        from hyde.user_interface.shared.plugin import capture_subwindow_geometry

        self._last_normal_geometry = tuple(capture_subwindow_geometry(self._subwindow))

    def capture_geometry(self):
        if self._subwindow is None:
            return None
        from hyde.user_interface.shared.plugin import capture_subwindow_geometry

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
        from hyde.user_interface.shared.plugin import capture_saveable_window_state

        return capture_saveable_window_state(self._subwindow)

    def window_handle(self):
        return self.window_identifier()

    def formatted_window_title(self, title_suffix=None, warning_text=None):
        stable_name = str(self.window_handle())
        suffix_text = str(title_suffix).strip() if title_suffix is not None else ""
        base_title = stable_name if not suffix_text else f"{stable_name}: {suffix_text}"
        warning = str(warning_text).strip() if warning_text is not None else ""
        if warning:
            return f"{base_title} [{warning}]"
        return base_title

    def prepare_saveable_state(self):
        capture_layout_state = getattr(self, "capture_layout_state", None)
        if callable(capture_layout_state):
            capture_layout_state()

    def tracked_namespace_names(self):
        return ()

    def tracked_namespace_state_from_view(self, view):
        return tracked_namespace_signature(
            view,
            self.tracked_namespace_names(),
        )

    def current_tracked_namespace_state(self):
        python_variables_service = self.services.get("namespace_view_service")
        if python_variables_service is None:
            return ()
        return self.tracked_namespace_state_from_view(
            python_variables_service.namespace_view()
        )

    def update_tracked_namespace_state(self, view=None):
        if view is None:
            new_state = self.current_tracked_namespace_state()
        else:
            new_state = self.tracked_namespace_state_from_view(view)
        if new_state == self._tracked_namespace_state:
            return False
        self._tracked_namespace_state = new_state
        return True

    def execute_hidden_command(self, code):
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        return bool(python_execution_service.execute_hidden(code))

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
        from hyde.user_interface.shared.plugin import build_window_function_source

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
        from hyde.user_interface.shared.plugin import build_window_restore_source

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
        return super().closeEvent(event)

    def finalize_interactive_close(self, event):
        return self.complete_interactive_close(event)

    def closeEvent(self, event):
        if self.is_close_complete():
            return self.complete_interactive_close(event)
        if QtWidgets.QApplication.keyboardModifiers() == QtCore.Qt.ShiftModifier:
            return self.finalize_interactive_close(event)
        save_window_dialog_service = self.service("save_window_dialog_service")
        if save_window_dialog_service is not None:
            self.prepare_saveable_state()
            should_close = save_window_dialog_service.prompt_to_save_window_macro(
                saveable=self
            )
            if not should_close:
                event.ignore()
                return
        return self.finalize_interactive_close(event)

    def eventFilter(self, watched, event):
        subwindow = getattr(self, "_subwindow", None)
        if watched is not subwindow or event.type() != QtCore.QEvent.Move:
            return super().eventFilter(watched, event)
        if subwindow is not None and not subwindow.isMinimized():
            self._remember_subwindow_geometry()
        return super().eventFilter(watched, event)
