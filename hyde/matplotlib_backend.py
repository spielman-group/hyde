from __future__ import annotations

import ast
import base64
import io
import inspect
import logging
import re
import sys
import textwrap
import threading

import numpy as np
from ipykernel.comm import Comm
from matplotlib import rcParams
from matplotlib import ticker as mticker
from matplotlib.axes import Axes
from matplotlib.backend_bases import FigureManagerBase, _Backend
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.projections import register_projection

from hyde.features.matplotlib_features import (
    FigureCodec,
    FigureIRCodec,
    apply_figure_state,
    figure_ir_append_trace,
    figure_ir_apply_title,
    figure_ir_default_state,
    operand_from_runtime_value,
)
from hyde.user_interface.shared.project import resolve_requested_name
from hyde.user_interface.shared.figure import COMM_TARGET


_BUILD_SESSION_LOCAL = threading.local()
LOGGER = logging.getLogger("hyde")
_DEFAULT_FIGURE_LABEL_RE = re.compile(r"^Figure\s+(\d+)$")


def _canonicalize_default_figure_name(name):
    text = str(name or "")
    match = _DEFAULT_FIGURE_LABEL_RE.fullmatch(text)
    if match is None:
        return text
    return f"Figure{match.group(1)}"


def _default_figure_title(figure, number):
    label = figure.get_label()
    if label:
        return _canonicalize_default_figure_name(label)
    return f"Figure{number}"


def _is_windowed_figure(figure):
    return bool(
        getattr(figure, "_hyde_is_first_class", False)
        or getattr(figure, "_hyde_build_session", None) is not None
    )


def _iter_windowed_figures():
    try:
        from matplotlib._pylab_helpers import Gcf
    except Exception:
        return ()

    figures = []
    for manager in Gcf.get_all_fig_managers():
        figure = getattr(getattr(manager, "canvas", None), "figure", None)
        if figure is None or not _is_windowed_figure(figure):
            continue
        figures.append(figure)
    return tuple(figures)


def _canonical_windowed_figure_name(name):
    return _canonicalize_default_figure_name(str(name or "").strip())


def _windowed_figure_with_name(name, *, exclude=None):
    canonical_name = _canonical_windowed_figure_name(name)
    if not canonical_name:
        return None
    for figure in _iter_windowed_figures():
        if figure is exclude:
            continue
        current_name = _canonical_windowed_figure_name(
            figure.get_label()
            or getattr(figure, "_hyde_ir", {}).get("settings", {}).get("title")
        )
        if current_name == canonical_name:
            return figure
    return None


def get_first_class_figure(name):
    canonical_name = _canonical_windowed_figure_name(name)
    if not canonical_name:
        raise ValueError("First-class figure lookup requires a non-empty name.")
    figure = _windowed_figure_with_name(canonical_name)
    if figure is not None and getattr(figure, "_hyde_is_first_class", False):
        return figure
    raise ValueError(f"Could not resolve first-class figure {name!r}.")


def _display_in_ipython_terminal(figure):
    try:
        from IPython.display import display
    except Exception:
        return
    display(figure)


def _current_build_session():
    return getattr(_BUILD_SESSION_LOCAL, "session", None)


class FigureBuildSession:
    def __init__(self, func, args, kwargs, metadata=None):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.metadata = dict(metadata or {})
        self.previous = None
        self.created_figures = []
        self.named_values = {}
        self.bound_values = {}
        self.source_artifact = None
        self.ast_artifact = None
        self._capture_artifacts()
        self._bind_named_values()

    def _capture_artifacts(self):
        try:
            source = inspect.getsource(self.func)
        except (OSError, TypeError):
            return
        self.source_artifact = textwrap.dedent(source)
        try:
            self.ast_artifact = ast.parse(self.source_artifact)
        except SyntaxError:
            self.ast_artifact = None

    def _bind_named_values(self):
        try:
            signature = inspect.signature(self.func)
            bound = signature.bind_partial(*self.args, **self.kwargs)
        except (TypeError, ValueError):
            return
        for name, value in bound.arguments.items():
            self.named_values[id(value)] = name
            self.bound_values[name] = value

    def register_figure(self, figure):
        if figure not in self.created_figures:
            self.created_figures.append(figure)


def begin_figure_build_session(func, args, kwargs, metadata=None):
    session = FigureBuildSession(func, args, kwargs, metadata=metadata)
    session.previous = _current_build_session()
    _BUILD_SESSION_LOCAL.session = session
    return session


def end_figure_build_session(session):
    current = _current_build_session()
    if current is not session:
        return
    _BUILD_SESSION_LOCAL.session = session.previous


def _resolve_runtime_figure(value):
    if value is None:
        return None
    if hasattr(value, "canvas"):
        return value
    if isinstance(value, (list, tuple, set)):
        candidates = [item for item in value if hasattr(item, "canvas")]
        if len(candidates) == 1:
            return candidates[0]
    return None


def finalize_figure_build_session(session, result):
    created = list(session.created_figures)
    if not created:
        raise ValueError("@hyde.figure functions must create exactly one figure.")
    if len(created) != 1:
        raise ValueError("@hyde.figure functions must create exactly one figure.")

    created_figure = created[0]
    resolved = _resolve_runtime_figure(result)
    if resolved is not None and resolved is not created_figure:
        raise ValueError("@hyde.figure functions must resolve to the one created figure.")

    figure = created_figure if resolved is None else resolved
    requested_name = figure.get_label() or figure._hyde_ir["settings"].get("title")
    existing_names = set()
    try:
        from matplotlib._pylab_helpers import Gcf

        for manager in Gcf.get_all_fig_managers():
            live_figure = getattr(getattr(manager, "canvas", None), "figure", None)
            if live_figure is None or live_figure is figure:
                continue
            if not _is_windowed_figure(live_figure):
                continue
            label = str(live_figure.get_label() or "").strip()
            if label:
                existing_names.add(label)
    except Exception:
        existing_names = set()
    resolved_name = resolve_requested_name(
        "Figure",
        existing_names,
        requested_name=requested_name,
    )
    figure.set_label(resolved_name)
    figure._hyde_ir = figure_ir_apply_title(
        figure._hyde_ir,
        resolved_name,
    )
    figure._hyde_defaults = _figure_defaults_snapshot(figure._hyde_ir)
    figure._hyde_is_first_class = True
    figure._hyde_source_artifact = session.source_artifact
    figure._hyde_ast_artifact = session.ast_artifact
    figure._hyde_bound_values = dict(session.bound_values)
    figure._hyde_metadata = dict(session.metadata)
    return figure


