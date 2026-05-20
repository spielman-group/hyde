import ast
import copy

from hyde.features.base import FeatureCodec


def _coerce_path(path):
    return tuple(path or ())


def _set_path(state, path, value):
    target = state
    path = _coerce_path(path)
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


class SimpleHydeCommandCodec(FeatureCodec):
    feature_name = "hyde_command"
    state_version = 1
    _valid_commands = {
        "new_project",
        "load_project",
        "heal_project",
        "save_project",
        "quit",
    }
    _valid_save_modes = {"save", "save_as", "copy"}

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
            normalized["state_version"] = state.get("state_version", normalized["state_version"])
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
        if command not in cls._valid_commands:
            raise ValueError(f"Unsupported Hyde command: {command!r}.")

        settings = normalized["settings"]
        if command in {"new_project", "load_project", "heal_project"}:
            if not settings["project_dir"]:
                raise ValueError(f"{command} requires settings.project_dir.")

        if command == "save_project":
            mode = settings["mode"]
            if mode not in cls._valid_save_modes:
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
            _set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            _set_path(normalized, action["path"], None)
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


class RuntimeCommandCodec(FeatureCodec):
    feature_name = "runtime_command"
    state_version = 1
    _valid_commands = {
        "reload_procedures",
        "remote_request",
        "callable_invocation",
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
        if command not in cls._valid_commands:
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
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")

        if action_type == "set_command":
            normalized["command"] = action["command"]
        elif action_type == "set":
            _set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            _set_path(normalized, action["path"], None)
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
        raise ValueError(f"Unsupported runtime command: {command!r}.")


class TableCodec(FeatureCodec):
    feature_name = "table"
    state_version = 1
    _valid_commands = {
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
            normalized["state_version"] = state.get("state_version", normalized["state_version"])
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
        if command not in cls._valid_commands:
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
            _set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            _set_path(normalized, action["path"], None)
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
    def _table_python_arguments(cls, normalized, include_layout=True):
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
    def _append_table_arguments(cls, normalized):
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
            return (
                "hyde.create_table("
                f"{cls._table_python_arguments(normalized, include_layout=True)})"
            )
        if command == "append":
            return (
                "hyde.append_table("
                f"{cls._append_table_arguments(normalized)})"
            )
        if command == "push_table_data":
            return (
                "hyde.execution.ipc.push_table_data("
                f"{list(normalized['items'])!r}, {settings['request_id']!r})"
            )
        if command == "publish_table_macros":
            return "hyde.recreation_registry.publish_registry('table')"
        raise ValueError(f"Unsupported table command: {command!r}.")

    @classmethod
    def state_to_macro_source(
        cls,
        state,
        macro_name,
        context=None,
    ):
        del context
        normalized = cls.validate_state(state)
        parameters = ", ".join(normalized["items"])
        macro_state = copy.deepcopy(normalized)
        macro_state["settings"]["command"] = "open"
        # Table recreation macros intentionally preserve saved GUI layout even
        # though session.toml also stores it, because macros must fully reopen
        # the table window as the user last arranged it.
        body = cls.state_to_python(macro_state)
        return (
            "@hyde.table\n"
            f"def {macro_name}({parameters}):\n"
            f"    {body}\n"
        )


class MutationCodec(FeatureCodec):
    feature_name = "mutation"
    state_version = 1
    _valid_commands = {
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
            normalized["state_version"] = state.get("state_version", normalized["state_version"])
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
        if command not in cls._valid_commands:
            raise ValueError(f"Unsupported mutation command: {command!r}.")
        if command != "create_array" and not settings["var_name"]:
            raise ValueError("Mutation commands require settings.var_name.")

        if command in {"edit_value", "append_value", "create_array"}:
            cls.format_entry_literal(settings["value_text"])
        if command == "edit_value" and settings["index"] is None:
            raise ValueError("Cell edits require settings.index.")
        if command == "delete_indices":
            if settings["indices"] is None:
                raise ValueError("Delete commands require settings.indices.")
        if command == "delete_name":
            if settings["indices"] not in (None, []):
                raise ValueError("delete_name does not support settings.indices.")
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")

        if action_type == "set_command":
            normalized["settings"]["command"] = action["command"]
        elif action_type == "set":
            _set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            _set_path(normalized, action["path"], None)
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
            return f"{var_name} = np.array([{cls.format_entry_literal(settings['value_text'])}])"
        if command == "delete_indices":
            indices = sorted(set(settings["indices"] or []))
            return f"{var_name} = np.delete({var_name}, {indices!r})"
        if command == "delete_name":
            return f"del {var_name}"
        raise ValueError(f"Unsupported mutation command: {command!r}.")


def is_eligible_for_table(metadata):
    """
    Determines if a variable (from Python Variables metadata) is eligible for table display.
    Scoped to 1D numeric arrays initially.
    """
    python_type = metadata.get("python_type", "").lower()
    numpy_type = metadata.get("numpy_type", "")
    ndim = metadata.get("ndim", 1)
    kind = metadata.get("numpy_kind", "f")

    is_array = python_type in ("ndarray", "series") or numpy_type == "Array"
    is_numeric = kind in "biuf"

    return is_array and is_numeric and ndim == 1
