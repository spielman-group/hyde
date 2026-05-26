import os
import textwrap
from dataclasses import dataclass, replace

from hyde.features.hyde_features import (
    heal_project_source,
    load_project_source,
    new_project_source,
    quit_source,
    save_project_source,
)
from hyde.paths import DEFAULT_PROJECTS_DIR
from hyde.user_interface.base_hyde_widgets import HydeFileDialog
from hyde.user_interface.shared.core import HydeIR, HydeIRDiff


VALID_APP_COMMANDS = {
    "new_project",
    "load_project",
    "heal_project",
    "save_project",
    "quit",
    "reload_procedures",
    "remote_request",
    "callable_invocation",
    "session_restore",
}
VALID_SAVE_MODES = {"save", "save_as", "copy"}


def normalize_project_dir(project_dir):
    if project_dir in (None, ""):
        return None
    return os.path.abspath(str(project_dir))


def project_paths_match(left_path, right_path):
    left_path = normalize_project_dir(left_path)
    right_path = normalize_project_dir(right_path)
    if not left_path or not right_path:
        return False
    return left_path == right_path


def app_ir_python_source(
    *,
    command,
    target_project_dir=None,
    save_mode="save",
    load=True,
    overwrite=False,
    project_dir=None,
    hyde_source_root=None,
    reset_namespace=False,
    request_filepath=None,
    callable_name=None,
    callable_args=(),
    session_source=None,
):
    if command == "new_project":
        return new_project_source(
            target_project_dir,
            load=load,
            overwrite=overwrite,
        )
    if command == "load_project":
        return load_project_source(target_project_dir)
    if command == "heal_project":
        return heal_project_source(target_project_dir)
    if command == "save_project":
        if save_mode == "save":
            return save_project_source(mode="save")
        return save_project_source(
            target_project_dir,
            mode=save_mode,
            overwrite=overwrite,
        )
    if command == "quit":
        return quit_source()
    if command == "reload_procedures":
        return (
            "import sys\n"
            f"if {hyde_source_root!r} not in sys.path:\n"
            f"    sys.path.insert(0, {hyde_source_root!r})\n"
            "from hyde.project_tools import execute_procedures_bootstrap\n"
            f"execute_procedures_bootstrap({project_dir!r}, "
            f"{hyde_source_root!r}, "
            f"reset_namespace={bool(reset_namespace)!r})\n"
        )
    if command == "remote_request":
        return f"remote({request_filepath!r})"
    if command == "callable_invocation":
        args = ", ".join(callable_args)
        return f"{callable_name}({args})"
    if command == "session_restore":
        indented_source = textwrap.indent(f"{session_source}\n", "    ")
        return (
            "import hyde\n"
            "try:\n"
            f"{indented_source}"
            "except Exception:\n"
            '    hyde.task_complete("session_restore", False)\n'
            "    raise\n"
            "else:\n"
            '    hyde.task_complete("session_restore", True)\n'
        )
    raise ValueError(f"Unsupported Hyde app command: {command!r}.")


