from __future__ import annotations

import ast
import base64
import io
import inspect
import logging
import sys
import textwrap
import threading

import numpy as np
from ipykernel.comm import Comm
from matplotlib.axes import Axes
from matplotlib.backend_bases import FigureManagerBase, _Backend
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.projections import register_projection

from hyde.features.matplotlib_features import (
    FigureCodec,
    FigureIRCodec,
    figure_ir_append_trace,
    figure_ir_apply_title,
    figure_ir_default_state,
    operand_from_runtime_value,
)
from hyde.user_interface.figure_comm import COMM_TARGET


_BUILD_SESSION_LOCAL = threading.local()
LOGGER = logging.getLogger("hyde")


def _default_figure_title(figure, number):
    label = figure.get_label()
    if label:
        return str(label)
    return f"Figure {number}"


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
    if figure._hyde_ir["settings"].get("title") is None:
        figure._hyde_ir = figure_ir_apply_title(
            figure._hyde_ir,
            figure.get_label() or None,
        )
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


def _line_kwargs(line):
    kwargs = {}
    color = line.get_color()
    if color is not None:
        kwargs["color"] = color
    linestyle = line.get_linestyle()
    if linestyle not in (None, "-", "solid"):
        kwargs["linestyle"] = linestyle
    marker = line.get_marker()
    if marker not in (None, "", "None", "none"):
        kwargs["marker"] = marker
    linewidth = line.get_linewidth()
    if linewidth not in (None, 1.5):
        kwargs["linewidth"] = linewidth
    label = _line_label(line)
    if label:
        kwargs["label"] = label
    return kwargs


def _format_plot_call(line):
    x_values = line.get_xdata()
    y_values = line.get_ydata()
    kwargs = _line_kwargs(line)
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
    for line in lines:
        source_lines.append(_format_plot_call(line))
    if legend is not None:
        source_lines.append("ax.legend()")
    if grid_on:
        source_lines.append("ax.grid(True)")
    source_lines.append("fig.show()")
    source_lines.append("fig.canvas.draw_idle()")
    return "\n".join(source_lines)


def figure_snapshot_payload(figure, number):
    open_token = getattr(figure, "_hyde_open_token", None)
    figure_ir = getattr(figure, "_hyde_ir", None)
    live_state = getattr(figure, "_hyde_live_state", None)
    hyde_metadata = dict(getattr(figure, "_hyde_metadata", {}) or {})
    if getattr(figure, "_hyde_is_first_class", False) and figure_ir is not None:
        payload = {
            "default_macro_name": _default_figure_title(figure, number),
            "call_source": FigureIRCodec.state_to_python(figure_ir),
            "save_error": None,
            "figure_size": tuple(
                int(value * figure.dpi) for value in figure.get_size_inches()
            ),
            "tracked_names": list(FigureIRCodec.tracked_names(figure_ir)),
            "live_state": None,
            "figure_ir": figure_ir,
            "command_log": list(getattr(figure, "_hyde_command_log", [])),
            "open_token": open_token,
            "hyde_metadata": hyde_metadata,
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
        "open_token": open_token,
        "hyde_metadata": hyde_metadata,
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


def _resolve_ir_operand_value(operand, namespace, figure=None):
    if operand is None:
        return None
    kind = operand.get("kind")
    if kind == "name":
        operand_name = operand["value"]
        if operand_name in namespace:
            return namespace[operand_name]
        bound_values = getattr(figure, "_hyde_bound_values", {})
        if operand_name in bound_values:
            return bound_values[operand_name]
        raise KeyError(operand_name)
    if kind == "literal":
        return operand.get("value")
    if kind == "array_literal":
        return np.array(operand.get("value", []))
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


def _apply_line_style(line, kwargs):
    if "color" in kwargs:
        line.set_color(kwargs["color"])
    if "marker" in kwargs:
        line.set_marker(kwargs["marker"])
    if "linestyle" in kwargs:
        line.set_linestyle(kwargs["linestyle"])
    if "linewidth" in kwargs:
        line.set_linewidth(kwargs["linewidth"])
    if "label" in kwargs:
        line.set_label(kwargs["label"])


def regenerate_figure_from_ir(figure):
    figure_ir = getattr(figure, "_hyde_ir", None)
    if figure_ir is None:
        raise ValueError("Figure does not have Hyde IR.")

    normalized = FigureIRCodec.validate_state(figure_ir)
    namespace = _main_namespace()
    preserved_size = figure.get_size_inches()
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
    axis = figure.add_subplot(int(subplot["subplot_code"]))
    axis._hyde_subplot_id = subplot["id"]
    if subplot["title"]:
        axis.set_title(subplot["title"])
    if subplot["xlabel"]:
        axis.set_xlabel(subplot["xlabel"])
    if subplot["ylabel"]:
        axis.set_ylabel(subplot["ylabel"])
    for trace in subplot["traces"]:
        x_values = _resolve_ir_operand_value(trace["x_source"], namespace, figure)
        y_values = _resolve_ir_operand_value(trace["y_source"], namespace, figure)
        args = [y_values] if x_values is None else [x_values, y_values]
        kwargs = dict(trace["kwargs"] or {})
        line = axis.plot(*args, **kwargs)[0]
        line._hyde_trace_id = trace["id"]
    if subplot["legend"]:
        axis.legend()
    if subplot["x_limits"] is not None:
        axis.set_xlim(*subplot["x_limits"])
    if subplot["y_limits"] is not None:
        axis.set_ylim(*subplot["y_limits"])
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
        return regenerate_figure_from_ir(figure)

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
        else:
            axis.set_ylabel(label)
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
        axis = _resolve_live_axis(figure, action.get("subplot_id"))
        line = _resolve_live_line(axis, action.get("trace_id"))
        _apply_line_style(line, dict(action.get("style", {}) or {}))
        if axis.get_legend() is not None:
            axis.legend()
        figure.canvas.draw_idle()
        return figure
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
            "title": self.get_window_title(),
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
                label = kwargs.get("label")
                if label not in (None, "", "_nolegend_"):
                    trace_kwargs["label"] = label
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

    def add_subplot(self, *args, **kwargs):
        if "axes_class" not in kwargs and "projection" not in kwargs:
            kwargs["axes_class"] = AxesHyde
        axis = super().add_subplot(*args, **kwargs)
        if getattr(self, "_hyde_building", False):
            subplots = self._hyde_ir["layout"]["subplots"]
            if not subplots:
                subplot_id = "subplot0"
                subplot_code = "111" if len(args) == 1 else "111"
                subplots.append(
                    {
                        "id": subplot_id,
                        "subplot_code": subplot_code,
                        "title": None,
                        "xlabel": None,
                        "ylabel": None,
                        "x_limits": None,
                        "y_limits": None,
                        "legend": False,
                        "traces": [],
                        "opaque_nodes": [],
                    }
                )
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
