from __future__ import annotations

import base64
import io
import sys

import numpy as np
from ipykernel.comm import Comm
from matplotlib.backend_bases import FigureManagerBase
from matplotlib.backends.backend_agg import FigureCanvasAgg

from hyde.features.matplotlib_features import FigureCodec


COMM_TARGET = "hyde_figure"


def _default_figure_title(figure, number):
    label = figure.get_label()
    if label:
        return str(label)
    return f"Figure {number}"


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
    live_state = getattr(figure, "_hyde_live_state", None)
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
        try:
            if self._comm is not None:
                self._comm.send(
                    {
                        "event": "close",
                        "figure_number": self.num,
                    }
                )
                self._comm.close()
        except Exception:
            pass
        self._comm = None
        super().destroy()

    def set_window_title(self, title):
        self.canvas.figure.set_label(title)

    def get_window_title(self):
        return _default_figure_title(self.canvas.figure, self.num)

    def _ensure_comm(self):
        if self._comm is not None:
            return self._comm
        payload = self._payload(event="open")
        comm = Comm(target_name=COMM_TARGET, data=payload)
        comm.on_close(self._on_comm_close)
        self._comm = comm
        return comm

    def _on_comm_close(self, msg):
        del msg
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
            pass


class FigureCanvasHyde(FigureCanvasAgg):
    required_interactive_framework = "qt"
    manager_class = FigureManagerHyde

    def draw(self):
        super().draw()
        manager = getattr(self, "manager", None)
        if manager is not None:
            manager._push_draw()

    def draw_idle(self):
        self.draw()

    def flush_events(self):
        return


FigureCanvas = FigureCanvasHyde
FigureManager = FigureManagerHyde