@dataclass(frozen=True)
class HydeAppIR(HydeIR):
    current_project_dir: str | None = None
    command: str | None = None
    target_project_dir: str | None = None
    save_mode: str = "save"
    load: bool = True
    overwrite: bool = False
    project_dir: str | None = None
    hyde_source_root: str | None = None
    reset_namespace: bool = False
    request_filepath: str | None = None
    callable_name: str | None = None
    callable_args: tuple[str, ...] = ()
    session_source: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "current_project_dir",
            normalize_project_dir(self.current_project_dir),
        )
        object.__setattr__(
            self,
            "target_project_dir",
            normalize_project_dir(self.target_project_dir),
        )
        if self.command is not None:
            object.__setattr__(self, "command", str(self.command))
        object.__setattr__(self, "save_mode", str(self.save_mode))
        object.__setattr__(self, "load", bool(self.load))
        object.__setattr__(self, "overwrite", bool(self.overwrite))
        object.__setattr__(self, "project_dir", normalize_project_dir(self.project_dir))
        if self.hyde_source_root is None:
            object.__setattr__(self, "hyde_source_root", None)
        else:
            object.__setattr__(self, "hyde_source_root", str(self.hyde_source_root))
        object.__setattr__(self, "reset_namespace", bool(self.reset_namespace))
        if self.request_filepath is None:
            object.__setattr__(self, "request_filepath", None)
        else:
            object.__setattr__(self, "request_filepath", str(self.request_filepath))
        if self.callable_name is None:
            object.__setattr__(self, "callable_name", None)
        else:
            object.__setattr__(self, "callable_name", str(self.callable_name))
        object.__setattr__(
            self,
            "callable_args",
            tuple(str(value) for value in (self.callable_args or ()) if str(value)),
        )
        if self.session_source is None:
            object.__setattr__(self, "session_source", None)
        else:
            object.__setattr__(self, "session_source", str(self.session_source))

    def debug_state(self):
        return {
            "current_project_dir": self.current_project_dir,
            "command": self.command,
            "target_project_dir": self.target_project_dir,
            "save_mode": self.save_mode,
            "load": self.load,
            "overwrite": self.overwrite,
            "project_dir": self.project_dir,
            "hyde_source_root": self.hyde_source_root,
            "reset_namespace": self.reset_namespace,
            "request_filepath": self.request_filepath,
            "callable_name": self.callable_name,
            "callable_args": list(self.callable_args),
            "session_source": self.session_source,
        }

    def validate(self):
        if self.command not in VALID_APP_COMMANDS:
            raise ValueError(f"Unsupported Hyde app command: {self.command!r}.")
        if self.command in {"new_project", "load_project", "heal_project"}:
            if not self.target_project_dir:
                raise ValueError(f"{self.command} requires a project target.")
        if self.command == "save_project":
            if self.save_mode not in VALID_SAVE_MODES:
                raise ValueError(f"Unsupported save mode: {self.save_mode!r}.")
            if self.save_mode != "save" and not self.target_project_dir:
                raise ValueError(f"{self.save_mode} requires a project target.")
        if self.command == "reload_procedures":
            if not self.project_dir:
                raise ValueError("reload_procedures requires a project directory.")
            if not self.hyde_source_root:
                raise ValueError("reload_procedures requires a Hyde source root.")
        if self.command == "remote_request" and not self.request_filepath:
            raise ValueError("remote_request requires a request filepath.")
        if self.command == "callable_invocation" and not self.callable_name:
            raise ValueError("callable_invocation requires a callable name.")
        if self.command == "session_restore" and not self.session_source:
            raise ValueError("session_restore requires session source.")
        return self

    def with_new_project(self, project_dir, *, load=True, overwrite=False):
        return replace(
            self,
            command="new_project",
            target_project_dir=project_dir,
            save_mode="save",
            load=load,
            overwrite=overwrite,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=None,
            callable_name=None,
            callable_args=(),
            session_source=None,
        )

    def with_load_project(self, project_dir):
        return replace(
            self,
            command="load_project",
            target_project_dir=project_dir,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=None,
            callable_name=None,
            callable_args=(),
            session_source=None,
        )

    def with_heal_project(self, project_dir):
        return replace(
            self,
            command="heal_project",
            target_project_dir=project_dir,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=None,
            callable_name=None,
            callable_args=(),
            session_source=None,
        )

    def with_save_project(self, *, target_project_dir=None, mode="save", overwrite=False):
        return replace(
            self,
            command="save_project",
            target_project_dir=target_project_dir,
            save_mode=mode,
            overwrite=overwrite,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=None,
            callable_name=None,
            callable_args=(),
            session_source=None,
        )

    def with_quit(self):
        return replace(
            self,
            command="quit",
            target_project_dir=None,
            save_mode="save",
            overwrite=False,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=None,
            callable_name=None,
            callable_args=(),
            session_source=None,
        )

    def with_reload_procedures(
        self,
        project_dir,
        hyde_source_root,
        *,
        reset_namespace=False,
    ):
        return replace(
            self,
            command="reload_procedures",
            target_project_dir=None,
            save_mode="save",
            overwrite=False,
            project_dir=project_dir,
            hyde_source_root=hyde_source_root,
            reset_namespace=reset_namespace,
            request_filepath=None,
            callable_name=None,
            callable_args=(),
            session_source=None,
        )

    def with_remote_request(self, request_filepath):
        return replace(
            self,
            command="remote_request",
            target_project_dir=None,
            save_mode="save",
            overwrite=False,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=request_filepath,
            callable_name=None,
            callable_args=(),
            session_source=None,
        )

    def with_callable_invocation(self, callable_name, args):
        return replace(
            self,
            command="callable_invocation",
            target_project_dir=None,
            save_mode="save",
            overwrite=False,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=None,
            callable_name=callable_name,
            callable_args=tuple(args or ()),
            session_source=None,
        )

    def with_session_restore_source(self, session_source):
        return replace(
            self,
            command="session_restore",
            target_project_dir=None,
            save_mode="save",
            overwrite=False,
            project_dir=None,
            hyde_source_root=None,
            reset_namespace=False,
            request_filepath=None,
            callable_name=None,
            callable_args=(),
            session_source=session_source,
        )

    def current_diff(self, current_ir=None):
        resolved_current = self if current_ir is None else current_ir
        return HydeAppIRDiff.from_irs(self, resolved_current)

    def _python_source(self):
        return app_ir_python_source(
            command=self.command,
            target_project_dir=self.target_project_dir,
            save_mode=self.save_mode,
            load=self.load,
            overwrite=self.overwrite,
            project_dir=self.project_dir,
            hyde_source_root=self.hyde_source_root,
            reset_namespace=self.reset_namespace,
            request_filepath=self.request_filepath,
            callable_name=self.callable_name,
            callable_args=self.callable_args,
            session_source=self.session_source,
        )


