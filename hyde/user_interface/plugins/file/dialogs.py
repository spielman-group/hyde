import os

from hyde.features.hyde_ir import (
    HydeAppIR,
    project_paths_match,
)
from hyde.paths import DEFAULT_PROJECTS_DIR
from hyde.user_interface.base_hyde_widgets import HydeFileDialog


class ProjectSelectionDialog(HydeFileDialog):
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
    same_target_validation_message = None
    app_command = None
    save_mode = "save"
    load_new_project = True

    def __init__(self, services, parent=None):
        dialog_parent = parent
        if dialog_parent is None:
            dialog_parent = services.get("ui")
        super().__init__(dialog_parent, services=services)
        self.setWindowTitle(self.dialog_title)

    def provided_app_ir(self, services):
        get_current_app_ir = services.get("get_current_app_ir")
        if callable(get_current_app_ir):
            app_ir = get_current_app_ir()
            if isinstance(app_ir, HydeAppIR):
                return app_ir
        get_current_project_dir = services.get("get_current_project_dir")
        current_project_dir = (
            get_current_project_dir() if callable(get_current_project_dir) else None
        )
        return HydeAppIR(current_project_dir=current_project_dir)

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
        return self.provided_app_ir(self.services).current_project_dir

    def paths_match(self, left_path, right_path):
        return project_paths_match(left_path, right_path)

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

    def build_widget_ir(self, selected_path):
        app_ir = self.provided_app_ir(self.services)
        same_target = self.paths_match(selected_path, app_ir.current_project_dir)
        overwrite = bool(selected_path) and self.confirm_overwrite and self.needs_overwrite_confirmation(
            selected_path
        )
        if self.app_command == "new_project":
            return app_ir.with_new_project(
                selected_path,
                load=self.load_new_project,
                overwrite=overwrite,
            )
        if self.app_command == "load_project":
            return app_ir.with_load_project(selected_path)
        if self.app_command == "heal_project":
            return app_ir.with_heal_project(selected_path)
        if self.app_command == "save_project":
            if self.save_mode == "save_as" and same_target:
                return app_ir.with_save_project(mode="save")
            return app_ir.with_save_project(
                target_project_dir=selected_path,
                mode=self.save_mode,
                overwrite=overwrite,
            )
        raise ValueError(f"Unsupported app_command: {self.app_command!r}.")

    def execute_do_it_payload(self, payload):
        begin_project_operation = self.services.get("begin_project_operation")
        if self.operation_label and callable(begin_project_operation):
            begin_project_operation(self.operation_label)
        return super().execute_do_it_payload(payload)

    def needs_overwrite_confirmation(self, selected_path):
        if not self.confirm_overwrite:
            return False
        current_project_dir = self.current_project_dir()
        if self.paths_match(selected_path, current_project_dir):
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
    app_command = "new_project"
    dialog_title = "Create New Hyde Project"
    operation_label = "Creating Hyde project..."
    confirm_overwrite = True
    ensure_projects_dir = True


class LoadProjectDialog(ProjectSelectionDialog):
    app_command = "load_project"
    dialog_title = "Open Hyde Project"
    require_existing = True
    operation_label = "Loading Hyde project..."


class HealProjectDialog(ProjectSelectionDialog):
    app_command = "heal_project"
    dialog_title = "Heal Hyde Project"
    require_existing = True
    operation_label = "Healing Hyde project..."


class ProjectSaveTargetDialog(ProjectSelectionDialog):
    app_command = "save_project"
    operation_label = "Saving Hyde project..."
    confirm_overwrite = True
    ensure_projects_dir = True
    suggest_current_project_name = True
    require_current_project = True


class SaveAsProjectDialog(ProjectSaveTargetDialog):
    dialog_title = "Save Hyde Project As"
    save_mode = "save_as"


class SaveCopyProjectDialog(ProjectSaveTargetDialog):
    dialog_title = "Save Hyde Project Copy"
    operation_label = "Saving Hyde project copy..."
    save_mode = "copy"
    same_target_validation_message = (
        "Save a Copy... requires a different .hy directory than the current project."
    )


__all__ = [
    "HealProjectDialog",
    "LoadProjectDialog",
    "NewProjectDialog",
    "ProjectSelectionDialog",
    "ProjectSaveTargetDialog",
    "SaveAsProjectDialog",
    "SaveCopyProjectDialog",
]