def _line_label(line):
    label = line.get_label()
    if not label or label.startswith("_"):
        return None
    return label


def _array_expression(values):
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError("Only 1D line data can be saved in Hyde figure macros.")
    return f"np.array({array.tolist()!r})"


def _is_default_xdata(x_values):
    try:
        array = np.asarray(x_values)
    except Exception:
        return False
    if array.ndim != 1:
        return False
    expected = np.arange(array.size)
    return np.array_equal(array, expected)


def _line_kwargs(line, default_style=None):
    style = _line_style_snapshot(line)
    default_style = dict(default_style or {})
    kwargs = {}
    if style["color"] is not None and style["color"] != default_style.get("color"):
        kwargs["color"] = style["color"]
    if style["visible"] is False and style["visible"] != default_style.get("visible"):
        kwargs["visible"] = False
    if style["linestyle"] != default_style.get("linestyle") and style["linestyle"] not in (None, "-", "solid"):
        kwargs["linestyle"] = style["linestyle"]
    if style["marker"] != default_style.get("marker") and style["marker"] not in (None, "", "None", "none"):
        kwargs["marker"] = style["marker"]
    if style["linewidth"] != default_style.get("linewidth") and style["linewidth"] is not None:
        kwargs["linewidth"] = style["linewidth"]
    if style["alpha"] != default_style.get("alpha") and style["alpha"] is not None:
        kwargs["alpha"] = style["alpha"]
    if style["drawstyle"] != default_style.get("drawstyle") and style["drawstyle"] not in (None, "default"):
        kwargs["drawstyle"] = style["drawstyle"]
    if style["markersize"] != default_style.get("markersize") and style["markersize"] is not None:
        kwargs["markersize"] = style["markersize"]
    if style["markerfacecolor"] != default_style.get("markerfacecolor") and style["markerfacecolor"] not in (None, "auto", style["color"]):
        kwargs["markerfacecolor"] = style["markerfacecolor"]
    if style["markeredgecolor"] != default_style.get("markeredgecolor") and style["markeredgecolor"] not in (None, "auto", style["color"]):
        kwargs["markeredgecolor"] = style["markeredgecolor"]
    if style["markeredgewidth"] != default_style.get("markeredgewidth") and style["markeredgewidth"] is not None:
        kwargs["markeredgewidth"] = style["markeredgewidth"]
    label = style.get("label")
    if label:
        kwargs["label"] = label
    return kwargs


def _normalize_line_color(value, fallback=None):
    if value in (None, ""):
        return fallback
    if isinstance(value, str) and value.lower() == "auto":
        return "auto"
    try:
        return to_hex(value)
    except Exception:
        return str(value)


def _line_style_snapshot(line):
    color = _normalize_line_color(line.get_color())
    marker = line.get_marker()
    if marker in (None, "", "none"):
        marker = "None"
    linestyle = line.get_linestyle()
    if linestyle in (None, ""):
        linestyle = "None"
    return {
        "visible": bool(line.get_visible()),
        "color": color,
        "linestyle": linestyle,
        "linewidth": float(line.get_linewidth()),
        "label": _line_label(line),
        "alpha": 1.0 if line.get_alpha() is None else float(line.get_alpha()),
        "drawstyle": str(line.get_drawstyle()),
        "marker": str(marker),
        "markersize": float(line.get_markersize()),
        "markerfacecolor": _normalize_line_color(
            line.get_markerfacecolor(),
            fallback=color,
        ),
        "markeredgecolor": _normalize_line_color(
            line.get_markeredgecolor(),
            fallback=color,
        ),
        "markeredgewidth": float(line.get_markeredgewidth()),
    }


def _default_tick_color(axis_name):
    label_color = rcParams.get(f"{axis_name}tick.labelcolor", "inherit")
    if label_color in (None, "inherit"):
        label_color = rcParams.get(
            f"{axis_name}tick.color",
            rcParams.get("axes.edgecolor"),
        )
    return _normalize_line_color(label_color)


def _default_label_color():
    label_color = rcParams.get("axes.labelcolor", rcParams.get("axes.edgecolor"))
    if label_color in (None, "inherit", "auto"):
        label_color = rcParams.get("axes.edgecolor")
    return _normalize_line_color(label_color)


def _default_axis_state(axis_name):
    tick_direction = str(
        rcParams.get(f"{axis_name}tick.direction", "out")
    )
    direction = {
        "in": "inside",
        "out": "outside",
        "inout": "both",
    }.get(tick_direction, "outside")
    grid_visible = bool(rcParams.get("axes.grid", False))
    grid_which = str(rcParams.get("axes.grid.which", "major"))
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
            "side": "bottom" if axis_name == "x" else "left",
            "position_mode": "auto",
            "position": None,
            "offset": float(rcParams.get("axes.labelpad", 4.0)),
            "rotation": 0.0,
            "line_spacing": 1.2,
            "color": _default_label_color(),
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
            "direction": direction,
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
            "visible": grid_visible,
            "which": grid_which,
            "linestyle": str(rcParams.get("grid.linestyle", "-")),
            "linewidth": float(rcParams.get("grid.linewidth", 0.8)),
            "color": _normalize_line_color(rcParams.get("grid.color")),
        },
        "zero_line": {
            "visible": False,
            "linestyle": "-",
            "linewidth": None,
            "color": None,
        },
    }


