"""Close figure dialog UI package."""

from __future__ import annotations

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui


class CloseFigureDialog(QtWidgets.QDialog):
    save_selected = QtCore.Signal(str)
    discard_selected = QtCore.Signal()

    def __init__(self, suggested_name, parent=None):
        super().__init__(parent)
        self.ui = load_ui("close_figure_dialog/close_figure_dialog.ui", self)
        self.name_edit = self.ui.name_edit
        self.save_button = self.ui.save_button
        self.no_save_button = self.ui.no_save_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button
        self.name_edit.setText(suggested_name)
        self.save_button.clicked.connect(self._emit_save)
        self.no_save_button.clicked.connect(self._emit_discard)
        self.help_button.clicked.connect(self._show_help)
        self.cancel_button.clicked.connect(self.reject)

    def _emit_save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        self.save_selected.emit(name)
        self.accept()

    def _emit_discard(self):
        self.discard_selected.emit()
        self.accept()

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Close Window",
            "Save stores a replayable Hyde function in procedures/master.py. No Save closes the window without writing a function.",
        )


__all__ = ["CloseFigureDialog"]
