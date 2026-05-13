import base64
import copy
import logging
import re

from qtutils import inmain_decorator
from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_features import (
    FigureCodec,
    FigureIRCodec,
    figure_ir_apply_title,
)
from hyde.user_interface.base import HydeGuiState
from hyde.user_interface.namespace_tracking import tracked_namespace_signature
from hyde.user_interface.plugin_tools import (
    apply_saveable_window_state,
    build_window_function_source,
    build_window_restore_source,
    capture_saveable_window_state,
    capture_subwindow_geometry,
)
from hyde.user_interface.window_naming import (
    bind_stable_window_name,
    stable_window_name,
    window_title,
)
from hyde.user_interface.window_macro_store import MacroStoreError

LOGGER = logging.getLogger("hyde")
_DEFAULT_FIGURE_LABEL_RE = re.compile(r"^Figure\s+(\d+)$")


def _canonicalize_figure_window_name(name, fallback_number):
    text = str(name or "").strip()
    if not text:
        return f"Figure{int(fallback_number)}"
    match = _DEFAULT_FIGURE_LABEL_RE.fullmatch(text)
    if match is not None:
        return f"Figure{match.group(1)}"
    return text


class FigureState(HydeGuiState):
    codec = FigureCodec

    def configure_defaults(self):
        self.set_command("create")

    def _temporary_state(self, command=None, **settings):
        state = self.normalized_state()
        if command is not None:
            state["settings"]["command"] = command
        state["settings"].update(settings)
        return state

    def set_command(self, command):
        self.apply_action({"type": "set_command", "command": command})

    def set_items(self, names):
        self.apply_action({"type": "replace_items", "items": list(names)})

    def set_title(self, title):
        if title:
            self.apply_action(
                {"type": "set", "path": ("settings", "title"), "value": title}
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "title")})

    def set_x_name(self, x_name):
        if x_name:
            self.apply_action(
                {"type": "set", "path": ("settings", "x_name"), "value": x_name}
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "x_name")})

    def set_figsize(self, width, height):
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "figsize"),
                "value": (float(width), float(height)),
            }
        )

    def source_for_command(self, command, **settings):
        return self.codec.state_to_python(
            self._temporary_state(command=command, **settings)
        )

    def default_macro_name(self):
        settings = self.normalized_state()["settings"]
        return settings["title"] or "Figure"


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
        live_state=None,
        trace_styles=None,
    ):
        self._default_macro_name = default_macro_name or "Figure"
        self._tracked_names = ()
        self._figure_ir = None
        self._figure_defaults = None
        self._call_source = None
        self._save_error = None
        self._figure_size = None
        self._live_state = None
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
            live_state=live_state,
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
        live_state=None,
        trace_styles=None,
    ):
        self._figure_ir = copy.deepcopy(figure_ir)
        self._figure_defaults = copy.deepcopy(figure_defaults)
        self._resolved_axis_limits = copy.deepcopy(resolved_axis_limits) or {}
        if default_macro_name:
            self._default_macro_name = str(default_macro_name)
        elif self._figure_ir is not None:
            title = FigureIRCodec.normalize_state(self._figure_ir)["settings"]["title"]
            if title:
                self._default_macro_name = title
        self._call_source = call_source
        if not self._call_source and self._figure_ir is not None:
            self._call_source = FigureIRCodec.state_to_python(
                self._figure_ir,
                context={"figure_defaults": self._figure_defaults},
            )
        if tracked_names:
            self._tracked_names = tuple(tracked_names)
        elif self._figure_ir is not None:
            self._tracked_names = FigureIRCodec.tracked_names(self._figure_ir)
        else:
            self._tracked_names = ()
        self._save_error = save_error
        self._figure_size = None if figure_size is None else tuple(figure_size)
        self._live_state = copy.deepcopy(live_state)
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

    def live_state(self):
        return copy.deepcopy(self._live_state)

    def trace_styles(self):
        return copy.deepcopy(self._trace_styles)

    def set_live_state(self, state):
        self._live_state = copy.deepcopy(state)
        if state is None:
            self._tracked_names = ()
            return
        self._tracked_names = FigureCodec.tracked_names(state)
        self._call_source = FigureCodec.state_to_python(state)
        title = FigureCodec.normalize_state(state)["settings"]["title"]
        if title:
            self._default_macro_name = title

    def macro_source(self, macro_name, figure_title=None):
        if self._save_error:
            raise MacroStoreError(self._save_error)
        if self._figure_ir is not None:
            figure_ir = self._figure_ir
            if figure_title not in (None, ""):
                figure_ir = figure_ir_apply_title(figure_ir, figure_title)
            return FigureIRCodec.state_to_macro_source(
                figure_ir,
                macro_name,
                context={"figure_defaults": self._figure_defaults},
            )
        if self._live_state is not None:
            live_state = self._live_state
            if figure_title not in (None, ""):
                live_state = FigureCodec.normalize_state(live_state)
                live_state["settings"]["title"] = str(figure_title)
            return FigureCodec.state_to_macro_source(live_state, macro_name)
        if not self._call_source:
            raise MacroStoreError("This figure does not have a saveable recreation macro yet.")
        body = "\n".join(f"    {line}" for line in self._call_source.splitlines())
        return (
            "@hyde.figure\n"
            f"def {macro_name}():\n"
            f"{body}\n"
            "    return fig\n"
        )