def _default_axis_side_state(side):
    axis_name = "x" if side in {"bottom", "top"} else "y"
    primary = (axis_name == "x" and side == "bottom") or (
        axis_name == "y" and side == "left"
    )
    return {
        "side": side,
        "axis": axis_name,
        "spine_visible": bool(rcParams.get(f"axes.spines.{side}", primary)),
        "ticks_visible": bool(
            rcParams.get(f"{axis_name}tick.{side}", primary)
        ),
        "tick_labels_visible": bool(
            rcParams.get(f"{axis_name}tick.label{side}", primary)
        ),
        "spine_color": _normalize_line_color(rcParams.get("axes.edgecolor")),
        "spine_width": float(rcParams.get("axes.linewidth", 0.8)),
        "tick_label_color": _default_tick_color(axis_name),
        "tick_label_rotation": 0.0,
        "tick_label_offset": 0.0,
        "offset": 0.0,
        "draw_on_top": False,
    }


def _default_subplot_margins():
    temp_figure = Figure(figsize=tuple(float(value) for value in rcParams["figure.figsize"]))
    temp_figure.add_subplot(111)
    subplotpars = temp_figure.subplotpars
    return {
        "left": float(subplotpars.left),
        "bottom": float(subplotpars.bottom),
        "right": float(subplotpars.right),
        "top": float(subplotpars.top),
    }


def _default_subplot_state(subplot_id="subplot0", subplot_code="111"):
    return {
        "id": str(subplot_id),
        "subplot_code": str(subplot_code),
        "title": None,
        "margins": _default_subplot_margins(),
        "xlabel": None,
        "ylabel": None,
        "x_limits": None,
        "y_limits": None,
        "legend": False,
        "traces": [],
        "axes": {
            "x": _default_axis_state("x"),
            "y": _default_axis_state("y"),
        },
        "axis_sides": {
            side: _default_axis_side_state(side)
            for side in ("bottom", "top", "left", "right")
        },
        "opaque_nodes": [],
    }


def _default_trace_style(index):
    temp_figure = Figure(figsize=tuple(float(value) for value in rcParams["figure.figsize"]))
    temp_axis = temp_figure.add_subplot(111)
    lines = []
    for _ in range(index + 1):
        lines = temp_axis.plot([0.0, 1.0], [0.0, 1.0])
    style = _line_style_snapshot(lines[-1])
    style["label"] = None
    return style


def _figure_defaults_snapshot(figure_ir):
    normalized = FigureIRCodec.validate_state(figure_ir)
    default_ir = FigureIRCodec.default_state()
    default_ir["settings"]["figsize"] = tuple(
        float(value) for value in rcParams["figure.figsize"]
    )
    default_ir["layout"]["subplots"] = []
    trace_style_defaults = {}
    for subplot in normalized["layout"]["subplots"]:
        default_subplot = _default_subplot_state(
            subplot_id=subplot["id"],
            subplot_code=subplot["subplot_code"],
        )
        default_ir["layout"]["subplots"].append(default_subplot)
        subplot_trace_defaults = {}
        for index, trace in enumerate(subplot["traces"]):
            default_style = _default_trace_style(index)
            subplot_trace_defaults[trace["id"]] = default_style
            default_subplot["traces"].append(
                {
                    "id": trace["id"],
                    "kind": trace["kind"],
                    "x_source": trace["x_source"],
                    "y_source": trace["y_source"],
                    "kwargs": dict(default_style),
                }
            )
        trace_style_defaults[subplot["id"]] = subplot_trace_defaults
    default_ir = FigureIRCodec.validate_state(default_ir)
    default_ir["trace_styles"] = trace_style_defaults
    return default_ir


def _format_plot_call(line, default_style=None):
    x_values = line.get_xdata()
    y_values = line.get_ydata()
    kwargs = _line_kwargs(line, default_style=default_style)
    keyword = ", ".join(f"{name}={value!r}" for name, value in kwargs.items())
    if _is_default_xdata(x_values):
        arguments = [_array_expression(y_values)]
    else:
        arguments = [_array_expression(x_values), _array_expression(y_values)]
    if keyword:
        arguments.append(keyword)
    return f"ax.plot({', '.join(arguments)})"


def figure_call_source(figure, number):
    axes = list(figure.axes)
    if len(axes) != 1:
        raise ValueError("Hyde can only save single-subplot figures right now.")

    axes0 = axes[0]
    if axes0.images or axes0.collections:
        raise ValueError("Hyde can only save line-based figures right now.")

    lines = list(axes0.lines)
    if not lines:
        raise ValueError("Hyde can only save figures that contain plotted line data.")

    title = _default_figure_title(figure, number)
    axes_title = axes0.get_title()
    xlabel = axes0.get_xlabel()
    ylabel = axes0.get_ylabel()
    grid_on = any(line.get_visible() for line in axes0.get_xgridlines() + axes0.get_ygridlines())
    legend = axes0.get_legend()

    source_lines = []
    if title:
        source_lines.append(f"fig = plt.figure({title!r})")
    else:
        source_lines.append("fig = plt.figure()")
    source_lines.append("ax = fig.add_subplot(111)")
    if axes_title:
        source_lines.append(f"ax.set_title({axes_title!r})")
    elif title:
        source_lines.append(f"ax.set_title({title!r})")
    if xlabel:
        source_lines.append(f"ax.set_xlabel({xlabel!r})")
    if ylabel:
        source_lines.append(f"ax.set_ylabel({ylabel!r})")
    for index, line in enumerate(lines):
        source_lines.append(_format_plot_call(line, default_style=_default_trace_style(index)))
    if legend is not None:
        source_lines.append("ax.legend()")
    if grid_on:
        source_lines.append("ax.grid(True)")
    source_lines.append("fig.show()")
    source_lines.append("fig.canvas.draw_idle()")
    return "\n".join(source_lines)


