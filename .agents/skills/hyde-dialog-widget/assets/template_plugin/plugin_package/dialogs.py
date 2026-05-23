from qtutils.qt import QtWidgets

from hyde.user_interface.base_hyde_widgets import HydeDialogWidget
from hyde.features.example_features import ExampleCodec


class ExampleDialog(HydeDialogWidget):
    ui_filename = "example_dialog.ui"
    help_filename = "example_dialog_help.md"

    def __init__(self, services=None, parent=None):
        super().__init__(parent=parent, services=dict(services or {}))
        self.codec = ExampleCodec()
        self._draft_state = {"target_name": "", "enabled": False}
        self.load_ui(self.ui_filename, module_name=__name__)
        self._connect_signals()
        self._refresh_from_widgets()

    def _connect_signals(self):
        self.ui.targetNameEdit.textChanged.connect(self._refresh_from_widgets)
        self.ui.enabledCheckBox.toggled.connect(self._refresh_from_widgets)

    def _sync_state_from_widgets(self):
        self._draft_state = {
            "target_name": self.ui.targetNameEdit.text().strip(),
            "enabled": bool(self.ui.enabledCheckBox.isChecked()),
        }

    def _refresh_from_widgets(self):
        self._sync_state_from_widgets()
        validation = self.codec.validate_state(self._draft_state)
        if not validation["valid"]:
            self.set_preview_string("", display_text=validation["message"])
            self.refresh_shell()
            return
        command_source = self.codec.state_to_python(self._draft_state)
        self.set_preview_string(command_source)
        self.refresh_shell()

    def can_do_it(self):
        return bool(self._preview_string)

    def handle_do_it(self):
        # Keep local validation/bookkeeping here only when needed.
        self.dispatch_do_it_payload()