@dataclass(frozen=True)
class HydeAppIRDiff(HydeIRDiff):
    initial_project_dir: str | None = None
    current_project_dir: str | None = None
    command: str | None = None
    target_project_dir: str | None = None
    save_mode: str = "save"
    load: bool = True
    overwrite: bool = False
    project_dir: str | None = None
    hyde_source_root: str | None = None
    reset_namespace: bool = False
    request_filepath: str | None = None
    callable_name: str | None = None
    callable_args: tuple[str, ...] = ()
    session_source: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "initial_project_dir",
            normalize_project_dir(self.initial_project_dir),
        )
        object.__setattr__(
            self,
            "current_project_dir",
            normalize_project_dir(self.current_project_dir),
        )
        object.__setattr__(
            self,
            "target_project_dir",
            normalize_project_dir(self.target_project_dir),
        )
        if self.command is not None:
            object.__setattr__(self, "command", str(self.command))
        object.__setattr__(self, "save_mode", str(self.save_mode))
        object.__setattr__(self, "load", bool(self.load))
        object.__setattr__(self, "overwrite", bool(self.overwrite))
        object.__setattr__(self, "project_dir", normalize_project_dir(self.project_dir))
        if self.hyde_source_root is None:
            object.__setattr__(self, "hyde_source_root", None)
        else:
            object.__setattr__(self, "hyde_source_root", str(self.hyde_source_root))
        object.__setattr__(self, "reset_namespace", bool(self.reset_namespace))
        if self.request_filepath is None:
            object.__setattr__(self, "request_filepath", None)
        else:
            object.__setattr__(self, "request_filepath", str(self.request_filepath))
        if self.callable_name is None:
            object.__setattr__(self, "callable_name", None)
        else:
            object.__setattr__(self, "callable_name", str(self.callable_name))
        object.__setattr__(
            self,
            "callable_args",
            tuple(str(value) for value in (self.callable_args or ()) if str(value)),
        )
        if self.session_source is None:
            object.__setattr__(self, "session_source", None)
        else:
            object.__setattr__(self, "session_source", str(self.session_source))

    @classmethod
    def from_irs(cls, initial_ir, current_ir):
        return cls(
            initial_project_dir=initial_ir.current_project_dir,
            current_project_dir=current_ir.current_project_dir,
            command=current_ir.command,
            target_project_dir=current_ir.target_project_dir,
            save_mode=current_ir.save_mode,
            load=current_ir.load,
            overwrite=current_ir.overwrite,
            project_dir=current_ir.project_dir,
            hyde_source_root=current_ir.hyde_source_root,
            reset_namespace=current_ir.reset_namespace,
            request_filepath=current_ir.request_filepath,
            callable_name=current_ir.callable_name,
            callable_args=current_ir.callable_args,
            session_source=current_ir.session_source,
        )

    def debug_state(self):
        return {
            "initial_project_dir": self.initial_project_dir,
            "current_project_dir": self.current_project_dir,
            "command": self.command,
            "target_project_dir": self.target_project_dir,
            "save_mode": self.save_mode,
            "load": self.load,
            "overwrite": self.overwrite,
            "project_dir": self.project_dir,
            "hyde_source_root": self.hyde_source_root,
            "reset_namespace": self.reset_namespace,
            "request_filepath": self.request_filepath,
            "callable_name": self.callable_name,
            "callable_args": list(self.callable_args),
            "session_source": self.session_source,
        }

    def validate(self):
        HydeAppIR(
            current_project_dir=self.current_project_dir,
            command=self.command,
            target_project_dir=self.target_project_dir,
            save_mode=self.save_mode,
            load=self.load,
            overwrite=self.overwrite,
            project_dir=self.project_dir,
            hyde_source_root=self.hyde_source_root,
            reset_namespace=self.reset_namespace,
            request_filepath=self.request_filepath,
            callable_name=self.callable_name,
            callable_args=self.callable_args,
            session_source=self.session_source,
        ).validate()
        return self

    def _python_source(self):
        return app_ir_python_source(
            command=self.command,
            target_project_dir=self.target_project_dir,
            save_mode=self.save_mode,
            load=self.load,
            overwrite=self.overwrite,
            project_dir=self.project_dir,
            hyde_source_root=self.hyde_source_root,
            reset_namespace=self.reset_namespace,
            request_filepath=self.request_filepath,
            callable_name=self.callable_name,
            callable_args=self.callable_args,
            session_source=self.session_source,
        )