def figure_snapshot_payload(figure, number):
    figure_ir = getattr(figure, "_hyde_ir", None)
    live_state = getattr(figure, "_hyde_live_state", None)
    hyde_metadata = dict(getattr(figure, "_hyde_metadata", {}) or {})
    if _is_windowed_figure(figure) and figure_ir is not None:
        normalized_figure_ir = FigureIRCodec.validate_state(figure_ir)
        figure_defaults = getattr(figure, "_hyde_defaults", None)
        if figure_defaults is None:
            figure_defaults = _figure_defaults_snapshot(normalized_figure_ir)
            figure._hyde_defaults = figure_defaults
        call_source = None
        save_error = None
        tracked_names = []
        try:
            call_source = FigureIRCodec.state_to_python(
                normalized_figure_ir,
                context={"figure_defaults": figure_defaults},
            )
            tracked_names = list(FigureIRCodec.tracked_names(normalized_figure_ir))
        except Exception as exc:
            save_error = str(exc)
        payload = {
            "default_macro_name": _default_figure_title(figure, number),
            "call_source": call_source,
            "save_error": save_error,
            "figure_size": tuple(
                int(value * figure.dpi) for value in figure.get_size_inches()
            ),
            "tracked_names": tracked_names,
            "live_state": None,
            "figure_ir": normalized_figure_ir,
            "figure_defaults": figure_defaults,
            "resolved_axis_limits": _resolved_axis_limits_snapshot(
                figure,
                normalized_figure_ir,
            ),
            "trace_styles": _figure_trace_styles(figure, normalized_figure_ir),
            "command_log": list(getattr(figure, "_hyde_command_log", [])),
            "hyde_metadata": hyde_metadata,
            "is_first_class": True,
        }
        return payload
    if live_state is None:
        live_state = _infer_live_state(figure, sys.modules["__main__"].__dict__)
        if live_state is not None:
            figure._hyde_live_state = live_state
    payload = {
        "default_macro_name": _default_figure_title(figure, number),
        "call_source": None,
        "save_error": None,
        "figure_size": tuple(
            int(value * figure.dpi) for value in figure.get_size_inches()
        ),
        "tracked_names": [],
        "live_state": None,
        "hyde_metadata": hyde_metadata,
        "is_first_class": False,
    }
    if live_state is not None:
        payload["call_source"] = FigureCodec.state_to_python(live_state)
        payload["tracked_names"] = list(FigureCodec.tracked_names(live_state))
        payload["live_state"] = live_state
        return payload
    try:
        payload["call_source"] = figure_call_source(figure, number)
    except Exception as exc:
        payload["save_error"] = str(exc)
    return payload


def _main_namespace():
    return sys.modules["__main__"].__dict__


def _resolve_ir_operand_value(operand, namespace, figure=None, use_bound_values=True):
    if operand is None:
        return None
    kind = operand.get("kind")
    if kind == "name":
        operand_name = operand["value"]
        if operand_name in namespace:
            return namespace[operand_name]
        if use_bound_values:
            bound_values = getattr(figure, "_hyde_bound_values", {})
            if operand_name in bound_values:
                return bound_values[operand_name]
        raise KeyError(operand_name)
    if kind == "literal":
        return operand.get("value")
    if kind == "array_literal":
        return np.array(operand.get("value", []))
    if kind == "attribute_path":
        value = _resolve_ir_operand_value(
            operand.get("root"),
            namespace,
            figure=figure,
            use_bound_values=use_bound_values,
        )
        for attribute in operand.get("path", []):
            value = getattr(value, attribute)
        return value
    raise ValueError(f"Unsupported figure IR operand kind: {kind!r}.")


def _resolve_live_axis(figure, subplot_id=None):
    axes = list(figure.axes)
    if not axes:
        raise ValueError("Figure does not contain any axes.")
    if subplot_id in (None, ""):
        return axes[0]
    for axis in axes:
        if getattr(axis, "_hyde_subplot_id", None) == str(subplot_id):
            return axis
    raise ValueError(f"Unknown live subplot id: {subplot_id!r}.")


def _resolve_live_line(axis, trace_id=None):
    lines = list(axis.lines)
    if not lines:
        raise ValueError("Figure axis does not contain any traces.")
    if trace_id in (None, ""):
        return lines[0]
    for line in lines:
        if getattr(line, "_hyde_trace_id", None) == str(trace_id):
            return line
    raise ValueError(f"Unknown live trace id: {trace_id!r}.")


def _figure_trace_styles(figure, figure_ir):
    styles = {}
    normalized = FigureIRCodec.validate_state(figure_ir)
    for subplot in normalized["layout"]["subplots"]:
        axis = _resolve_live_axis(figure, subplot["id"])
        live_lines = {
            getattr(line, "_hyde_trace_id", None): line
            for line in axis.lines
            if getattr(line, "_hyde_trace_id", None) is not None
        }
        subplot_styles = {}
        for trace in subplot["traces"]:
            line = live_lines.get(trace["id"])
            if line is None:
                continue
            subplot_styles[trace["id"]] = _line_style_snapshot(line)
        styles[subplot["id"]] = subplot_styles
    return styles


def _resolved_axis_limits_snapshot(figure, figure_ir):
    limits = {}
    normalized = FigureIRCodec.validate_state(figure_ir)
    for subplot in normalized["layout"]["subplots"]:
        axis = _resolve_live_axis(figure, subplot["id"])
        limits[subplot["id"]] = {
            "x": tuple(float(value) for value in axis.get_xlim()),
            "y": tuple(float(value) for value in axis.get_ylim()),
        }
    return limits


