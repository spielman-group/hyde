import copy

from hyde.features.base import FeatureCodec


def _set_path(state, path, value):
    target = state
    for key in tuple(path or ())[:-1]:
        target = target[key]
    target[tuple(path or ())[-1]] = value


def _ordered_unique(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


class FigureCodec(FeatureCodec):
    feature_name = "figure"
    state_version = 1
    _valid_commands = {
        "create",
        "publish_figure_macros",
        "refresh",
        "close",
        "track",
    }

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "settings": {
                "command": "create",
                "title": None,
                "x_name": None,
                "subplot_code": "111",
                "figure_number": None,
                "open_token": None,
                "tracked_state": None,
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
        settings["command"] = str(settings.get("command", "create"))
        title = settings.get("title")
        settings["title"] = None if title in (None, "") else str(title)
        x_name = settings.get("x_name")
        settings["x_name"] = None if x_name in (None, "") else str(x_name)
        settings["subplot_code"] = str(settings.get("subplot_code", "111"))
        figure_number = settings.get("figure_number")
        settings["figure_number"] = (
            None if figure_number in (None, "") else int(figure_number)
        )
        open_token = settings.get("open_token")
        settings["open_token"] = None if open_token in (None, "") else str(open_token)
        tracked_state = settings.get("tracked_state")
        settings["tracked_state"] = (
            None
            if tracked_state in (None, "")
            else cls.normalize_state(tracked_state)
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
            raise ValueError(f"Unsupported figure command: {command!r}.")

        if command == "create" and not normalized["items"]:
            raise ValueError("Figure creation requires at least one plotted object.")
        if command in {"refresh", "close"} and not settings["figure_number"]:
            raise ValueError(f"Figure command {command!r} requires a figure number.")
        if command == "track":
            if not settings["figure_number"]:
                raise ValueError("Figure command 'track' requires a figure number.")
            tracked_state = settings.get("tracked_state")
            if tracked_state is None:
                raise ValueError("Figure command 'track' requires tracked figure state.")
            settings["tracked_state"] = cls.validate_state(tracked_state)
        if settings["subplot_code"] != "111":
            raise ValueError("Initial Hyde figure editing only supports subplot code '111'.")
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
        else:
            raise ValueError(f"Unsupported figure action: {action_type!r}.")

        return cls.normalize_state(normalized)

    @classmethod
    def _creation_lines(cls, normalized):
        settings = normalized["settings"]
        title = settings["title"]
        x_name = settings["x_name"]
        y_names = list(normalized["items"])

        if title:
            lines = [f"fig = plt.figure({title!r})"]
        else:
            lines = ["fig = plt.figure()"]
        if settings["open_token"]:
            lines.append(f"fig._hyde_open_token = {settings['open_token']!r}")
        lines.append(f"ax = fig.add_subplot({settings['subplot_code']})")
        if title:
            lines.append(f"ax.set_title({title!r})")
        for y_name in y_names:
            if x_name:
                lines.append(f"ax.plot({x_name}, {y_name}, label={y_name!r})")
            else:
                lines.append(f"ax.plot({y_name}, label={y_name!r})")
        if len(y_names) > 1:
            lines.append("ax.legend()")
        lines.append("fig.show()")
        lines.append("fig.canvas.draw_idle()")
        return lines

    @classmethod
    def tracked_names(cls, state):
        normalized = cls.normalize_state(state)
        settings = normalized["settings"]
        names = []
        if settings["x_name"]:
            names.append(settings["x_name"])
        names.extend(normalized["items"])
        return tuple(_ordered_unique(names))

    @classmethod
    def wrapped_creation_lines(cls, state, helper_name="_hyde_figure"):
        normalized = cls.validate_state(state)
        parameters = list(cls.tracked_names(normalized))
        lines = [f"def {helper_name}({', '.join(parameters)}):"]
        lines.extend(f"    {line}" for line in cls._creation_lines(normalized))
        lines.append(f"{helper_name}({', '.join(parameters)})")
        lines.append(f"del {helper_name}")
        return lines

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        command = normalized["settings"]["command"]
        if command == "create":
            return "\n".join(cls.wrapped_creation_lines(normalized))
        if command == "publish_figure_macros":
            return "hyde.recreation_registry.publish_figure_macro_registry()"
        if command == "refresh":
            return f"hyde.refresh_figure({normalized['settings']['figure_number']})"
        if command == "close":
            return f"plt.close({normalized['settings']['figure_number']})"
        if command == "track":
            return (
                "hyde.track_figure("
                f"{normalized['settings']['figure_number']}, "
                f"{normalized['settings']['tracked_state']!r})"
            )
        raise ValueError(f"Unsupported figure command: {command!r}.")

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        del context
        normalized = cls.validate_state(state)
        parameters = list(cls.tracked_names(normalized))
        body = "\n".join(f"    {line}" for line in cls._creation_lines(normalized))
        return (
            "@hyde.figure\n"
            f"def {macro_name}({', '.join(parameters)}):\n"
            f"{body}\n"
            "    return fig\n"
        )


def is_eligible_for_plot(metadata):
    python_type = metadata.get("python_type", "").lower()
    numpy_type = metadata.get("numpy_type", "")
    ndim = metadata.get("ndim", 1)
    kind = metadata.get("numpy_kind", "f")

    is_array = python_type in ("ndarray", "series") or numpy_type == "Array"
    is_numeric = kind in "biuf"

    return is_array and is_numeric and ndim == 1


def apply_figure_state(figure, state, namespace):
    normalized = FigureCodec.normalize_state(state)
    settings = normalized["settings"]
    title = settings["title"]
    x_name = settings["x_name"]
    y_names = list(normalized["items"])

    namespace = dict(namespace or {})
    x_values = namespace.get(x_name) if x_name else None

    figure.clear()
    if title:
        figure.set_label(title)
    axis = figure.add_subplot(int(settings["subplot_code"]))
    if title:
        axis.set_title(title)

    plotted = 0
    for y_name in y_names:
        if y_name not in namespace:
            continue
        y_values = namespace[y_name]
        if x_name and x_name in namespace:
            axis.plot(x_values, y_values, label=y_name)
        else:
            axis.plot(y_values, label=y_name)
        plotted += 1

    if plotted > 1:
        axis.legend()
    figure.canvas.draw_idle()
    return plotted
