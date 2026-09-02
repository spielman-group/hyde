import base64
import logging

from qtutils import inmain_decorator
from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_ir import (
    FigureIR,
    canonicalize_figure_window_name as _canonicalize_figure_window_name,
)
from hyde.features.matplotlib_figure_records import supported_trace_records
from hyde.features.hyde_features import figure_decorator_source
from hyde.user_interface.base_hyde_widgets import HydeInteractiveWidget
from hyde.user_interface.shared.plugin import apply_saveable_window_state
from hyde.user_interface.shared.project import MacroStoreError

LOGGER = logging.getLogger("hyde")


class FigureSnapshotState:
    """What the kernel says about a figure that the figure's IR cannot carry.

    The IR is the window's only account of the figure's contents, so nothing
    here duplicates it. What is left is the pixel size matplotlib resolved (the
    IR carries inches, and carries none at all for a default-sized figure), the
    warning for a figure Hyde could not fully describe, and the call source
    that is all a figure without an IR has to be saved from.
    """

    def __init__(self, default_macro_name="Figure"):
        self._default_macro_name = default_macro_name or "Figure"
        self._call_source = None
        self._save_error = None
        self._figure_size = None

    def update(
        self,
        default_macro_name=None,
        call_source=None,
        save_error=None,
        figure_size=None,
    ):
        if default_macro_name:
            self._default_macro_name = str(default_macro_name)
        self._call_source = call_source
        self._save_error = save_error
        self._figure_size = None if figure_size is None else tuple(figure_size)

    def default_macro_name(self):
        return self._default_macro_name

    def figure_size(self):
        return self._figure_size

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

    def macro_source(self, macro_name, *, register=True):
        if self._save_error:
            raise MacroStoreError(self._save_error)
        if not self._call_source:
            raise MacroStoreError("This figure does not have a saveable recreation macro yet.")
        body = "\n".join(f"    {line}" for line in self._call_source.splitlines())
        return (
            f"{figure_decorator_source(register=register)}\n"
            f"def {macro_name}():\n"
            f"{body}\n"
            "    return fig\n"
        )


