import os
from qtutils import UiLoader
from qtutils.qt import QtWidgets

class HydeMainWindow(QtWidgets.QMainWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

class HydeApp:
    def __init__(self, qapplication):
        self.qapplication = qapplication
        
        # Load the UI
        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), 'main.ui')
        self.ui = loader.load(ui_path, HydeMainWindow(self))
        
        # Connect Quit
        self.ui.actionQuit.triggered.connect(self.qapplication.quit)
