"""Procedure browser UI package."""

from hyde.user_interface import load_ui

from qtutils.qt import QtCore, QtWidgets


class ProcedureBrowserWidget(QtWidgets.QWidget):
    open_requested = QtCore.Signal(str)
    run_requested = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = load_ui("procedure_browser/procedure_browser.ui", self)
        self.tree = self.ui.tree
        self.open_button = self.ui.open_button
        self.run_button = self.ui.run_button

        self.tree.setHeaderLabels(["Title", "Kind", "Path"])
        self.tree.itemDoubleClicked.connect(self._open_selected)
        self.open_button.clicked.connect(self._open_selected)
        self.run_button.clicked.connect(self._run_selected)

    def set_entries(self, entries):
        self.tree.clear()
        for entry in entries:
            item = QtWidgets.QTreeWidgetItem([entry.title, entry.kind, entry.path])
            item.setData(0, QtCore.Qt.UserRole, entry)
            self.tree.addTopLevelItem(item)

    def selected_entry(self):
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, QtCore.Qt.UserRole)

    def _open_selected(self, *_args):
        entry = self.selected_entry()
        if entry is not None:
            self.open_requested.emit(entry.path)

    def _run_selected(self):
        entry = self.selected_entry()
        if entry is not None:
            self.run_requested.emit(entry.path, entry.function_name)


__all__ = ["ProcedureBrowserWidget"]