class FigureWindow(QtWidgets.QWidget):
    REFRESH_TIMEOUT_MS = 5000
    CLOSE_TIMEOUT_MS = 5000

    def __init__(self, figure_number, services=None, parent=None):
        super().__init__(parent)
        self.figure_number = int(figure_number)
        self.services = dict(services or {})
        self._subwindow = None
        self._closed = False
        self._kernel_close_in_progress = False
        self._closing_from_kernel = False
        self._pixmap = None
        self._initial_size_applied = False
        self._pending_window_pos = None
        self._pending_window_state = None
        self._last_normal_geometry = None
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
        self._tracked_namespace_state = ()
        self.snapshot_state = FigureSnapshotState(
            default_macro_name=f"Figure{self.figure_number}"
        )
        self.command_state = FigureState()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = QtWidgets.QLabel(self)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setMinimumSize(240, 180)
        self.image_label.setBackgroundRole(QtGui.QPalette.Base)
        self.image_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        layout.addWidget(self.image_label)

        python_variables_service = self.services.get("namespace_view_service")
        if python_variables_service is not None:
            python_variables_service.connect_namespace_view_updated(
                self._on_namespace_view_updated
            )

    def bind_subwindow(self, subwindow, stable_name=None):
        self._subwindow = subwindow
        resolved_name = _canonicalize_figure_window_name(
            stable_name
            if stable_name is not None
            else stable_window_name(subwindow),
            self.figure_number,
        )
        bind_stable_window_name(
            subwindow,
            resolved_name,
        )
        subwindow.installEventFilter(self)
        self._remember_subwindow_geometry()

    def update_payload(self, payload):
        snapshot = dict(payload.get("snapshot", {}) or {})
        self.snapshot_state.update(
            default_macro_name=snapshot.get("default_macro_name"),
            call_source=snapshot.get("call_source"),
            save_error=snapshot.get("save_error"),
            figure_size=snapshot.get("figure_size"),
            tracked_names=snapshot.get("tracked_names"),
            figure_ir=snapshot.get("figure_ir"),
            figure_defaults=snapshot.get("figure_defaults"),
            resolved_axis_limits=snapshot.get("resolved_axis_limits"),
            live_state=snapshot.get("live_state"),
            trace_styles=snapshot.get("trace_styles"),
        )
        if self._subwindow is not None:
            self._subwindow.setWindowTitle(
                window_title(
                    self.window_handle(),
                    warning_text=(
                        "Macro Incomplete"
                        if self.snapshot_state.has_save_warning()
                        else None
                    ),
                )
            )
        self._tracked_namespace_state = self._current_tracked_namespace_state()

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

    def set_live_state(self, state):
        self.snapshot_state.set_live_state(state)
        self._tracked_namespace_state = self._current_tracked_namespace_state()

    def capture_geometry(self):
        if self._subwindow is None:
            return None
        if self._subwindow.isMinimized() and self._last_normal_geometry is not None:
            return list(self._last_normal_geometry)
        return capture_subwindow_geometry(self._subwindow)

    def window_state(self):
        if self._subwindow is None:
            return None
        return capture_saveable_window_state(self._subwindow)

    def _recreation_function_source(
        self,
        macro_name,
        decorator_name,
        register=None,
        window_pos=None,
        window_state=None,
        figure_title=None,
    ):
        return build_window_function_source(
            self.snapshot_state.macro_source(
                macro_name,
                figure_title=figure_title,
            ),
            decorator_name=decorator_name,
            register=register,
            window_pos=window_pos,
            window_state=window_state,
        )

    def session_restore_source(self):
        geometry = self.capture_geometry()
        if geometry is None:
            return None
        handle = self.window_handle()
        return build_window_restore_source(
            self.snapshot_state.macro_source(handle, figure_title=handle),
            handle=handle,
            arguments=self.snapshot_state.tracked_names(),
            decorator_name="@hyde.figure",
            window_pos=tuple(geometry[:2]),
            window_state=self.window_state(),
        )

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

    def eventFilter(self, watched, event):
        subwindow = getattr(self, "_subwindow", None)
        if (
            watched is subwindow
            and event.type() in (QtCore.QEvent.Move, QtCore.QEvent.Resize)
        ):
            self._remember_subwindow_geometry()
        return super().eventFilter(watched, event)

    def contextMenuEvent(self, event):
        mdi_area = self.services.get("mdi_area")
        if mdi_area is not None and self._subwindow is not None:
            mdi_area.setActiveSubWindow(self._subwindow)
        popup_menu = self.services.get("popup_menu")
        if popup_menu is None:
            return super().contextMenuEvent(event)
        popup_menu("figure", event.globalPos())

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
        send_figure_action = self.services.get("send_figure_action")
        if send_figure_action is None:
            return False
        return bool(send_figure_action(self.figure_number, dict(action or {})))

    def request_regenerate_from_ir(self):
        if self.snapshot_state.figure_ir() is None:
            return False
        return self.request_figure_action({"type": "regenerate_from_ir"})

    def request_refresh_from_live_state(self):
        if self.snapshot_state.live_state() is None:
            return False
        return self.request_figure_action({"type": "refresh_from_live_state"})

    @inmain_decorator()
    def _on_resize_redraw_timeout(self):
        if self._closed:
            return
        if not self._initial_size_applied:
            return
        self.request_resize_redraw()

    def _queue_silent_command(self, code):
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        return bool(python_execution_service.execute_hidden(code))

    def _command_source(self, command, **settings):
        return self.command_state.source_for_command(command, **settings)

    def refresh_figure(self):
        if self._closed:
            return False
        if not self.snapshot_state.tracked_names():
            return False
        if self._refresh_in_flight:
            self._refresh_requested = True
            return False
        self._refresh_in_flight = True
        self._refresh_requested = False
        if self.snapshot_state.figure_ir() is not None:
            requested = self.request_figure_action(
                {"type": "regenerate_from_ir", "use_bound_values": False}
            )
        else:
            requested = self.request_refresh_from_live_state()
        if requested:
            self._refresh_timeout_timer.start(self.REFRESH_TIMEOUT_MS)
            return True
        self._clear_refresh_in_flight()
        return False

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

    def _current_tracked_namespace_state(self):
        python_variables_service = self.services.get("namespace_view_service")
        if python_variables_service is None:
            return ()
        return self._tracked_namespace_state_from_view(
            python_variables_service.namespace_view()
        )

    def _tracked_namespace_state_from_view(self, view):
        return tracked_namespace_signature(
            view,
            self.snapshot_state.tracked_names(),
        )

    def _on_namespace_view_updated(self, view):
        if self._closed:
            return
        new_state = self._tracked_namespace_state_from_view(view or {})
        if new_state == self._tracked_namespace_state:
            return
        self._tracked_namespace_state = new_state
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

    def default_macro_name(self):
        return self.window_handle() or self.snapshot_state.default_macro_name()

    def window_handle(self):
        return stable_window_name(self._subwindow)

    def macro_source(self, macro_name):
        geometry = self.capture_geometry()
        window_state = self.window_state()
        return self._recreation_function_source(
            macro_name,
            decorator_name="@hyde.figure",
            window_pos=None if geometry is None else tuple(geometry[:2]),
            window_state=None if window_state == "minimized" else window_state,
            figure_title=self.window_handle(),
        )

    def closeEvent(self, event):
        if self._closed or self._closing_from_kernel:
            self._closed = True
            self._disconnect_namespace_updates()
            return super().closeEvent(event)

        get_shutting_down = self.services.get("get_shutting_down")
        if get_shutting_down is not None and get_shutting_down():
            self._closed = True
            self._disconnect_namespace_updates()
            return super().closeEvent(event)

        if self._kernel_close_in_progress:
            LOGGER.debug(
                "Figure window %s ignored duplicate close while waiting for kernel confirmation.",
                self.figure_number,
            )
            event.ignore()
            return

        if not (QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier):
            save_window_dialog_service = self.services.get("save_window_dialog_service")
            get_procedures_init = self.services.get("get_procedures_init")
            reload_procedures = self.services.get("reload_procedures")
            if (
                save_window_dialog_service is not None
                and get_procedures_init is not None
                and reload_procedures is not None
            ):
                procedures_init = get_procedures_init()
                if procedures_init and not save_window_dialog_service.prompt_to_save_window_macro(
                    saveable=self,
                    parent=self.services.get("ui", self),
                    procedures_init=procedures_init,
                    reload_procedures=reload_procedures,
                ):
                    event.ignore()
                    return

        self._kernel_close_in_progress = True
        if not self._queue_silent_command(
            self._command_source("close", figure_number=self.figure_number)
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

    def _remember_subwindow_geometry(self):
        if self._subwindow is None or self._subwindow.isMinimized():
            return
        self._last_normal_geometry = tuple(capture_subwindow_geometry(self._subwindow))
