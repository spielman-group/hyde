import os
import sys

from qtutils import UiLoader
from qtutils.qt import QtCore, QtWidgets
from qtutils.qt.QtCore import QUrl
from qtutils.qt.QtGui import QDesktopServices


def resolve_owner_path(owner, filename, *, module_name=None):
    resolved_module_name = module_name or type(owner).__module__
    module = sys.modules[resolved_module_name]
    module_file = module.__file__
    return os.path.join(os.path.dirname(module_file), filename)


def load_ui_for_owner(owner, ui_filename, *, module_name=None):
    ui_path = resolve_owner_path(owner, ui_filename, module_name=module_name)
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

    def execute_hidden_command(self, code):
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        return bool(python_execution_service.execute_hidden(code))

    def load_ui(self, ui_filename, *, module_name=None):
        self.ui = load_ui_for_owner(self, ui_filename, module_name=module_name)
        return self.ui


class HydeDialogWidget(HydeDialog):
    ui_filename = "hyde_dialog_widget.ui"
    help_filename = None

    def __init__(self, *args, services=None, **kwargs):
        super().__init__(*args, services=services, **kwargs)
        self.shell_ui = load_ui_for_owner(
            self,
            self.ui_filename,
            module_name="hyde.user_interface",
        )
        self.mounted_child = None
        self._mounted_content_rows = {}
        self._preview_string = ""
        self._preview_display_text = None
        self.lower_text_edit.setReadOnly(True)
        self.do_it_button.setDefault(True)
        self.do_it_button.setAutoDefault(True)
        self.cancel_button.setAutoDefault(False)
        self.do_it_button.clicked.connect(self.handle_do_it)
        self.to_cmd_line_button.clicked.connect(self.send_to_cmd_line)
        self.to_clip_button.clicked.connect(self.copy_to_clip)
        self.help_button.clicked.connect(self.handle_help)
        self.cancel_button.clicked.connect(self.reject)
        self.refresh_shell()

    def _refresh_content_rows(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for row in sorted(self._mounted_content_rows):
            self.content_layout.addWidget(self._mounted_content_rows[row])
        self.mounted_child = self._mounted_content_rows.get(0)

    def mount_content_widget(self, child, *, row=0):
        row = int(row)
        if row < 0:
            raise ValueError("row must be >= 0")
        if self._mounted_content_rows.get(row) is child:
            return child
        for existing_row, existing_widget in list(self._mounted_content_rows.items()):
            if existing_widget is child:
                del self._mounted_content_rows[existing_row]
                break
        self._mounted_content_rows[row] = child
        self._refresh_content_rows()
        return child

    def load_ui(self, ui_filename, *, module_name=None, row=0):
        content = load_ui_for_owner(
            QtWidgets.QWidget(self),
            ui_filename,
            module_name=module_name,
        )
        self.ui = content
        self.mount_content_widget(content, row=row)
        return content

    def preview_string(self):
        return self._preview_string

    def preview_display_text(self):
        if self._preview_display_text is None:
            return self.preview_string()
        return self._preview_display_text

    def set_preview_string(self, payload, *, display_text=None):
        self._preview_string = str(payload or "")
        self._preview_display_text = (
            None if display_text is None else str(display_text or "")
        )
        return self.preview_string()

    def set_preview_message(self, message):
        self.set_preview_string("", display_text=message)
        return self.preview_display_text()

    def can_do_it(self):
        return bool(self.preview_string())

    def can_send_to_cmd_line(self):
        return self.service("visible_terminal_service") is not None

    def can_show_help(self):
        return self.resolved_help_path() is not None

    def do_it_dispatch_mode(self):
        return "hidden"

    def execute_do_it_payload(self, payload):
        python_execution_service = self.service("python_execution_service")
        if python_execution_service is None:
            return False
        if self.do_it_dispatch_mode() == "visible":
            return bool(python_execution_service.execute_visible(payload))
        return bool(python_execution_service.execute_hidden(payload))

    def dispatch_do_it_payload(
        self,
        payload=None,
        *,
        executor=None,
        accept_on_success=True,
    ):
        resolved_payload = self.preview_string() if payload is None else payload
        if not str(resolved_payload or "").strip():
            return False
        dispatch = self.execute_do_it_payload if executor is None else executor
        if not dispatch(resolved_payload):
            return False
        if accept_on_success:
            self.accept()
        return True

    def resolved_help_path(self):
        help_filename = str(self.help_filename or "").strip()
        if not help_filename:
            return None
        help_path = resolve_owner_path(self, help_filename)
        if not os.path.isfile(help_path):
            return None
        return help_path

    def handle_do_it(self):
        self.dispatch_do_it_payload()

    def handle_help(self):
        help_path = self.resolved_help_path()
        if help_path is None:
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(help_path)))

    def copy_to_clip(self):
        payload = self.preview_string()
        if not payload:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(payload)

    def send_to_cmd_line(self):
        payload = self.preview_string()
        if not payload:
            return
        visible_terminal_service = self.service("visible_terminal_service")
        if visible_terminal_service is None:
            return
        visible_terminal_service.execute_visible(payload)

    def refresh_shell(self):
        payload = self.preview_string()
        self.lower_text_edit.setPlainText(self.preview_display_text())
        self.do_it_button.setEnabled(self.can_do_it())
        self.to_cmd_line_button.setEnabled(bool(payload) and self.can_send_to_cmd_line())
        self.to_clip_button.setEnabled(bool(payload))
        self.help_button.setEnabled(self.can_show_help())


