import copy
import keyword
import textwrap

from hyde.features.base import FeatureCodec, set_path


def new_project_source(project_dir, *, load=True, overwrite=False):
    return (
        f"hyde.new_project({project_dir!r}, "
        f"load={bool(load)!r}, overwrite={bool(overwrite)!r})"
    )


def load_project_source(project_dir):
    return f"hyde.load_project({project_dir!r})"


def heal_project_source(project_dir):
    return f"hyde.heal_project({project_dir!r})"


def save_project_source(project_dir=None, *, mode="save", overwrite=False):
    arguments = []
    if project_dir is not None:
        arguments.append(repr(project_dir))
    arguments.append(f"mode={mode!r}")
    if mode != "save":
        arguments.append(f"overwrite={bool(overwrite)!r}")
    return f"hyde.save_project({', '.join(arguments)})"


def quit_source():
    return "hyde.quit()"


def reload_procedures_source(
    project_dir,
    hyde_source_root,
    *,
    reset_namespace=False,
):
    return (
        "import sys\n"
        f"if {hyde_source_root!r} not in sys.path:\n"
        f"    sys.path.insert(0, {hyde_source_root!r})\n"
        "from hyde.project_tools import execute_procedures_bootstrap\n"
        f"execute_procedures_bootstrap({project_dir!r}, "
        f"{hyde_source_root!r}, "
        f"reset_namespace={bool(reset_namespace)!r})\n"
    )


def remote_request_source(request_filepath):
    return f"remote({request_filepath!r})"


def callable_invocation_source(callable_name, callable_args=()):
    args = ", ".join(str(value) for value in tuple(callable_args or ()))
    return f"{callable_name}({args})"


def session_restore_source(session_source):
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


def normalize_namespace_names(namespace_names):
    return tuple(
        str(name).strip()
        for name in tuple(namespace_names or ())
        if str(name).strip()
    )


def validate_namespace_names(namespace_names):
    normalized_names = normalize_namespace_names(namespace_names)
    if not normalized_names:
        raise ValueError("delete_namespace_names requires at least one namespace name.")
    for name in normalized_names:
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ValueError(f"Invalid Python variable name: {name!r}")
    return normalized_names


def delete_namespace_names_source(namespace_names):
    return f"del {', '.join(validate_namespace_names(namespace_names))}"


def hyde_app_python_source(
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
    namespace_names=(),
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
        return reload_procedures_source(
            project_dir,
            hyde_source_root,
            reset_namespace=reset_namespace,
        )
    if command == "remote_request":
        return remote_request_source(request_filepath)
    if command == "callable_invocation":
        return callable_invocation_source(callable_name, callable_args)
    if command == "session_restore":
        return session_restore_source(session_source)
    if command == "delete_namespace_names":
        return delete_namespace_names_source(namespace_names)
    raise ValueError(f"Unsupported Hyde app command: {command!r}.")


def publish_registry_source(registry_name):
    return f"hyde.recreation_registry.publish_registry({str(registry_name)!r})"


def figure_decorator_source(*, register=True):
    if register:
        return "@hyde.figure"
    return "@hyde.figure(register=False)"


def figure_lookup_prelude_lines(figure_name, *, include_axes=False):
    lines = [f"fig = hyde.get_figure({str(figure_name)!r})"]
    if include_axes:
        lines.append("ax = fig.axes[0]")
    return lines


def figure_refresh_source(figure_name, *, use_bound_values=False):
    return "\n".join(
        figure_lookup_prelude_lines(figure_name)
        + [
            f"hyde.refresh_figure(fig, use_bound_values={bool(use_bound_values)!r})"
        ]
    )


def remove_traces_source(figure_name, trace_ids):
    joined_ids = ", ".join(repr(str(trace_id)) for trace_id in tuple(trace_ids or ()))
    return "\n".join(
        figure_lookup_prelude_lines(figure_name)
        + [f"hyde.remove_traces(fig, {joined_ids})"]
    )


VALID_TABLE_COMMANDS = {
    "open",
    "append",
    "push_table_data",
    "publish_table_macros",
}


def table_python_arguments(
    names,
    *,
    name=None,
    geometry=None,
    column_widths=None,
    include_layout=True,
):
    arguments = [str(item) for item in (names or ()) if str(item)]
    kwargs = []
    if name:
        kwargs.append(f"name={name!r}")
    if include_layout and geometry is not None:
        kwargs.append(f"geometry={tuple(geometry)!r}")
    if include_layout and column_widths:
        kwargs.append(f"column_widths={dict(column_widths)!r}")
    if kwargs:
        arguments.extend(kwargs)
    return ", ".join(arguments)


def append_table_arguments(names, *, name):
    arguments = [str(item) for item in (names or ()) if str(item)]
    arguments.append(f"name={name!r}")
    return ", ".join(arguments)


def table_ir_python_source(
    *,
    command,
    names=(),
    name=None,
    geometry=None,
    column_widths=None,
    request_id=None,
):
    if command not in VALID_TABLE_COMMANDS:
        raise ValueError(f"Unsupported table command: {command!r}.")
    if command in {"open", "append", "push_table_data"} and not tuple(names or ()):
        raise ValueError(f"Table command {command!r} requires at least one item.")
    if command == "append" and not name:
        raise ValueError("Table append requires a target name.")
    if command == "push_table_data" and not request_id:
        raise ValueError("Table data push requires a request_id.")

    if command == "open":
        return f"hyde.create_table({table_python_arguments(names, name=name, geometry=geometry, column_widths=column_widths, include_layout=True)})"
    if command == "append":
        return f"hyde.append_table({append_table_arguments(names, name=name)})"
    if command == "push_table_data":
        return (
            "hyde.execution.ipc.push_table_data("
            f"{list(names)!r}, {request_id!r})"
        )
    return "hyde.recreation_registry.publish_registry('table')"


def table_ir_macro_source(
    *,
    macro_name,
    names=(),
    name=None,
    geometry=None,
    column_widths=None,
):
    parameters = ", ".join(str(item) for item in (names or ()) if str(item))
    body = table_ir_python_source(
        command="open",
        names=names,
        name=name,
        geometry=geometry,
        column_widths=column_widths,
    )
    return "@hyde.table\n" f"def {macro_name}({parameters}):\n" f"    {body}\n"


class ProjectCommandModel:
    feature_name = "hyde_command"
    state_version = 1
    valid_commands = {
        "new_project",
        "load_project",
        "heal_project",
        "save_project",
        "quit",
        "delete_namespace_names",
    }
    valid_save_modes = {"save", "save_as", "copy"}

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "command": None,
            "settings": {
                "project_dir": None,
                "mode": "save",
                "load": True,
                "overwrite": False,
                "namespace_names": [],
            },
            "items": [],
            "ui": {},
        }

    @classmethod
    def normalize_state(cls, state):
        normalized = copy.deepcopy(cls.default_state())
        if state:
            normalized["feature"] = state.get("feature", normalized["feature"])
            normalized["state_version"] = state.get(
                "state_version", normalized["state_version"]
            )
            normalized["command"] = state.get("command")
            settings = state.get("settings", {})
            if isinstance(settings, dict):
                normalized["settings"].update(settings)
            normalized["items"] = list(state.get("items", []))
            ui = state.get("ui", {})
            normalized["ui"] = dict(ui) if isinstance(ui, dict) else {}

        settings = normalized["settings"]
        project_dir = settings.get("project_dir")
        settings["project_dir"] = None if project_dir in (None, "") else str(project_dir)
        settings["mode"] = str(settings.get("mode", "save"))
        settings["load"] = bool(settings.get("load", True))
        settings["overwrite"] = bool(settings.get("overwrite", False))
        settings["namespace_names"] = list(
            normalize_namespace_names(settings.get("namespace_names", ()))
        )
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")
        command = normalized["command"]
        if command not in cls.valid_commands:
            raise ValueError(f"Unsupported Hyde command: {command!r}.")

        settings = normalized["settings"]
        if command in {"new_project", "load_project", "heal_project"}:
            if not settings["project_dir"]:
                raise ValueError(f"{command} requires settings.project_dir.")

        if command == "save_project":
            mode = settings["mode"]
            if mode not in cls.valid_save_modes:
                raise ValueError(f"Unsupported save mode: {mode!r}.")
            if mode != "save" and not settings["project_dir"]:
                raise ValueError(f"{mode} requires settings.project_dir.")
        if command == "delete_namespace_names":
            validate_namespace_names(settings["namespace_names"])

        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")

        if action_type == "set_command":
            normalized["command"] = action["command"]
        elif action_type == "set":
            set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            set_path(normalized, action["path"], None)
        else:
            raise ValueError(f"Unsupported simple command action: {action_type!r}.")

        return cls.normalize_state(normalized)

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        command = normalized["command"]
        settings = normalized["settings"]
        return hyde_app_python_source(
            command=command,
            target_project_dir=settings["project_dir"],
            save_mode=settings["mode"],
            load=settings["load"],
            overwrite=settings["overwrite"],
            namespace_names=settings["namespace_names"],
        )


