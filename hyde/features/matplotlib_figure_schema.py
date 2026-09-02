"""Figure IR state schema.

The shape of a figure IR state dictionary, and the normalizers that put an
incoming state into that shape. Kept apart from the authority that lowers such
a state to Python, so the schema can be read without the lowering beside it.
"""

import copy
import numbers

import numpy as np
from matplotlib import rcParams

from hyde.features.matplotlib_color import normalize_matplotlib_color_text


def operand_to_python(operand):
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
        expression = operand_to_python(operand["root"])
        for attribute in operand["path"]:
            expression = f"getattr({expression}, {attribute!r})"
        return expression
    raise ValueError(f"Unsupported figure operand kind: {kind!r}.")


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


def normalize_empty_choice(value):
    if value in (None, "", "none", "None", " "):
        return "None"
    return str(value)


SUPPORTED_TRACE_STYLE_DEFAULTS = {
    "visible": True,
    "linestyle": "-",
    "linewidth": 1.5,
    "alpha": 1.0,
    "drawstyle": "default",
    "marker": "None",
    "markersize": 6.0,
    "markerfacecolor": "auto",
    "markeredgecolor": "auto",
    "markeredgewidth": 1.0,
}

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


def default_trace_color(index):
    colors = rcParams["axes.prop_cycle"].by_key().get("color", ["#1f77b4"])
    return normalize_trace_style_color(colors[index % len(colors)], "#1f77b4")


def normalize_trace_style_color(value, fallback):
    if value in (None, ""):
        return fallback

    normalized = normalize_matplotlib_color_text(value, allow_auto=True)
    return fallback if normalized in (None, "") else normalized


def apply_trace_style_values(style, values):
    if not isinstance(values, dict):
        return style
    for key in ("color",) + TRACE_STYLE_ACTION_KEYS:
        if key not in values:
            continue
        value = values[key]
        if key == "color":
            style[key] = normalize_trace_style_color(value, style[key])
        elif key in {"markerfacecolor", "markeredgecolor"}:
            style[key] = normalize_trace_style_color(value, style[key])
        elif key in {"linestyle", "marker"}:
            style[key] = normalize_empty_choice(value)
        elif key == "visible":
            style[key] = bool(value)
        elif key in {"linewidth", "alpha", "markersize", "markeredgewidth"}:
            style[key] = float(value)
        else:
            style[key] = value
    return style


def trace_style_defaults_by_subplot(figure_defaults):
    defaults = dict(figure_defaults or {})
    default_ir = defaults.get("figure_ir")
    if default_ir is None and ("layout" in defaults or "settings" in defaults):
        default_ir = defaults
    trace_defaults_by_subplot = {}
    if isinstance(default_ir, dict):
        for subplot in default_ir.get("layout", {}).get("subplots", []):
            subplot_id = str(subplot.get("id"))
            trace_defaults_by_subplot[subplot_id] = {
                str(trace.get("id")): dict(trace or {})
                for trace in subplot.get("traces", [])
            }
    for subplot_id, trace_defaults in dict(defaults.get("trace_styles", {}) or {}).items():
        subplot_defaults = trace_defaults_by_subplot.setdefault(str(subplot_id), {})
        for trace_id, style in dict(trace_defaults or {}).items():
            subplot_defaults.setdefault(
                str(trace_id),
                {"kwargs": dict(style or {})},
            )
    return trace_defaults_by_subplot


def supported_trace_style_state(
    trace,
    *,
    index,
    default_trace=None,
    live_style=None,
):
    style = dict(SUPPORTED_TRACE_STYLE_DEFAULTS)
    style["color"] = default_trace_color(index)
    if isinstance(default_trace, dict):
        apply_trace_style_values(style, default_trace.get("kwargs", {}))
    apply_trace_style_values(style, dict(trace.get("kwargs", {}) or {}))
    apply_trace_style_values(style, live_style)
    return style


_AXIS_SIDE_TO_AXIS = {
    "bottom": "x",
    "top": "x",
    "left": "y",
    "right": "y",
}
_PRIMARY_SIDE = {"x": "bottom", "y": "left"}
_MIRROR_SIDE = {"x": "top", "y": "right"}


