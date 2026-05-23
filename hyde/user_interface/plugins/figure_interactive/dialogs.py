from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import sorted_eligible_names
from hyde.user_interface.base_hyde_widgets import HydeDialogWidget

from .window import FigureState


class NewFigureDialog(HydeDialogWidget):
    def __init__(self, objects_metadata, preselection=None, services=None, parent=None):
        self.figure_state = FigureState()
        super().__init__(parent=parent, services=dict(services or {}))
        self.objects_metadata = objects_metadata or {}
        self.preselection = list(preselection or [])
        self.setWindowTitle("New Figure")
        self.load_ui("new_figure_dialog.ui", module_name=__name__)

        self._populate_widgets()
        self._refresh_from_widgets()

        self.ui.xComboBox.currentIndexChanged.connect(self._refresh_from_widgets)
        self.ui.yListWidget.itemSelectionChanged.connect(self._refresh_from_widgets)
        self.ui.titleEdit.textChanged.connect(self._refresh_from_widgets)
        self.ui.widthSpinBox.valueChanged.connect(self._refresh_from_widgets)
        self.ui.heightSpinBox.valueChanged.connect(self._refresh_from_widgets)

    def _populate_widgets(self):
        eligible_names = sorted_eligible_names(self.objects_metadata)
        self.ui.xComboBox.addItem("(index)", "")
        for name in eligible_names:
            self.ui.xComboBox.addItem(name, name)
            item = QtWidgets.QListWidgetItem(name)
            self.ui.yListWidget.addItem(item)
            if name in self.preselection:
                item.setSelected(True)
        if self.preselection:
            preferred_x = self.preselection[0]
            index = self.ui.xComboBox.findData(preferred_x)
            if index > 0:
                self.ui.xComboBox.setCurrentIndex(index)

    def _sync_state_from_widgets(self):
        if self.ui is None:
            return
        y_names = [item.text() for item in self.ui.yListWidget.selectedItems()]
        self.figure_state.set_items(y_names)
        self.figure_state.set_x_name(self.ui.xComboBox.currentData())
        title = self.ui.titleEdit.text().strip()
        self.figure_state.set_title(title or None)
        self.figure_state.set_figsize(
            self.ui.widthSpinBox.value(),
            self.ui.heightSpinBox.value(),
        )

    def _refresh_from_widgets(self):
        self._sync_state_from_widgets()
        self.set_preview_string(self.figure_state.source_for_command("create"))
        self.refresh_shell()

    def normalized_state(self):
        self._sync_state_from_widgets()
        return self.figure_state.normalized_state()