def _apply_line_style(line, kwargs):
    if "visible" in kwargs:
        line.set_visible(bool(kwargs["visible"]))
    if "alpha" in kwargs:
        line.set_alpha(kwargs["alpha"])
    if "color" in kwargs:
        line.set_color(kwargs["color"])
    if "drawstyle" in kwargs:
        line.set_drawstyle(kwargs["drawstyle"])
    if "marker" in kwargs:
        marker = kwargs["marker"]
        line.set_marker("None" if marker in (None, "", "none") else marker)
    if "markersize" in kwargs:
        line.set_markersize(kwargs["markersize"])
    if "markerfacecolor" in kwargs:
        line.set_markerfacecolor(kwargs["markerfacecolor"])
    if "markeredgecolor" in kwargs:
        line.set_markeredgecolor(kwargs["markeredgecolor"])
    if "markeredgewidth" in kwargs:
        line.set_markeredgewidth(kwargs["markeredgewidth"])
    if "linestyle" in kwargs:
        linestyle = kwargs["linestyle"]
        line.set_linestyle("None" if linestyle in (None, "", "none") else linestyle)
    if "linewidth" in kwargs:
        line.set_linewidth(kwargs["linewidth"])
    if "label" in kwargs:
        line.set_label(kwargs["label"])


def _semantic_axis(axis_name):
    return "xaxis" if axis_name == "x" else "yaxis"


def _primary_side(axis_name):
    return "bottom" if axis_name == "x" else "left"


def _mirror_side(axis_name):
    return "top" if axis_name == "x" else "right"


def _tick_direction(direction):
    return {
        "inside": "in",
        "outside": "out",
        "both": "inout",
    }[direction]


def _set_axis_scale(axis, axis_name, axis_state):
    if axis_state["scale_mode"] == "linear":
        getattr(axis, f"set_{axis_name}scale")("linear")
    elif axis_state["scale_mode"] == "log":
        getattr(axis, f"set_{axis_name}scale")("log")
    else:
        getattr(axis, f"set_{axis_name}scale")("log", base=2)


def _set_axis_label(axis, axis_name, axis_state):
    label = axis_state["label"]
    axis_axis = getattr(axis, _semantic_axis(axis_name))
    axis_axis.set_label_position(label["side"])
    getattr(axis, f"set_{axis_name}label")(label["text"])
    axis_axis.label.set_visible(bool(label["visible"]))
    if label["color"] is not None:
        axis_axis.label.set_color(label["color"])
    if label["rotation"] is not None:
        axis_axis.label.set_rotation(label["rotation"])
    axis_axis.label.set_linespacing(label["line_spacing"])
    if label["position_mode"] == "manual" and label["position"] is not None:
        current_x, current_y = axis_axis.label.get_position()
        if axis_name == "x":
            axis_axis.set_label_coords(label["position"], current_y)
        else:
            axis_axis.set_label_coords(current_x, label["position"])
    axis_axis.labelpad = label["offset"]


def _set_axis_range(axis, axis_name, axis_state):
    range_state = axis_state["range"]
    limits = range_state["limits"]
    limit_mode = range_state["limit_mode"]
    setter = getattr(axis, f"set_{axis_name}lim")
    manual_kwargs = {}
    if limits is not None and limit_mode["min"] == "manual":
        manual_kwargs["left" if axis_name == "x" else "bottom"] = limits[0]
    if limits is not None and limit_mode["max"] == "manual":
        manual_kwargs["right" if axis_name == "x" else "top"] = limits[1]
    if (
        limits is not None
        and limit_mode["min"] == "manual"
        and limit_mode["max"] == "manual"
    ):
        setter(*limits)
    else:
        axis.autoscale(enable=True, axis=axis_name)
        if manual_kwargs:
            setter(**manual_kwargs)
    if axis_state["range"]["reverse"]:
        getattr(axis, f"invert_{axis_name}axis")()


def _set_axis_side_state(axis, axis_name, subplot):
    primary = subplot["axis_sides"][_primary_side(axis_name)]
    mirror = subplot["axis_sides"][_mirror_side(axis_name)]
    axis.tick_params(
        axis=axis_name,
        which="both",
        **{
            _primary_side(axis_name): primary["ticks_visible"],
            f"label{_primary_side(axis_name)}": primary["tick_labels_visible"],
            _mirror_side(axis_name): mirror["ticks_visible"],
            f"label{_mirror_side(axis_name)}": mirror["tick_labels_visible"],
            "direction": _tick_direction(subplot["axes"][axis_name]["ticks"]["direction"]),
        },
    )
    for side_name in (_primary_side(axis_name), _mirror_side(axis_name)):
        side_state = subplot["axis_sides"][side_name]
        spine = axis.spines[side_name]
        spine.set_visible(side_state["spine_visible"])
        if side_state["spine_color"] is not None:
            spine.set_color(side_state["spine_color"])
        if side_state["spine_width"] is not None:
            spine.set_linewidth(side_state["spine_width"])
        if side_state["offset"]:
            spine.set_position(("outward", side_state["offset"]))

def _set_axis_ticks(axis, axis_name, axis_state):
    axis_axis = getattr(axis, _semantic_axis(axis_name))
    major = axis_state["ticks"]["major"]
    if major["positions"] is not None:
        axis_axis.set_major_locator(mticker.FixedLocator(major["positions"]))
        if major["labels"] is not None:
            axis_axis.set_major_formatter(mticker.FixedFormatter(major["labels"]))
    elif major["mode"] == "manual" and major["step"] is not None:
        axis_axis.set_major_locator(mticker.MultipleLocator(major["step"]))
    elif major["count"] is not None:
        axis_axis.set_major_locator(mticker.MaxNLocator(nbins=major["count"]))
    if axis_state["ticks"]["minor"]["visible"]:
        if axis_state["scale_mode"] in {"log", "log2"}:
            base = 2 if axis_state["scale_mode"] == "log2" else 10
            axis_axis.set_minor_locator(mticker.LogLocator(base=base, subs="auto"))
        else:
            axis_axis.set_minor_locator(mticker.AutoMinorLocator())
    else:
        axis_axis.set_minor_locator(mticker.NullLocator())


def _set_axis_tick_label_style(axis, axis_name, subplot):
    axis_axis = getattr(axis, _semantic_axis(axis_name))
    primary_side = _primary_side(axis_name)
    mirror_side = _mirror_side(axis_name)
    for side_name, label_attr in (
        (primary_side, "label1"),
        (mirror_side, "label2"),
    ):
        side_state = subplot["axis_sides"][side_name]
        rotation = side_state["tick_label_rotation"]
        color = side_state["tick_label_color"]
        if color is None and not rotation:
            continue
        for tick in axis_axis.get_major_ticks() + axis_axis.get_minor_ticks():
            label = getattr(tick, label_attr)
            if color is not None:
                label.set_color(color)
            if rotation:
                label.set_rotation(rotation)