class HydeFileWidget(QtWidgets.QFileDialog):
    selection_changed = QtCore.Signal()

    def __init__(
        self,
        selection_mode="file",
        require_existing=False,
        allowed_suffixes=(),
        name_filters=(),
        initial_path=None,
        parent=None,
        **kwargs,
    ):
        self.selection_mode = str(selection_mode)
        self.require_existing = bool(require_existing)
        self.allowed_suffixes = tuple(
            suffix.lower()
            for suffix in allowed_suffixes
            if str(suffix or "").strip()
        )
        self.name_filters = tuple(
            str(name_filter)
            for name_filter in name_filters
            if str(name_filter or "").strip()
        )
        self.initial_path = (
            None if initial_path is None else os.path.abspath(str(initial_path))
        )
        super().__init__(parent, "", self.initial_directory(), **kwargs)
        self.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        self.setAcceptMode(QtWidgets.QFileDialog.AcceptOpen)
        self.setOption(QtWidgets.QFileDialog.DontConfirmOverwrite, True)
        self.configure_file_dialog()
        if self.name_filters:
            self.setNameFilters(list(self.name_filters))
        self.hide_dialog_buttons()

        self.file_name_edit = self.findChild(
            QtWidgets.QLineEdit,
            "fileNameEdit",
        )
        if self.file_name_edit is not None:
            self.file_name_edit.textChanged.connect(self.emit_selection_changed)
        self.currentChanged.connect(lambda _path: self.emit_selection_changed())
        self.directoryEntered.connect(lambda _path: self.emit_selection_changed())

        if self.initial_path:
            self.set_selected_path(self.initial_path)
        else:
            self.emit_selection_changed()

    def initial_directory(self):
        initial_path = self.initial_path
        if not initial_path:
            return ""
        return os.path.dirname(initial_path) or initial_path

    def configure_file_dialog(self):
        if self.selection_mode == "directory":
            self.setFileMode(QtWidgets.QFileDialog.Directory)
            self.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
            return
        if self.selection_mode == "file":
            self.setFileMode(
                QtWidgets.QFileDialog.ExistingFile
                if self.require_existing
                else QtWidgets.QFileDialog.AnyFile
            )
            return
        raise ValueError(f"Unsupported selection_mode: {self.selection_mode!r}")

    def hide_dialog_buttons(self):
        for button_box in self.findChildren(QtWidgets.QDialogButtonBox):
            button_box.hide()

    def emit_selection_changed(self):
        self.selection_changed.emit()

    def accept(self):
        self.emit_selection_changed()
        parent = self.outer_dialog(HydeDialogWidget)
        if parent is not None and parent.do_it_button.isEnabled():
            parent.do_it_button.click()

    def outer_dialog(self, dialog_type):
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, dialog_type):
            parent = parent.parentWidget()
        return parent

    def reject(self):
        parent = self.outer_dialog(QtWidgets.QDialog)
        if parent is not None:
            parent.reject()
            return
        super().reject()

    def set_selected_path(self, path):
        if path is None:
            return None
        normalized_path = os.path.abspath(str(path))
        parent_dir = os.path.dirname(normalized_path)
        if parent_dir:
            self.setDirectory(parent_dir)
        self.selectFile(normalized_path)
        if self.file_name_edit is not None:
            self.file_name_edit.setText(os.path.basename(normalized_path))
        self.emit_selection_changed()
        return normalized_path

    def set_selection_policy(
        self,
        *,
        allowed_suffixes=None,
        name_filters=None,
        selected_name_filter=None,
    ):
        if allowed_suffixes is not None:
            self.allowed_suffixes = tuple(
                suffix.lower()
                for suffix in allowed_suffixes
                if str(suffix or "").strip()
            )
        if name_filters is not None:
            self.name_filters = tuple(
                str(name_filter)
                for name_filter in name_filters
                if str(name_filter or "").strip()
            )
            if self.name_filters:
                self.setNameFilters(list(self.name_filters))
        if selected_name_filter:
            self.selectNameFilter(str(selected_name_filter))
        elif self.name_filters:
            self.selectNameFilter(self.name_filters[0])

    def selected_path(self):
        if self.file_name_edit is not None:
            text = self.file_name_edit.text().strip()
            if text:
                return os.path.abspath(self.directory().absoluteFilePath(text))
        selected_files = self.selectedFiles()
        if selected_files:
            return os.path.abspath(selected_files[0])
        return None

    def validation_error(self, path=None):
        selected_path = self.selected_path() if path is None else os.path.abspath(str(path))
        if not selected_path:
            return "Select a target."
        if self.allowed_suffixes and not selected_path.lower().endswith(
            self.allowed_suffixes
        ):
            allowed = ", ".join(self.allowed_suffixes)
            return f"Target must end with {allowed}."
        if self.require_existing and not os.path.exists(selected_path):
            return f"{selected_path} does not exist."
        if self.selection_mode == "directory":
            if os.path.exists(selected_path) and not os.path.isdir(selected_path):
                return f"{selected_path} is not a directory."
            return None
        if os.path.exists(selected_path) and os.path.isdir(selected_path):
            return f"{selected_path} is a directory."
        return None


