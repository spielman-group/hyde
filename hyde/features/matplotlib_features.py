import copy
import numbers
from dataclasses import dataclass

import numpy as np

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


def _patch_empty_choice(value):
    if value in (None, "", "none", "None", " "):
        return "None"
    return str(value)


def _patch_can_dispatch_trace_style_edit(source_trace, target_trace):
    if not isinstance(source_trace, dict) or not isinstance(target_trace, dict):
        return False
    source_copy = copy.deepcopy(source_trace)
    target_copy = copy.deepcopy(target_trace)
    source_kwargs = dict(source_copy.pop("kwargs", {}) or {})
    target_kwargs = dict(target_copy.pop("kwargs", {}) or {})
    if source_copy != target_copy:
        return False
    changed_keys = {
        key
        for key in set(source_kwargs) | set(target_kwargs)
        if source_kwargs.get(key) != target_kwargs.get(key)
    }
    if not changed_keys:
        return False
    if "label" in changed_keys and "label" not in target_kwargs:
        return False
    return changed_keys <= set(TRACE_STYLE_ACTION_KEYS)


TRACE_STYLE_ACTION_KEYS = (
    "alpha",
    "color",
    "drawstyle",
    "label",
    "linestyle",
    "linewidth",
    "marker",
    "markeredgecolor",
    "markeredgewidth",
    "markerfacecolor",
    "markersize",
    "visible",
)

GRAPHICS_EXPORT_SUFFIX_VARIANTS = {
    "jpeg": ("jpg",),
    "jpg": ("jpeg",),
    "tif": ("tiff",),
    "tiff": ("tif",),
}
GRAPHICS_EXPORT_TRANSPARENCY_UNSUPPORTED_FORMATS = frozenset({"jpeg", "jpg"})


@dataclass(frozen=True)
class GraphicsExportFormat:
    key: str
    display_label: str
    preferred_suffix: str
    compatible_suffixes: tuple[str, ...]
    name_filter: str


def _operand_to_python(operand):
    if operand is None:
        return None
    kind = operand.get("kind")
    if kind == "name":
        return operand["value"]
    if kind == "literal":
        return repr(operand["value"])
    if kind == "array_literal":
        return f"np.array({operand['value']!r})"
    if kind == "attribute_path":
        expression = _operand_to_python(operand["root"])
        for attribute in operand["path"]:
            expression = f"getattr({expression}, {attribute!r})"
        return expression
    raise ValueError(f"Unsupported figure operand kind: {kind!r}.")


def _operand_names(operand):
    if operand is None:
        return []
    if operand.get("kind") == "name":
        return [operand["value"]]
    if operand.get("kind") == "attribute_path":
        return _operand_names(operand.get("root"))
    return []


def _macro_ready_lines(lines):
    return [line for line in lines if line.strip() != "fig.canvas.draw_idle()"]


def figure_command_prelude_lines(
    figure_name,
    *,
    extra_imports=(),
    include_axes=False,
):
    lines = [str(line) for line in tuple(extra_imports or ())]
    lines.append(f"fig = hyde.get_figure({str(figure_name)!r})")
    if include_axes:
        lines.append("ax = fig.axes[0]")
    return lines


def figure_refresh_command_source(figure_name, *, use_bound_values=False):
    normalized_name = str(figure_name or "").strip()
    if not normalized_name:
        raise ValueError("Figure refresh requires a stable first-class figure name.")
    return "\n".join(
        figure_command_prelude_lines(normalized_name)
        + [f"hyde.refresh_figure(fig, use_bound_values={bool(use_bound_values)!r})"]
    )


def runtime_graphics_export_filetypes():
    import matplotlib.pyplot as plt

    backend_module = plt._get_backend_mod()
    canvas_type = getattr(backend_module, "FigureCanvas", None)
    return dict(getattr(canvas_type, "filetypes", {}) or {})


def graphics_export_suffixes_for_format(format_key, filetypes=None):
    normalized_key = str(format_key or "").strip().lower()
    if not normalized_key:
        return ()
    available_filetypes = (
        runtime_graphics_export_filetypes() if filetypes is None else dict(filetypes)
    )
    suffixes = [f".{normalized_key}"]
    for variant in GRAPHICS_EXPORT_SUFFIX_VARIANTS.get(normalized_key, ()):
        if variant in available_filetypes:
            suffixes.append(f".{variant}")
    return tuple(_ordered_unique(suffixes))


def graphics_export_name_filter(display_label, suffixes):
    patterns = " ".join(f"*{suffix}" for suffix in tuple(suffixes or ()))
    if not patterns:
        patterns = "*"
    return f"{display_label} Files ({patterns})"


def runtime_graphics_export_formats(filetypes=None):
    resolved_filetypes = (
        runtime_graphics_export_filetypes() if filetypes is None else dict(filetypes)
    )
    formats = []
    for key in resolved_filetypes:
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        display_label = normalized_key.upper()
        compatible_suffixes = graphics_export_suffixes_for_format(
            normalized_key,
            resolved_filetypes,
        )
        formats.append(
            GraphicsExportFormat(
                key=normalized_key,
                display_label=display_label,
                preferred_suffix=f".{normalized_key}",
                compatible_suffixes=compatible_suffixes,
                name_filter=graphics_export_name_filter(
                    display_label,
                    compatible_suffixes,
                ),
            )
        )

    def sort_key(item):
        if item.key == "pdf":
            return (0, item.display_label.lower())
        if item.key == "png":
            return (1, item.display_label.lower())
        return (2, item.display_label.lower())

    return sorted(formats, key=sort_key)


def graphics_output_transparency_supported(output_format):
    normalized_format = str(output_format or "").strip().lower()
    if not normalized_format:
        return False
    return normalized_format not in GRAPHICS_EXPORT_TRANSPARENCY_UNSUPPORTED_FORMATS


def graphics_output_options(
    output_format,
    *,
    dpi=300,
    transparent=False,
    size_inches=None,
):
    normalized_format = str(output_format or "").strip().lower()
    if not normalized_format:
        raise ValueError("Graphics output requires an output format.")
    if not isinstance(dpi, numbers.Integral) or int(dpi) <= 0:
        raise ValueError("Graphics output requires a positive integer DPI.")
    normalized_size = None
    if size_inches is not None:
        if not isinstance(size_inches, (list, tuple)) or len(size_inches) != 2:
            raise ValueError("Graphics output size_inches must be a length-2 sequence.")
        normalized_size = (float(size_inches[0]), float(size_inches[1]))
        if normalized_size[0] <= 0 or normalized_size[1] <= 0:
            raise ValueError("Graphics output size_inches values must be positive.")
    return {
        "format": normalized_format,
        "dpi": int(dpi),
        "transparent": bool(transparent)
        and graphics_output_transparency_supported(normalized_format),
        "size_inches": normalized_size,
    }