def _set_axis_grid(axis, axis_name, axis_state):
    grid = axis_state["grid"]
    if not grid["visible"]:
        axis.grid(False, axis=axis_name, which="both")
        return
    kwargs = {
        "axis": axis_name,
        "which": grid["which"],
        "linestyle": grid["linestyle"],
    }
    if grid["linewidth"] is not None:
        kwargs["linewidth"] = grid["linewidth"]
    if grid["color"] is not None:
        kwargs["color"] = grid["color"]
    axis.grid(True, **kwargs)


def _add_zero_line(axis, axis_name, axis_state):
    zero_line = axis_state["zero_line"]
    if not zero_line["visible"]:
        return
    kwargs = {"linestyle": zero_line["linestyle"]}
    if zero_line["linewidth"] is not None:
        kwargs["linewidth"] = zero_line["linewidth"]
    if zero_line["color"] is not None:
        kwargs["color"] = zero_line["color"]
    line = axis.axvline(0, **kwargs) if axis_name == "x" else axis.axhline(0, **kwargs)
    line._hyde_semantic_role = f"{axis_name}_zero_line"


def _apply_subplot_axis_state(axis, subplot):
    axis.set_axisbelow(
        not any(side_state["draw_on_top"] for side_state in subplot["axis_sides"].values())
    )
    for axis_name in ("x", "y"):
        axis_state = subplot["axes"][axis_name]
        _set_axis_scale(axis, axis_name, axis_state)
        _set_axis_range(axis, axis_name, axis_state)
        _set_axis_ticks(axis, axis_name, axis_state)
        _set_axis_side_state(axis, axis_name, subplot)
        _set_axis_label(axis, axis_name, axis_state)
        _set_axis_tick_label_style(axis, axis_name, subplot)
        _set_axis_grid(axis, axis_name, axis_state)
        _add_zero_line(axis, axis_name, axis_state)


def regenerate_figure_from_ir(figure, use_bound_values=True):
    figure_ir = getattr(figure, "_hyde_ir", None)
    if figure_ir is None:
        raise ValueError("Figure does not have Hyde IR.")

    normalized = FigureIRCodec.validate_state(figure_ir)
    default_subplot = None
    figure_defaults = getattr(figure, "_hyde_defaults", None)
    if figure_defaults is not None:
        try:
            default_subplot = FigureIRCodec.validate_state(figure_defaults)["layout"][
                "subplots"
            ][0]
        except Exception:
            default_subplot = None
    namespace = _main_namespace()
    preserved_size = figure.get_size_inches()
    manager = getattr(figure.canvas, "manager", None)
    was_ready_to_push = None
    was_building = getattr(figure, "_hyde_building", False)
    if manager is not None and hasattr(manager, "_ready_to_push"):
        was_ready_to_push = manager._ready_to_push
        manager._ready_to_push = False
    try:
        figure._hyde_building = False
        figure.clear()
        figsize = normalized["settings"].get("figsize")
        if figsize is None:
            figure.set_size_inches(preserved_size, forward=False)
        else:
            figure.set_size_inches(*figsize, forward=False)

        title = normalized["settings"].get("title")
        if title:
            figure.set_label(title)

        subplots = normalized["layout"]["subplots"]
        if not subplots:
            figure.canvas.draw_idle()
            return figure

        subplot = subplots[0]
        margin_kwargs = {}
        default_margins = (
            {}
            if default_subplot is None
            else dict(default_subplot.get("margins", {}) or {})
        )
        for side in ("left", "bottom", "right", "top"):
            value = subplot["margins"].get(side)
            if value is None:
                value = default_margins.get(side)
            if value is not None:
                margin_kwargs[side] = float(value)
        if margin_kwargs:
            figure.subplots_adjust(**margin_kwargs)
        axis = figure.add_subplot(int(subplot["subplot_code"]))
        axis._hyde_subplot_id = subplot["id"]
        if subplot["title"]:
            axis.set_title(subplot["title"])
        plotted_count = 0
        for trace in subplot["traces"]:
            try:
                x_values = _resolve_ir_operand_value(
                    trace["x_source"],
                    namespace,
                    figure,
                    use_bound_values=use_bound_values,
                )
                y_values = _resolve_ir_operand_value(
                    trace["y_source"],
                    namespace,
                    figure,
                    use_bound_values=use_bound_values,
                )
            except KeyError:
                continue
            args = [y_values] if x_values is None else [x_values, y_values]
            kwargs = dict(trace["kwargs"] or {})
            line = axis.plot(*args, **kwargs)[0]
            line._hyde_trace_id = trace["id"]
            plotted_count += 1
        if subplot["legend"] and plotted_count > 0:
            axis.legend()
        _apply_subplot_axis_state(axis, subplot)
    finally:
        figure._hyde_building = was_building
        if was_ready_to_push is not None:
            manager._ready_to_push = was_ready_to_push
    figure.canvas.draw_idle()
    return figure


