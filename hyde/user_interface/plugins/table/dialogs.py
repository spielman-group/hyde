import os

from qtutils import UiLoader
from qtutils.qt import QtWidgets

from hyde.features.hyde_features import is_eligible_for_table

from .window import TableState


class NewTableDialog(QtWidgets.QDialog):
    def __init__(self, objects_metadata, preselection=None, parent=None):
        super().__init__(parent)
        self.objects_metadata = objects_metadata or {}
        self.preselection = preselection or []
        self.table_state = TableState()

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "new_table_dialog.ui")
        self.ui = loader.load(ui_path, self)

        ok_button = self.ui.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        if ok_button:
            ok_button.setText("Do It")

        self._populate_list()
        self._sync_state_from_widgets()
        self.ui.objectList.itemSelectionChanged.connect(self._sync_state_from_widgets)
        self.ui.titleEdit.textChanged.connect(self._sync_state_from_widgets)
        self.ui.buttonBox.accepted.connect(self.accept)
        self.ui.buttonBox.rejected.connect(self.reject)

    def _populate_list(self):
        for name, metadata in sorted(self.objects_metadata.items()):
            if is_eligible_for_table(metadata):
                item = QtWidgets.QListWidgetItem(name)
                self.ui.objectList.addItem(item)
                if name in self.preselection:
                    item.setSelected(True)

    def _sync_state_from_widgets(self):
        selected_items = self.ui.objectList.selectedItems()
        names = [item.text() for item in selected_items]
        self.table_state.set_items(names)
        title = self.ui.titleEdit.text().strip()
        self.table_state.set_name(title or None)

    def get_command(self):
        self._sync_state_from_widgets()
        if not self.table_state.normalized_state()["items"]:
            return None
        return self.table_state.python_source()
