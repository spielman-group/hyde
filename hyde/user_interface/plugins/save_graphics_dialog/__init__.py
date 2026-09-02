import base64
from functools import partial

from qtutils.qt import QtGui, QtWidgets

from hyde.features.matplotlib_features import (
    combinable_clipboard_representations,
    graphics_clipboard_representation,
    graphics_clipboard_representations,
)
from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.shared.clipboard_platform import (
    preferred_clipboard_format,
    register_clipboard_converters,
)
from hyde.user_interface.shared.plugin import HydePlugin

from .clipboard import clipboard_mime_data
from .copy_request import FigureCopyRequest
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
    # Neither clock bounds the kernel: a copy queued behind the user's own cell
    # waits as long as that takes.
    busy_cursor_delay_ms = 200
    busy_cursor_hold_ms = 2000
    # Once the render has run its bytes are already in transit on the other
    # channel, so this gap is transport, not work.
    payload_timeout_ms = 2000

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self._copy_request = None

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
        for index, item in enumerate(graphics_clipboard_representations()):
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
                            self.copy_active_figure, representation=item.key
                        ),
                        "enabled": self.has_active_editable_figure,
                    }
                )
        return contributions

    def copy_active_figure(self, checked=False, representation=None):
        """Copy the active figure to the clipboard.

        With no representation named, the copy carries every representation a
        picture-or-drawing consumer might want and the receiving application
        picks. Naming one forces it, which is the way to insist on a vector when
        an application would otherwise settle for the raster.
        """
        del checked
        clipboard_formats = self._clipboard_formats(representation)
        if not clipboard_formats:
            self._outcome_message(
                "Could not copy the figure: no clipboard format is available."
            )
            return False
        if self.copy_in_flight():
            # One at a time. The rendered bytes arrive on a channel that does
            # not say which copy they answer, so a second copy in flight would
            # make "the next payload is mine" untrue for both.
            self._outcome_message("A figure copy is already in progress.")
            return False
        figure_context = self.active_editable_figure()
        if figure_context is None:
            return False
        source = (
            FigureIR(figure_name=figure_context.figure_name())
            .with_copy_graphics(clipboard_formats=clipboard_formats)
            .python_source()
        )
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        self._begin_copy(self._copy_label(representation))
        kernel_request = python_execution_service.request(
            source, on_finished=self.on_copy_render_finished
        )
        if kernel_request is None:
            self._fail_copy("Could not reach the kernel to copy the figure.")
            return False
        self._copy_request.kernel_request = kernel_request
        return True

    def _copy_label(self, representation):
        """What to call this copy while it is in flight."""
        named = graphics_clipboard_representation(representation)
        return "" if named is None else named.display_label

    def _clipboard_formats(self, representation):
        """One format per representation, chosen by what the platform can use.

        A representation offers several candidate formats because platforms
        differ in which they republish natively. Only the chosen one is
        rendered: asking the kernel for every candidate would render figures
        nothing on this machine can paste.
        """
        if representation is None:
            representations = combinable_clipboard_representations()
        else:
            named = graphics_clipboard_representation(representation)
            representations = () if named is None else (named,)
        formats = []
        for item in representations:
            output_format = preferred_clipboard_format(item.output_formats)
            if output_format is not None:
                formats.append(output_format)
        return tuple(formats)

    def copy_in_flight(self):
        return self._copy_request is not None

    def on_copy_render_finished(self, kernel_request):
        """The kernel answered the render command. The bytes are separate."""
        if not self.copy_in_flight():
            # The bytes beat the reply and the copy is already done.
            return
        if self._copy_request.kernel_request is not kernel_request:
            return
        if kernel_request.ran():
            self._copy_request.await_payload(self.payload_timeout_ms)
            return
        # Until the GUI read replies, a command that raised in the kernel was
        # invisible here and the copy could only time out anonymously.
        self._fail_copy(
            f"Could not copy the figure: {kernel_request.error}"
            if kernel_request.error
            else None
        )

    def on_copy_payload_timeout(self):
        # Mandatory rather than optional: an unrestored busy cursor makes the
        # whole application look hung, which is worse than no feedback at all.
        if not self.copy_in_flight():
            return
        self._fail_copy(
            "Could not copy the figure: it rendered, but its data never arrived."
        )

    def _fail_copy(self, message=None):
        self._end_copy()
        self._outcome_message(
            message or "Could not copy the figure to the clipboard."
        )

    def _status_message(self, text):
        """A copy still in flight; it stays until the outcome replaces it."""
        service = self.services.get("status_message_service")
        if service is not None:
            service.show_status_message(text)

    def _outcome_message(self, text):
        service = self.services.get("status_message_service")
        if service is not None:
            service.show_transient_message(text)

    def _begin_copy(self, label):
        self._end_copy()
        self._copy_request = FigureCopyRequest(
            busy_delay_ms=self.busy_cursor_delay_ms,
            busy_hold_ms=self.busy_cursor_hold_ms,
            on_payload_timeout=self.on_copy_payload_timeout,
        )
        self._status_message(
            f"Copying figure as {label}..." if label else "Copying figure..."
        )

    def _end_copy(self):
        if self._copy_request is not None:
            self._copy_request.settle()
            self._copy_request = None

    def setup(self, data=None):
        del data
        # Copy is the only feature that puts a vector on the clipboard, so it
        # is the one that has to teach the platform about vector types.
        register_clipboard_converters()

    def get_event_handlers(self):
        # Without this the rendered bytes are dispatched to every plugin that
        # asked for kernel messages, and this one never asked, so every copy
        # waited out its payload timeout.
        return {"kernel_message": self.on_kernel_message}

    def on_kernel_message(self, payload):
        # The kernel rendered the figure and handed the bytes over; the
        # clipboard belongs to this process.
        if payload.get("task") != "COPY_TO_CLIPBOARD_REQUEST":
            return
        if not self.copy_in_flight():
            # Bytes for a copy that already failed, or that this plugin never
            # asked for. Reporting success now would contradict the failure the
            # user has already been shown.
            return
        data = payload.get("data", {}) or {}
        if not self._payload_answers_current_copy(data):
            return
        try:
            representations = [
                (
                    str(item.get("output_format", "")),
                    base64.b64decode(item.get("payload_base64", "")),
                )
                for item in data.get("representations", []) or []
            ]
        except Exception:
            self._fail_copy()
            return
        representations = [
            (output_format, rendered)
            for output_format, rendered in representations
            if rendered
        ]
        if not representations:
            self._fail_copy()
            return
        payload = clipboard_mime_data(representations)
        clipboard = QtWidgets.QApplication.clipboard()
        if payload is None or clipboard is None:
            # Nothing pasteable to hand over. Settle the request rather than
            # leaving its timers armed and its cursor on the way.
            self._fail_copy()
            return
        clipboard.setMimeData(payload.mime_data)
        self._end_copy()
        # What the payload placed, not what was rendered for it: a copy that
        # named everything it asked for would claim a paste that cannot happen.
        self._outcome_message(
            f"Copied figure to the clipboard as {payload.describe()}."
        )

    def _payload_answers_current_copy(self, data):
        """Reject bytes that belong to a copy this one already gave up on.

        A copy that rendered but whose data was too slow fails, and its bytes
        can still land afterwards. If the user has started another copy by then,
        the stale bytes would satisfy it. The parent-message channel carries no
        Jupyter header, so the payload names the request that produced it.
        An empty name means the kernel could not tell us, which is not evidence
        against this copy.
        """
        payload_msg_id = str(data.get("request_msg_id") or "")
        if not payload_msg_id:
            return True
        kernel_request = self._copy_request.kernel_request
        return kernel_request is None or kernel_request.msg_id == payload_msg_id

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
        return dialog.exec() == QtWidgets.QDialog.Accepted


