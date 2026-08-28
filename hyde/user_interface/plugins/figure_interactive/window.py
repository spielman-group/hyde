import base64
import copy
import logging

from qtutils import inmain_decorator
from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_ir import (
    FigureIR,
    canonicalize_figure_window_name as _canonicalize_figure_window_name,
    normalize_figure_defaults as _normalize_figure_defaults,
)
from hyde.features.matplotlib_figure_state import FigureIRAuthority
from hyde.features.matplotlib_figure_records import supported_trace_records
from hyde.features.hyde_features import figure_decorator_source
from hyde.user_interface.base_hyde_widgets import HydeInteractiveWidget
from hyde.user_interface.shared.plugin import apply_saveable_window_state
from hyde.user_interface.shared.project import MacroStoreError

LOGGER = logging.getLogger("hyde")


class FigureSnapshotState:
    def __init__(
        self,
        default_macro_name="Figure",
        call_source=None,
        save_error=None,
        figure_size=None,
        tracked_names=None,
        figure_ir=None,
        figure_defaults=None,
        resolved_axis_limits=None,
        trace_styles=None,
    ):
        self._default_macro_name = default_macro_name or "Figure"
        self._tracked_names = ()
        self._figure_ir = None
        self._figure_defaults = None
        self._call_source = None
        self._save_error = None
        self._figure_size = None
        self._trace_styles = {}
        self.update(
            default_macro_name=default_macro_name,
            call_source=call_source,
            save_error=save_error,
            figure_size=figure_size,
            tracked_names=tracked_names,
            figure_ir=figure_ir,
            figure_defaults=figure_defaults,
            resolved_axis_limits=resolved_axis_limits,
            trace_styles=trace_styles,
        )

    def update(
        self,
        default_macro_name=None,
        call_source=None,
        save_error=None,
        figure_size=None,
        tracked_names=None,
        figure_ir=None,
        figure_defaults=None,
        resolved_axis_limits=None,
        trace_styles=None,
    ):
        self._figure_ir = copy.deepcopy(figure_ir)
        self._figure_defaults = _normalize_figure_defaults(figure_defaults)
        self._resolved_axis_limits = copy.deepcopy(resolved_axis_limits) or {}
        if default_macro_name:
            self._default_macro_name = str(default_macro_name)
        elif self._figure_ir is not None:
            title = FigureIRAuthority.validate_state(self._figure_ir)["settings"]["title"]
            if title:
                self._default_macro_name = title
        self._call_source = call_source
        if not self._call_source and self._figure_ir is not None:
            current_ir = FigureIR(
                figure_state=self._figure_ir,
                figure_defaults=self._figure_defaults,
            )
            self._call_source = current_ir.python_source(log=False)
        if tracked_names:
            self._tracked_names = tuple(tracked_names)
        elif self._figure_ir is not None:
            self._tracked_names = FigureIR(
                figure_state=self._figure_ir,
                figure_defaults=self._figure_defaults,
            ).tracked_names()
        else:
            self._tracked_names = ()
        self._save_error = save_error
        self._figure_size = None if figure_size is None else tuple(figure_size)
        self._trace_styles = copy.deepcopy(trace_styles) or {}

    def default_macro_name(self):
        return self._default_macro_name

    def call_source(self):
        return self._call_source

    def figure_size(self):
        return self._figure_size

    def tracked_names(self):
        return self._tracked_names

    def figure_ir(self):
        return copy.deepcopy(self._figure_ir)

    def figure_defaults(self):
        return copy.deepcopy(self._figure_defaults)

    def resolved_axis_limits(self):
        return copy.deepcopy(self._resolved_axis_limits)

    def has_save_warning(self):
        return bool(self._save_error)

    def window_warning_text(self):
        if not self._save_error:
            return None
        if "unsupported" in str(self._save_error).lower():
            return "Unsupported Feature"
        return "Macro Incomplete"

    def window_warning_message(self):
        warning_text = self.window_warning_text()
        if warning_text is None:
            return ""
        return f"{warning_text}: {self._save_error}"

    def trace_styles(self):
        return copy.deepcopy(self._trace_styles)

    def macro_source(self, macro_name, figure_title=None):
        if self._save_error and self._figure_ir is None:
            raise MacroStoreError(self._save_error)
        if self._figure_ir is not None:
            return FigureIR(
                figure_state=self._figure_ir,
                figure_defaults=self._figure_defaults,
            ).recreation_function_source(
                macro_name,
                name=figure_title,
            )
        if not self._call_source:
            raise MacroStoreError("This figure does not have a saveable recreation macro yet.")
        body = "\n".join(f"    {line}" for line in self._call_source.splitlines())
        return (
            f"{figure_decorator_source()}\n"
            f"def {macro_name}():\n"
            f"{body}\n"
            "    return fig\n"
        )


