import os

from qtutils import UiLoader
from qtutils.qt import QtWidgets


class SaveWindowDialog(QtWidgets.QDialog):
    SAVE = 1
    NO_SAVE = 2
    CANCEL = 0

    def __init__(self, table_state, parent=None):
        super().__init__(parent)
        self.choice = self.CANCEL
        # The dialog reads from the existing TableState directly so it does not
        # need its own save-state mirror or extra message-passing.
        self.table_state = table_state

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "save_window_dialog.ui")
        self.ui = loader.load(ui_path, self)

        self.ui.nameEdit.setText(self.table_state.default_macro_name())
        self.ui.nameEdit.selectAll()
        self.ui.saveButton.clicked.connect(self._accept_save)
        self.ui.noSaveButton.clicked.connect(self._accept_no_save)
        self.ui.cancelButton.clicked.connect(self.reject)
        self.ui.helpButton.clicked.connect(self._show_help)

    def macro_name(self):
        return self.ui.nameEdit.text().strip()

    def macro_source(self):
        return self.table_state.macro_source(self.macro_name())

    def _accept_save(self):
        self.choice = self.SAVE
        self.accept()

    def _accept_no_save(self):
        self.choice = self.NO_SAVE
        self.accept()

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Window Recreation Macros",
            "Save stores a parameterized recreation macro in procedures/__init__.py.\n\n"
            "No Save closes the window without writing a macro.\n\n"
            "Cancel leaves the window open.",
        )
