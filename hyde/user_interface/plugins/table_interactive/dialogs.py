from qtutils.qt import QtWidgets

from hyde.features.base import is_eligible_for_numeric_series
from hyde.user_interface.base_hyde_widgets import HydeDialogWidget

from .window import TableIR


class NewTableDialog(HydeDialogWidget):
    def __init__(self, objects_metadata, preselection=None, services=None, parent=None):
        super().__init__(parent=parent, services=dict(services or {}))
        self.objects_metadata = objects_metadata or {}
        self.preselection = preselection or []
        self.widget_ir = TableIR()
        self.setWindowTitle("New Table")
        self.load_ui("new_table_dialog.ui", module_name=__name__)

        self._populate_list()
        self._refresh_from_widgets()
        self.ui.objectList.itemSelectionChanged.connect(self._refresh_from_widgets)
        self.ui.titleEdit.textChanged.connect(self._refresh_from_widgets)

    def _populate_list(self):
        for name, metadata in sorted(self.objects_metadata.items()):
            if is_eligible_for_numeric_series(metadata):
                item = QtWidgets.QListWidgetItem(name)
                self.ui.objectList.addItem(item)
                if name in self.preselection:
                    item.setSelected(True)

    def _refresh_from_widgets(self):
        if self.ui is None:
            return
        selected_items = self.ui.objectList.selectedItems()
        self.widget_ir = TableIR(
            names=[item.text() for item in selected_items],
            name=self.ui.titleEdit.text().strip() or None,
        )
        payload = ""
        if self.widget_ir.names:
            payload = self.widget_ir.python_source(log=False)
        self.set_preview_string(payload)
        self.refresh_shell()

    def do_it_dispatch_mode(self):
        return "visible"
