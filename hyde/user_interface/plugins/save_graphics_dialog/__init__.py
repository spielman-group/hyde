import base64
from functools import partial

from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_features import graphics_clipboard_formats
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.shared.plugin import HydePlugin

from .clipboard import clipboard_mime_data
from .dialogs import SaveGraphicsDialog


class Plugin(HydePlugin):
    # Where the Copy As submenu is contributed, and the group it joins in each
    # location so it sits beside that location's Copy entry.
    COPY_AS_LOCATIONS = (
        ("edit", "clipboard", 0),
        ("figure", "figure_export", 100),
    )

    # Copy renders in the kernel and the bytes come back asynchronously, so a
    # fast copy must show nothing while a slow one must not look like a hang.
    busy_cursor_delay_ms = 200
    copy_timeout_ms = 10000

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self._copy_format = None
        self._busy_cursor_shown = False
        self._busy_timer = None
        self._timeout_timer = None

    def get_menu_contributions(self):
        return [
            {
                "location": "figure",
                "group": "figure_export",
                "group_order": 100,
                "order": 10,
                "name": "Save Graphics...",
                "action": self.show_save_graphics_dialog,
                "enabled": self.has_active_editable_figure,
            },
            {
                "location": "figure",
                "group": "figure_export",
                "group_order": 100,
                "order": 20,
                "name": "Copy",
                "action": self.copy_active_figure,
                "enabled": self.has_active_editable_figure,
            },
            {
                "location": "edit",
                "group": "clipboard",
                "group_order": 0,
                "order": 0,
                "name": "Copy",
                "action": self.copy_active_figure,
                "enabled": self.has_active_editable_figure,
                "shortcut": QtGui.QKeySequence.Copy,
            },
            *self._copy_as_contributions(),
        ]

    def _copy_as_contributions(self):
        # Declared into both locations because the figure context menu
        # re-renders the whole `figure` location, and into the same group as
        # Copy so the submenu sits beside it.
        contributions = []
        for index, item in enumerate(graphics_clipboard_formats()):
            for location, group, group_order in self.COPY_AS_LOCATIONS:
                contributions.append(
                    {
                        "location": location,
                        "path": ("Copy As",),
                        "group": group,
                        "group_order": group_order,
                        "order": 30 + index,
                        "name": item.display_label,
                        "action": partial(
                            self.copy_active_figure, output_format=item.key
                        ),
                        "enabled": self.has_active_editable_figure,
                    }
                )
        return contributions

    def copy_active_figure(self, checked=False, output_format="pdf"):
        del checked
        figure_context = self.active_editable_figure()
        if figure_context is None:
            return False
        source = (
            FigureIR(figure_name=figure_context.figure_name())
            .with_copy_graphics(output_format=output_format)
            .python_source()
        )
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        self._begin_copy(output_format)
        python_execution_service.execute_hidden(source)
        return True

    def copy_in_flight(self):
        return self._copy_format is not None

    def show_busy_cursor(self):
        if self._busy_cursor_shown:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self._busy_cursor_shown = True

    def restore_cursor(self):
        if not self._busy_cursor_shown:
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self._busy_cursor_shown = False

    def on_copy_timeout(self):
        # Mandatory rather than optional: an unrestored busy cursor makes the
        # whole application look hung, which is worse than no feedback at all.
        if not self.copy_in_flight():
            return
        self._fail_copy()

    def _fail_copy(self):
        self._end_copy()
        self._status_message("Could not copy the figure to the clipboard.")

    def _status_message(self, text):
        service = self.services.get("status_message_service")
        if service is not None:
            service.show_status_message(text)

    def _begin_copy(self, output_format):
        self._end_copy()
        self._copy_format = str(output_format)
        self._status_message(f"Copying figure as {self._copy_format.upper()}...")

        self._busy_timer = QtCore.QTimer()
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self.show_busy_cursor)
        self._busy_timer.start(self.busy_cursor_delay_ms)

        self._timeout_timer = QtCore.QTimer()
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self.on_copy_timeout)
        self._timeout_timer.start(self.copy_timeout_ms)

    def _end_copy(self):
        for attr in ("_busy_timer", "_timeout_timer"):
            timer = getattr(self, attr)
            if timer is not None:
                timer.stop()
                setattr(self, attr, None)
        self.restore_cursor()
        self._copy_format = None

    def on_kernel_message(self, payload):
        # The kernel rendered the figure and handed the bytes over; the
        # clipboard belongs to this process.
        if payload.get("task") != "COPY_TO_CLIPBOARD_REQUEST":
            return
        if not self.copy_in_flight():
            # A reply for a copy that already timed out, or that this plugin
            # never asked for. Reporting success now would contradict the
            # failure the user has already been shown.
            return
        data = payload.get("data", {}) or {}
        try:
            rendered = base64.b64decode(data.get("payload_base64", ""))
            companion_png = base64.b64decode(data.get("companion_png_base64") or "")
        except Exception:
            self._fail_copy()
            return
        if not rendered:
            self._fail_copy()
            return
        mime_data = clipboard_mime_data(
            rendered,
            output_format=data.get("output_format", "pdf"),
            is_text=bool(data.get("is_text")),
            companion_png=companion_png or None,
        )
        clipboard = QtWidgets.QApplication.clipboard()
        if mime_data is None or clipboard is None:
            # Nothing pasteable to hand over. Settle the request rather than
            # leaving its timers armed and its cursor on the way.
            self._fail_copy()
            return
        clipboard.setMimeData(mime_data)
        output_format = str(data.get("output_format", "") or "").upper()
        self._end_copy()
        self._status_message(f"Copied figure to the clipboard as {output_format}.")

    def show_save_graphics_dialog(self, checked=False):
        del checked
        figure_context = self.active_editable_figure()
        if figure_context is None:
            return False
        dialog = SaveGraphicsDialog(
            figure_context,
            services=self.services,
            parent=self.services.get("ui"),
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted


