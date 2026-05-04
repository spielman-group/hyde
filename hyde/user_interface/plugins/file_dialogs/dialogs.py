import os

from qtutils.qt import QtWidgets

from hyde.features.hyde_features import SimpleHydeCommandCodec
from hyde.paths import DEFAULT_PROJECTS_DIR
from hyde.user_interface.base import HydeGuiState


class SimpleCommandState(HydeGuiState):
    # Hyde intentionally uses the same state/codec pattern for these trivial
    # project-file commands so command-generation ownership stays consolidated
    # in one place. This is a deliberate architectural choice, not an
    # accidental abstraction to be collapsed back into `main`.
    codec = SimpleHydeCommandCodec
    command_name = None

    def __init__(self):
        super().__init__()
        self.apply_action({"type": "set_command", "command": self.command_name})
        self.configure_command_defaults()

    def configure_command_defaults(self):
        """Hook for subclasses to seed command-specific state defaults."""

    def set_project_dir(self, project_dir):
        if project_dir:
            self.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "project_dir"),
                    "value": project_dir,
                }
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "project_dir")})

    def project_dir(self):
        return self.normalized_state()["settings"]["project_dir"]

    def set_overwrite(self, overwrite):
        self.apply_action(
            {"type": "set", "path": ("settings", "overwrite"), "value": bool(overwrite)}
        )

    def set_save_mode(self, mode):
        self.apply_action({"type": "set", "path": ("settings", "mode"), "value": mode})


class NewProjectState(SimpleCommandState):
    command_name = "new_project"

    def configure_command_defaults(self):
        self.apply_action({"type": "set", "path": ("settings", "load"), "value": True})
        self.set_overwrite(False)


class LoadProjectState(SimpleCommandState):
    command_name = "load_project"


class HealProjectState(SimpleCommandState):
    command_name = "heal_project"


class SaveProjectState(SimpleCommandState):
    command_name = "save_project"

    def configure_command_defaults(self):
        self.set_save_mode("save")


class SaveAsProjectState(SaveProjectState):
    def configure_command_defaults(self):
        self.set_save_mode("save_as")
        self.set_overwrite(False)


class SaveCopyProjectState(SaveProjectState):
    def configure_command_defaults(self):
        self.set_save_mode("copy")
        self.set_overwrite(False)


class QuitState(SimpleCommandState):
    command_name = "quit"


class ProjectSelectionDialog(QtWidgets.QFileDialog):
    STATE_CLASS = None
    DIALOG_TITLE = ""
    ACCEPT_LABEL = ""
    REQUIRE_EXISTING = False
    OPERATION_LABEL = None

    def __init__(self, services, parent=None):
        self.services = services
        self.state = self.STATE_CLASS()
        self._selected_path = None
        dialog_parent = parent
        if dialog_parent is None:
            dialog_parent = services.get("ui")
        super().__init__(dialog_parent, self.DIALOG_TITLE, DEFAULT_PROJECTS_DIR)
        self.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        self.setFileMode(QtWidgets.QFileDialog.Directory)
        self.setAcceptMode(self.accept_mode())
        self.setLabelText(QtWidgets.QFileDialog.Accept, self.ACCEPT_LABEL)
        self.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)

        self._file_name_edit = self.findChild(QtWidgets.QLineEdit, "fileNameEdit")
        self._accept_button = None
        for button in self.findChildren(QtWidgets.QPushButton):
            if button.text() == self.labelText(QtWidgets.QFileDialog.Accept):
                self._accept_button = button
                break

        if self._file_name_edit is not None:
            self._file_name_edit.textChanged.connect(self._sync_state_from_widgets)
        self.currentChanged.connect(lambda _path: self._sync_state_from_widgets())
        self.directoryEntered.connect(lambda _path: self._sync_state_from_widgets())

        suggested_path = self.suggested_project_path()
        if suggested_path:
            self.selectFile(suggested_path)
        self._sync_state_from_widgets()

    def accept_mode(self):
        if self.REQUIRE_EXISTING:
            return QtWidgets.QFileDialog.AcceptOpen
        return QtWidgets.QFileDialog.AcceptSave

    def suggested_project_path(self):
        return os.path.join(DEFAULT_PROJECTS_DIR, "untitled.hy")

    def current_project_path(self):
        if self._file_name_edit is not None:
            text = self._file_name_edit.text().strip()
            if text:
                return os.path.abspath(self.directory().absoluteFilePath(text))
        selected_files = super().selectedFiles()
        if selected_files:
            return os.path.abspath(selected_files[0])
        return None

    def _sync_state_from_widgets(self):
        self.state.set_project_dir(self.current_project_path())
        self.update_accept_button()

    def _allows_project_dir(self, project_dir):
        enabled = bool(project_dir and project_dir.endswith(".hy"))
        if enabled and self.REQUIRE_EXISTING:
            enabled = os.path.isdir(project_dir)
        return enabled

    def update_accept_button(self):
        if self._accept_button is None:
            return
        self._accept_button.setEnabled(
            self._allows_project_dir(self.current_project_path())
        )

    def accept(self):
        project_dir = self.current_project_path()
        if project_dir is None:
            return
        self._selected_path = project_dir
        QtWidgets.QDialog.accept(self)

    def selectedFiles(self):
        if self._selected_path is not None:
            return [self._selected_path]
        return super().selectedFiles()

    def validate_selected_project_dir(self, project_dir):
        if not project_dir:
            return False
        if not project_dir.endswith(".hy"):
            QtWidgets.QMessageBox.warning(
                self.services["ui"],
                "Invalid Project Directory",
                "Hyde projects must be directories ending in .hy.",
            )
            return False
        if os.path.exists(project_dir) and not os.path.isdir(project_dir):
            QtWidgets.QMessageBox.warning(
                self.services["ui"],
                "Invalid Project Path",
                f"{project_dir} is not a directory.",
            )
            return False
        if self.REQUIRE_EXISTING and not os.path.isdir(project_dir):
            QtWidgets.QMessageBox.warning(
                self.services["ui"],
                "Missing Project Directory",
                f"{project_dir} does not exist.",
            )
            return False
        return True

    def prepare_for_dispatch(self, project_dir):
        del project_dir
        return True

    def dispatch_python(self):
        if self.OPERATION_LABEL:
            self.services["begin_project_operation"](self.OPERATION_LABEL)
        self.services["execute_command"](self.state.python_source(), visible=True)
        return True

    def run(self):
        if not self.exec_():
            return False
        selected_files = self.selectedFiles()
        if not selected_files:
            return False
        project_dir = os.path.abspath(selected_files[0])
        self.state.set_project_dir(project_dir)
        if not self.validate_selected_project_dir(project_dir):
            return False
        if not self.prepare_for_dispatch(project_dir):
            return False
        return self.dispatch_python()


