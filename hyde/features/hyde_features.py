import copy

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

        if command == "new_project":
            return (
                f"hyde.new_project({settings['project_dir']!r}, "
                f"load={settings['load']!r}, overwrite={settings['overwrite']!r})"
            )
        if command == "load_project":
            return f"hyde.load_project({settings['project_dir']!r})"
        if command == "heal_project":
            return f"hyde.heal_project({settings['project_dir']!r})"
        if command == "save_project":
            arguments = []
            if settings["project_dir"] is not None:
                arguments.append(repr(settings["project_dir"]))
            arguments.append(f"mode={settings['mode']!r}")
            if settings["mode"] != "save":
                arguments.append(f"overwrite={settings['overwrite']!r}")
            return f"hyde.save_project({', '.join(arguments)})"
        if command == "quit":
            return "hyde.quit()"
        raise ValueError(f"Unsupported Hyde command: {command!r}.")


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


class HydeCodecView:
    feature_name = None

    @classmethod
    def default_state(cls):
        return HydeCodec.default_state(feature=cls.feature_name)

    @classmethod
    def normalize_state(cls, state):
        return HydeCodec.normalize_state(cls.with_feature(state))

    @classmethod
    def validate_state(cls, state):
        return HydeCodec.validate_state(cls.with_feature(state))

    @classmethod
    def update_state(cls, state, action):
        return HydeCodec.update_state(cls.with_feature(state), action)

    @classmethod
    def state_to_python(cls, state, context=None):
        return HydeCodec.state_to_python(cls.with_feature(state), context=context)

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        return HydeCodec.state_to_macro_source(
            cls.with_feature(state),
            macro_name,
            context=context,
        )

    @classmethod
    def with_feature(cls, state):
        normalized = {} if state is None else copy.deepcopy(state)
        normalized["feature"] = cls.feature_name
        return normalized


class SimpleHydeCommandCodec(HydeCodecView):
    feature_name = HydeCodec.project_command_feature