class FigureGraphicsExportCodec(FeatureCodec):
    feature_name = "figure_graphics_export"
    state_version = 1

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "settings": {
                "figure_name": None,
                "output_path": None,
                "output_format": "pdf",
                "dpi": 300,
                "transparent": False,
                "size_inches": None,
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
        for key in ("figure_name", "output_path", "output_format"):
            value = settings.get(key)
            settings[key] = None if value in (None, "") else str(value)
        settings["dpi"] = int(settings.get("dpi", 300))
        settings["transparent"] = bool(settings.get("transparent", False))
        size_inches = settings.get("size_inches")
        if size_inches in (None, ""):
            settings["size_inches"] = None
        else:
            settings["size_inches"] = (float(size_inches[0]), float(size_inches[1]))
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")
        settings = normalized["settings"]
        if not settings["figure_name"]:
            raise ValueError("Graphics export requires settings.figure_name.")
        if not settings["output_path"]:
            raise ValueError("Graphics export requires settings.output_path.")
        options = graphics_output_options(
            settings["output_format"],
            dpi=settings["dpi"],
            transparent=settings["transparent"],
            size_inches=settings["size_inches"],
        )
        settings["output_format"] = options["format"]
        settings["dpi"] = options["dpi"]
        settings["transparent"] = options["transparent"]
        settings["size_inches"] = options["size_inches"]
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")
        if action_type == "set":
            _set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            _set_path(normalized, action["path"], None)
        else:
            raise ValueError(f"Unsupported graphics export action: {action_type!r}.")
        return cls.normalize_state(normalized)

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        settings = normalized["settings"]
        savefig_source = (
            f"fig.savefig({settings['output_path']!r}, "
            f"format={settings['output_format']!r}, "
            f"dpi={settings['dpi']!r}, "
            f"transparent={settings['transparent']!r})"
        )
        if settings["size_inches"] is None:
            return "\n".join(
                figure_command_prelude_lines(settings["figure_name"]) + [savefig_source]
            )
        width, height = settings["size_inches"]
        return "\n".join(
            figure_command_prelude_lines(settings["figure_name"])
            + [
                "_hyde_original_size = tuple(fig.get_size_inches())",
                "try:",
                f"    fig.set_size_inches({width!r}, {height!r}, forward=False)",
                f"    {savefig_source}",
                "finally:",
                "    fig.set_size_inches(*_hyde_original_size, forward=False)",
            ]
        )


def figure_graphics_export_command_source(
    figure_name,
    output_path,
    *,
    output_format="pdf",
    dpi=300,
    transparent=False,
    size_inches=None,
):
    return FigureGraphicsExportCodec.state_to_python(
        {
            "settings": {
                "figure_name": figure_name,
                "output_path": output_path,
                "output_format": output_format,
                "dpi": dpi,
                "transparent": transparent,
                "size_inches": size_inches,
            }
        }
    )


class FigureCodec(FeatureCodec):
    feature_name = "figure"
    state_version = 1
    _valid_commands = {
        "create",
        "publish_figure_macros",
        "close",
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
                "figsize": None,
                "subplot_code": "111",
                "figure_number": None,
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
        figsize = settings.get("figsize")
        if figsize in (None, ""):
            settings["figsize"] = None
        else:
            if not isinstance(figsize, (list, tuple)) or len(figsize) != 2:
                raise ValueError("Figure figsize must be a length-2 sequence.")
            settings["figsize"] = (float(figsize[0]), float(figsize[1]))
        settings["subplot_code"] = str(settings.get("subplot_code", "111"))
        figure_number = settings.get("figure_number")
        settings["figure_number"] = (
            None if figure_number in (None, "") else int(figure_number)
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

        if settings["figsize"] is not None:
            if settings["figsize"][0] <= 0 or settings["figsize"][1] <= 0:
                raise ValueError("Figure figsize values must be positive.")
        if command == "close" and not settings["figure_number"]:
            raise ValueError(f"Figure command {command!r} requires a figure number.")
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
        figsize = settings["figsize"]
        y_names = list(normalized["items"])

        figure_args = []
        if title:
            figure_args.append(repr(title))
        if figsize is not None:
            figure_args.append(f"figsize={figsize!r}")
        lines = [f"fig = plt.figure({', '.join(figure_args)})"] if figure_args else ["fig = plt.figure()"]
        lines.append(f"ax = fig.add_subplot({settings['subplot_code']})")
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
        if settings["x_name"] and normalized["items"]:
            names.append(settings["x_name"])
        names.extend(normalized["items"])
        return tuple(_ordered_unique(names))

    @classmethod
    def wrapped_creation_lines(cls, state, helper_name="_hyde_figure"):
        normalized = cls.validate_state(state)
        parameters = list(cls.tracked_names(normalized))
        lines = [f"@hyde.figure(register=False)", f"def {helper_name}({', '.join(parameters)}):"]
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
            return "hyde.recreation_registry.publish_registry('figure')"
        if command == "close":
            return f"plt.close({normalized['settings']['figure_number']})"
        raise ValueError(f"Unsupported figure command: {command!r}.")

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        del context
        normalized = cls.validate_state(state)
        parameters = list(cls.tracked_names(normalized))
        body_lines = _macro_ready_lines(cls._creation_lines(normalized))
        body = "\n".join(f"    {line}" for line in body_lines)
        return (
            "@hyde.figure\n"
            f"def {macro_name}({', '.join(parameters)}):\n"
            f"{body}\n"
        )


def is_eligible_for_plot(metadata):
    python_type = metadata.get("python_type", "").lower()
    numpy_type = metadata.get("numpy_type", "")
    ndim = metadata.get("ndim", 1)
    kind = metadata.get("numpy_kind", "f")

    is_array = python_type in ("ndarray", "series") or numpy_type == "Array"
    is_numeric = kind in "biuf"

    return is_array and is_numeric and ndim == 1


def sorted_eligible_names(objects_metadata):
    eligible = []
    for name, metadata in dict(objects_metadata or {}).items():
        if is_eligible_for_plot(dict(metadata or {})):
            eligible.append(str(name))
    return sorted(eligible)


def apply_figure_state(figure, state, namespace):
    normalized = FigureCodec.normalize_state(state)
    settings = normalized["settings"]
    title = settings["title"]
    x_name = settings["x_name"]
    figsize = settings["figsize"]
    y_names = list(normalized["items"])

    namespace = dict(namespace or {})
    x_values = namespace.get(x_name) if x_name else None

    figure.clear()
    if figsize is not None:
        figure.set_size_inches(*figsize, forward=False)
    if title:
        figure.set_label(title)
    axis = figure.add_subplot(int(settings["subplot_code"]))

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


_AXIS_SIDE_TO_AXIS = {
    "bottom": "x",
    "top": "x",
    "left": "y",
    "right": "y",
}
_PRIMARY_SIDE = {"x": "bottom", "y": "left"}
_MIRROR_SIDE = {"x": "top", "y": "right"}


def _deep_merge_dict(target, updates):
    for key, value in dict(updates or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_dict(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def _normalize_optional_float(value):
    if value in (None, ""):
        return None
    return float(value)


def _normalize_float_pair(value, field_name, default=None):
    if value in (None, ""):
        return copy.deepcopy(default)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field_name} must be a length-2 sequence.")
    return (float(value[0]), float(value[1]))


def _default_axis_state(axis_name):
    return {
        "id": axis_name,
        "scale_mode": "linear",
        "log_tick_mode": "plain",
        "range": {
            "limits": None,
            "limit_mode": {
                "min": "auto",
                "max": "auto",
            },
            "autoscale": "data",
            "reverse": False,
        },
        "label": {
            "text": None,
            "visible": True,
            "side": _PRIMARY_SIDE[axis_name],
            "position_mode": "auto",
            "position": None,
            "offset": 0.0,
            "rotation": None,
            "line_spacing": 1.2,
            "color": None,
        },
        "ticks": {
            "major": {
                "mode": "auto",
                "count": None,
                "step": None,
                "positions": None,
                "labels": None,
            },
            "minor": {
                "visible": False,
            },
            "direction": "outside",
            "formatter": {
                "style": "plain",
                "low_trip": None,
                "high_trip": None,
                "exponent_prescale": None,
                "use_thousands_separator": False,
                "zero_as_zero": True,
                "trim_trailing_zeros": False,
                "trim_leading_zero": False,
                "prefer_exponent": False,
            },
            "suppressed_values": [],
            "display_range": None,
            "max_log_cycles_minor": None,
            "max_log_cycles_minor_labels": None,
        },
        "grid": {
            "visible": False,
            "which": "major",
            "linestyle": "-",
            "linewidth": None,
            "color": None,
        },
        "zero_line": {
            "visible": False,
            "linestyle": "-",
            "linewidth": None,
            "color": None,
        },
    }


def _normalize_axis_label(axis_name, label, legacy_text=None):
    normalized = _default_axis_state(axis_name)["label"]
    explicit_visible = isinstance(label, dict) and "visible" in label
    if isinstance(label, dict):
        _deep_merge_dict(normalized, label)
    elif label not in (None, ""):
        normalized["text"] = str(label)
    if normalized["text"] in (None, ""):
        normalized["text"] = None if legacy_text in (None, "") else str(legacy_text)
    else:
        normalized["text"] = str(normalized["text"])
    if explicit_visible:
        normalized["visible"] = bool(normalized.get("visible"))
    else:
        normalized["visible"] = bool(normalized.get("visible", True))
    if normalized["side"] not in {
        _PRIMARY_SIDE[axis_name],
        _MIRROR_SIDE[axis_name],
    }:
        raise ValueError(f"Axis {axis_name!r} label side is invalid.")
    normalized["position_mode"] = str(normalized.get("position_mode", "auto"))
    position = normalized.get("position")
    normalized["position"] = _normalize_optional_float(position)
    normalized["offset"] = float(normalized.get("offset", 0.0) or 0.0)
    normalized["rotation"] = _normalize_optional_float(normalized.get("rotation"))
    normalized["line_spacing"] = float(normalized.get("line_spacing", 1.2) or 1.2)
    color = normalized.get("color")
    normalized["color"] = None if color in (None, "") else str(color)
    return normalized


def _normalize_axis_range(axis_name, range_state, legacy_limits=None):
    normalized = _default_axis_state(axis_name)["range"]
    if isinstance(range_state, dict):
        _deep_merge_dict(normalized, range_state)
    limit_mode = dict(normalized.get("limit_mode", {}) or {})
    normalized["limit_mode"] = {
        "min": str(limit_mode.get("min", "auto")),
        "max": str(limit_mode.get("max", "auto")),
    }
    limits = normalized.get("limits")
    if limits in (None, []):
        normalized["limits"] = (
            None
            if legacy_limits in (None, [])
            else _normalize_float_pair(legacy_limits, "axis limits")
        )
    else:
        if not isinstance(limits, (list, tuple)) or len(limits) != 2:
            raise ValueError("axis limits must be a length-2 sequence.")
        minimum = (
            None
            if limits[0] in (None, "")
            else float(limits[0])
        )
        maximum = (
            None
            if limits[1] in (None, "")
            else float(limits[1])
        )
        normalized["limits"] = (minimum, maximum)
    normalized["autoscale"] = str(normalized.get("autoscale", "data"))
    normalized["reverse"] = bool(normalized.get("reverse"))
    return normalized


def _normalize_axis_ticks(axis_name, ticks):
    normalized = _default_axis_state(axis_name)["ticks"]
    if isinstance(ticks, dict):
        _deep_merge_dict(normalized, ticks)
    major = dict(normalized.get("major", {}) or {})
    positions = major.get("positions")
    major["positions"] = (
        None
        if positions in (None, [])
        else [float(value) for value in positions]
    )
    labels = major.get("labels")
    major["labels"] = (
        None if labels in (None, []) else [str(value) for value in labels]
    )
    major["mode"] = str(major.get("mode", "auto"))
    major["count"] = (
        None if major.get("count") in (None, "") else int(major.get("count"))
    )
    major["step"] = _normalize_optional_float(major.get("step"))
    normalized["major"] = major
    normalized["minor"] = {
        "visible": bool(dict(normalized.get("minor", {}) or {}).get("visible"))
    }
    normalized["direction"] = str(normalized.get("direction", "outside"))
    formatter = dict(normalized.get("formatter", {}) or {})
    normalized["formatter"] = {
        "style": str(formatter.get("style", "plain")),
        "low_trip": _normalize_optional_float(formatter.get("low_trip")),
        "high_trip": _normalize_optional_float(formatter.get("high_trip")),
        "exponent_prescale": _normalize_optional_float(
            formatter.get("exponent_prescale")
        ),
        "use_thousands_separator": bool(
            formatter.get("use_thousands_separator", False)
        ),
        "zero_as_zero": bool(formatter.get("zero_as_zero", True)),
        "trim_trailing_zeros": bool(formatter.get("trim_trailing_zeros", False)),
        "trim_leading_zero": bool(formatter.get("trim_leading_zero", False)),
        "prefer_exponent": bool(formatter.get("prefer_exponent", False)),
    }
    suppressed = normalized.get("suppressed_values", [])
    normalized["suppressed_values"] = [
        float(value)
        for value in suppressed
    ]
    normalized["display_range"] = _normalize_float_pair(
        normalized.get("display_range"),
        "tick display range",
        default=None,
    )
    normalized["max_log_cycles_minor"] = _normalize_optional_float(
        normalized.get("max_log_cycles_minor")
    )
    normalized["max_log_cycles_minor_labels"] = _normalize_optional_float(
        normalized.get("max_log_cycles_minor_labels")
    )
    return normalized


def _normalize_axis_grid(axis_name, grid):
    normalized = _default_axis_state(axis_name)["grid"]
    if isinstance(grid, dict):
        _deep_merge_dict(normalized, grid)
    normalized["visible"] = bool(normalized.get("visible"))
    normalized["which"] = str(normalized.get("which", "major"))
    normalized["linestyle"] = str(normalized.get("linestyle", "-"))
    normalized["linewidth"] = _normalize_optional_float(normalized.get("linewidth"))
    color = normalized.get("color")
    normalized["color"] = None if color in (None, "") else str(color)
    return normalized


def _normalize_axis_zero_line(axis_name, zero_line):
    normalized = _default_axis_state(axis_name)["zero_line"]
    if isinstance(zero_line, dict):
        _deep_merge_dict(normalized, zero_line)
    normalized["visible"] = bool(normalized.get("visible"))
    normalized["linestyle"] = str(normalized.get("linestyle", "-"))
    normalized["linewidth"] = _normalize_optional_float(normalized.get("linewidth"))
    color = normalized.get("color")
    normalized["color"] = None if color in (None, "") else str(color)
    return normalized


def _normalize_axis_state(axis_name, axis_state, legacy_label=None, legacy_limits=None):
    normalized = _default_axis_state(axis_name)
    if isinstance(axis_state, dict):
        _deep_merge_dict(normalized, axis_state)
    normalized["id"] = axis_name
    normalized["scale_mode"] = str(normalized.get("scale_mode", "linear"))
    normalized["log_tick_mode"] = str(normalized.get("log_tick_mode", "plain"))
    normalized["range"] = _normalize_axis_range(
        axis_name,
        normalized.get("range"),
        legacy_limits=legacy_limits,
    )
    normalized["label"] = _normalize_axis_label(
        axis_name,
        normalized.get("label"),
        legacy_text=legacy_label,
    )
    normalized["ticks"] = _normalize_axis_ticks(axis_name, normalized.get("ticks"))
    normalized["grid"] = _normalize_axis_grid(axis_name, normalized.get("grid"))
    normalized["zero_line"] = _normalize_axis_zero_line(
        axis_name,
        normalized.get("zero_line"),
    )
    return normalized


def _default_axis_side_state(side):
    axis_name = _AXIS_SIDE_TO_AXIS[side]
    primary = _PRIMARY_SIDE[axis_name] == side
    return {
        "side": side,
        "axis": axis_name,
        "spine_visible": primary,
        "ticks_visible": primary,
        "tick_labels_visible": primary,
        "spine_color": None,
        "spine_width": None,
        "tick_label_color": None,
        "tick_label_rotation": 0.0,
        "tick_label_offset": 0.0,
        "offset": 0.0,
        "draw_on_top": False,
    }


def _default_subplot_margins():
    return {
        "left": None,
        "bottom": None,
        "right": None,
        "top": None,
    }


def _normalize_subplot_margins(margins):
    normalized = _default_subplot_margins()
    if isinstance(margins, dict):
        _deep_merge_dict(normalized, margins)
    for side in ("left", "bottom", "right", "top"):
        normalized[side] = _normalize_optional_float(normalized.get(side))
    return normalized


def _normalize_axis_side_state(side, side_state):
    normalized = _default_axis_side_state(side)
    if isinstance(side_state, dict):
        _deep_merge_dict(normalized, side_state)
    normalized.pop("draw_between", None)
    normalized["side"] = side
    normalized["axis"] = _AXIS_SIDE_TO_AXIS[side]
    normalized["spine_visible"] = bool(normalized.get("spine_visible"))
    normalized["ticks_visible"] = bool(normalized.get("ticks_visible"))
    normalized["tick_labels_visible"] = bool(normalized.get("tick_labels_visible"))
    spine_color = normalized.get("spine_color")
    normalized["spine_color"] = None if spine_color in (None, "") else str(spine_color)
    tick_label_color = normalized.get("tick_label_color")
    normalized["tick_label_color"] = (
        None if tick_label_color in (None, "") else str(tick_label_color)
    )
    normalized["spine_width"] = _normalize_optional_float(normalized.get("spine_width"))
    normalized["tick_label_rotation"] = float(
        normalized.get("tick_label_rotation", 0.0) or 0.0
    )
    normalized["tick_label_offset"] = float(
        normalized.get("tick_label_offset", 0.0) or 0.0
    )
    normalized["offset"] = float(normalized.get("offset", 0.0) or 0.0)
    normalized["draw_on_top"] = bool(normalized.get("draw_on_top"))
    return normalized


def _sync_legacy_subplot_axis_fields(subplot):
    subplot["xlabel"] = subplot["axes"]["x"]["label"]["text"]
    subplot["ylabel"] = subplot["axes"]["y"]["label"]["text"]
    subplot["x_limits"] = subplot["axes"]["x"]["range"]["limits"]
    subplot["y_limits"] = subplot["axes"]["y"]["range"]["limits"]
    return subplot


class FigureIRCodec(FeatureCodec):
    feature_name = "figure"
    state_version = 1

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "settings": {
                "title": None,
                "figsize": None,
            },
            "layout": {
                "kind": "single_subplot",
                "subplots": [],
            },
            "opaque_nodes": [],
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
            layout = state.get("layout", {})
            if isinstance(layout, dict):
                normalized["layout"]["kind"] = str(
                    layout.get("kind", normalized["layout"]["kind"])
                )
                subplots = layout.get("subplots", [])
                normalized["layout"]["subplots"] = [
                    cls._normalize_subplot(subplot, index)
                    for index, subplot in enumerate(subplots)
                ]
            opaque_nodes = state.get("opaque_nodes", [])
            normalized["opaque_nodes"] = [
                cls._normalize_opaque_node(node)
                for node in opaque_nodes
            ]

        title = normalized["settings"].get("title")
        normalized["settings"]["title"] = None if title in (None, "") else str(title)
        figsize = normalized["settings"].get("figsize")
        if figsize in (None, ""):
            normalized["settings"]["figsize"] = None
        else:
            if not isinstance(figsize, (list, tuple)) or len(figsize) != 2:
                raise ValueError("Figure IR figsize must be a length-2 sequence.")
            normalized["settings"]["figsize"] = (float(figsize[0]), float(figsize[1]))
        return normalized

    @classmethod
    def _normalize_subplot(cls, subplot, index):
        normalized = {
            "id": f"subplot{index}",
            "subplot_code": "111",
            "title": None,
            "margins": _default_subplot_margins(),
            "xlabel": None,
            "ylabel": None,
            "x_limits": None,
            "y_limits": None,
            "legend": False,
            "traces": [],
            "axes": {},
            "axis_sides": {},
            "opaque_nodes": [],
        }
        if isinstance(subplot, dict):
            normalized.update(
                {
                    "id": str(subplot.get("id", normalized["id"])),
                    "subplot_code": str(
                        subplot.get("subplot_code", normalized["subplot_code"])
                    ),
                    "legend": bool(subplot.get("legend", normalized["legend"])),
                }
            )
            for field in ("title", "xlabel", "ylabel"):
                value = subplot.get(field)
                normalized[field] = None if value in (None, "") else str(value)
            for field in ("x_limits", "y_limits"):
                value = subplot.get(field)
                if value in (None, []):
                    normalized[field] = None
                else:
                    normalized[field] = tuple(value)
            normalized["margins"] = _normalize_subplot_margins(
                subplot.get("margins")
            )
            normalized["traces"] = [
                cls._normalize_trace(trace, trace_index)
                for trace_index, trace in enumerate(subplot.get("traces", []))
            ]
            normalized["opaque_nodes"] = [
                cls._normalize_opaque_node(node)
                for node in subplot.get("opaque_nodes", [])
            ]
            axes = dict(subplot.get("axes", {}) or {})
            normalized["axes"] = {
                "x": _normalize_axis_state(
                    "x",
                    axes.get("x"),
                    legacy_label=normalized["xlabel"],
                    legacy_limits=normalized["x_limits"],
                ),
                "y": _normalize_axis_state(
                    "y",
                    axes.get("y"),
                    legacy_label=normalized["ylabel"],
                    legacy_limits=normalized["y_limits"],
                ),
            }
            axis_sides = dict(subplot.get("axis_sides", {}) or {})
            normalized["axis_sides"] = {
                side: _normalize_axis_side_state(side, axis_sides.get(side))
                for side in ("bottom", "top", "left", "right")
            }
        else:
            normalized["margins"] = _normalize_subplot_margins(None)
            normalized["axes"] = {
                "x": _normalize_axis_state("x", None),
                "y": _normalize_axis_state("y", None),
            }
            normalized["axis_sides"] = {
                side: _normalize_axis_side_state(side, None)
                for side in ("bottom", "top", "left", "right")
            }
        return _sync_legacy_subplot_axis_fields(normalized)

    @classmethod
    def _normalize_trace(cls, trace, index):
        normalized = {
            "id": f"trace{index}",
            "kind": "line",
            "x_source": None,
            "y_source": None,
            "kwargs": {},
        }
        if isinstance(trace, dict):
            normalized["id"] = str(trace.get("id", normalized["id"]))
            normalized["kind"] = str(trace.get("kind", normalized["kind"]))
            normalized["x_source"] = cls._normalize_operand(trace.get("x_source"))
            normalized["y_source"] = cls._normalize_operand(trace.get("y_source"))
            kwargs = trace.get("kwargs", {})
            if isinstance(kwargs, dict):
                normalized["kwargs"] = dict(kwargs)
        return normalized

    @classmethod
    def _normalize_operand(cls, operand):
        if operand in (None, ""):
            return None
        if not isinstance(operand, dict):
            raise ValueError("Figure operands must be mappings.")
        kind = str(operand.get("kind"))
        if kind == "name":
            return {"kind": "name", "value": str(operand["value"])}
        if kind == "literal":
            return {"kind": "literal", "value": operand.get("value")}
        if kind == "array_literal":
            return {"kind": "array_literal", "value": list(operand.get("value", []))}
        if kind == "attribute_path":
            root = cls._normalize_operand(operand.get("root"))
            if root is None:
                raise ValueError("Figure attribute_path operands require a root operand.")
            path = [str(part) for part in operand.get("path", []) if str(part)]
            if not path:
                raise ValueError("Figure attribute_path operands require a path.")
            return {"kind": "attribute_path", "root": root, "path": path}
        raise ValueError(f"Unsupported figure operand kind: {kind!r}.")

    @classmethod
    def _normalize_opaque_node(cls, node):
        source = ""
        if isinstance(node, dict):
            source = str(node.get("source", ""))
        elif node not in (None, ""):
            source = str(node)
        return {"kind": "opaque", "source": source}

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")
        figsize = normalized["settings"].get("figsize")
        if figsize is not None and (figsize[0] <= 0 or figsize[1] <= 0):
            raise ValueError("Figure IR figsize values must be positive.")
        layout = normalized["layout"]
        if layout["kind"] not in {"single_subplot", "gridspec"}:
            raise ValueError(f"Unsupported figure layout kind: {layout['kind']!r}.")
        for subplot in layout["subplots"]:
            if subplot["subplot_code"] != "111":
                raise ValueError("Initial Hyde figure IR only supports subplot code '111'.")
            margins = subplot["margins"]
            for side in ("left", "bottom", "right", "top"):
                value = margins[side]
                if value is not None and not 0.0 <= value <= 1.0:
                    raise ValueError("Subplot margins must stay within [0, 1].")
            if (
                margins["left"] is not None
                and margins["right"] is not None
                and margins["left"] >= margins["right"]
            ):
                raise ValueError("Subplot left margin must be smaller than right.")
            if (
                margins["bottom"] is not None
                and margins["top"] is not None
                and margins["bottom"] >= margins["top"]
            ):
                raise ValueError("Subplot bottom margin must be smaller than top.")
            for axis_name in ("x", "y"):
                axis_state = subplot["axes"][axis_name]
                if axis_state["scale_mode"] not in {"linear", "log", "log2"}:
                    raise ValueError(
                        f"Unsupported {axis_name}-axis scale mode: {axis_state['scale_mode']!r}."
                    )
                if axis_state["range"]["limit_mode"]["min"] not in {"auto", "manual"}:
                    raise ValueError("Axis minimum mode must be 'auto' or 'manual'.")
                if axis_state["range"]["limit_mode"]["max"] not in {"auto", "manual"}:
                    raise ValueError("Axis maximum mode must be 'auto' or 'manual'.")
                limits = axis_state["range"]["limits"]
                if limits is not None:
                    if (
                        axis_state["range"]["limit_mode"]["min"] == "manual"
                        and limits[0] is None
                    ):
                        raise ValueError("Manual axis minimum requires a numeric limit.")
                    if (
                        axis_state["range"]["limit_mode"]["max"] == "manual"
                        and limits[1] is None
                    ):
                        raise ValueError("Manual axis maximum requires a numeric limit.")
                    if limits[0] is not None and limits[1] is not None and limits[0] >= limits[1]:
                        raise ValueError("Axis limits must be strictly increasing.")
                    if axis_state["scale_mode"] in {"log", "log2"}:
                        if (
                            limits[0] is not None
                            and limits[0] <= 0
                        ) or (
                            limits[1] is not None
                            and limits[1] <= 0
                        ):
                            raise ValueError("Log axes require positive limits.")
                if (
                    axis_state["ticks"]["major"]["labels"] is not None
                    and axis_state["ticks"]["major"]["positions"] is not None
                    and len(axis_state["ticks"]["major"]["labels"])
                    != len(axis_state["ticks"]["major"]["positions"])
                ):
                    raise ValueError("Manual tick labels must match manual positions.")
                if axis_state["ticks"]["direction"] not in {
                    "inside",
                    "outside",
                    "both",
                }:
                    raise ValueError("Axis tick direction is invalid.")
                if axis_state["grid"]["which"] not in {"major", "minor", "both"}:
                    raise ValueError("Axis grid 'which' must be major, minor, or both.")
            for side, side_state in subplot["axis_sides"].items():
                if side_state["axis"] != _AXIS_SIDE_TO_AXIS[side]:
                    raise ValueError(f"Axis side {side!r} is mapped to the wrong axis.")
            for trace in subplot["traces"]:
                if trace["kind"] != "line":
                    raise ValueError(f"Unsupported figure trace kind: {trace['kind']!r}.")
                if trace["y_source"] is None:
                    raise ValueError("Figure traces require y_source.")
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.validate_state(state)
        action_type = str(action.get("type", ""))
        subplot = cls._resolve_subplot(normalized, action.get("subplot_id"))

        if action_type == "set_axis_limits":
            axis_name = str(action.get("axis", ""))
            if axis_name not in {"x", "y"}:
                raise ValueError("Figure axis limit edits require axis='x' or axis='y'.")
            subplot["axes"][axis_name]["range"]["limits"] = (
                float(action.get("min")),
                float(action.get("max")),
            )
            subplot["axes"][axis_name]["range"]["limit_mode"] = {
                "min": "manual",
                "max": "manual",
            }
        elif action_type == "set_axis_label":
            axis_name = str(action.get("axis", ""))
            if axis_name not in {"x", "y"}:
                raise ValueError("Figure axis label edits require axis='x' or axis='y'.")
            label = None if action.get("label") in (None, "") else str(action.get("label"))
            subplot["axes"][axis_name]["label"]["text"] = label
            if label is not None:
                subplot["axes"][axis_name]["label"]["visible"] = True
        elif action_type == "set_axis_state":
            axis_name = str(action.get("axis", ""))
            if axis_name not in {"x", "y"}:
                raise ValueError("Figure axis edits require axis='x' or axis='y'.")
            axis_state = copy.deepcopy(subplot["axes"][axis_name])
            if action.get("replace"):
                axis_state = _default_axis_state(axis_name)
            _deep_merge_dict(axis_state, action.get("state"))
            subplot["axes"][axis_name] = axis_state
        elif action_type == "set_axis_side_state":
            side = str(action.get("side", ""))
            if side not in _AXIS_SIDE_TO_AXIS:
                raise ValueError(f"Unsupported figure axis side: {side!r}.")
            side_state = copy.deepcopy(subplot["axis_sides"][side])
            if action.get("replace"):
                side_state = _default_axis_side_state(side)
            _deep_merge_dict(side_state, action.get("state"))
            subplot["axis_sides"][side] = side_state
        elif action_type == "set_subplot_margins":
            margins = copy.deepcopy(subplot["margins"])
            if action.get("replace"):
                margins = _default_subplot_margins()
            _deep_merge_dict(margins, action.get("state"))
            subplot["margins"] = margins
        elif action_type in {"set_subplot_title", "set_figure_title"}:
            title = None if action.get("title") in (None, "") else str(action.get("title"))
            subplot["title"] = title
            normalized["settings"]["title"] = title
        elif action_type == "set_legend_visible":
            subplot["legend"] = bool(action.get("visible"))
        elif action_type == "set_trace_style":
            trace = cls._resolve_trace(subplot, action.get("trace_id"))
            style = dict(action.get("style", {}) or {})
            if action.get("replace"):
                for key in (
                    "alpha",
                    "color",
                    "drawstyle",
                    "linestyle",
                    "linewidth",
                    "marker",
                    "markeredgecolor",
                    "markeredgewidth",
                    "markerfacecolor",
                    "markersize",
                    "visible",
                ):
                    trace["kwargs"].pop(key, None)
            for key in (
                "alpha",
                "color",
                "drawstyle",
                "label",
                "linestyle",
                "linewidth",
                "marker",
                "markeredgecolor",
                "markeredgewidth",
                "markerfacecolor",
                "markersize",
                "visible",
            ):
                if key in style:
                    trace["kwargs"][key] = style[key]
        elif action_type == "set_trace":
            trace_id = str(action.get("trace_id") or "")
            if not trace_id:
                raise ValueError("Figure trace edits require trace_id.")
            traces = subplot["traces"]
            trace_index = next(
                (
                    index
                    for index, trace in enumerate(traces)
                    if trace["id"] == trace_id
                ),
                None,
            )
            trace_state = action.get("trace")
            if trace_state is None:
                if trace_index is not None:
                    del traces[trace_index]
            else:
                normalized_trace = cls._normalize_trace(
                    {**dict(trace_state), "id": trace_id},
                    len(traces) if trace_index is None else trace_index,
                )
                if trace_index is None:
                    traces.append(normalized_trace)
                else:
                    traces[trace_index] = normalized_trace
        else:
            raise ValueError(f"Unsupported figure IR action: {action_type!r}.")

        _sync_legacy_subplot_axis_fields(subplot)
        return cls.validate_state(normalized)

    @classmethod
    def _resolve_subplot(cls, normalized, subplot_id):
        subplots = normalized["layout"]["subplots"]
        if not subplots:
            raise ValueError("Figure IR does not contain any subplots.")
        if subplot_id in (None, ""):
            return subplots[0]
        for subplot in subplots:
            if subplot["id"] == str(subplot_id):
                return subplot
        raise ValueError(f"Unknown figure subplot id: {subplot_id!r}.")

    @classmethod
    def _resolve_trace(cls, subplot, trace_id):
        traces = subplot["traces"]
        if not traces:
            raise ValueError("Figure IR does not contain any traces.")
        if trace_id in (None, ""):
            return traces[0]
        for trace in traces:
            if trace["id"] == str(trace_id):
                return trace
        raise ValueError(f"Unknown figure trace id: {trace_id!r}.")

    @classmethod
    def tracked_names(cls, state):
        normalized = cls.validate_state(state)
        names = []
        for subplot in normalized["layout"]["subplots"]:
            for trace in subplot["traces"]:
                names.extend(_operand_names(trace["x_source"]))
                names.extend(_operand_names(trace["y_source"]))
        return tuple(_ordered_unique(names))

    @classmethod
    def _lowering_defaults(cls, normalized, context):
        defaults = dict((context or {}).get("figure_defaults", {}) or {})
        default_ir = defaults.get("figure_ir")
        if default_ir is None and (
            "layout" in defaults or "settings" in defaults
        ):
            default_ir = defaults
        normalized_ir = None
        if default_ir is not None:
            try:
                normalized_ir = cls.validate_state(default_ir)
            except Exception:
                normalized_ir = None
        trace_styles = dict(defaults.get("trace_styles", {}) or {})
        return normalized_ir, trace_styles

    @classmethod
    def _subplot_default(cls, default_ir):
        if default_ir is None:
            return None
        subplots = list(default_ir.get("layout", {}).get("subplots", []))
        return None if not subplots else subplots[0]

    @classmethod
    def _trace_default_style(cls, trace_styles, subplot_id, trace_id):
        return dict(trace_styles.get(subplot_id, {}).get(trace_id, {}) or {})

    @classmethod
    def _plot_call(cls, trace, default_style=None):
        arguments = []
        x_source = _operand_to_python(trace["x_source"])
        y_source = _operand_to_python(trace["y_source"])
        if x_source:
            arguments.append(x_source)
        arguments.append(y_source)
        default_style = dict(default_style or {})
        kwargs = ", ".join(
            f"{name}={value!r}"
            for name, value in trace["kwargs"].items()
            if value is not None and default_style.get(name) != value
        )
        if kwargs:
            arguments.append(kwargs)
        return f"ax.plot({', '.join(arguments)})"

    @classmethod
    def _scale_lines(cls, axis_name, axis_state, default_axis_state=None):
        default_mode = None if default_axis_state is None else default_axis_state["scale_mode"]
        if default_mode == axis_state["scale_mode"]:
            return []
        if axis_state["scale_mode"] == "linear":
            return []
        if axis_state["scale_mode"] == "log":
            return [f"ax.set_{axis_name}scale('log')"]
        return [f"ax.set_{axis_name}scale('log', base=2)"]

    @classmethod
    def _tick_params_line(cls, axis_name, subplot, default_subplot=None):
        primary = subplot["axis_sides"][_PRIMARY_SIDE[axis_name]]
        mirror = subplot["axis_sides"][_MIRROR_SIDE[axis_name]]
        default_primary = None
        default_mirror = None
        default_direction = None
        if default_subplot is not None:
            default_primary = default_subplot["axis_sides"][_PRIMARY_SIDE[axis_name]]
            default_mirror = default_subplot["axis_sides"][_MIRROR_SIDE[axis_name]]
            default_direction = default_subplot["axes"][axis_name]["ticks"]["direction"]
            if (
                default_primary["ticks_visible"] == primary["ticks_visible"]
                and default_primary["tick_labels_visible"] == primary["tick_labels_visible"]
                and default_mirror["ticks_visible"] == mirror["ticks_visible"]
                and default_mirror["tick_labels_visible"] == mirror["tick_labels_visible"]
                and default_direction == subplot["axes"][axis_name]["ticks"]["direction"]
            ):
                return None
        direction_map = {
            "inside": "in",
            "outside": "out",
            "both": "inout",
        }
        kwargs = [
            f"axis={axis_name!r}",
            "which='both'",
            f"{_MIRROR_SIDE[axis_name]}={mirror['ticks_visible']!r}",
            f"label{_MIRROR_SIDE[axis_name]}={mirror['tick_labels_visible']!r}",
            f"{_PRIMARY_SIDE[axis_name]}={primary['ticks_visible']!r}",
            f"label{_PRIMARY_SIDE[axis_name]}={primary['tick_labels_visible']!r}",
            f"direction={direction_map[subplot['axes'][axis_name]['ticks']['direction']]!r}",
        ]
        return f"ax.tick_params({', '.join(kwargs)})"

    @classmethod
    def _spine_lines(cls, axis_name, subplot, default_subplot=None):
        lines = []
        for side in (_PRIMARY_SIDE[axis_name], _MIRROR_SIDE[axis_name]):
            side_state = subplot["axis_sides"][side]
            default_side_state = None
            if default_subplot is not None:
                default_side_state = default_subplot["axis_sides"][side]
            if default_side_state is None or default_side_state["spine_visible"] != side_state["spine_visible"]:
                lines.append(f"ax.spines[{side!r}].set_visible({side_state['spine_visible']!r})")
            if side_state["spine_color"] is not None and (
                default_side_state is None or default_side_state["spine_color"] != side_state["spine_color"]
            ):
                lines.append(f"ax.spines[{side!r}].set_color({side_state['spine_color']!r})")
            if side_state["spine_width"] is not None and (
                default_side_state is None or default_side_state["spine_width"] != side_state["spine_width"]
            ):
                lines.append(f"ax.spines[{side!r}].set_linewidth({side_state['spine_width']!r})")
            if side_state["offset"] and (
                default_side_state is None or default_side_state["offset"] != side_state["offset"]
            ):
                lines.append(
                    f"ax.spines[{side!r}].set_position(('outward', {side_state['offset']!r}))"
                )
        return lines

    @classmethod
    def _label_lines(cls, axis_name, axis_state, default_axis_state=None):
        label = axis_state["label"]
        setter = "xlabel" if axis_name == "x" else "ylabel"
        position_method = "xaxis" if axis_name == "x" else "yaxis"
        if default_axis_state is None:
            lines = [
                f"ax.{position_method}.set_label_position({label['side']!r})",
                f"ax.set_{setter}({label['text']!r})",
            ]
            if not label["visible"]:
                lines.append(f"ax.{position_method}.label.set_visible(False)")
            if label["color"] is not None:
                lines.append(f"ax.{position_method}.label.set_color({label['color']!r})")
            if label["rotation"] is not None:
                lines.append(f"ax.{position_method}.label.set_rotation({label['rotation']!r})")
            if label["line_spacing"] != 1.2:
                lines.append(
                    f"ax.{position_method}.label.set_linespacing({label['line_spacing']!r})"
                )
            if label["position_mode"] == "manual" and label["position"] is not None:
                coord_name = f"_hyde_{axis_name}_label_coords"
                if axis_name == "x":
                    lines.append(f"{coord_name} = ax.{position_method}.label.get_position()")
                    lines.append(
                        f"ax.{position_method}.set_label_coords({label['position']!r}, {coord_name}[1])"
                    )
                else:
                    lines.append(f"{coord_name} = ax.{position_method}.label.get_position()")
                    lines.append(
                        f"ax.{position_method}.set_label_coords({coord_name}[0], {label['position']!r})"
                    )
            if label["offset"]:
                lines.append(f"ax.{position_method}.labelpad = {label['offset']!r}")
            return lines
        default_label = default_axis_state["label"]
        lines = []
        if label["side"] != default_label["side"]:
            lines.append(f"ax.{position_method}.set_label_position({label['side']!r})")
        if label["text"] != default_label["text"] and label["text"] is not None:
            lines.append(f"ax.set_{setter}({label['text']!r})")
        if not label["visible"] and label["visible"] != default_label["visible"]:
            lines.append(f"ax.{position_method}.label.set_visible(False)")
        if label["color"] is not None and label["color"] != default_label["color"]:
            lines.append(f"ax.{position_method}.label.set_color({label['color']!r})")
        if label["rotation"] is not None and label["rotation"] != default_label["rotation"]:
            lines.append(f"ax.{position_method}.label.set_rotation({label['rotation']!r})")
        if label["line_spacing"] != default_label["line_spacing"]:
            lines.append(
                f"ax.{position_method}.label.set_linespacing({label['line_spacing']!r})"
            )
        if label["position_mode"] == "manual" and label["position"] is not None:
            coord_name = f"_hyde_{axis_name}_label_coords"
            if axis_name == "x":
                lines.append(f"{coord_name} = ax.{position_method}.label.get_position()")
                lines.append(
                    f"ax.{position_method}.set_label_coords({label['position']!r}, {coord_name}[1])"
                )
            else:
                lines.append(f"{coord_name} = ax.{position_method}.label.get_position()")
                lines.append(
                    f"ax.{position_method}.set_label_coords({coord_name}[0], {label['position']!r})"
                )
        if label["offset"] != default_label["offset"]:
            lines.append(f"ax.{position_method}.labelpad = {label['offset']!r}")
        return lines

    @classmethod
    @classmethod
    def _range_lines(cls, axis_name, axis_state, default_axis_state=None):
        if default_axis_state is not None and axis_state["range"] == default_axis_state["range"]:
            return []
        lines = []
        range_state = axis_state["range"]
        limits = range_state["limits"]
        limit_mode = range_state["limit_mode"]
        lower_name, upper_name = (
            ("left", "right") if axis_name == "x" else ("bottom", "top")
        )
        if (
            limits is not None
            and limit_mode["min"] == "manual"
            and limit_mode["max"] == "manual"
        ):
            lines.append(f"ax.set_{axis_name}lim({limits[0]!r}, {limits[1]!r})")
        else:
            lines.append(f"ax.autoscale(enable=True, axis={axis_name!r})")
            keyword_args = []
            if limits is not None and limit_mode["min"] == "manual":
                keyword_args.append(f"{lower_name}={limits[0]!r}")
            if limits is not None and limit_mode["max"] == "manual":
                keyword_args.append(f"{upper_name}={limits[1]!r}")
            if keyword_args:
                lines.append(f"ax.set_{axis_name}lim({', '.join(keyword_args)})")
        if axis_state["range"]["reverse"]:
            lines.append(f"ax.invert_{axis_name}axis()")
        return lines

    @classmethod
    def _axis_layer_lines(cls, subplot, default_subplot=None):
        default_draw_on_top = False
        if default_subplot is not None:
            default_draw_on_top = any(
                side_state["draw_on_top"]
                for side_state in default_subplot["axis_sides"].values()
            )
        current_draw_on_top = any(
            side_state["draw_on_top"]
            for side_state in subplot["axis_sides"].values()
        )
        if current_draw_on_top and current_draw_on_top != default_draw_on_top:
            return ["ax.set_axisbelow(False)"]
        return []

    @classmethod
    def _tick_locator_lines(cls, axis_name, axis_state, default_axis_state=None):
        if default_axis_state is not None and axis_state["ticks"] == default_axis_state["ticks"]:
            return False, []
        lines = []
        needs_ticker = False
        major = axis_state["ticks"]["major"]
        if major["positions"] is not None:
            needs_ticker = True
            lines.append(
                f"ax.{axis_name}axis.set_major_locator(mticker.FixedLocator({major['positions']!r}))"
            )
            if major["labels"] is not None:
                lines.append(
                    f"ax.{axis_name}axis.set_major_formatter(mticker.FixedFormatter({major['labels']!r}))"
                )
        elif major["mode"] == "manual" and major["step"] is not None:
            needs_ticker = True
            lines.append(
                f"ax.{axis_name}axis.set_major_locator(mticker.MultipleLocator({major['step']!r}))"
            )
        elif major["count"] is not None:
            needs_ticker = True
            lines.append(
                f"ax.{axis_name}axis.set_major_locator(mticker.MaxNLocator(nbins={major['count']!r}))"
            )
        if axis_state["ticks"]["minor"]["visible"]:
            needs_ticker = True
            if axis_state["scale_mode"] in {"log", "log2"}:
                base = 2 if axis_state["scale_mode"] == "log2" else 10
                lines.append(
                    f"ax.{axis_name}axis.set_minor_locator(mticker.LogLocator(base={base!r}, subs='auto'))"
                )
            else:
                lines.append(
                    f"ax.{axis_name}axis.set_minor_locator(mticker.AutoMinorLocator())"
                )
        return needs_ticker, lines

    @classmethod
    def _tick_label_style_lines(cls, axis_name, subplot, default_subplot=None):
        lines = []
        axis_accessor = f"ax.{axis_name}axis"
        primary_side = _PRIMARY_SIDE[axis_name]
        mirror_side = _MIRROR_SIDE[axis_name]
        for side, label_attr in (
            (primary_side, "label1"),
            (mirror_side, "label2"),
        ):
            side_state = subplot["axis_sides"][side]
            default_side_state = None
            if default_subplot is not None:
                default_side_state = default_subplot["axis_sides"][side]
            operations = []
            if side_state["tick_label_color"] is not None and (
                default_side_state is None
                or default_side_state["tick_label_color"] != side_state["tick_label_color"]
            ):
                operations.append(
                    f"_hyde_tick.{label_attr}.set_color({side_state['tick_label_color']!r})"
                )
            rotation = side_state["tick_label_rotation"]
            default_rotation = 0.0 if default_side_state is None else default_side_state["tick_label_rotation"]
            if rotation != default_rotation:
                operations.append(
                    f"_hyde_tick.{label_attr}.set_rotation({rotation!r})"
                )
            if not operations:
                continue
            lines.append(
                f"for _hyde_tick in {axis_accessor}.get_major_ticks() + {axis_accessor}.get_minor_ticks():"
            )
            lines.extend(f"    {operation}" for operation in operations)
        return lines

    @classmethod
    def _grid_lines(cls, axis_name, axis_state, default_axis_state=None):
        grid = axis_state["grid"]
        default_grid = None if default_axis_state is None else default_axis_state["grid"]
        if default_grid is not None and grid == default_grid:
            return []
        if not grid["visible"]:
            return []
        arguments = [
            "True",
            f"axis={axis_name!r}",
            f"which={grid['which']!r}",
            f"linestyle={grid['linestyle']!r}",
        ]
        if grid["linewidth"] is not None:
            arguments.append(f"linewidth={grid['linewidth']!r}")
        if grid["color"] is not None:
            arguments.append(f"color={grid['color']!r}")
        return [f"ax.grid({', '.join(arguments)})"]

    @classmethod
    def _zero_line_lines(cls, axis_name, axis_state, default_axis_state=None):
        zero_line = axis_state["zero_line"]
        default_zero_line = None if default_axis_state is None else default_axis_state["zero_line"]
        if default_zero_line is not None and zero_line == default_zero_line:
            return []
        if not zero_line["visible"]:
            return []
        call = "axvline" if axis_name == "x" else "axhline"
        arguments = ["0", f"linestyle={zero_line['linestyle']!r}"]
        if zero_line["linewidth"] is not None:
            arguments.append(f"linewidth={zero_line['linewidth']!r}")
        if zero_line["color"] is not None:
            arguments.append(f"color={zero_line['color']!r}")
        return [f"ax.{call}({', '.join(arguments)})"]

    @classmethod
    def state_to_python(cls, state, context=None):
        normalized = cls.validate_state(state)
        default_ir, trace_styles = cls._lowering_defaults(normalized, context)
        default_subplot = cls._subplot_default(default_ir)
        default_settings = (
            {}
            if default_ir is None
            else dict(default_ir.get("settings", {}) or {})
        )
        title = normalized["settings"]["title"]
        figsize = normalized["settings"]["figsize"]
        figure_args = []
        if title and title != default_settings.get("title"):
            figure_args.append(repr(title))
        if figsize is not None and figsize != default_settings.get("figsize"):
            figure_args.append(f"figsize={figsize!r}")
        lines = [f"fig = plt.figure({', '.join(figure_args)})" if figure_args else "fig = plt.figure()"]
        for figure_opaque in normalized["opaque_nodes"]:
            if figure_opaque["source"]:
                lines.extend(figure_opaque["source"].splitlines())
        subplots = normalized["layout"]["subplots"]
        if not subplots:
            lines.append("fig.show()")
            return "\n".join(lines)

        subplot = subplots[0]
        needs_ticker_import = False
        lines.append(f"ax = fig.add_subplot({subplot['subplot_code']})")
        margin_kwargs = []
        default_margins = (
            {}
            if default_subplot is None
            else dict(default_subplot.get("margins", {}) or {})
        )
        for side in ("left", "bottom", "right", "top"):
            value = subplot["margins"].get(side)
            if value is None:
                continue
            if default_subplot is not None and value == default_margins.get(side):
                continue
            margin_kwargs.append(f"{side}={value!r}")
        if margin_kwargs:
            lines.append(f"fig.subplots_adjust({', '.join(margin_kwargs)})")
        if subplot["title"] and (
            default_subplot is None or subplot["title"] != default_subplot["title"]
        ):
            lines.append(f"ax.set_title({subplot['title']!r})")
        for trace in subplot["traces"]:
            lines.append(
                cls._plot_call(
                    trace,
                    default_style=cls._trace_default_style(
                        trace_styles,
                        subplot["id"],
                        trace["id"],
                    ),
                )
            )
        if subplot["legend"] and (
            default_subplot is None or subplot["legend"] != default_subplot["legend"]
        ):
            lines.append("ax.legend()")
        lines.extend(cls._axis_layer_lines(subplot, default_subplot=default_subplot))
        for axis_name in ("x", "y"):
            axis_state = subplot["axes"][axis_name]
            default_axis_state = None if default_subplot is None else default_subplot["axes"][axis_name]
            lines.extend(cls._scale_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            lines.extend(cls._label_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            lines.extend(cls._range_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            tick_params_line = cls._tick_params_line(
                axis_name,
                subplot,
                default_subplot=default_subplot,
            )
            if tick_params_line:
                lines.append(tick_params_line)
            lines.extend(cls._spine_lines(axis_name, subplot, default_subplot=default_subplot))
            needs_ticker, locator_lines = cls._tick_locator_lines(
                axis_name,
                axis_state,
                default_axis_state=default_axis_state,
            )
            if needs_ticker:
                needs_ticker_import = True
                lines.extend(locator_lines)
            lines.extend(
                cls._tick_label_style_lines(
                    axis_name,
                    subplot,
                    default_subplot=default_subplot,
                )
            )
            lines.extend(cls._grid_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            lines.extend(
                cls._zero_line_lines(
                    axis_name,
                    axis_state,
                    default_axis_state=default_axis_state,
                )
            )
        if needs_ticker_import:
            lines.insert(1, "import matplotlib.ticker as mticker")
        for opaque in subplot["opaque_nodes"]:
            if opaque["source"]:
                lines.extend(opaque["source"].splitlines())
        lines.append("fig.show()")
        return "\n".join(lines)

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        normalized = cls.validate_state(state)
        parameters = ", ".join(cls.tracked_names(normalized))
        body_lines = _macro_ready_lines(
            cls.state_to_python(normalized, context=context).splitlines()
        )
        body = "\n".join(f"    {line}" for line in body_lines)
        return (
            "@hyde.figure\n"
            f"def {macro_name}({parameters}):\n"
            f"{body}\n"
        )


def figure_ir_default_state():
    return FigureIRCodec.default_state()


def figure_ir_from_live_state(state):
    normalized = FigureCodec.validate_state(state)
    title = normalized["settings"]["title"]
    subplot = {
        "id": "subplot0",
        "subplot_code": normalized["settings"]["subplot_code"],
        "title": None,
        "xlabel": None,
        "ylabel": None,
        "x_limits": None,
        "y_limits": None,
        "legend": len(normalized["items"]) > 1,
        "traces": [],
        "opaque_nodes": [],
    }
    for index, y_name in enumerate(normalized["items"]):
        subplot["traces"].append(
            {
                "id": f"trace{index}",
                "kind": "line",
                "x_source": (
                    None
                    if not normalized["settings"]["x_name"]
                    else {"kind": "name", "value": normalized["settings"]["x_name"]}
                ),
                "y_source": {"kind": "name", "value": y_name},
                "kwargs": {"label": y_name},
            }
        )
    ir = FigureIRCodec.default_state()
    ir["settings"]["title"] = title
    ir["settings"]["figsize"] = normalized["settings"]["figsize"]
    ir["layout"]["subplots"] = [subplot]
    return FigureIRCodec.validate_state(ir)


def figure_ir_apply_title(figure_ir, title):
    normalized = FigureIRCodec.normalize_state(figure_ir)
    normalized["settings"]["title"] = None if title in (None, "") else str(title)
    return FigureIRCodec.validate_state(normalized)


def figure_ir_append_trace(figure_ir, trace):
    normalized = FigureIRCodec.normalize_state(figure_ir)
    if not normalized["layout"]["subplots"]:
        normalized["layout"]["subplots"].append(FigureIRCodec._normalize_subplot({}, 0))
    subplot = normalized["layout"]["subplots"][0]
    trace_index = len(subplot["traces"])
    subplot["traces"].append(FigureIRCodec._normalize_trace(trace, trace_index))
    subplot["legend"] = len(subplot["traces"]) > 1
    return FigureIRCodec.validate_state(normalized)


def _figure_patch_subplot(state, subplot_id):
    normalized = FigureIRCodec.validate_state(state)
    return FigureIRCodec._resolve_subplot(normalized, subplot_id)


def _figure_patch_reset_color(target, default_expr):
    return repr(target) if target is not None else default_expr


def _figure_patch_label_lines(axis_name, source_axis_state, target_axis_state):
    setter = "xlabel" if axis_name == "x" else "ylabel"
    axis_obj = f"ax.{axis_name}axis"
    source_label = source_axis_state["label"]
    target_label = target_axis_state["label"]
    lines = []
    if source_label["side"] != target_label["side"]:
        lines.append(f"{axis_obj}.set_label_position({target_label['side']!r})")
    if source_label["text"] != target_label["text"]:
        lines.append(f"ax.set_{setter}({target_label['text']!r})")
    if source_label["visible"] != target_label["visible"]:
        lines.append(f"{axis_obj}.label.set_visible({target_label['visible']!r})")
    if source_label["color"] != target_label["color"]:
        color_value = _figure_patch_reset_color(
            target_label["color"],
            "rcParams['axes.labelcolor']",
        )
        lines.append(
            f"{axis_obj}.label.set_color({color_value})"
        )
    if source_label["rotation"] != target_label["rotation"]:
        lines.append(
            f"{axis_obj}.label.set_rotation({(target_label['rotation'] or 0.0)!r})"
        )
    if source_label["line_spacing"] != target_label["line_spacing"]:
        lines.append(
            f"{axis_obj}.label.set_linespacing({target_label['line_spacing']!r})"
        )
    if (
        source_label["position_mode"] != target_label["position_mode"]
        or source_label["position"] != target_label["position"]
    ):
        coord_name = f"_hyde_{axis_name}_label_coords"
        lines.append(f"{coord_name} = {axis_obj}.label.get_position()")
        if target_label["position_mode"] == "manual" and target_label["position"] is not None:
            if axis_name == "x":
                lines.append(
                    f"{axis_obj}.set_label_coords({target_label['position']!r}, {coord_name}[1])"
                )
            else:
                lines.append(
                    f"{axis_obj}.set_label_coords({coord_name}[0], {target_label['position']!r})"
                )
        elif axis_name == "x":
            lines.append(f"{axis_obj}.set_label_coords(0.5, {coord_name}[1])")
        else:
            lines.append(f"{axis_obj}.set_label_coords({coord_name}[0], 0.5)")
    if source_label["offset"] != target_label["offset"]:
        lines.append(f"{axis_obj}.labelpad = {target_label['offset']!r}")
    return lines


def _figure_patch_range_lines(axis_name, source_axis_state, target_axis_state):
    source_range = source_axis_state["range"]
    target_range = target_axis_state["range"]
    if source_range == target_range:
        return []
    lower_name, upper_name = (
        ("left", "right") if axis_name == "x" else ("bottom", "top")
    )
    setter = f"ax.set_{axis_name}lim"
    limit_mode = target_range["limit_mode"]
    limits = target_range["limits"]
    lines = []
    if (
        limits is not None
        and limit_mode["min"] == "manual"
        and limit_mode["max"] == "manual"
    ):
        lines.append(f"{setter}({limits[0]!r}, {limits[1]!r})")
    else:
        lines.append(f"ax.autoscale(enable=True, axis={axis_name!r})")
        kwargs = []
        if limits is not None and limit_mode["min"] == "manual":
            kwargs.append(f"{lower_name}={limits[0]!r}")
        if limits is not None and limit_mode["max"] == "manual":
            kwargs.append(f"{upper_name}={limits[1]!r}")
        if kwargs:
            lines.append(f"{setter}({', '.join(kwargs)})")
    if source_range["reverse"] != target_range["reverse"]:
        lines.append(
            f"ax.{axis_name}axis.set_inverted({target_range['reverse']!r})"
        )
    return lines


def _figure_patch_tick_params_lines(axis_name, source_subplot, target_subplot):
    primary_side = _PRIMARY_SIDE[axis_name]
    mirror_side = _MIRROR_SIDE[axis_name]
    source_axis_state = source_subplot["axes"][axis_name]
    target_axis_state = target_subplot["axes"][axis_name]
    source_primary = source_subplot["axis_sides"][primary_side]
    target_primary = target_subplot["axis_sides"][primary_side]
    source_mirror = source_subplot["axis_sides"][mirror_side]
    target_mirror = target_subplot["axis_sides"][mirror_side]
    if (
        source_primary["ticks_visible"] == target_primary["ticks_visible"]
        and source_primary["tick_labels_visible"] == target_primary["tick_labels_visible"]
        and source_mirror["ticks_visible"] == target_mirror["ticks_visible"]
        and source_mirror["tick_labels_visible"] == target_mirror["tick_labels_visible"]
        and source_axis_state["ticks"]["direction"] == target_axis_state["ticks"]["direction"]
    ):
        return []
    return [
        "ax.tick_params("
        f"axis={axis_name!r}, "
        "which='both', "
        f"{primary_side}={target_primary['ticks_visible']!r}, "
        f"label{primary_side}={target_primary['tick_labels_visible']!r}, "
        f"{mirror_side}={target_mirror['ticks_visible']!r}, "
        f"label{mirror_side}={target_mirror['tick_labels_visible']!r}, "
        f"direction={{'inside': 'in', 'outside': 'out', 'both': 'inout'}}[{target_axis_state['ticks']['direction']!r}]"
        ")"
    ]


def _figure_patch_spine_lines(axis_name, source_subplot, target_subplot):
    lines = []
    for side in (_PRIMARY_SIDE[axis_name], _MIRROR_SIDE[axis_name]):
        source_side = source_subplot["axis_sides"][side]
        target_side = target_subplot["axis_sides"][side]
        if source_side["spine_visible"] != target_side["spine_visible"]:
            lines.append(f"ax.spines[{side!r}].set_visible({target_side['spine_visible']!r})")
        if source_side["spine_color"] != target_side["spine_color"]:
            color_value = _figure_patch_reset_color(
                target_side["spine_color"],
                "rcParams['axes.edgecolor']",
            )
            lines.append(
                f"ax.spines[{side!r}].set_color({color_value})"
            )
        if source_side["spine_width"] != target_side["spine_width"]:
            width = (
                "rcParams['axes.linewidth']"
                if target_side["spine_width"] is None
                else repr(target_side["spine_width"])
            )
            lines.append(f"ax.spines[{side!r}].set_linewidth({width})")
        if source_side["offset"] != target_side["offset"]:
            lines.append(
                f"ax.spines[{side!r}].set_position(('outward', {float(target_side['offset'] or 0.0)!r}))"
            )
    return lines


def _figure_patch_tick_locator_lines(axis_name, source_axis_state, target_axis_state):
    if (
        source_axis_state["ticks"] == target_axis_state["ticks"]
        and source_axis_state["scale_mode"] == target_axis_state["scale_mode"]
    ):
        return []
    axis_obj = f"ax.{axis_name}axis"
    major = target_axis_state["ticks"]["major"]
    lines = []
    if major["positions"] is not None:
        lines.append(f"{axis_obj}.set_major_locator(mticker.FixedLocator({major['positions']!r}))")
        if major["labels"] is not None:
            lines.append(f"{axis_obj}.set_major_formatter(mticker.FixedFormatter({major['labels']!r}))")
        else:
            lines.append(f"{axis_obj}.set_major_formatter(mticker.ScalarFormatter())")
    elif major["mode"] == "manual" and major["step"] is not None:
        lines.append(f"{axis_obj}.set_major_locator(mticker.MultipleLocator({major['step']!r}))")
        lines.append(f"{axis_obj}.set_major_formatter(mticker.ScalarFormatter())")
    elif major["count"] is not None:
        lines.append(f"{axis_obj}.set_major_locator(mticker.MaxNLocator(nbins={major['count']!r}))")
        lines.append(f"{axis_obj}.set_major_formatter(mticker.ScalarFormatter())")
    else:
        lines.append(f"{axis_obj}.set_major_locator(mticker.AutoLocator())")
        lines.append(f"{axis_obj}.set_major_formatter(mticker.ScalarFormatter())")
    if target_axis_state["ticks"]["minor"]["visible"]:
        if target_axis_state["scale_mode"] in {"log", "log2"}:
            base = 2 if target_axis_state["scale_mode"] == "log2" else 10
            lines.append(f"{axis_obj}.set_minor_locator(mticker.LogLocator(base={base!r}, subs='auto'))")
        else:
            lines.append(f"{axis_obj}.set_minor_locator(mticker.AutoMinorLocator())")
    else:
        lines.append(f"{axis_obj}.set_minor_locator(mticker.NullLocator())")
    return lines


def _figure_patch_tick_label_style_lines(axis_name, source_subplot, target_subplot):
    axis_obj = f"ax.{axis_name}axis"
    default_color_expr = f"rcParams['{axis_name}tick.color']"
    lines = []
    for side, label_attr in ((_PRIMARY_SIDE[axis_name], "label1"), (_MIRROR_SIDE[axis_name], "label2")):
        source_side = source_subplot["axis_sides"][side]
        target_side = target_subplot["axis_sides"][side]
        color_changed = source_side["tick_label_color"] != target_side["tick_label_color"]
        rotation_changed = source_side["tick_label_rotation"] != target_side["tick_label_rotation"]
        if not color_changed and not rotation_changed:
            continue
        lines.append(f"for _hyde_tick in {axis_obj}.get_major_ticks() + {axis_obj}.get_minor_ticks():")
        if color_changed:
            color_value = _figure_patch_reset_color(target_side["tick_label_color"], default_color_expr)
            lines.append(f"    _hyde_tick.{label_attr}.set_color({color_value})")
        if rotation_changed:
            lines.append(f"    _hyde_tick.{label_attr}.set_rotation({target_side['tick_label_rotation']!r})")
    return lines


def _figure_patch_grid_lines(axis_name, source_axis_state, target_axis_state):
    source_grid = source_axis_state["grid"]
    target_grid = target_axis_state["grid"]
    if source_grid == target_grid:
        return []
    if not target_grid["visible"]:
        return [f"ax.grid(False, axis={axis_name!r}, which='both')"]
    arguments = [
        "True",
        f"axis={axis_name!r}",
        f"which={target_grid['which']!r}",
        f"linestyle={target_grid['linestyle']!r}",
    ]
    if target_grid["linewidth"] is not None:
        arguments.append(f"linewidth={target_grid['linewidth']!r}")
    if target_grid["color"] is not None:
        arguments.append(f"color={target_grid['color']!r}")
    return [f"ax.grid({', '.join(arguments)})"]


def _figure_patch_zero_line_lines(axis_name, source_axis_state, target_axis_state):
    source_zero = source_axis_state["zero_line"]
    target_zero = target_axis_state["zero_line"]
    if source_zero == target_zero:
        return []
    role = f"{axis_name}_zero_line"
    call = "axvline" if axis_name == "x" else "axhline"
    lines = [
        "for _hyde_line in list(ax.lines):",
        f"    if getattr(_hyde_line, '_hyde_semantic_role', None) == {role!r}:",
        "        _hyde_line.remove()",
    ]
    if target_zero["visible"]:
        arguments = ["0", f"linestyle={target_zero['linestyle']!r}"]
        if target_zero["linewidth"] is not None:
            arguments.append(f"linewidth={target_zero['linewidth']!r}")
        if target_zero["color"] is not None:
            arguments.append(f"color={target_zero['color']!r}")
        lines.append(f"ax.{call}({', '.join(arguments)})")
    return lines


def _figure_patch_trace_lines(source_trace, target_trace, *, trace_index):
    if not _patch_can_dispatch_trace_style_edit(source_trace, target_trace):
        return []
    source_kwargs = dict(source_trace.get("kwargs", {}) or {})
    target_kwargs = dict(target_trace.get("kwargs", {}) or {})
    changed_keys = [
        key
        for key in TRACE_STYLE_ACTION_KEYS
        if source_kwargs.get(key) != target_kwargs.get(key)
    ]
    if not changed_keys:
        return []
    lines = [f"line = ax.lines[{int(trace_index)}]"]
    setter_lines = {
        "visible": lambda value: f"line.set_visible({bool(value)!r})",
        "alpha": lambda value: f"line.set_alpha({value!r})",
        "color": lambda value: f"line.set_color({value!r})",
        "drawstyle": lambda value: f"line.set_drawstyle({value!r})",
        "marker": lambda value: f"line.set_marker({_patch_empty_choice(value)!r})",
        "markersize": lambda value: f"line.set_markersize({value!r})",
        "markerfacecolor": lambda value: f"line.set_markerfacecolor({value!r})",
        "markeredgecolor": lambda value: f"line.set_markeredgecolor({value!r})",
        "markeredgewidth": lambda value: f"line.set_markeredgewidth({value!r})",
        "linestyle": lambda value: f"line.set_linestyle({_patch_empty_choice(value)!r})",
        "linewidth": lambda value: f"line.set_linewidth({value!r})",
        "label": lambda value: f"line.set_label({value!r})",
    }
    for key in changed_keys:
        lines.append(setter_lines[key](target_kwargs.get(key)))
    return lines


def _figure_patch_remove_trace_lines(trace_id):
    return [
        (
            "_hyde_line = next(("
            "candidate for candidate in ax.lines "
            f"if getattr(candidate, '_hyde_trace_id', None) == {str(trace_id)!r}"
            "), None)"
        ),
        "if _hyde_line is not None:",
        "    _hyde_line.remove()",
    ]


def _figure_patch_remove_trace_helper_source(
    source_state,
    target_state,
    *,
    figure_name,
    refresh_trace_ids=(),
):
    if refresh_trace_ids:
        return ""
    source = FigureIRCodec.validate_state(source_state)
    target = FigureIRCodec.validate_state(target_state)
    source_subplots = list(source.get("layout", {}).get("subplots", ()) or ())
    target_subplots = list(target.get("layout", {}).get("subplots", ()) or ())
    if len(source_subplots) != 1 or len(target_subplots) != 1:
        return ""
    source_subplot = source_subplots[0]
    target_subplot = target_subplots[0]

    source_without_traces = dict(source_subplot)
    source_without_traces["traces"] = ()
    target_without_traces = dict(target_subplot)
    target_without_traces["traces"] = ()
    if source_without_traces != target_without_traces:
        return ""

    target_traces = {
        str(trace["id"]): trace for trace in target_subplot.get("traces", ())
    }
    removed_trace_ids = []
    for source_trace in source_subplot.get("traces", ()):
        trace_id = str(source_trace["id"])
        target_trace = target_traces.pop(trace_id, None)
        if target_trace is None:
            removed_trace_ids.append(trace_id)
            continue
        if source_trace != target_trace:
            return ""
    if target_traces or not removed_trace_ids:
        return ""

    joined_ids = ", ".join(repr(trace_id) for trace_id in removed_trace_ids)
    return "\n".join(
        figure_command_prelude_lines(figure_name)
        + [f"hyde.remove_traces(fig, {joined_ids})"]
    )


def _figure_patch_add_trace_lines(trace):
    arguments = []
    x_source = _operand_to_python(trace["x_source"])
    y_source = _operand_to_python(trace["y_source"])
    if x_source:
        arguments.append(x_source)
    arguments.append(y_source)
    kwargs = ", ".join(
        f"{name}={value!r}"
        for name, value in dict(trace.get("kwargs", {}) or {}).items()
        if value is not None
    )
    if kwargs:
        arguments.append(kwargs)
    return [
        f"_hyde_line = ax.plot({', '.join(arguments)})[0]",
        f"_hyde_line._hyde_trace_id = {str(trace['id'])!r}",
    ]


def figure_patch_source(
    source_state,
    target_state,
    *,
    figure_name,
    refresh_trace_ids=(),
    refresh_legend=True,
):
    source = FigureIRCodec.validate_state(source_state)
    target = FigureIRCodec.validate_state(target_state)
    helper_source = _figure_patch_remove_trace_helper_source(
        source,
        target,
        figure_name=figure_name,
        refresh_trace_ids=refresh_trace_ids,
    )
    if helper_source:
        return helper_source
    source_subplot = _figure_patch_subplot(source, None)
    target_subplot = _figure_patch_subplot(target, None)
    lines = []
    needs_ticker = False
    refresh_trace_ids = {str(trace_id) for trace_id in tuple(refresh_trace_ids or ())}

    changed_margins = [
        side
        for side in ("left", "bottom", "right", "top")
        if source_subplot["margins"].get(side) != target_subplot["margins"].get(side)
    ]
    if changed_margins:
        kwargs = [
            f"{side}={target_subplot['margins'].get(side)!r}"
            for side in changed_margins
        ]
        lines.append(f"fig.subplots_adjust({', '.join(kwargs)})")

    source_draw_on_top = any(
        side_state["draw_on_top"] for side_state in source_subplot["axis_sides"].values()
    )
    target_draw_on_top = any(
        side_state["draw_on_top"] for side_state in target_subplot["axis_sides"].values()
    )
    if source_draw_on_top != target_draw_on_top:
        lines.append(f"ax.set_axisbelow({(not target_draw_on_top)!r})")

    for axis_name in ("x", "y"):
        source_axis_state = source_subplot["axes"][axis_name]
        target_axis_state = target_subplot["axes"][axis_name]
        if source_axis_state["scale_mode"] != target_axis_state["scale_mode"]:
            if target_axis_state["scale_mode"] == "linear":
                lines.append(f"ax.set_{axis_name}scale('linear')")
            elif target_axis_state["scale_mode"] == "log":
                lines.append(f"ax.set_{axis_name}scale('log')")
            else:
                lines.append(f"ax.set_{axis_name}scale('log', base=2)")
        lines.extend(_figure_patch_label_lines(axis_name, source_axis_state, target_axis_state))
        lines.extend(_figure_patch_range_lines(axis_name, source_axis_state, target_axis_state))
        tick_param_lines = _figure_patch_tick_params_lines(axis_name, source_subplot, target_subplot)
        lines.extend(tick_param_lines)
        lines.extend(_figure_patch_spine_lines(axis_name, source_subplot, target_subplot))
        locator_lines = _figure_patch_tick_locator_lines(axis_name, source_axis_state, target_axis_state)
        if locator_lines:
            needs_ticker = True
            lines.extend(locator_lines)
        lines.extend(_figure_patch_tick_label_style_lines(axis_name, source_subplot, target_subplot))
        lines.extend(_figure_patch_grid_lines(axis_name, source_axis_state, target_axis_state))
        lines.extend(_figure_patch_zero_line_lines(axis_name, source_axis_state, target_axis_state))

    trace_lines = []
    legend_changed = source_subplot["legend"] != target_subplot["legend"]
    source_traces = {trace["id"]: trace for trace in source_subplot.get("traces", [])}
    target_traces = {trace["id"]: trace for trace in target_subplot.get("traces", [])}
    for source_trace in source_subplot.get("traces", []):
        if source_trace["id"] in target_traces:
            continue
        legend_changed = True
        trace_lines.extend(_figure_patch_remove_trace_lines(source_trace["id"]))
    for index, target_trace in enumerate(target_subplot.get("traces", [])):
        source_trace = source_traces.get(target_trace["id"])
        if source_trace is None:
            legend_changed = True
            trace_lines.extend(_figure_patch_add_trace_lines(target_trace))
            continue
        lowered = _figure_patch_trace_lines(source_trace, target_trace, trace_index=index)
        if lowered:
            legend_changed = True
            trace_lines.extend(lowered)
            continue
        if source_trace != target_trace:
            legend_changed = True
            trace_lines.extend(_figure_patch_remove_trace_lines(target_trace["id"]))
            trace_lines.extend(_figure_patch_add_trace_lines(target_trace))
            continue
        if target_trace["id"] in refresh_trace_ids:
            trace_lines.extend(_figure_patch_remove_trace_lines(target_trace["id"]))
            trace_lines.extend(_figure_patch_add_trace_lines(target_trace))
    lines.extend(trace_lines)
    legend_visibility_changed = source_subplot["legend"] != target_subplot["legend"]
    if refresh_legend and legend_changed:
        if target_subplot["legend"]:
            lines.append("ax.legend()")
        elif legend_visibility_changed:
            lines.append("if ax.get_legend() is not None:")
            lines.append("    ax.get_legend().remove()")
    if not lines:
        return ""

    prelude = []
    if needs_ticker:
        prelude.append("import matplotlib.ticker as mticker")
    if any("rcParams[" in line for line in lines):
        prelude.append("from matplotlib import rcParams")
    prelude.extend(
        figure_command_prelude_lines(
            figure_name,
            include_axes=True,
        )
    )
    return "\n".join(prelude + lines + ["fig.canvas.draw_idle()"])


def operand_from_runtime_value(value, named_values=None):
    named_values = dict(named_values or {})
    value_id = id(value)
    if value_id in named_values:
        return {"kind": "name", "value": named_values[value_id]}
    if isinstance(value, (str, bytes)) or value is None or isinstance(value, numbers.Real):
        return {"kind": "literal", "value": value}
    try:
        array = np.asarray(value)
    except Exception:
        return {"kind": "literal", "value": repr(value)}
    if array.ndim == 0:
        return {"kind": "literal", "value": array.item()}
    if array.ndim == 1:
        return {"kind": "array_literal", "value": array.tolist()}
    raise ValueError("Hyde figure IR currently supports only 1D runtime operands.")
