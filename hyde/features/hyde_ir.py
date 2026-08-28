import ast
import os
from dataclasses import dataclass, replace

from hyde.features.hyde_features import (
    hyde_app_python_source,
    normalize_namespace_names,
    table_ir_macro_source,
    table_ir_python_source,
    validate_namespace_names,
)
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
    "delete_namespace_names",
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


def normalize_app_namespace_names(namespace_names):
    return normalize_namespace_names(namespace_names)


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
    namespace_names: tuple[str, ...] = ()

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
        object.__setattr__(
            self,
            "namespace_names",
            normalize_app_namespace_names(self.namespace_names),
        )

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
            "namespace_names": list(self.namespace_names),
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
        if self.command == "delete_namespace_names":
            validate_namespace_names(self.namespace_names)
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
            namespace_names=(),
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
            namespace_names=(),
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
            namespace_names=(),
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
            namespace_names=(),
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
            namespace_names=(),
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
            namespace_names=(),
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
            namespace_names=(),
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
            namespace_names=(),
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
            namespace_names=(),
        )

    def with_delete_names(self, names):
        return replace(
            self,
            command="delete_namespace_names",
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
            namespace_names=normalize_app_namespace_names(names),
        )

    def current_diff(self, current_ir=None):
        resolved_current = self if current_ir is None else current_ir
        return HydeAppIRDiff.from_irs(self, resolved_current)

    def _python_source(self):
        return hyde_app_python_source(
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
            namespace_names=self.namespace_names,
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
    namespace_names: tuple[str, ...] = ()

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
        object.__setattr__(
            self,
            "namespace_names",
            normalize_app_namespace_names(self.namespace_names),
        )

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
            namespace_names=current_ir.namespace_names,
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
            "namespace_names": list(self.namespace_names),
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
            namespace_names=self.namespace_names,
        ).validate()
        return self

    def _python_source(self):
        return hyde_app_python_source(
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
            namespace_names=self.namespace_names,
        )

def normalize_table_names(names):
    return tuple(str(name) for name in (names or ()) if str(name))


def normalize_table_name(name):
    return None if name in (None, "") else str(name)


def normalize_table_geometry(geometry):
    if geometry in (None, []):
        return None
    return tuple(int(value) for value in geometry)


def normalize_table_column_widths(column_widths):
    return {
        str(name): int(width)
        for name, width in dict(column_widths or {}).items()
        if str(name) and width is not None
    }


