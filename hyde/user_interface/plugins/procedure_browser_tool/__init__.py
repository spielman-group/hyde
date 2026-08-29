import os
from qtutils.qt.QtCore import QUrl
from qtutils.qt.QtWidgets import QWidget
from qtutils.qt.QtGui import QDesktopServices
try:
    # Qt6 moved QFileSystemModel from QtWidgets to QtGui
    from qtutils.qt.QtGui import QFileSystemModel
except ImportError:
    from qtutils.qt.QtWidgets import QFileSystemModel
from hyde.user_interface.base_hyde_widgets import HydeToolWidget, load_ui_for_owner
from hyde.user_interface.shared.plugin import HydeToolWindowPlugin


class ProcedureBrowser(HydeToolWidget):
    def __init__(self, procedures_dir, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Procedures")
        content = load_ui_for_owner(
            QWidget(self),
            "procedure_browser.ui",
            module_name=__name__,
        )
        self.mount_child_widget(content)

        self.model = QFileSystemModel()
        self.model.setNameFilters(["*.py"])
        self.model.setNameFilterDisables(False)
        self.tree_view = content.treeView
        self.tree_view.setModel(self.model)
        self.tree_view.setColumnHidden(1, True)
        self.tree_view.setColumnHidden(2, True)
        self.tree_view.setColumnHidden(3, True)
        self.tree_view.doubleClicked.connect(self.on_double_click)
        self.set_procedures_dir(procedures_dir)

    def set_procedures_dir(self, procedures_dir):
        self.procedures_dir = procedures_dir
        if procedures_dir is None:
            root_index = self.model.setRootPath("")
            self.tree_view.setRootIndex(root_index)
            return
        root_index = self.model.setRootPath(procedures_dir)
        self.tree_view.setRootIndex(root_index)

    def on_double_click(self, index):
        """Opens the file in the default system editor."""
        file_path = self.model.filePath(index)
        if os.path.isfile(file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

class Plugin(HydeToolWindowPlugin):
    session_key = "procedure_browser_tool"
    window_title = "Procedures"
    menu_name = "Procedures"
    window_size = (300, 500)
    menu_order = 50
    creation_policy = "eager"
    restore_on_project_loaded = True
    enable_action_with_project = True
    hide_on_enter_no_project = True

    def create_tool_window_widget(self, parent=None):
        return ProcedureBrowser(
            procedures_dir=None,
            parent=parent,
            services=self.services,
            session_key=self.session_key,
        )

    def on_project_activated(self, data):
        super().on_project_activated(data)
        widget = self.mdi_widget(self.session_key)
        if widget is not None:
            widget.set_procedures_dir(data.get("procedures_dir"))

    def on_enter_no_project_state(self, data):
        super().on_enter_no_project_state(data)
        widget = self.mdi_widget(self.session_key)
        if widget is not None:
            widget.set_procedures_dir(None)