@dataclass(frozen=True)
class ProjectSelectionDialogIR(HydeIR):
    app_ir: HydeAppIR
    app_command: str | None = None
    selected_path: str | None = None
    save_mode: str = "save"
    load_new_project: bool = True
    overwrite: bool = False

    def __post_init__(self):
        if not isinstance(self.app_ir, HydeAppIR):
            raise TypeError("ProjectSelectionDialogIR requires a HydeAppIR snapshot.")
        if self.app_command is not None:
            object.__setattr__(self, "app_command", str(self.app_command))
        object.__setattr__(
            self,
            "selected_path",
            normalize_project_dir(self.selected_path),
        )
        object.__setattr__(self, "save_mode", str(self.save_mode))
        object.__setattr__(self, "load_new_project", bool(self.load_new_project))
        object.__setattr__(self, "overwrite", bool(self.overwrite))

    def debug_state(self):
        return {
            "app_ir": self.app_ir.debug_state(),
            "app_command": self.app_command,
            "selected_path": self.selected_path,
            "save_mode": self.save_mode,
            "load_new_project": self.load_new_project,
            "overwrite": self.overwrite,
        }

    def current_project_dir(self):
        return self.app_ir.current_project_dir

    def target_app_ir(self):
        same_target = project_paths_match(
            self.selected_path,
            self.current_project_dir(),
        )
        if self.app_command == "new_project":
            return self.app_ir.with_new_project(
                self.selected_path,
                load=self.load_new_project,
                overwrite=self.overwrite,
            )
        if self.app_command == "load_project":
            return self.app_ir.with_load_project(self.selected_path)
        if self.app_command == "heal_project":
            return self.app_ir.with_heal_project(self.selected_path)
        if self.app_command == "save_project":
            if self.save_mode == "save_as" and same_target:
                return self.app_ir.with_save_project(mode="save")
            return self.app_ir.with_save_project(
                target_project_dir=self.selected_path,
                mode=self.save_mode,
                overwrite=self.overwrite,
            )
        raise ValueError(f"Unsupported app_command: {self.app_command!r}.")

    def validate(self):
        if not self.selected_path:
            raise ValueError("ProjectSelectionDialogIR requires a project target.")
        self.target_app_ir().validate()
        return self

    def _python_source(self):
        return self.app_ir.current_diff(
            self.target_app_ir()
        ).python_source(log=False)


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

    def app_snapshot_ir(self):
        if isinstance(self.widget_ir, ProjectSelectionDialogIR):
            return self.widget_ir.app_ir
        return self.provided_app_ir(self.services)

    def current_project_dir(self):
        return self.app_snapshot_ir().current_project_dir

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
        overwrite = bool(selected_path) and self.confirm_overwrite and self.needs_overwrite_confirmation(
            selected_path
        )
        return ProjectSelectionDialogIR(
            app_ir=self.app_snapshot_ir(),
            app_command=self.app_command,
            selected_path=selected_path,
            save_mode=self.save_mode,
            load_new_project=self.load_new_project,
            overwrite=overwrite,
        )

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
    "HydeAppIR",
    "HydeAppIRDiff",
    "LoadProjectDialog",
    "NewProjectDialog",
    "ProjectSelectionDialogIR",
    "ProjectSelectionDialog",
    "ProjectSaveTargetDialog",
    "SaveAsProjectDialog",
    "SaveCopyProjectDialog",
]