class FigureWindow(HydeInteractiveWidget):
    def __init__(self, figure_number, services=None, parent=None):
        self.figure_number = int(figure_number)
        super().__init__(
            services=services,
            initial_window_name=f"Figure{self.figure_number}",
            parent=parent,
        )
        self._closed = False
        self._closing_from_kernel = False
        self._pixmap = None
        self._initial_size_applied = False
        self._pending_window_pos = None
        self._pending_window_state = None
        self._refresh_requested = False
        self._resize_redraw_timer = QtCore.QTimer(self)
        self._resize_redraw_timer.setSingleShot(True)
        self._resize_redraw_timer.timeout.connect(self._on_resize_redraw_timeout)
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

    def update_payload(self, payload):
        snapshot = dict(payload.get("snapshot", {}) or {})
        self.widget_ir = FigureIR.from_snapshot(snapshot)
        self.snapshot_state.update(
            default_macro_name=snapshot.get("default_macro_name"),
            call_source=snapshot.get("call_source"),
            save_error=snapshot.get("save_error"),
            figure_size=snapshot.get("figure_size"),
        )
        if self._subwindow is not None:
            self._subwindow.setWindowTitle(
                self._visible_window_title()
            )
        warning_message = self.snapshot_state.window_warning_message()
        self.warning_label.setVisible(bool(warning_message))
        self.warning_label.setText(warning_message)
        # The new IR may track different names, so the signature the next
        # namespace update is compared against has to be rebuilt over them.
        self._tracked_namespace_state = self.current_tracked_namespace_state()

        image_base64 = payload.get("image_png_base64")
        if image_base64:
            png_bytes = base64.b64decode(image_base64.encode("ascii"))
            image = QtGui.QImage.fromData(png_bytes, "PNG")
            if not image.isNull():
                self._pixmap = QtGui.QPixmap.fromImage(image)
                self.settle_payload_request("refresh")
                self._update_scaled_pixmap()
                if not self._initial_size_applied:
                    self._apply_initial_subwindow_size()
                    self._initial_size_applied = True
                    self._apply_pending_window_state()
                self._retry_pending_refresh()
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
        if self.widget_ir is None:
            return None
        return self.widget_ir.normalized_state()

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

    def _visible_trace_title_suffix(self):
        return ", ".join(
            record["display_name"] for record in self.supported_trace_records()
        )

    def _visible_window_title(self):
        return self.formatted_window_title(
            title_name=self.saveable_default_macro_name(),
            title_suffix=self._visible_trace_title_suffix(),
            warning_text=self.snapshot_state.window_warning_text(),
        )

    def request_regenerate_from_ir(self):
        if not self.has_figure_ir():
            return False
        return self.execute_hidden_command(
            self._refresh_command_source(use_bound_values=True)
        )

    @inmain_decorator()
    def _on_resize_redraw_timeout(self):
        if self._closed:
            return
        if not self._initial_size_applied:
            return
        self.request_resize_redraw()

    def tracked_namespace_names(self):
        """The figure's one account of what it reads from the namespace.

        Both halves of tracking read this: the signature that decides whether a
        namespace update touched this figure at all, and `refresh_figure`'s own
        gate. Asking the IR twice, once here and once there, let a figure be
        watched for names it would never refresh on.
        """
        if self.widget_ir is None:
            return ()
        return self.widget_ir.tracked_names()

    def refresh_figure(self):
        if self._closed:
            return False
        if not self.tracked_namespace_names():
            return False
        if self.payload_request_in_flight("refresh"):
            self._refresh_requested = True
            return False
        self._refresh_requested = False
        return (
            self.begin_payload_request(
                "refresh",
                self._refresh_command_source(use_bound_values=False),
                description=f"Refreshing figure {self.window_handle()}",
                on_failed=self._retry_pending_refresh,
            )
            is not None
        )

    def _retry_pending_refresh(self):
        """Run the refresh asked for while the last one was still in flight."""
        if self._refresh_requested and not self._closed:
            self._refresh_requested = False
            self.refresh_figure()

    def _refresh_command_source(self, *, use_bound_values):
        # A refresh lowers to the figure's name and a flag, so the command
        # carries no figure state and the window's own IR is not part of it.
        return (
            FigureIR()
            .with_refresh_figure(
                self.saveable_default_macro_name(),
                use_bound_values=use_bound_values,
            )
            .python_source(log=False)
        )

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
        self.settle_payload_request("close")
        self._closing_from_kernel = True
        if self._subwindow is not None:
            self._subwindow.close()
        else:
            self.close()

    def force_close(self):
        self._closing_from_kernel = True
        self.settle_payload_request("close")
        self.close_from_kernel()

    def saveable_default_macro_name(self):
        if self.widget_ir is not None:
            return self.widget_ir.default_macro_name()
        return self.snapshot_state.default_macro_name() or self.window_handle()

    def saveable_decorator_name(self):
        return figure_decorator_source()

    def macro_definition_source(self, macro_name, *, handle, register=True):
        # Whether Hyde could describe this figure as an IR is the one thing the
        # snapshot still answers that the IR cannot: without one, all the
        # window has to save is the call the kernel recorded.
        if self.widget_ir is None:
            return self.snapshot_state.macro_source(macro_name, register=register)
        return self.widget_ir.recreation_function_source(
            macro_name,
            name=handle,
            register=register,
        )

    def session_restore_definition_source(self, handle):
        # A restored figure is rebuilt, not re-registered: the session file
        # calls the function it defines rather than adding it to the project.
        return self.macro_definition_source(handle, handle=handle, register=False)

    def session_restore_warning(self):
        message = self.snapshot_state.window_warning_message()
        if not message:
            return None
        return f"{self.window_handle()}: {message}"

    def session_restore_arguments(self):
        return self.tracked_namespace_names()

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
        if self.payload_request_in_flight("close"):
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
        if (
            self.begin_payload_request(
                "close",
                # A close lowers to the figure number alone, so it carries no
                # figure state either.
                FigureIR().with_close_figure(self.figure_number).python_source(
                    log=False
                ),
                description=f"Closing figure {self.figure_number} in the kernel",
                announce_progress=True,
            )
            is None
        ):
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
        # The window stays open until the kernel confirms, however long the
        # kernel takes to get to the request. Closing it first would make the
        # GUI, not the kernel, the authority on whether the figure exists.
        event.ignore()

    def _disconnect_namespace_updates(self):
        self.settle_payload_requests()
        self._resize_redraw_timer.stop()
        try:
            python_variables_service = self.services.get("namespace_view_service")
            if python_variables_service is not None:
                python_variables_service.disconnect_namespace_view_updated(
                    self._on_namespace_view_updated
                )
        except Exception:
            pass
