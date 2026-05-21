from qtutils.qt import QtWidgets

from hyde.features.hyde_features import is_eligible_for_table
from hyde.user_interface.base_hyde_widgets import HydeDialogWidget

from .window import TableState


class NewTableDialog(HydeDialogWidget):
    def __init__(self, objects_metadata, preselection=None, services=None, parent=None):
        self.table_state = TableState()
        super().__init__(parent=parent, services=dict(services or {}))
        self.objects_metadata = objects_metadata or {}
        self.preselection = preselection or []
        self.setWindowTitle("New Table")
        self.load_ui("new_table_dialog.ui", module_name=__name__)

        self._populate_list()
        self._refresh_from_widgets()
        self.ui.objectList.itemSelectionChanged.connect(self._refresh_from_widgets)
        self.ui.titleEdit.textChanged.connect(self._refresh_from_widgets)

    def _populate_list(self):
        for name, metadata in sorted(self.objects_metadata.items()):
            if is_eligible_for_table(metadata):
                item = QtWidgets.QListWidgetItem(name)
                self.ui.objectList.addItem(item)
                if name in self.preselection:
                    item.setSelected(True)

    def _sync_state_from_widgets(self):
        if self.ui is None:
            return
        selected_items = self.ui.objectList.selectedItems()
        names = [item.text() for item in selected_items]
        self.table_state.set_items(names)
        title = self.ui.titleEdit.text().strip()
        self.table_state.set_name(title or None)

    def _refresh_from_widgets(self):
        self._sync_state_from_widgets()
        self.refresh_shell()

    def canonical_text_payload(self):
        self._sync_state_from_widgets()
        if not self.table_state.normalized_state()["items"]:
            return ""
        return self.table_state.python_source()

    def can_do_it(self):
        self._sync_state_from_widgets()
        return bool(self.table_state.normalized_state()["items"])

    def can_send_to_cmd_line(self):
        return True

    def handle_do_it(self):
        if self.can_do_it():
            self.accept()

    def get_command(self):
        payload = self.canonical_text_payload()
        return payload or None