def apply_figure_action(figure, action):
    action = dict(action or {})
    action_type = str(action.get("type", ""))
    if action_type == "resize_redraw":
        width = int(action.get("width", 0))
        height = int(action.get("height", 0))
        if width <= 0 or height <= 0:
            raise ValueError("Figure resize action requires positive width and height.")
        figure.set_size_inches(width / figure.dpi, height / figure.dpi, forward=False)
        figure.canvas.draw_idle()
        return figure
    if action_type == "regenerate_from_ir":
        return regenerate_figure_from_ir(
            figure,
            use_bound_values=bool(action.get("use_bound_values", True)),
        )
    if action_type == "refresh_from_live_state":
        live_state = getattr(figure, "_hyde_live_state", None)
        if live_state is None:
            live_state = _infer_live_state(figure, _main_namespace())
            if live_state is not None:
                figure._hyde_live_state = live_state
        if live_state is None:
            return figure
        apply_figure_state(
            figure,
            live_state,
            _main_namespace(),
        )
        return figure

    figure_ir = getattr(figure, "_hyde_ir", None)
    if figure_ir is None:
        raise ValueError("Figure does not support Hyde semantic actions.")
    figure._hyde_ir = FigureIRCodec.update_state(figure_ir, action)

    if action_type == "set_axis_limits":
        axis = _resolve_live_axis(figure, action.get("subplot_id"))
        limits = (action.get("min"), action.get("max"))
        if action.get("axis") == "x":
            axis.set_xlim(*limits)
        else:
            axis.set_ylim(*limits)
        figure.canvas.draw_idle()
        return figure
    if action_type == "set_axis_label":
        axis = _resolve_live_axis(figure, action.get("subplot_id"))
        label = action.get("label")
        if action.get("axis") == "x":
            axis.set_xlabel(label)
            if label not in (None, ""):
                axis.xaxis.label.set_visible(True)
        else:
            axis.set_ylabel(label)
            if label not in (None, ""):
                axis.yaxis.label.set_visible(True)
        figure.canvas.draw_idle()
        return figure
    if action_type in {"set_subplot_title", "set_figure_title"}:
        axis = _resolve_live_axis(figure, action.get("subplot_id"))
        title = action.get("title")
        axis.set_title(title)
        if title:
            figure.set_label(title)
        figure.canvas.draw_idle()
        return figure
    if action_type == "set_legend_visible":
        axis = _resolve_live_axis(figure, action.get("subplot_id"))
        legend = axis.get_legend()
        if action.get("visible"):
            axis.legend()
        elif legend is not None:
            legend.remove()
        figure.canvas.draw_idle()
        return figure
    if action_type == "set_trace_style":
        if action.get("replace"):
            regenerate_figure_from_ir(figure)
            return figure
        axis = _resolve_live_axis(figure, action.get("subplot_id"))
        line = _resolve_live_line(axis, action.get("trace_id"))
        _apply_line_style(line, dict(action.get("style", {}) or {}))
        if axis.get_legend() is not None:
            axis.legend()
        figure.canvas.draw_idle()
        return figure
    if action_type in {
        "set_axis_state",
        "set_axis_side_state",
        "set_subplot_margins",
        "set_trace",
    }:
        return regenerate_figure_from_ir(figure)
    raise ValueError(f"Unsupported figure action: {action_type!r}.")


def _candidate_series_names(namespace):
    candidates = []
    for name, value in sorted((namespace or {}).items()):
        if not name or name.startswith("_"):
            continue
        try:
            array = np.asarray(value)
        except Exception:
            continue
        if array.ndim != 1 or array.dtype.kind not in "biuf":
            continue
        candidates.append((name, array))
    return candidates


