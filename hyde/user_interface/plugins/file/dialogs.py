import os

from hyde.features.hyde_features import SimpleHydeCommandCodec
from hyde.paths import DEFAULT_PROJECTS_DIR
from hyde.user_interface.base_hyde_widgets import HydeFileDialog
from hyde.user_interface.shared.core import HydeGuiState


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


class ProjectSelectionDialog(HydeFileDialog):
    state_class = None
    dialog_title = ""
    operation_label = None
    selection_mode = "directory"
    allowed_suffixes = (".hy",)
    name_filters = ("Hyde Packages (*.hy)",)
    require_existing = False
    ensure_projects_dir = False
    suggest_current_project_name = False
    require_current_project = False
    no_current_project_message = "No current Hyde project is active."
    same_target_state_class = None
    same_target_validation_message = None

    def __init__(self, services, parent=None):
        dialog_parent = parent
        if dialog_parent is None:
            dialog_parent = services.get("ui")
        super().__init__(dialog_parent, services=services)
        self.setWindowTitle(self.dialog_title)

    def suggested_path(self):
        if self.ensure_projects_dir:
            os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
        current_project_dir = self.current_project_dir()
        return os.path.join(
            DEFAULT_PROJECTS_DIR,
            self.suggested_project_name(current_project_dir),
        )

    def suggested_project_name(self, current_project_dir):
        if self.suggest_current_project_name and current_project_dir:
            return os.path.splitext(os.path.basename(current_project_dir))[0] + ".hy"
        return "untitled.hy"

    def current_project_dir(self):
        get_current_project_dir = self.services.get("get_current_project_dir")
        if callable(get_current_project_dir):
            return get_current_project_dir()
        return None

    def paths_match(self, left_path, right_path):
        if not left_path or not right_path:
            return False
        return os.path.abspath(left_path) == os.path.abspath(right_path)

    def selection_validation_message(self, selected_path):
        current_project_dir = self.current_project_dir()
        if self.require_current_project and current_project_dir is None:
            return self.no_current_project_message
        if (
            self.same_target_validation_message is not None
            and self.paths_match(selected_path, current_project_dir)
        ):
            return self.same_target_validation_message
        return None

    def build_state_for_selected_path(self, selected_path):
        current_project_dir = self.current_project_dir()
        if (
            self.same_target_state_class is not None
            and self.paths_match(selected_path, current_project_dir)
        ):
            state = self.same_target_state_class()
        else:
            state = self.state_class()
            state.set_project_dir(selected_path)
        if self.confirm_overwrite:
            state.set_overwrite(self.needs_overwrite_confirmation(selected_path))
        return state

    def build_preview_state(self, selected_path):
        return self.build_state_for_selected_path(selected_path)

    def execute_do_it_payload(self, payload):
        begin_project_operation = self.services.get("begin_project_operation")
        if self.operation_label and callable(begin_project_operation):
            begin_project_operation(self.operation_label)
        return super().execute_do_it_payload(payload)

    def needs_overwrite_confirmation(self, selected_path):
        if not self.confirm_overwrite:
            return False
        current_project_dir = self.current_project_dir()
        if (
            self.same_target_state_class is not None
            and self.paths_match(selected_path, current_project_dir)
        ):
            return False
        project_target_needs_confirmation = self.services.get(
            "project_target_needs_confirmation"
        )
        if callable(project_target_needs_confirmation):
            return bool(project_target_needs_confirmation(selected_path))
        return super().needs_overwrite_confirmation(selected_path)

    def confirm_overwrite_target(self, selected_path):
        confirm_overwrite_project = self.services.get("confirm_overwrite_project")
        if callable(confirm_overwrite_project):
            return bool(confirm_overwrite_project(selected_path))
        return super().confirm_overwrite_target(selected_path)


class NewProjectDialog(ProjectSelectionDialog):
    state_class = NewProjectState
    dialog_title = "Create New Hyde Project"
    operation_label = "Creating Hyde project..."
    confirm_overwrite = True
    ensure_projects_dir = True


class LoadProjectDialog(ProjectSelectionDialog):
    state_class = LoadProjectState
    dialog_title = "Open Hyde Project"
    require_existing = True
    operation_label = "Loading Hyde project..."


class HealProjectDialog(ProjectSelectionDialog):
    state_class = HealProjectState
    dialog_title = "Heal Hyde Project"
    require_existing = True
    operation_label = "Healing Hyde project..."


class ProjectSaveTargetDialog(ProjectSelectionDialog):
    operation_label = "Saving Hyde project..."
    confirm_overwrite = True
    ensure_projects_dir = True
    suggest_current_project_name = True
    require_current_project = True


class SaveAsProjectDialog(ProjectSaveTargetDialog):
    state_class = SaveAsProjectState
    dialog_title = "Save Hyde Project As"
    same_target_state_class = SaveProjectState


class SaveCopyProjectDialog(ProjectSaveTargetDialog):
    state_class = SaveCopyProjectState
    dialog_title = "Save Hyde Project Copy"
    operation_label = "Saving Hyde project copy..."
    same_target_validation_message = (
        "Save a Copy... requires a different .hy directory than the current project."
    )

__all__ = [
    "HealProjectDialog",
    "HealProjectState",
    "LoadProjectDialog",
    "LoadProjectState",
    "NewProjectDialog",
    "NewProjectState",
    "ProjectSelectionDialog",
    "ProjectSaveTargetDialog",
    "QuitState",
    "SaveAsProjectDialog",
    "SaveAsProjectState",
    "SaveCopyProjectDialog",
    "SaveCopyProjectState",
    "SaveProjectState",
    "SimpleCommandState",
]
