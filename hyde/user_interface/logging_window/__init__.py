from qtutils.qt.QtWidgets import QWidget, QVBoxLayout
from labscript_utils.qtwidgets.outputbox import OutputBox

class LoggingWindow(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Logging")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Initialize the OutputBox, which populates our layout
        self.output_box = OutputBox(self.layout)
    
    @property
    def port(self):
        return self.output_box.port

    def closeEvent(self, event):
        # Instead of destroying, we just hide the entire MDI sub-window.
        # This allows the window to be toggled via the 'Windows' menu.
        if self.parentWidget():
            self.parentWidget().hide()
        else:
            self.hide()
        event.ignore()
