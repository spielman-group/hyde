import os
from qtutils.qt.QtCore import QUrl
from qtutils.qt.QtWidgets import QWidget, QVBoxLayout, QTreeView, QFileSystemModel
from qtutils.qt.QtGui import QDesktopServices

class ProcedureBrowser(QWidget):
    def __init__(self, procedures_dir, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Procedures")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # File System Model configured for the procedures directory
        self.model = QFileSystemModel()
        # Filters: only files (no dirs in top level for now), only .py files
        self.model.setNameFilters(["*.py"])
        self.model.setNameFilterDisables(False)
        
        # Tree View setup
        self.tree_view = QTreeView()
        self.tree_view.setModel(self.model)
        
        # UI Polish: Hide unnecessary columns (Size, Type, Date)
        self.tree_view.setColumnHidden(1, True)
        self.tree_view.setColumnHidden(2, True)
        self.tree_view.setColumnHidden(3, True)
        self.tree_view.header().hide()
        
        self.tree_view.doubleClicked.connect(self.on_double_click)
        
        self.layout.addWidget(self.tree_view)
        self.set_procedures_dir(procedures_dir)

    def set_procedures_dir(self, procedures_dir):
        self.procedures_dir = procedures_dir
        if procedures_dir is None:
            self.tree_view.setRootIndex(self.model.index(""))
            return
        root_index = self.model.setRootPath(procedures_dir)
        self.tree_view.setRootIndex(root_index)

    def on_double_click(self, index):
        """Opens the file in the default system editor."""
        file_path = self.model.filePath(index)
        if os.path.isfile(file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

    def closeEvent(self, event):
        # Hide instead of close to allow persistent state
        if self.parentWidget():
            self.parentWidget().hide()
        else:
            self.hide()
        event.ignore()