def deep_merge_dict(target, updates):
    for key, value in dict(updates or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge_dict(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def normalize_optional_float(value):
    if value in (None, ""):
        return None
    return float(value)


def normalize_float_pair(value, field_name, default=None):
    if value in (None, ""):
        return copy.deepcopy(default)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field_name} must be a length-2 sequence.")
    return (float(value[0]), float(value[1]))


def default_axis_state(axis_name):
    return {
        "id": axis_name,
        "scale_mode": "linear",
        "log_tick_mode": "plain",
        "range": {
            "limits": None,
            "limit_mode": {"min": "auto", "max": "auto"},
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
            "minor": {"visible": False},
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


def normalize_axis_label(axis_name, label, legacy_text=None):
    normalized = default_axis_state(axis_name)["label"]
    explicit_visible = isinstance(label, dict) and "visible" in label
    if isinstance(label, dict):
        deep_merge_dict(normalized, label)
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
    if normalized["side"] not in {_PRIMARY_SIDE[axis_name], _MIRROR_SIDE[axis_name]}:
        raise ValueError(f"Axis {axis_name!r} label side is invalid.")
    normalized["position_mode"] = str(normalized.get("position_mode", "auto"))
    normalized["position"] = normalize_optional_float(normalized.get("position"))
    normalized["offset"] = float(normalized.get("offset", 0.0) or 0.0)
    normalized["rotation"] = normalize_optional_float(normalized.get("rotation"))
    normalized["line_spacing"] = float(normalized.get("line_spacing", 1.2) or 1.2)
    color = normalized.get("color")
    normalized["color"] = None if color in (None, "") else str(color)
    return normalized


def normalize_axis_range(axis_name, range_state, legacy_limits=None):
    normalized = default_axis_state(axis_name)["range"]
    if isinstance(range_state, dict):
        deep_merge_dict(normalized, range_state)
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
            else normalize_float_pair(legacy_limits, "axis limits")
        )
    else:
        if not isinstance(limits, (list, tuple)) or len(limits) != 2:
            raise ValueError("axis limits must be a length-2 sequence.")
        minimum = None if limits[0] in (None, "") else float(limits[0])
        maximum = None if limits[1] in (None, "") else float(limits[1])
        normalized["limits"] = (minimum, maximum)
    normalized["autoscale"] = str(normalized.get("autoscale", "data"))
    normalized["reverse"] = bool(normalized.get("reverse"))
    return normalized


def normalize_axis_ticks(axis_name, ticks):
    normalized = default_axis_state(axis_name)["ticks"]
    if isinstance(ticks, dict):
        deep_merge_dict(normalized, ticks)
    major = dict(normalized.get("major", {}) or {})
    positions = major.get("positions")
    major["positions"] = None if positions in (None, []) else [float(value) for value in positions]
    labels = major.get("labels")
    major["labels"] = None if labels in (None, []) else [str(value) for value in labels]
    major["mode"] = str(major.get("mode", "auto"))
    major["count"] = None if major.get("count") in (None, "") else int(major.get("count"))
    major["step"] = normalize_optional_float(major.get("step"))
    normalized["major"] = major
    normalized["minor"] = {"visible": bool(dict(normalized.get("minor", {}) or {}).get("visible"))}
    normalized["direction"] = str(normalized.get("direction", "outside"))
    formatter = dict(normalized.get("formatter", {}) or {})
    normalized["formatter"] = {
        "style": str(formatter.get("style", "plain")),
        "low_trip": normalize_optional_float(formatter.get("low_trip")),
        "high_trip": normalize_optional_float(formatter.get("high_trip")),
        "exponent_prescale": normalize_optional_float(formatter.get("exponent_prescale")),
        "use_thousands_separator": bool(formatter.get("use_thousands_separator", False)),
        "zero_as_zero": bool(formatter.get("zero_as_zero", True)),
        "trim_trailing_zeros": bool(formatter.get("trim_trailing_zeros", False)),
        "trim_leading_zero": bool(formatter.get("trim_leading_zero", False)),
        "prefer_exponent": bool(formatter.get("prefer_exponent", False)),
    }
    normalized["suppressed_values"] = [float(value) for value in normalized.get("suppressed_values", [])]
    normalized["display_range"] = normalize_float_pair(
        normalized.get("display_range"),
        "tick display range",
        default=None,
    )
    normalized["max_log_cycles_minor"] = normalize_optional_float(normalized.get("max_log_cycles_minor"))
    normalized["max_log_cycles_minor_labels"] = normalize_optional_float(
        normalized.get("max_log_cycles_minor_labels")
    )
    return normalized


def normalize_axis_grid(axis_name, grid):
    normalized = default_axis_state(axis_name)["grid"]
    if isinstance(grid, dict):
        deep_merge_dict(normalized, grid)
    normalized["visible"] = bool(normalized.get("visible"))
    normalized["which"] = str(normalized.get("which", "major"))
    normalized["linestyle"] = str(normalized.get("linestyle", "-"))
    normalized["linewidth"] = normalize_optional_float(normalized.get("linewidth"))
    color = normalized.get("color")
    normalized["color"] = None if color in (None, "") else str(color)
    return normalized


def normalize_axis_zero_line(axis_name, zero_line):
    normalized = default_axis_state(axis_name)["zero_line"]
    if isinstance(zero_line, dict):
        deep_merge_dict(normalized, zero_line)
    normalized["visible"] = bool(normalized.get("visible"))
    normalized["linestyle"] = str(normalized.get("linestyle", "-"))
    normalized["linewidth"] = normalize_optional_float(normalized.get("linewidth"))
    color = normalized.get("color")
    normalized["color"] = None if color in (None, "") else str(color)
    return normalized


def normalize_axis_state(axis_name, axis_state, legacy_label=None, legacy_limits=None):
    normalized = default_axis_state(axis_name)
    if isinstance(axis_state, dict):
        deep_merge_dict(normalized, axis_state)
    normalized["id"] = axis_name
    normalized["scale_mode"] = str(normalized.get("scale_mode", "linear"))
    normalized["log_tick_mode"] = str(normalized.get("log_tick_mode", "plain"))
    normalized["range"] = normalize_axis_range(axis_name, normalized.get("range"), legacy_limits=legacy_limits)
    normalized["label"] = normalize_axis_label(axis_name, normalized.get("label"), legacy_text=legacy_label)
    normalized["ticks"] = normalize_axis_ticks(axis_name, normalized.get("ticks"))
    normalized["grid"] = normalize_axis_grid(axis_name, normalized.get("grid"))
    normalized["zero_line"] = normalize_axis_zero_line(axis_name, normalized.get("zero_line"))
    return normalized


def default_axis_side_state(side):
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


def default_subplot_margins():
    return {"left": None, "bottom": None, "right": None, "top": None}


def normalize_subplot_margins(margins):
    normalized = default_subplot_margins()
    if isinstance(margins, dict):
        deep_merge_dict(normalized, margins)
    for side in ("left", "bottom", "right", "top"):
        normalized[side] = normalize_optional_float(normalized.get(side))
    return normalized


def normalize_axis_side_state(side, side_state):
    normalized = default_axis_side_state(side)
    if isinstance(side_state, dict):
        deep_merge_dict(normalized, side_state)
    normalized.pop("draw_between", None)
    normalized["side"] = side
    normalized["axis"] = _AXIS_SIDE_TO_AXIS[side]
    normalized["spine_visible"] = bool(normalized.get("spine_visible"))
    normalized["ticks_visible"] = bool(normalized.get("ticks_visible"))
    normalized["tick_labels_visible"] = bool(normalized.get("tick_labels_visible"))
    spine_color = normalized.get("spine_color")
    normalized["spine_color"] = None if spine_color in (None, "") else str(spine_color)
    tick_label_color = normalized.get("tick_label_color")
    normalized["tick_label_color"] = None if tick_label_color in (None, "") else str(tick_label_color)
    normalized["spine_width"] = normalize_optional_float(normalized.get("spine_width"))
    normalized["tick_label_rotation"] = float(normalized.get("tick_label_rotation", 0.0) or 0.0)
    normalized["tick_label_offset"] = float(normalized.get("tick_label_offset", 0.0) or 0.0)
    normalized["offset"] = float(normalized.get("offset", 0.0) or 0.0)
    normalized["draw_on_top"] = bool(normalized.get("draw_on_top"))
    return normalized


def sync_legacy_subplot_axis_fields(subplot):
    subplot["xlabel"] = subplot["axes"]["x"]["label"]["text"]
    subplot["ylabel"] = subplot["axes"]["y"]["label"]["text"]
    subplot["x_limits"] = subplot["axes"]["x"]["range"]["limits"]
    subplot["y_limits"] = subplot["axes"]["y"]["range"]["limits"]
    return subplot


def operand_names(operand):
    if not isinstance(operand, dict):
        return ()
    kind = operand.get("kind")
    if kind == "name":
        value = str(operand.get("value") or "").strip()
        return () if not value else (value,)
    if kind == "attribute_path":
        return operand_names(operand.get("root"))
    return ()
