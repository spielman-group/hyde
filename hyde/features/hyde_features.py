import ast
import copy
import textwrap

from hyde.features.base import FeatureCodec, set_path


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


class RuntimeCommandModel:
    feature_name = "runtime_command"
    state_version = 1
    valid_commands = {
        "reload_procedures",
        "remote_request",
        "callable_invocation",
        "session_restore",
    }

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "command": None,
            "settings": {
                "project_dir": None,
                "hyde_source_root": None,
                "reset_namespace": False,
                "request_filepath": None,
                "callable_name": None,
                "callable_args": [],
                "session_source": None,
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
        for key in (
            "project_dir",
            "hyde_source_root",
            "request_filepath",
            "callable_name",
            "session_source",
        ):
            value = settings.get(key)
            settings[key] = None if value in (None, "") else str(value)
        settings["reset_namespace"] = bool(settings.get("reset_namespace", False))
        settings["callable_args"] = [
            str(value) for value in settings.get("callable_args", []) if str(value)
        ]
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")

        command = normalized["command"]
        if command not in cls.valid_commands:
            raise ValueError(f"Unsupported runtime command: {command!r}.")

        settings = normalized["settings"]
        if command == "reload_procedures":
            if not settings["project_dir"]:
                raise ValueError("reload_procedures requires settings.project_dir.")
            if not settings["hyde_source_root"]:
                raise ValueError(
                    "reload_procedures requires settings.hyde_source_root."
                )
        elif command == "remote_request" and not settings["request_filepath"]:
            raise ValueError("remote_request requires settings.request_filepath.")
        elif command == "callable_invocation":
            if not settings["callable_name"]:
                raise ValueError(
                    "callable_invocation requires settings.callable_name."
                )
        elif command == "session_restore" and not settings["session_source"]:
            raise ValueError("session_restore requires settings.session_source.")
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
            raise ValueError(f"Unsupported runtime action: {action_type!r}.")

        return cls.normalize_state(normalized)

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        settings = normalized["settings"]
        command = normalized["command"]

        if command == "reload_procedures":
            return (
                "import sys\n"
                f"if {settings['hyde_source_root']!r} not in sys.path:\n"
                f"    sys.path.insert(0, {settings['hyde_source_root']!r})\n"
                "from hyde.project_tools import execute_procedures_bootstrap\n"
                f"execute_procedures_bootstrap({settings['project_dir']!r}, "
                f"{settings['hyde_source_root']!r}, "
                f"reset_namespace={settings['reset_namespace']!r})\n"
            )
        if command == "remote_request":
            return f"remote({settings['request_filepath']!r})"
        if command == "callable_invocation":
            args = ", ".join(settings["callable_args"])
            return f"{settings['callable_name']}({args})"
        if command == "session_restore":
            indented_source = textwrap.indent(f"{settings['session_source']}\n", "    ")
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
        raise ValueError(f"Unsupported runtime command: {command!r}.")


class TableModel:
    feature_name = "table"
    state_version = 1
    valid_commands = {
        "open",
        "append",
        "push_table_data",
        "publish_table_macros",
    }

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "settings": {
                "command": "open",
                "name": None,
                "geometry": None,
                "column_widths": {},
                "request_id": None,
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
            settings = state.get("settings", {})
            if isinstance(settings, dict):
                normalized["settings"].update(settings)
            normalized["items"] = [str(item) for item in state.get("items", []) if str(item)]
            ui = state.get("ui", {})
            normalized["ui"] = dict(ui) if isinstance(ui, dict) else {}

        settings = normalized["settings"]
        settings["command"] = str(settings.get("command", "open"))
        name = settings.get("name")
        settings["name"] = None if name in (None, "") else str(name)
        geometry = settings.get("geometry")
        if geometry in (None, []):
            settings["geometry"] = None
        else:
            settings["geometry"] = tuple(int(value) for value in geometry)
        column_widths = settings.get("column_widths", {})
        if isinstance(column_widths, dict):
            settings["column_widths"] = {
                str(name): int(width)
                for name, width in column_widths.items()
                if str(name) and width is not None
            }
        else:
            settings["column_widths"] = {}
        request_id = settings.get("request_id")
        settings["request_id"] = None if request_id in (None, "") else str(request_id)
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")

        settings = normalized["settings"]
        command = settings["command"]
        if command not in cls.valid_commands:
            raise ValueError(f"Unsupported table command: {command!r}.")

        if command in {"open", "append", "push_table_data"} and not normalized["items"]:
            raise ValueError(f"Table command {command!r} requires at least one item.")
        if command == "append" and not settings["name"]:
            raise ValueError("Table append requires settings.name.")
        if command == "push_table_data" and not settings["request_id"]:
            raise ValueError("Table data push requires settings.request_id.")

        geometry = settings["geometry"]
        if geometry is not None and len(geometry) != 4:
            raise ValueError("Table geometry must contain four integers.")
        for width in settings["column_widths"].values():
            if width <= 0:
                raise ValueError("Table column widths must be positive integers.")
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")

        if action_type == "set_command":
            normalized["settings"]["command"] = action["command"]
        elif action_type == "set":
            set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            set_path(normalized, action["path"], None)
        elif action_type == "replace_items":
            normalized["items"] = list(action.get("items", []))
        elif action_type == "set_column_width":
            name = str(action["name"])
            width = int(action["width"])
            normalized["settings"]["column_widths"][name] = width
        else:
            raise ValueError(f"Unsupported table action: {action_type!r}.")

        return cls.normalize_state(normalized)

    @classmethod
    def table_python_arguments(cls, normalized, include_layout=True):
        arguments = list(normalized["items"])
        settings = normalized["settings"]
        kwargs = []
        if settings["name"]:
            kwargs.append(f"name={settings['name']!r}")
        if include_layout and settings["geometry"] is not None:
            kwargs.append(f"geometry={settings['geometry']!r}")
        if include_layout and settings["column_widths"]:
            kwargs.append(f"column_widths={settings['column_widths']!r}")
        if kwargs:
            arguments.extend(kwargs)
        return ", ".join(arguments)

    @classmethod
    def append_table_arguments(cls, normalized):
        arguments = list(normalized["items"])
        arguments.append(f"name={normalized['settings']['name']!r}")
        return ", ".join(arguments)

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        settings = normalized["settings"]
        command = settings["command"]

        if command == "open":
            arguments = cls.table_python_arguments(normalized, include_layout=True)
            return f"hyde.create_table({arguments})"
        if command == "append":
            return f"hyde.append_table({cls.append_table_arguments(normalized)})"
        if command == "push_table_data":
            return (
                "hyde.execution.ipc.push_table_data("
                f"{list(normalized['items'])!r}, {settings['request_id']!r})"
            )
        if command == "publish_table_macros":
            return "hyde.recreation_registry.publish_registry('table')"
        raise ValueError(f"Unsupported table command: {command!r}.")

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        del context
        normalized = cls.validate_state(state)
        parameters = ", ".join(normalized["items"])
        macro_state = copy.deepcopy(normalized)
        macro_state["settings"]["command"] = "open"
        body = cls.state_to_python(macro_state)
        return "@hyde.table\n" f"def {macro_name}({parameters}):\n" f"    {body}\n"


class MutationModel:
    feature_name = "mutation"
    state_version = 1
    valid_commands = {
        "edit_value",
        "append_value",
        "create_array",
        "delete_indices",
        "delete_name",
    }

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "settings": {
                "command": None,
                "var_name": None,
                "value_text": None,
                "index": None,
                "indices": None,
                "existing_names": [],
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
            settings = state.get("settings", {})
            if isinstance(settings, dict):
                normalized["settings"].update(settings)
            normalized["items"] = list(state.get("items", []))
            ui = state.get("ui", {})
            normalized["ui"] = dict(ui) if isinstance(ui, dict) else {}

        settings = normalized["settings"]
        command = settings.get("command")
        settings["command"] = None if command in (None, "") else str(command)
        var_name = settings.get("var_name")
        settings["var_name"] = None if var_name in (None, "") else str(var_name)
        value_text = settings.get("value_text")
        settings["value_text"] = None if value_text is None else str(value_text)
        index = settings.get("index")
        settings["index"] = None if index is None else int(index)
        indices = settings.get("indices")
        if indices in (None, []):
            settings["indices"] = None if indices is None else []
        else:
            settings["indices"] = [int(value) for value in indices]
        existing_names = settings.get("existing_names", [])
        settings["existing_names"] = [str(name) for name in existing_names if str(name)]
        if settings["command"] == "create_array" and not settings["var_name"]:
            settings["var_name"] = cls.suggest_new_array_name(
                settings["existing_names"],
                settings["value_text"],
            )
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")

        settings = normalized["settings"]
        command = settings["command"]
        if command not in cls.valid_commands:
            raise ValueError(f"Unsupported mutation command: {command!r}.")
        if command != "create_array" and not settings["var_name"]:
            raise ValueError("Mutation commands require settings.var_name.")

        if command in {"edit_value", "append_value", "create_array"}:
            cls.format_entry_literal(settings["value_text"])
        if command == "edit_value" and settings["index"] is None:
            raise ValueError("Cell edits require settings.index.")
        if command == "delete_indices" and settings["indices"] is None:
            raise ValueError("Delete commands require settings.indices.")
        if command == "delete_name" and settings["indices"] not in (None, []):
            raise ValueError("delete_name does not support settings.indices.")
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")

        if action_type == "set_command":
            normalized["settings"]["command"] = action["command"]
        elif action_type == "set":
            set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            set_path(normalized, action["path"], None)
        else:
            raise ValueError(f"Unsupported mutation action: {action_type!r}.")

        return cls.normalize_state(normalized)

    @classmethod
    def format_entry_literal(cls, value_text):
        text = str(value_text or "").strip()
        if not text:
            raise ValueError("Empty cell edits are not supported.")
        try:
            value = ast.literal_eval(text)
        except Exception:
            value = text
        return repr(value)

    @classmethod
    def suggest_new_array_name(cls, existing_names, value_text):
        existing = {str(name) for name in existing_names}
        try:
            value = ast.literal_eval(str(value_text).strip())
        except Exception:
            value = value_text

        prefix = "string_array" if isinstance(value, str) else "array"
        index = 0
        while f"{prefix}{index}" in existing:
            index += 1
        return f"{prefix}{index}"

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        settings = normalized["settings"]
        command = settings["command"]
        var_name = settings["var_name"]

        if command == "edit_value":
            return (
                f"{var_name}[{settings['index']}] = "
                f"{cls.format_entry_literal(settings['value_text'])}"
            )
        if command == "append_value":
            literal = cls.format_entry_literal(settings["value_text"])
            return (
                f"{var_name} = np.concatenate(("
                f"{var_name}, np.array([{literal}], dtype={var_name}.dtype)"
                f"))"
            )
        if command == "create_array":
            literal = cls.format_entry_literal(settings["value_text"])
            return f"{var_name} = np.array([{literal}])"
        if command == "delete_indices":
            indices = sorted(set(settings["indices"] or []))
            return f"{var_name} = np.delete({var_name}, {indices!r})"
        if command == "delete_name":
            return f"del {var_name}"
        raise ValueError(f"Unsupported mutation command: {command!r}.")


class HydeCodec(FeatureCodec):
    feature_name = "hyde"
    state_version = 1
    project_command_feature = ProjectCommandModel.feature_name
    runtime_command_feature = RuntimeCommandModel.feature_name
    table_feature = TableModel.feature_name
    mutation_feature = MutationModel.feature_name

    @classmethod
    def default_state(cls, feature=None):
        feature_kind = cls.feature_kind(feature=feature)
        model = cls.model_for_feature(feature_kind)
        return cls.canonicalize_feature(model.default_state(), feature_kind)

    @classmethod
    def normalize_state(cls, state):
        feature_kind = cls.feature_kind(state)
        model = cls.model_for_feature(feature_kind)
        delegated = cls.delegate_state(feature_kind, state)
        return cls.canonicalize_feature(model.normalize_state(delegated), feature_kind)

    @classmethod
    def validate_state(cls, state):
        feature_kind = cls.feature_kind(state)
        model = cls.model_for_feature(feature_kind)
        delegated = cls.delegate_state(feature_kind, state)
        return cls.canonicalize_feature(model.validate_state(delegated), feature_kind)

    @classmethod
    def update_state(cls, state, action):
        feature_kind = cls.feature_kind(state)
        model = cls.model_for_feature(feature_kind)
        delegated = cls.delegate_state(feature_kind, state)
        return cls.canonicalize_feature(model.update_state(delegated, action), feature_kind)

    @classmethod
    def state_to_python(cls, state, context=None):
        feature_kind = cls.feature_kind(state)
        model = cls.model_for_feature(feature_kind)
        return model.state_to_python(cls.delegate_state(feature_kind, state), context=context)

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        feature_kind = cls.feature_kind(state)
        model = cls.model_for_feature(feature_kind)
        if not hasattr(model, "state_to_macro_source"):
            raise NotImplementedError(
                f"{model.__name__} does not support macro source generation."
            )
        return model.state_to_macro_source(
            cls.delegate_state(feature_kind, state),
            macro_name,
            context=context,
        )

    @classmethod
    def format_entry_literal(cls, value_text):
        return MutationModel.format_entry_literal(value_text)

    @classmethod
    def suggest_new_array_name(cls, existing_names, value_text):
        return MutationModel.suggest_new_array_name(existing_names, value_text)

    @classmethod
    def feature_kind(cls, state=None, *, feature=None):
        candidate = feature
        if candidate in (None, "") and isinstance(state, dict):
            candidate = state.get("feature")
        if candidate == cls.project_command_feature:
            return cls.project_command_feature
        if candidate == cls.runtime_command_feature:
            return cls.runtime_command_feature
        if candidate == cls.table_feature:
            return cls.table_feature
        if candidate == cls.mutation_feature:
            return cls.mutation_feature
        if isinstance(state, dict):
            settings = dict(state.get("settings", {}) or {})
            if any(
                key in settings
                for key in ("request_id", "column_widths", "geometry", "name")
            ):
                return cls.table_feature
            if any(
                key in settings
                for key in ("var_name", "value_text", "index", "indices", "existing_names")
            ):
                return cls.mutation_feature
            if any(
                key in settings
                for key in (
                    "hyde_source_root",
                    "request_filepath",
                    "callable_name",
                    "callable_args",
                    "session_source",
                    "reset_namespace",
                )
            ):
                return cls.runtime_command_feature
        return cls.project_command_feature

    @classmethod
    def model_for_feature(cls, feature_kind):
        if feature_kind == cls.project_command_feature:
            return ProjectCommandModel
        if feature_kind == cls.runtime_command_feature:
            return RuntimeCommandModel
        if feature_kind == cls.table_feature:
            return TableModel
        if feature_kind == cls.mutation_feature:
            return MutationModel
        raise ValueError(f"Unsupported Hyde feature kind: {feature_kind!r}.")

    @classmethod
    def delegate_state(cls, feature_kind, state):
        candidate = copy.deepcopy(state) if state is not None else None
        if candidate is None:
            return None
        candidate["feature"] = cls.model_for_feature(feature_kind).feature_name
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


class RuntimeCommandCodec(HydeCodecView):
    feature_name = HydeCodec.runtime_command_feature


class TableCodec(HydeCodecView):
    feature_name = HydeCodec.table_feature


class MutationCodec(HydeCodecView):
    feature_name = HydeCodec.mutation_feature

    @classmethod
    def format_entry_literal(cls, value_text):
        return MutationModel.format_entry_literal(value_text)

    @classmethod
    def suggest_new_array_name(cls, existing_names, value_text):
        return MutationModel.suggest_new_array_name(existing_names, value_text)
