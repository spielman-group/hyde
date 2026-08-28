import base64

from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.shared.plugin import HydePlugin

from .clipboard import clipboard_mime_data
from .dialogs import SaveGraphicsDialog


class Plugin(HydePlugin):
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
        ]

    def copy_active_figure(self, checked=False, output_format="pdf"):
        del checked
        figure_context = self._active_editable_figure()
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
        python_execution_service.execute_hidden(source)
        return True

    def on_kernel_message(self, payload):
        # The kernel rendered the figure and handed the bytes over; the
        # clipboard belongs to this process.
        if payload.get("task") != "COPY_TO_CLIPBOARD_REQUEST":
            return
        data = payload.get("data", {}) or {}
        try:
            rendered = base64.b64decode(data.get("payload_base64", ""))
        except Exception:
            return
        if not rendered:
            return
        mime_data = clipboard_mime_data(
            rendered,
            output_format=data.get("output_format", "pdf"),
            is_text=bool(data.get("is_text")),
        )
        if mime_data is None:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setMimeData(mime_data)

    def show_save_graphics_dialog(self, checked=False):
        del checked
        figure_context = self._active_editable_figure()
        if figure_context is None:
            return False
        dialog = SaveGraphicsDialog(
            figure_context,
            services=self.services,
            parent=self.services.get("ui"),
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted

    def has_active_editable_figure(self):
        return self._active_editable_figure() is not None

    def _active_editable_figure(self):
        figure_context_service = self.services.get("figure_context_service")
        if figure_context_service is None:
            return None
        return figure_context_service.active_editable_figure()
