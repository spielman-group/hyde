import os

from qtutils import UiLoader
from qtutils.qt import QtWidgets

from hyde.features.matplotlib_features import is_eligible_for_plot

from .window import FigureState


class NewFigureDialog(QtWidgets.QDialog):
    def __init__(self, objects_metadata, preselection=None, parent=None):
        super().__init__(parent)
        self.objects_metadata = objects_metadata or {}
        self.preselection = list(preselection or [])
        self.figure_state = FigureState()

        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "new_figure_dialog.ui")
        self.ui = loader.load(ui_path, self)

        ok_button = self.ui.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        if ok_button:
            ok_button.setText("Do It")

        self._populate_widgets()
        self._sync_state_from_widgets()

        self.ui.xComboBox.currentIndexChanged.connect(self._sync_state_from_widgets)
        self.ui.yListWidget.itemSelectionChanged.connect(self._sync_state_from_widgets)
        self.ui.titleEdit.textChanged.connect(self._sync_state_from_widgets)
        self.ui.widthSpinBox.valueChanged.connect(self._sync_state_from_widgets)
        self.ui.heightSpinBox.valueChanged.connect(self._sync_state_from_widgets)
        self.ui.buttonBox.accepted.connect(self.accept)
        self.ui.buttonBox.rejected.connect(self.reject)

    def _eligible_names(self):
        return [
            name
            for name, metadata in sorted(self.objects_metadata.items())
            if is_eligible_for_plot(metadata)
        ]

    def _populate_widgets(self):
        eligible_names = self._eligible_names()
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
        y_names = [item.text() for item in self.ui.yListWidget.selectedItems()]
        self.figure_state.set_items(y_names)
        self.figure_state.set_x_name(self.ui.xComboBox.currentData())
        title = self.ui.titleEdit.text().strip()
        self.figure_state.set_title(title or None)
        self.figure_state.set_figsize(
            self.ui.widthSpinBox.value(),
            self.ui.heightSpinBox.value(),
        )

    def get_command(self, default_title=None, open_token=None):
        self._sync_state_from_widgets()
        if default_title and not self.figure_state.normalized_state()["settings"]["title"]:
            self.figure_state.set_title(default_title)
        if not self.figure_state.normalized_state()["items"]:
            return None
        return self.figure_state.source_for_command("create", open_token=open_token)

    def normalized_state(self):
        self._sync_state_from_widgets()
        return self.figure_state.normalized_state()
