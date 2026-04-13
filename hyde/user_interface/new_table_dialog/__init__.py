import os
from qtutils import UiLoader
from qtutils.qt import QtWidgets, QtCore


class NewTableDialog(QtWidgets.QDialog):
    def __init__(self, objects_metadata, preselection=None, parent=None):
        super().__init__(parent)
        self.objects_metadata = objects_metadata or {}
        self.preselection = preselection or []

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "new_table_dialog.ui")
        self.ui = loader.load(ui_path, self)

        # Spec: OK button -> "Do It"
        ok_button = self.ui.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        if ok_button:
            ok_button.setText("Do It")

        self._populate_list()
        self.ui.buttonBox.accepted.connect(self.accept)
        self.ui.buttonBox.rejected.connect(self.reject)

    def _populate_list(self):
        from hyde.features.hyde_features import is_eligible_for_table
        
        for name, metadata in sorted(self.objects_metadata.items()):
            if is_eligible_for_table(metadata):
                item = QtWidgets.QListWidgetItem(name)
                self.ui.objectList.addItem(item)
                if name in self.preselection:
                    item.setSelected(True)

    def get_command(self):
        """Generates the hyde.table(...) command via hyde_features."""
        from hyde.features.hyde_features import format_table_command
        
        selected_items = self.ui.objectList.selectedItems()
        names = [item.text() for item in selected_items]
        if not names:
            return None
        
        title = self.ui.titleEdit.text().strip()

        return format_table_command(names, title=title or None)

    def get_visible_title(self):
        """Returns the user-specified title for the window label."""
        return self.ui.titleEdit.text().strip()
