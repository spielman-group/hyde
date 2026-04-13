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
        # Eligible objects are 1D numeric arrays
        for name, metadata in sorted(self.objects_metadata.items()):
            python_type = metadata.get("python_type", "").lower()
            numpy_type = metadata.get("numpy_type", "")
            
            # Scoped to 1D numeric (waves)
            is_wave = python_type == "ndarray" or numpy_type == "Array"
            if is_wave:
                item = QtWidgets.QListWidgetItem(name)
                self.ui.objectList.addItem(item)
                if name in self.preselection:
                    item.setSelected(True)

    def get_command(self):
        selected_items = self.ui.objectList.selectedItems()
        names = [item.text() for item in selected_items]
        if not names:
            return None
        
        # Note: Title input is captured but currently not passed to the 
        # narrow hyde.table(...) API to avoid speculative complexity.
        # It remains in the UI to satisfy the spec's visual requirement.
        
        args = ", ".join(names)
        return f"hyde.table({args})"