class FigureWindow(HydeInteractiveWidget):
    REFRESH_TIMEOUT_MS = 5000
    CLOSE_TIMEOUT_MS = 5000

    def __init__(self, figure_number, services=None, parent=None):
        self.figure_number = int(figure_number)
        super().__init__(
            services=services,
            initial_window_name=f"Figure{self.figure_number}",
            parent=parent,
        )
        self._closed = False
        self._kernel_close_in_progress = False
        self._closing_from_kernel = False
        self._pixmap = None
        self._initial_size_applied = False
        self._pending_window_pos = None
        self._pending_window_state = None
        self._refresh_in_flight = False
        self._refresh_requested = False
        self._refresh_timeout_timer = QtCore.QTimer(self)
        self._refresh_timeout_timer.setSingleShot(True)
        self._refresh_timeout_timer.timeout.connect(self._on_refresh_timeout)
        self._resize_redraw_timer = QtCore.QTimer(self)
        self._resize_redraw_timer.setSingleShot(True)
        self._resize_redraw_timer.timeout.connect(self._on_resize_redraw_timeout)
        self._close_timeout_timer = QtCore.QTimer(self)
        self._close_timeout_timer.setSingleShot(True)
        self._close_timeout_timer.timeout.connect(self._on_close_timeout)
        self.snapshot_state = FigureSnapshotState(
            default_macro_name=f"Figure{self.figure_number}"
        )

        content = QtWidgets.QWidget(self.ui.content_widget)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.warning_label = QtWidgets.QLabel(content)
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        self.warning_label.setStyleSheet(
            "QLabel {"
            " background: #fff3cd;"
            " color: #5c4400;"
            " border: 1px solid #e0c46c;"
            " border-radius: 4px;"
            " padding: 6px 8px;"
            "}"
        )
        layout.addWidget(self.warning_label)
        self.image_label = QtWidgets.QLabel(content)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setMinimumSize(240, 180)
        self.image_label.setBackgroundRole(QtGui.QPalette.Base)
        self.image_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        layout.addWidget(self.image_label)
        self.mount_child_widget(content)

        python_variables_service = self.services.get("namespace_view_service")
        if python_variables_service is not None:
            python_variables_service.connect_namespace_view_updated(
                self._on_namespace_view_updated
            )

    def bind_subwindow(self, subwindow, stable_name=None):
        resolved_name = _canonicalize_figure_window_name(
            stable_name
            if stable_name is not None
            else self.read_subwindow_identifier(subwindow),
            self.figure_number,
        )
        super().bind_subwindow(subwindow, stable_name=resolved_name)

    @property
    def current_ir(self):
        return self.widget_ir

    def update_payload(self, payload):
        snapshot = dict(payload.get("snapshot", {}) or {})
        self.widget_ir = FigureIR.from_snapshot(snapshot)
        self.snapshot_state.update(
            default_macro_name=snapshot.get("default_macro_name"),
            call_source=snapshot.get("call_source"),
            save_error=snapshot.get("save_error"),
            figure_size=snapshot.get("figure_size"),
            tracked_names=snapshot.get("tracked_names"),
            figure_ir=snapshot.get("figure_ir"),
            figure_defaults=snapshot.get("figure_defaults"),
            resolved_axis_limits=snapshot.get("resolved_axis_limits"),
            trace_styles=snapshot.get("trace_styles"),
        )
        if self._subwindow is not None:
            self._subwindow.setWindowTitle(
                self._visible_window_title()
            )
        warning_message = self.snapshot_state.window_warning_message()
        self.warning_label.setVisible(bool(warning_message))
        self.warning_label.setText(warning_message)
        self._tracked_namespace_state = self.current_tracked_namespace_state()

        image_base64 = payload.get("image_png_base64")
        if image_base64:
            png_bytes = base64.b64decode(image_base64.encode("ascii"))
            image = QtGui.QImage.fromData(png_bytes, "PNG")
            if not image.isNull():
                self._pixmap = QtGui.QPixmap.fromImage(image)
                self._clear_refresh_in_flight()
                self._update_scaled_pixmap()
                if not self._initial_size_applied:
                    self._apply_initial_subwindow_size()
                    self._initial_size_applied = True
                    self._apply_pending_window_state()
                if self._refresh_requested and not self._closed:
                    self._refresh_requested = False
                    self.refresh_figure()
        elif not self._initial_size_applied and self.snapshot_state.figure_size() is not None:
            self._apply_initial_subwindow_size()
            self._initial_size_applied = True
            self._apply_pending_window_state()

    def apply_window_metadata(self, metadata):
        metadata = dict(metadata or {})
        self.apply_window_pos(metadata.get("window_pos"))
        self.apply_window_state(metadata.get("window_state"))

    def apply_window_pos(self, window_pos):
        if self._subwindow is None or not window_pos or len(window_pos) != 2:
            return
        normalized = (int(window_pos[0]), int(window_pos[1]))
        if not self._initial_size_applied:
            self._pending_window_pos = normalized
        self._subwindow.move(*normalized)
        self._remember_subwindow_geometry()

    def apply_window_state(self, window_state):
        if self._subwindow is None or window_state is None:
            return
        if not self._initial_size_applied:
            self._pending_window_state = window_state
            return
        apply_saveable_window_state(self._subwindow, window_state)

    def _apply_pending_window_state(self):
        if self._subwindow is None:
            return
        if self._pending_window_pos is not None:
            self._subwindow.move(*self._pending_window_pos)
            self._pending_window_pos = None
        if self._pending_window_state is not None:
            apply_saveable_window_state(self._subwindow, self._pending_window_state)
            self._pending_window_state = None

    def _apply_initial_subwindow_size(self):
        if self._subwindow is None:
            return
        figure_size = self.snapshot_state.figure_size()
        if figure_size is None:
            if self._pixmap is None:
                return
            target_size = self._pixmap.size()
        else:
            target_size = QtCore.QSize(*figure_size)
        frame_size = self._subwindow.size() - self._subwindow.contentsRect().size()
        mdi_area = self._subwindow.mdiArea()
        if mdi_area is not None:
            viewport_size = mdi_area.viewport().size()
            available_size = QtCore.QSize(
                max(160, viewport_size.width() - max(0, frame_size.width())),
                max(120, viewport_size.height() - max(0, frame_size.height())),
            )
            if (
                target_size.width() > available_size.width()
                or target_size.height() > available_size.height()
            ):
                target_size.scale(available_size, QtCore.Qt.KeepAspectRatio)
        self._subwindow.resize(
            target_size.width() + max(0, frame_size.width()),
            target_size.height() + max(0, frame_size.height()),
        )
        self._remember_subwindow_geometry()

    def _update_scaled_pixmap(self):
        if self._pixmap is None:
            self.image_label.clear()
            return
        label_size = self.image_label.contentsRect().size()
        if label_size.isEmpty():
            return
        scaled = self._pixmap.scaled(
            label_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled_pixmap()
        if not self._closed:
            self._resize_redraw_timer.start(150)

    def contextMenuEvent(self, event):
        if not self.activate_popup_menu("figure", event.globalPos()):
            return super().contextMenuEvent(event)

    def request_resize_redraw(self, width=None, height=None):
        if width is None or height is None:
            target_size = self.image_label.contentsRect().size()
            width = target_size.width()
            height = target_size.height()
        if int(width) <= 0 or int(height) <= 0:
            return False
        return self.request_figure_action(
            {
                "type": "resize_redraw",
                "width": int(width),
                "height": int(height),
            }
        )

    def request_figure_action(self, action):
        figure_action_service = self.services.get("figure_action_service")
        if figure_action_service is None:
            return False
        return bool(
            figure_action_service.request_figure_action(
                self.figure_number,
                dict(action or {}),
            )
        )

    def figure_ir(self):
        if self.current_ir is None:
            return None
        return self.current_ir.normalized_state()

    def figure_defaults(self):
        if self.current_ir is None:
            return self.snapshot_state.figure_defaults()
        return copy.deepcopy(self.current_ir.figure_defaults)

    def resolved_axis_limits(self):
        return self.snapshot_state.resolved_axis_limits()

    def trace_styles(self):
        return self.snapshot_state.trace_styles()

    def has_figure_ir(self):
        return self.figure_ir() is not None

    def can_request_figure_actions(self):
        return self.services.get("figure_action_service") is not None

    def is_editable_figure_ready(self):
        return self.has_figure_ir()

    def supported_trace_records(self):
        return supported_trace_records(self.figure_ir())

    def has_supported_traces(self):
        return bool(self.supported_trace_records())

    def _visible_title_name(self):
        if self.current_ir is not None:
            return self.current_ir.default_macro_name()
        return self.snapshot_state.default_macro_name() or self.window_handle()

    def _visible_trace_title_suffix(self):
        return ", ".join(
            record["display_name"] for record in self.supported_trace_records()
        )

    def _visible_window_title(self):
        return self.formatted_window_title(
            title_name=self._visible_title_name(),
            title_suffix=self._visible_trace_title_suffix(),
            warning_text=self.snapshot_state.window_warning_text(),
        )

    def request_regenerate_from_ir(self):
        if not self.has_figure_ir():
            return False
        return self._execute_refresh_command(use_bound_values=True)

    @inmain_decorator()
    def _on_resize_redraw_timeout(self):
        if self._closed:
            return
        if not self._initial_size_applied:
            return
        self.request_resize_redraw()

    def tracked_namespace_names(self):
        if self.current_ir is not None:
            return self.current_ir.tracked_names()
        return self.snapshot_state.tracked_names()

    def refresh_figure(self):
        if self._closed:
            return False
        if not self.snapshot_state.tracked_names():
            return False
        if self._refresh_in_flight:
            self._refresh_requested = True
            return False
        if not self.has_figure_ir():
            return False
        self._refresh_in_flight = True
        self._refresh_requested = False
        requested = self._execute_refresh_command(use_bound_values=False)
        if requested:
            self._refresh_timeout_timer.start(self.REFRESH_TIMEOUT_MS)
            return True
        self._clear_refresh_in_flight()
        return False

    def _execute_refresh_command(self, *, use_bound_values):
        figure_name = (
            self.current_ir.default_macro_name()
            if self.current_ir is not None
            else self.snapshot_state.default_macro_name() or self.window_handle()
        )
        command_ir = (
            FigureIR()
            if self.current_ir is None
            else self.current_ir
        )
        return self.execute_hidden_command(
            command_ir.with_refresh_figure(
                figure_name,
                use_bound_values=use_bound_values,
            ).python_source(log=False)
        )

    def _clear_refresh_in_flight(self):
        self._refresh_timeout_timer.stop()
        self._refresh_in_flight = False

    @inmain_decorator()
    def _on_refresh_timeout(self):
        if self._closed or not self._refresh_in_flight:
            return
        self._clear_refresh_in_flight()
        if self._refresh_requested and not self._closed:
            self._refresh_requested = False
            self.refresh_figure()

    def _on_namespace_view_updated(self, view):
        if self._closed:
            return
        if not self.update_tracked_namespace_state(view or {}):
            return
        self.refresh_figure()

    def close_from_kernel(self):
        if self._closed or self._closing_from_kernel:
            return
        LOGGER.debug(
            "Figure window %s received kernel close confirmation.",
            self.figure_number,
        )
        self._close_timeout_timer.stop()
        self._kernel_close_in_progress = False
        self._closing_from_kernel = True
        if self._subwindow is not None:
            self._subwindow.close()
        else:
            self.close()

    def force_close(self):
        self._closing_from_kernel = True
        self._kernel_close_in_progress = False
        self.close_from_kernel()

    def saveable_default_macro_name(self):
        if self.current_ir is not None:
            return self.current_ir.default_macro_name()
        return self.snapshot_state.default_macro_name()

    def saveable_decorator_name(self):
        return figure_decorator_source()

    def macro_definition_source(self, macro_name, *, handle):
        if self.current_ir is not None:
            return self.current_ir.recreation_function_source(
                macro_name,
                name=handle,
            )
        return self.snapshot_state.macro_source(macro_name, figure_title=handle)

    def session_restore_definition_source(self, handle):
        if self.current_ir is not None:
            return self.current_ir.recreation_function_source(
                handle,
                name=handle,
                register=False,
            )
        return self.snapshot_state.macro_source(handle, figure_title=handle)

    def session_restore_warning(self):
        message = self.snapshot_state.window_warning_message()
        if not message:
            return None
        return f"{self.window_handle()}: {message}"

    def session_restore_arguments(self):
        if self.current_ir is not None:
            return self.current_ir.tracked_names()
        return self.snapshot_state.tracked_names()

    def macro_window_metadata(self, geometry, window_state):
        return {
            "window_pos": None if geometry is None else tuple(geometry[:2]),
            "window_state": None if window_state == "minimized" else window_state,
        }

    def session_restore_window_metadata(self, geometry, window_state):
        if geometry is None:
            return None
        return {
            "window_pos": tuple(geometry[:2]),
            "window_state": window_state,
        }

    def closeEvent(self, event):
        if self._kernel_close_in_progress:
            LOGGER.debug(
                "Figure window %s ignored duplicate close while waiting for kernel confirmation.",
                self.figure_number,
            )
            event.ignore()
            return
        return super().closeEvent(event)

    def is_close_complete(self):
        return self._closed or self._closing_from_kernel

    def complete_interactive_close(self, event):
        self._closed = True
        self._disconnect_namespace_updates()
        return super().complete_interactive_close(event)

    def finalize_interactive_close(self, event):
        get_shutting_down = self.service("get_shutting_down")
        if get_shutting_down is not None and get_shutting_down():
            self.complete_interactive_close(event)
            return
        self._kernel_close_in_progress = True
        command_ir = FigureIR() if self.current_ir is None else self.current_ir
        if not self.execute_hidden_command(
            command_ir.with_close_figure(self.figure_number).python_source(log=False)
        ):
            self._kernel_close_in_progress = False
            LOGGER.warning(
                "Figure window %s failed to queue kernel close command.",
                self.figure_number,
            )
            event.ignore()
            return
        LOGGER.debug(
            "Figure window %s queued kernel close command and is awaiting confirmation.",
            self.figure_number,
        )
        self._close_timeout_timer.start(self.CLOSE_TIMEOUT_MS)
        event.ignore()

    @inmain_decorator()
    def _on_close_timeout(self):
        if self._closed:
            return
        LOGGER.warning(
            "Figure window %s close confirmation timed out; window remains open.",
            self.figure_number,
        )
        self._kernel_close_in_progress = False

    def _disconnect_namespace_updates(self):
        self._refresh_timeout_timer.stop()
        self._resize_redraw_timer.stop()
        self._close_timeout_timer.stop()
        try:
            python_variables_service = self.services.get("namespace_view_service")
            if python_variables_service is not None:
                python_variables_service.disconnect_namespace_view_updated(
                    self._on_namespace_view_updated
                )
        except Exception:
            pass
