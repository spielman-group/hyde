import ast
import copy

from hyde.features.base import FeatureCodec


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
            target = normalized
            path = list(action["path"])
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = action["value"]
        elif action_type == "clear":
            target = normalized
            path = list(action["path"])
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = None
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
def format_table_command(names, target=None, title=None):
    """
    Formulates a hyde.table(...) command string.
    
    Args:
        names: List of variable names.
        target: Optional internal handle of the target table.
        title: Optional visible window title for a new table.
        
    Returns:
        str: The Python command string.
    """
    args_str = ", ".join(names)
    kwargs = []
    if target:
        kwargs.append(f"target={target!r}")
    if title:
        kwargs.append(f"title={title!r}")

    if kwargs:
        return f"hyde.table({args_str}, {', '.join(kwargs)})"
    return f"hyde.table({args_str})"


def format_table_macro_source(macro_name, names, title=None):
    """
    Build a parameterized decorated table recreation macro definition.
    """
    parameters = ", ".join(names)
    kwargs = []
    if title:
        kwargs.append(f"title={title!r}")
    arguments = parameters
    if kwargs:
        arguments = f"{arguments}, {', '.join(kwargs)}"
    return (
        "@hyde.table\n"
        f"def {macro_name}({parameters}):\n"
        f"    hyde.table({arguments})\n"
    )
def format_publish_table_macros_command():
    """Formulate the silent table-macro publication command string."""
    return "hyde.table_macros.publish_table_macro_registry()"


def format_push_table_data_command(names, request_id):
    """Formulate the silent table-data request command string."""
    return f"hyde.execution.ipc.push_table_data({list(names)!r}, {request_id!r})"


def format_cell_edit_command(var_name, index, value):
    """
    Formulates a muted mutation command for table cell editing.
    """
    return f"{var_name}[{index}] = {format_entry_literal(value)}"


def format_cell_append_command(var_name, value):
    """
    Formulates a muted append command for table row extension.

    The appended value is explicitly converted through the existing array dtype so
    incompatible entries fail in the kernel instead of silently widening dtype.
    """
    literal = format_entry_literal(value)
    return (
        f"{var_name} = np.concatenate(("
        f"{var_name}, np.array([{literal}], dtype={var_name}.dtype)"
        f"))"
    )


def format_new_array_command(var_name, value):
    """Formulates a muted command creating a new 1D array from one entered value."""
    return f"{var_name} = np.array([{format_entry_literal(value)}])"


def format_delete_indices_command(var_name, indices):
    """Formulates a muted delete command for one array column."""
    index_list = sorted(set(indices))
    return f"{var_name} = np.delete({var_name}, {index_list!r})"


def format_entry_literal(value_text):
    """
    Convert user-entered cell text into a Python literal expression.

    Bare text is treated as a string literal, while valid Python literals
    such as numbers, quoted strings, booleans, and None are preserved.
    """
    text = value_text.strip()
    if not text:
        raise ValueError("Empty cell edits are not supported.")
    try:
        value = ast.literal_eval(text)
    except Exception:
        value = text
    return repr(value)


def suggest_new_array_name(existing_names, value_text):
    """
    Suggest a deterministic kernel variable name for a newly created table column.

    String-like entries use an Igor-style `textWaveN` prefix to match user
    expectation from the reference UI. All other entries use `waveN`.
    """
    existing = set(existing_names)
    try:
        value = ast.literal_eval(value_text.strip())
    except Exception:
        value = value_text

    prefix = "textWave" if isinstance(value, str) else "wave"

    index = 0
    while f"{prefix}{index}" in existing:
        index += 1
    return f"{prefix}{index}"


def is_eligible_for_table(metadata):
    """
    Determines if a variable (from Data Browser metadata) is eligible for table display.
    Scoped to 1D numeric waves initially.
    """
    python_type = metadata.get("python_type", "").lower()
    numpy_type = metadata.get("numpy_type", "")
    ndim = metadata.get("ndim", 1)
    kind = metadata.get("numpy_kind", "f") # Default to float if kind metadata is missing

    # Scoped to 1D numeric (numpy ndarray, pandas Series, etc.)
    is_array = python_type in ("ndarray", "series") or numpy_type == "Array"
    is_numeric = kind in 'biuf'
    
    return is_array and is_numeric and ndim == 1


def format_procedures_bootstrap_code(project_dir, hyde_source_root, reset_namespace=False):
    """
    Formulates the canonical procedure environment bootstrap string by
    invoking the real execution logic.
    """
    return (
        "import sys\n"
        f"if {hyde_source_root!r} not in sys.path:\n"
        f"    sys.path.insert(0, {hyde_source_root!r})\n"
        "from hyde.project_tools import execute_procedures_bootstrap\n"
        f"execute_procedures_bootstrap({project_dir!r}, {hyde_source_root!r}, reset_namespace={reset_namespace})\n"
    )


def format_remote_command(request_filepath):
    """
    Formulates a muted command to trigger remote execution for a file payload.
    """
    return f"remote({request_filepath!r})"