class HydeCodec(FeatureCodec):
    feature_name = "hyde"
    state_version = 1
    project_command_feature = ProjectCommandModel.feature_name

    @classmethod
    def default_state(cls, feature=None):
        feature_kind = cls.feature_kind(feature=feature)
        return cls.canonicalize_feature(ProjectCommandModel.default_state(), feature_kind)

    @classmethod
    def normalize_state(cls, state):
        feature_kind = cls.feature_kind(state)
        delegated = cls.delegate_state(feature_kind, state)
        return cls.canonicalize_feature(
            ProjectCommandModel.normalize_state(delegated),
            feature_kind,
        )

    @classmethod
    def validate_state(cls, state):
        feature_kind = cls.feature_kind(state)
        delegated = cls.delegate_state(feature_kind, state)
        return cls.canonicalize_feature(
            ProjectCommandModel.validate_state(delegated),
            feature_kind,
        )

    @classmethod
    def update_state(cls, state, action):
        feature_kind = cls.feature_kind(state)
        delegated = cls.delegate_state(feature_kind, state)
        return cls.canonicalize_feature(
            ProjectCommandModel.update_state(delegated, action),
            feature_kind,
        )

    @classmethod
    def state_to_python(cls, state, context=None):
        feature_kind = cls.feature_kind(state)
        return ProjectCommandModel.state_to_python(
            cls.delegate_state(feature_kind, state),
            context=context,
        )

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        feature_kind = cls.feature_kind(state)
        return ProjectCommandModel.state_to_macro_source(
            cls.delegate_state(feature_kind, state),
            macro_name,
            context=context,
        )

    @classmethod
    def feature_kind(cls, state=None, *, feature=None):
        candidate = feature
        if candidate in (None, "") and isinstance(state, dict):
            candidate = state.get("feature")
        if candidate not in (None, "", cls.project_command_feature):
            raise ValueError(f"Unsupported Hyde feature kind: {candidate!r}.")
        return cls.project_command_feature

    @classmethod
    def delegate_state(cls, feature_kind, state):
        candidate = copy.deepcopy(state) if state is not None else None
        if candidate is None:
            return None
        candidate["feature"] = ProjectCommandModel.feature_name
        return candidate

    @classmethod
    def canonicalize_feature(cls, state, feature_kind):
        normalized = copy.deepcopy(state)
        normalized["feature"] = feature_kind
        return normalized