class HydeFileDialog(HydeDialogWidget):
    selection_mode = "file"
    require_existing = False
    allowed_suffixes = ()
    name_filters = ()
    confirm_overwrite = False
    create_suggested_directory = False

    def __init__(self, *args, services=None, **kwargs):
        super().__init__(*args, services=services, **kwargs)
        suggested_path = self.suggested_path()
        self._create_suggested_directory_for_path(suggested_path)
        self.file_widget = HydeFileWidget(
            selection_mode=self.selection_mode,
            require_existing=self.require_existing,
            allowed_suffixes=self.allowed_suffixes,
            name_filters=self.name_filters,
            initial_path=suggested_path,
            parent=self,
        )
        self.mount_content_widget(self.file_widget, row=0)
        self.file_widget.selection_changed.connect(self.refresh_from_file_selection)
        self.refresh_from_file_selection()

    def suggested_path(self):
        return None

    def _create_suggested_directory_for_path(self, suggested_path):
        if not self.create_suggested_directory or not suggested_path:
            return None
        normalized_path = os.path.abspath(str(suggested_path))
        if self.selection_mode == "directory":
            directory_path = normalized_path
        else:
            directory_path = os.path.dirname(normalized_path) or None
        if not directory_path:
            return None
        try:
            os.makedirs(directory_path, exist_ok=True)
        except OSError:
            return None
        return directory_path

    def selected_path(self):
        return self.file_widget.selected_path()

    def build_preview_state(self, selected_path):
        del selected_path
        return None

    def selection_validation_message(self, selected_path):
        del selected_path
        return None

    def validation_message(self, selected_path):
        error_message = self.file_widget.validation_error(selected_path)
        if error_message is None:
            error_message = self.selection_validation_message(selected_path)
        return error_message

    def refresh_from_file_selection(self):
        selected_path = self.selected_path()
        error_message = self.validation_message(selected_path)
        if error_message is not None:
            self.set_preview_message(error_message)
            self.refresh_shell()
            return selected_path
        preview_state = self.build_preview_state(selected_path)
        payload = "" if preview_state is None else preview_state.python_source(log=False)
        self.set_preview_string(payload)
        self.refresh_shell()
        return selected_path

    def needs_overwrite_confirmation(self, selected_path):
        return bool(
            self.confirm_overwrite
            and selected_path
            and os.path.exists(selected_path)
        )

    def overwrite_confirmation_title(self, selected_path):
        del selected_path
        return "Overwrite Existing Target"

    def overwrite_confirmation_message(self, selected_path):
        return f"{selected_path} already exists. Overwrite it?"

    def confirm_overwrite_target(self, selected_path):
        response = QtWidgets.QMessageBox.question(
            self,
            self.overwrite_confirmation_title(selected_path),
            self.overwrite_confirmation_message(selected_path),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def handle_do_it(self):
        selected_path = self.selected_path()
        validation_message = self.validation_message(selected_path)
        if validation_message is not None:
            return False
        if self.needs_overwrite_confirmation(selected_path) and not self.confirm_overwrite_target(
            selected_path
        ):
            return False
        return self.dispatch_do_it_payload()


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

    def formatted_window_title(
        self,
        title_suffix=None,
        warning_text=None,
        title_name=None,
    ):
        stable_name = str(self.window_handle())
        visible_name = str(title_name).strip() if title_name is not None else stable_name
        if not visible_name:
            visible_name = stable_name
        suffix_text = str(title_suffix).strip() if title_suffix is not None else ""
        base_title = visible_name if not suffix_text else f"{visible_name}: {suffix_text}"
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
