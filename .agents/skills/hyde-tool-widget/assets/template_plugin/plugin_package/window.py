from qtutils.qt import QtWidgets

from hyde.user_interface.base_hyde_widgets import HydeToolWidget
from hyde.features.example_features import ExampleCodec


class ExampleContent(QtWidgets.QWidget):
    def __init__(self, services=None, parent=None):
        super().__init__(parent)
        self.services = dict(services or {})
        self.codec = ExampleCodec()
        self.layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel("Example tool content", self)
        self.layout.addWidget(self.label)


class ExampleTool(HydeToolWidget):
    def __init__(self, services=None, window_identifier=None, parent=None):
        super().__init__(
            services=services,
            window_identifier=window_identifier,
            parent=parent,
        )
        self.mount_child_widget(ExampleContent(services=self.services, parent=self))