class NewProjectDialog(ProjectSelectionDialog):
    STATE_CLASS = NewProjectState
    DIALOG_TITLE = "Create New Hyde Project"
    ACCEPT_LABEL = "Create New"
    OPERATION_LABEL = "Creating Hyde project..."

    def suggested_project_path(self):
        os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
        return super().suggested_project_path()

    def prepare_for_dispatch(self, project_dir):
        overwrite = False
        if self.services["project_target_needs_confirmation"](project_dir):
            if not self.services["confirm_overwrite_project"](project_dir):
                return False
            overwrite = True
        self.state.set_overwrite(overwrite)
        return True


class LoadProjectDialog(ProjectSelectionDialog):
    STATE_CLASS = LoadProjectState
    DIALOG_TITLE = "Open Hyde Project"
    ACCEPT_LABEL = "Open"
    REQUIRE_EXISTING = True
    OPERATION_LABEL = "Loading Hyde project..."


class HealProjectDialog(ProjectSelectionDialog):
    STATE_CLASS = HealProjectState
    DIALOG_TITLE = "Heal Hyde Project"
    ACCEPT_LABEL = "Heal"
    REQUIRE_EXISTING = True
    OPERATION_LABEL = "Healing Hyde project..."


class _ProjectSaveDialog(ProjectSelectionDialog):
    OPERATION_LABEL = "Saving Hyde project..."

    def suggested_project_path(self):
        os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
        current_project_dir = self.services["get_current_project_dir"]()
        suggested_name = (
            os.path.splitext(os.path.basename(current_project_dir))[0] + ".hy"
            if current_project_dir
            else "untitled.hy"
        )
        return os.path.join(DEFAULT_PROJECTS_DIR, suggested_name)

    def run(self):
        current_project_dir = self.services["get_current_project_dir"]()
        if not current_project_dir:
            return False
        if not self.exec_():
            return False
        selected_files = self.selectedFiles()
        if not selected_files:
            return False
        project_dir = os.path.abspath(selected_files[0])
        if os.path.abspath(project_dir) == os.path.abspath(current_project_dir):
            return self.handle_current_project_target()
        self.state.set_project_dir(project_dir)
        if not self.validate_selected_project_dir(project_dir):
            return False
        if not self.prepare_for_dispatch(project_dir):
            return False
        return self.dispatch_python()

    def prepare_for_dispatch(self, project_dir):
        if self.services["project_target_needs_confirmation"](project_dir):
            if not self.services["confirm_overwrite_project"](project_dir):
                return False
            self.state.set_overwrite(True)
        return True

    def handle_current_project_target(self):
        return SaveProjectCommand(self.services).run()


class SaveAsProjectDialog(_ProjectSaveDialog):
    STATE_CLASS = SaveAsProjectState
    DIALOG_TITLE = "Save Hyde Project As"
    ACCEPT_LABEL = "Save As"
    OPERATION_LABEL = "Saving Hyde project..."


class SaveCopyProjectDialog(_ProjectSaveDialog):
    STATE_CLASS = SaveCopyProjectState
    DIALOG_TITLE = "Save Hyde Project Copy"
    ACCEPT_LABEL = "Save Copy"
    OPERATION_LABEL = "Saving Hyde project copy..."

    def handle_current_project_target(self):
        QtWidgets.QMessageBox.warning(
            self.services["ui"],
            "Invalid Copy Target",
            "Save a Copy... requires a different .hy directory than the current project.",
        )
        return False


class SaveProjectCommand:
    def __init__(self, services):
        self.services = services
        self.state = SaveProjectState()

    def run(self):
        if not self.services["get_current_project_dir"]():
            return False
        self.services["begin_project_operation"]("Saving Hyde project...")
        self.services["execute_command"](self.state.python_source(), visible=True)
        return True


class QuitCommand:
    def __init__(self, services):
        self.services = services
        self.state = QuitState()

    def run(self):
        if self.services["get_shutting_down"]() or self.services["get_quit_command_sent"]():
            return False
        self.services["set_quit_command_sent"](True)
        self.services["execute_command"](self.state.python_source(), visible=True)
        return True


__all__ = [
    "HealProjectDialog",
    "HealProjectState",
    "LoadProjectDialog",
    "LoadProjectState",
    "NewProjectDialog",
    "NewProjectState",
    "ProjectSelectionDialog",
    "QuitCommand",
    "QuitState",
    "SaveAsProjectDialog",
    "SaveAsProjectState",
    "SaveCopyProjectDialog",
    "SaveCopyProjectState",
    "SaveProjectCommand",
    "SaveProjectState",
    "SimpleCommandState",
]