@dataclass(frozen=True)
class TableIR(HydeIR):
    names: tuple[str, ...] = ()
    command: str = "open"
    name: str | None = None
    geometry: tuple[int, int, int, int] | None = None
    column_widths: dict[str, int] | None = None
    request_id: str | None = None
    var_name: str | None = None
    value_text: str | None = None
    index: int | None = None
    indices: tuple[int, ...] | None = None
    existing_names: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "names", normalize_table_names(self.names))
        object.__setattr__(self, "command", str(self.command or "open"))
        object.__setattr__(self, "name", normalize_table_name(self.name))
        object.__setattr__(self, "geometry", normalize_table_geometry(self.geometry))
        object.__setattr__(
            self,
            "column_widths",
            normalize_table_column_widths(self.column_widths),
        )
        if self.request_id in (None, ""):
            object.__setattr__(self, "request_id", None)
        else:
            object.__setattr__(self, "request_id", str(self.request_id))
        object.__setattr__(self, "var_name", normalize_table_name(self.var_name))
        if self.value_text is None:
            object.__setattr__(self, "value_text", None)
        else:
            object.__setattr__(self, "value_text", str(self.value_text))
        if self.index is None:
            object.__setattr__(self, "index", None)
        else:
            object.__setattr__(self, "index", int(self.index))
        if self.indices is None:
            object.__setattr__(self, "indices", None)
        else:
            object.__setattr__(self, "indices", tuple(int(value) for value in self.indices))
        object.__setattr__(
            self,
            "existing_names",
            normalize_table_names(self.existing_names),
        )

    def debug_state(self):
        return {
            "names": list(self.names),
            "command": self.command,
            "name": self.name,
            "geometry": self.geometry,
            "column_widths": dict(self.column_widths or {}),
            "request_id": self.request_id,
            "var_name": self.var_name,
            "value_text": self.value_text,
            "index": self.index,
            "indices": None if self.indices is None else list(self.indices),
            "existing_names": list(self.existing_names),
        }

    def validate(self):
        if self.command in {"open", "append", "push_table_data"} and not self.names:
            raise ValueError(f"Table command {self.command!r} requires at least one item.")
        if self.command == "append" and not self.name:
            raise ValueError("Table append requires a target name.")
        if self.command == "push_table_data" and not self.request_id:
            raise ValueError("Table data push requires a request_id.")
        if self.command not in {
            "open",
            "append",
            "push_table_data",
            "publish_table_macros",
            "edit_value",
            "append_value",
            "create_array",
            "delete_indices",
        }:
            raise ValueError(f"Unsupported table command: {self.command!r}.")
        if self.command in {"edit_value", "append_value", "delete_indices"} and not self.var_name:
            raise ValueError(f"Table command {self.command!r} requires var_name.")
        if self.command in {"edit_value", "append_value", "create_array"}:
            self.format_entry_literal(self.value_text)
        if self.command == "create_array" and not self.var_name:
            raise ValueError("Table create_array requires var_name.")
        if self.command == "edit_value" and self.index is None:
            raise ValueError("Table edit_value requires index.")
        if self.command == "delete_indices" and self.indices is None:
            raise ValueError("Table delete_indices requires indices.")
        if self.geometry is not None and len(self.geometry) != 4:
            raise ValueError("Table geometry must contain four integers.")
        for width in self.column_widths.values():
            if width <= 0:
                raise ValueError("Table column widths must be positive integers.")
        return self

    @staticmethod
    def format_entry_literal(value_text):
        text = str(value_text or "").strip()
        if not text:
            raise ValueError("Empty cell edits are not supported.")
        try:
            value = ast.literal_eval(text)
        except Exception:
            value = text
        return repr(value)

    @staticmethod
    def suggest_new_array_name(existing_names, value_text):
        existing = {str(name) for name in (existing_names or ())}
        try:
            value = ast.literal_eval(str(value_text).strip())
        except Exception:
            value = value_text
        prefix = "string_array" if isinstance(value, str) else "array"
        index = 0
        while f"{prefix}{index}" in existing:
            index += 1
        return f"{prefix}{index}"

    def with_names(self, names):
        return replace(self, names=normalize_table_names(names))

    def with_command(self, command):
        return replace(self, command=command)

    def with_name(self, name):
        return replace(self, name=normalize_table_name(name))

    def with_geometry(self, geometry):
        return replace(self, geometry=normalize_table_geometry(geometry))

    def with_column_widths(self, column_widths):
        return replace(self, column_widths=normalize_table_column_widths(column_widths))

    def with_column_width(self, name, width):
        widths = dict(self.column_widths)
        widths[str(name)] = int(width)
        return replace(self, column_widths=widths)

    def with_push_table_data(self, request_id):
        return replace(self, command="push_table_data", request_id=str(request_id))

    def with_edit_value(self, var_name, index, value_text):
        return replace(
            self,
            command="edit_value",
            var_name=var_name,
            value_text=value_text,
            index=index,
            indices=None,
            request_id=None,
        )

    def with_append_value(self, var_name, value_text):
        return replace(
            self,
            command="append_value",
            var_name=var_name,
            value_text=value_text,
            index=None,
            indices=None,
            request_id=None,
        )

    def with_create_array(self, value_text, existing_names):
        return replace(
            self,
            command="create_array",
            var_name=self.suggest_new_array_name(existing_names, value_text),
            value_text=value_text,
            index=None,
            indices=None,
            existing_names=tuple(existing_names or ()),
            request_id=None,
        )

    def with_delete_indices(self, var_name, indices):
        return replace(
            self,
            command="delete_indices",
            var_name=var_name,
            value_text=None,
            index=None,
            indices=tuple(indices or ()),
            request_id=None,
        )

    def with_publish_table_macros(self):
        return replace(
            self,
            names=(),
            command="publish_table_macros",
            request_id=None,
        )

    def default_macro_name(self):
        return self.name or "Table"

    def recreation_function_source(self, macro_name, *, name=None):
        return table_ir_macro_source(
            macro_name=macro_name,
            names=self.names,
            name=self.name if name is None else normalize_table_name(name),
            geometry=self.geometry,
            column_widths=self.column_widths,
        )

    def macro_source(self, macro_name):
        return self.recreation_function_source(macro_name)

    def _python_source(self):
        if self.command == "edit_value":
            return f"{self.var_name}[{self.index}] = {self.format_entry_literal(self.value_text)}"
        if self.command == "append_value":
            literal = self.format_entry_literal(self.value_text)
            return (
                f"{self.var_name} = np.concatenate(("
                f"{self.var_name}, np.array([{literal}], dtype={self.var_name}.dtype)"
                f"))"
            )
        if self.command == "create_array":
            literal = self.format_entry_literal(self.value_text)
            return f"{self.var_name} = np.array([{literal}])"
        if self.command == "delete_indices":
            indices = sorted(set(self.indices or ()))
            return f"{self.var_name} = np.delete({self.var_name}, {indices!r})"
        return table_ir_python_source(
            command=self.command,
            names=self.names,
            name=self.name,
            geometry=self.geometry,
            column_widths=self.column_widths,
            request_id=self.request_id,
        )


@dataclass(frozen=True)
class TableIRDiff(TableIR, HydeIRDiff):
    initial_names: tuple[str, ...] = ()
    initial_name: str | None = None
    initial_geometry: tuple[int, int, int, int] | None = None
    initial_column_widths: dict[str, int] | None = None

    def __post_init__(self):
        super().__post_init__()
        object.__setattr__(self, "initial_names", normalize_table_names(self.initial_names))
        object.__setattr__(self, "initial_name", normalize_table_name(self.initial_name))
        object.__setattr__(
            self,
            "initial_geometry",
            normalize_table_geometry(self.initial_geometry),
        )
        object.__setattr__(
            self,
            "initial_column_widths",
            normalize_table_column_widths(self.initial_column_widths),
        )

    @classmethod
    def from_irs(cls, initial_ir, current_ir):
        return cls(
            names=current_ir.names,
            command=current_ir.command,
            name=current_ir.name,
            geometry=current_ir.geometry,
            column_widths=current_ir.column_widths,
            request_id=current_ir.request_id,
            var_name=current_ir.var_name,
            value_text=current_ir.value_text,
            index=current_ir.index,
            indices=current_ir.indices,
            existing_names=current_ir.existing_names,
            initial_names=initial_ir.names,
            initial_name=initial_ir.name,
            initial_geometry=initial_ir.geometry,
            initial_column_widths=initial_ir.column_widths,
        )

    def debug_state(self):
        state = super().debug_state()
        state.update(
            {
                "initial_names": list(self.initial_names),
                "initial_name": self.initial_name,
                "initial_geometry": self.initial_geometry,
                "initial_column_widths": dict(self.initial_column_widths or {}),
            }
        )
        return state