def _resolve_series_name(values, candidates):
    array = np.asarray(values)
    if array.ndim != 1:
        return None
    matches = [
        name
        for name, candidate in candidates
        if candidate.shape == array.shape and np.array_equal(candidate, array)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _infer_live_state(figure, namespace):
    axes = list(figure.axes)
    if len(axes) != 1:
        return None

    axis = axes[0]
    if axis.images or axis.collections:
        return None

    lines = list(axis.lines)
    if not lines:
        return None

    candidates = _candidate_series_names(namespace)
    x_name = None
    y_names = []
    for line in lines:
        y_name = _resolve_series_name(line.get_ydata(orig=True), candidates)
        if y_name is None:
            return None
        label = _line_label(line)
        if label not in (None, y_name):
            return None
        y_names.append(y_name)
        x_values = line.get_xdata(orig=True)
        if _is_default_xdata(x_values):
            continue
        resolved_x_name = _resolve_series_name(x_values, candidates)
        if resolved_x_name is None:
            return None
        if x_name is None:
            x_name = resolved_x_name
        elif x_name != resolved_x_name:
            return None

    title = axis.get_title() or figure.get_label() or None
    return FigureCodec.validate_state(
        {
            "feature": "figure",
            "settings": {
                "command": "create",
                "title": title,
                "x_name": x_name,
                "subplot_code": "111",
            },
            "items": y_names,
        }
    )


class FigureManagerHyde(FigureManagerBase):
    def __init__(self, canvas, num):
        self._comm = None
        self._comm_open_count = 0
        self._destroyed = False
        self._ready_to_push = False
        super().__init__(canvas, num)
        self._ready_to_push = True

    def show(self):
        if not _is_windowed_figure(self.canvas.figure):
            self.canvas.draw()
            _display_in_ipython_terminal(self.canvas.figure)
            return
        self._ensure_comm()
        self.canvas.draw()

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        comm = self._comm
        try:
            if comm is not None:
                comm.send(
                    {
                        "event": "close",
                        "figure_number": self.num,
                    }
                )
        except Exception:
            LOGGER.exception(
                "Figure manager failed to send close payload for figure %s.",
                self.num,
            )
        try:
            if comm is not None:
                comm.close()
        except Exception:
            LOGGER.exception(
                "Figure manager failed to close comm for figure %s.",
                self.num,
            )
        self._comm = None
        super().destroy()

    def set_window_title(self, title):
        self.canvas.figure.set_label(title)

    def get_window_title(self):
        return _default_figure_title(self.canvas.figure, self.num)

    def _ensure_comm(self):
        if not _is_windowed_figure(self.canvas.figure):
            return None
        if self._comm is not None:
            return self._comm
        if self._comm_open_count:
            LOGGER.warning(
                "Figure manager is reopening comm for still-live figure %s.",
                self.num,
            )
        else:
            LOGGER.debug(
                "Figure manager is opening first comm for figure %s.",
                self.num,
            )
        payload = self._payload(event="open")
        comm = Comm(target_name=COMM_TARGET, data=payload)
        comm.on_msg(self._on_comm_message)
        comm.on_close(self._on_comm_close)
        self._comm = comm
        self._comm_open_count += 1
        return comm

    def _on_comm_message(self, msg):
        payload = msg.get("content", {}).get("data", {})
        if payload.get("event") != "action":
            return
        action = payload.get("action", {})
        try:
            apply_figure_action(self.canvas.figure, action)
        except Exception:
            LOGGER.exception(
                "Figure manager failed to apply action for figure %s: %r",
                self.num,
                action,
            )

    def _on_comm_close(self, msg):
        del msg
        LOGGER.debug(
            "Figure manager observed comm close for figure %s.",
            self.num,
        )
        self._comm = None

    def _payload(self, event):
        return {
            "event": event,
            "figure_number": self.num,
            "snapshot": figure_snapshot_payload(self.canvas.figure, self.num),
        }

    def _push_draw(self):
        if not self._ready_to_push:
            return
        self._ensure_comm()
        if self._comm is None:
            return
        buffer = io.BytesIO()
        self.canvas.print_png(buffer)
        payload = self._payload(event="draw")
        payload["image_png_base64"] = base64.b64encode(buffer.getvalue()).decode("ascii")
        try:
            self._comm.send(payload)
        except Exception:
            LOGGER.exception(
                "Figure manager failed to send draw payload for figure %s.",
                self.num,
            )


class FigureCanvasHyde(FigureCanvasAgg):
    required_interactive_framework = "qt"
    manager_class = FigureManagerHyde

    def draw(self):
        super().draw()
        manager = getattr(self, "manager", None)
        if manager is not None:
            manager._push_draw()


class AxesHyde(Axes):
    name = "hyde"

    def plot(self, *args, **kwargs):
        lines = super().plot(*args, **kwargs)
        figure = self.figure
        if getattr(figure, "_hyde_building", False):
            named_values = {}
            session = getattr(figure, "_hyde_build_session", None)
            if session is not None:
                named_values = session.named_values
            x_source = None
            y_source = None
            if len(args) == 1:
                y_source = operand_from_runtime_value(args[0], named_values)
            elif len(args) >= 2:
                x_source = operand_from_runtime_value(args[0], named_values)
                y_source = operand_from_runtime_value(args[1], named_values)
            if y_source is not None:
                trace_kwargs = {}
                for name in (
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
                    if name not in kwargs:
                        continue
                    value = kwargs[name]
                    if name == "label" and value in (None, "", "_nolegend_"):
                        continue
                    trace_kwargs[name] = value
                figure._hyde_ir = figure_ir_append_trace(
                    figure._hyde_ir,
                    {
                        "kind": "line",
                        "x_source": x_source,
                        "y_source": y_source,
                        "kwargs": trace_kwargs,
                    },
                )
                subplot = figure._hyde_ir["layout"]["subplots"][0]
                trace = subplot["traces"][-1]
                if lines:
                    lines[0]._hyde_trace_id = trace["id"]
                source = FigureIRCodec._plot_call(trace)
                figure._record_command(
                    "plot",
                    source,
                    subplot_id=subplot["id"],
                    trace_id=trace["id"],
                )
        return lines


register_projection(AxesHyde)


class FigureHyde(Figure):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hyde_is_first_class = False
        self._hyde_ir = figure_ir_default_state()
        self._hyde_defaults = _figure_defaults_snapshot(self._hyde_ir)
        if kwargs.get("figsize") is not None:
            self._hyde_ir["settings"]["figsize"] = tuple(
                float(value) for value in self.get_size_inches()
            )
        self._hyde_command_log = []
        self._hyde_source_artifact = None
        self._hyde_ast_artifact = None
        self._hyde_bound_values = {}
        self._hyde_metadata = {}
        self._hyde_build_session = _current_build_session()
        self._hyde_building = self._hyde_build_session is not None
        if self._hyde_build_session is not None:
            self._hyde_metadata = dict(self._hyde_build_session.metadata)
            self._hyde_build_session.register_figure(self)

    def _record_command(self, op, source, **payload):
        self._hyde_command_log.append(
            {
                "op": op,
                "source": source,
                **payload,
            }
        )

    def set_label(self, s):
        if not _is_windowed_figure(self):
            return super().set_label(s)
        canonical_name = _canonical_windowed_figure_name(s)
        if not canonical_name:
            raise ValueError("First-class figures require a non-empty canonical name.")
        conflict = _windowed_figure_with_name(canonical_name, exclude=self)
        if conflict is not None:
            raise ValueError(
                f"First-class figure name {canonical_name!r} is already in use."
            )
        result = super().set_label(canonical_name)
        self._hyde_ir = figure_ir_apply_title(self._hyde_ir, canonical_name)
        return result

    def add_subplot(self, *args, **kwargs):
        if "axes_class" not in kwargs and "projection" not in kwargs:
            kwargs["axes_class"] = AxesHyde
        axis = super().add_subplot(*args, **kwargs)
        if getattr(self, "_hyde_building", False):
            subplots = self._hyde_ir["layout"]["subplots"]
            if not subplots:
                subplot_id = "subplot0"
                subplot_code = "111" if len(args) == 1 else "111"
                subplots.append(_default_subplot_state(subplot_id, subplot_code))
                axis._hyde_subplot_id = subplot_id
                self._record_command("add_subplot", f"ax = fig.add_subplot({subplot_code})")
        return axis


@_Backend.export
class _BackendHyde(_Backend):
    FigureCanvas = FigureCanvasHyde
    FigureManager = FigureManagerHyde

    @classmethod
    def new_figure_manager(cls, num, *args, **kwargs):
        figure_class = kwargs.get("FigureClass")
        if figure_class in (None, Figure):
            kwargs["FigureClass"] = FigureHyde
        return super().new_figure_manager(num, *args, **kwargs)

    def draw_idle(self):
        self.draw()

    def flush_events(self):
        return


FigureCanvas = FigureCanvasHyde
FigureManager = FigureManagerHyde
