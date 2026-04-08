from __future__ import annotations

import inspect
import io
import json
import os
import re
import sys
import traceback
import types
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import lmfit
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from IPython.core.interactiveshell import InteractiveShell
from IPython.core.completer import provisionalcompleter
from labscript_utils.modulewatcher import ModuleWatcher
from matplotlib.figure import Figure as MatplotlibFigure

from .annotations import discover_script_entries
from .data import TrackedArray, summarize_object

HIDDEN_NAMESPACE_NAMES = {"In", "Out"}


@dataclass(frozen=True)
class FigureCommandResult:
    figure_id: str
    script_source: str

    def __repr__(self):
        return self.script_source


class ExecutionRuntime:
    def __init__(self):
        self.namespace = {}
        self.figures = {}
        self.tables = {}
        self.history = []
        self.project_root = None
        self.incoming_shots = []
        self.message_handler = {"enabled": True}
        self.modulewatcher = ModuleWatcher()
        self.shell = InteractiveShell.instance()
        self.shell.reset(new_session=False)
        self._install_namespace()

    def _install_namespace(self):
        helpers = {
            "np": np,
            "wave": self.wave,
            "display": self.display,
            "open_table": self.open_table,
            "close_table": self.close_table,
            "append_to_graph": self.append_to_graph,
            "delete_object": self.delete_object,
            "show_where_used": self.show_where_used,
            "edit_figure": self.edit_figure,
            "edit_trace": self.edit_trace,
            "close_figure": self.close_figure,
            "save_graphics": self.save_graphics,
            "do_fit": self.do_fit,
            "record_incoming_shot": self.record_incoming_shot,
            "run_hyde_script": self.run_hyde_script,
            "_last_graph": self.last_graph_id,
            "_hyde_register_result": self._register_decorated_result,
        }
        self.namespace.clear()
        self.namespace.update(helpers)
        self.shell.user_ns = self.namespace
        self.shell.user_ns_hidden = {}
        self.shell.Completer.namespace = self.namespace
        self.shell.Completer.global_namespace = self.namespace
        self.namespace.setdefault("_ih", [""])
        self.namespace.setdefault("_oh", {})
        self.namespace.setdefault("_dh", [])
        self.namespace.setdefault("get_ipython", lambda: self.shell)

    def set_project_root(self, project_root):
        self.project_root = str(project_root)
        self._load_master_procedure()

    def execute(self, code, echo=True, record_history=True, silent=False):
        output = io.StringIO()
        error = None
        if record_history:
            self.history.append(code)
        try:
            import contextlib

            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = self.shell.run_cell(code, store_history=record_history, silent=silent)
        except Exception:  # pragma: no cover - IPython normally traps this
            success = False
            error = traceback.format_exc()
            output.write(error)
        else:
            success = (
                getattr(result, "error_before_exec", None) is None
                and getattr(result, "error_in_exec", None) is None
            )
            if not success:
                traceback_text = getattr(result, "error_before_exec", None) or getattr(
                    result, "error_in_exec", None
                )
                error = str(traceback_text)
        self._refresh_all_views()
        return {
            "success": success,
            "code": code if echo else "",
            "stdout": output.getvalue(),
            "error": error,
            "snapshot": self.snapshot(),
        }

    def snapshot(self):
        self._refresh_all_views()
        return {
            "objects": {
                name: self._serialize_object(name, value)
                for name, value in sorted(self.namespace.items())
                if not name.startswith("_")
                and name not in HIDDEN_NAMESPACE_NAMES
                and not callable(value)
                and not isinstance(value, types.ModuleType)
            },
            "namespace_summary": self.namespace_summary(),
            "figures": list(self.figures.values()),
            "tables": list(self.tables.values()),
            "history": list(self.history),
            "incoming_shots": list(self.incoming_shots),
            "message_handler": dict(self.message_handler),
            "application_version": "0.1.0",
        }

    def restore(self, state):
        self._install_namespace()
        self.history = list(state.get("history", []))
        self.incoming_shots = list(state.get("incoming_shots", []))
        self.message_handler = dict(state.get("message_handler", {"enabled": True}))
        for name, value in state.get("objects", {}).items():
            if value["kind"] == "wave":
                tracked_array = TrackedArray(name, value["data"], title=value.get("title"))
                tracked_array.revision = value.get("revision", 0)
                self.namespace[name] = tracked_array
            else:
                self.namespace[name] = value["value"]
        self.figures = {figure["id"]: figure for figure in state.get("figures", [])}
        self.tables = {table["id"]: table for table in state.get("tables", [])}
        self._load_master_procedure()
        self.shell.user_ns = self.namespace

    def export_state(self):
        return self.snapshot()

    def complete(self, code, cursor_pos=None):
        cursor_pos = len(code) if cursor_pos is None else cursor_pos
        with provisionalcompleter():
            completions = list(self.shell.Completer.completions(code, cursor_pos))
        matches = [completion.text for completion in completions]
        token_match = re.search(r"([A-Za-z_][A-Za-z0-9_\.]*)$", code[:cursor_pos])
        token = token_match.group(1) if token_match else ""
        return {"token": token, "matches": matches}

    def wave(self, name, data, title=None):
        tracked_array = TrackedArray(name, data, title=title)
        self.namespace[name] = tracked_array
        return tracked_array

    def open_table(self, *names, title=None):
        names = [self._table_object_name(name) for name in names]
        table_id = title or "_".join(names) or "table"
        snapshot = {
            "id": table_id,
            "title": title or f"Table: {', '.join(names)}",
            "objects": names,
            "data": {
                name: np.asarray(self._resolve_tracked_array(name)).tolist()
                for name in names
            },
        }
        self.tables[table_id] = snapshot
        return snapshot

    def display(
        self,
        y,
        x=None,
        figure_name=None,
        title=None,
        style="-",
        label=None,
        marker=None,
        markersize=6.0,
        linewidth=1.5,
    ):
        y_array = self._resolve_tracked_array(y)
        if x is None:
            x_data = np.arange(len(y_array))
            x_name = None
        else:
            x_array = self._resolve_tracked_array(x)
            x_data = np.asarray(x_array)
            x_name = x_array.name
        figure_id = figure_name or f"figure_{uuid.uuid4().hex[:8]}"
        snapshot = {
            "id": figure_id,
            "title": title or figure_name or y_array.name,
            "traces": [
                self._make_trace(
                    y_array,
                    x_name,
                    x_data,
                    label=label,
                    style=style,
                    marker=marker,
                    markersize=markersize,
                    linewidth=linewidth,
                )
            ],
            "size_inches": self._default_figure_size_inches(),
            "axes": {
                "xlabel": x_name or "index",
                "ylabel": y_array.name,
                "xscale": "linear",
                "yscale": "linear",
                "xgrid": False,
                "ygrid": False,
                "xmin": None,
                "xmax": None,
                "ymin": None,
                "ymax": None,
            },
        }
        snapshot["script_source"] = self._figure_function_source(snapshot, figure_id)
        self.figures[figure_id] = snapshot
        return FigureCommandResult(figure_id, snapshot["script_source"])

    def append_to_graph(
        self,
        figure_id,
        y,
        x=None,
        label=None,
        style="-",
        marker=None,
        markersize=6.0,
        linewidth=1.5,
    ):
        figure = self.figures[figure_id]
        y_array = self._resolve_tracked_array(y)
        if x is None:
            x_data = np.arange(len(y_array))
            x_name = None
        else:
            x_array = self._resolve_tracked_array(x)
            x_data = np.asarray(x_array)
            x_name = x_array.name
        figure["traces"].append(
            self._make_trace(
                y_array,
                x_name,
                x_data,
                label=label,
                style=style,
                marker=marker,
                markersize=markersize,
                linewidth=linewidth,
            )
        )
        figure["script_source"] = self._figure_function_source(figure, figure["id"])
        return FigureCommandResult(figure["id"], figure["script_source"])

    def edit_figure(self, figure_id, **updates):
        figure = self.figures[figure_id]
        figure["title"] = updates.get("title", figure["title"])
        axes = figure.setdefault("axes", {})
        for key in (
            "xlabel",
            "ylabel",
            "xscale",
            "yscale",
            "xgrid",
            "ygrid",
            "xmin",
            "xmax",
            "ymin",
            "ymax",
        ):
            if key in updates:
                axes[key] = updates[key]
        figure["script_source"] = self._figure_function_source(figure, figure["id"])
        return FigureCommandResult(figure["id"], figure["script_source"])

    def edit_trace(self, figure_id, index, **updates):
        figure = self.figures[figure_id]
        trace = figure["traces"][index]
        for key in ("label", "style", "color", "visible", "marker", "markersize", "linewidth", "gaps"):
            if key in updates:
                trace[key] = updates[key]
        figure["script_source"] = self._figure_function_source(figure, figure["id"])
        return FigureCommandResult(figure["id"], figure["script_source"])

    def close_figure(self, figure_id):
        self.figures.pop(figure_id, None)

    def close_table(self, table_id):
        self.tables.pop(table_id, None)

    def save_graphics(
        self,
        figure_id,
        path,
        format=None,
        size=None,
        units="inches",
        color=True,
        overwrite=False,
    ):
        output_path = Path(path)
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"{output_path} already exists")
        if units != "inches":
            raise ValueError(f"Unsupported save_graphics units: {units!r}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if size is None:
            size = tuple(self.figures[figure_id].get("size_inches", self._default_figure_size_inches()))
        figure = self._build_export_figure(self.figures[figure_id], size=size, color=color)
        try:
            save_format = format or output_path.suffix.lstrip(".") or None
            figure.savefig(output_path, format=save_format)
        finally:
            plt.close(figure)
        return str(output_path)

    def last_graph_id(self):
        if not self.figures:
            raise RuntimeError("No Hyde graphs are currently open")
        return list(self.figures)[-1]

    def delete_object(self, name):
        self.namespace.pop(name, None)
        self._refresh_dependents(name)

    def show_where_used(self, name):
        usage = []
        for figure in self.figures.values():
            if any(
                trace["y_name"] == name or trace["x_name"] == name
                for trace in figure["traces"]
            ):
                usage.append({"type": "figure", "id": figure["id"], "title": figure["title"]})
        for table in self.tables.values():
            if name in table["objects"]:
                usage.append({"type": "table", "id": table["id"], "title": table["title"]})
        return usage

    def do_fit(
        self,
        function_path,
        function_name,
        y,
        x=None,
        result_name="fit_result",
        params=None,
        x_range=None,
        store_residuals=True,
        graph=False,
        graph_target=None,
        preview=False,
    ):
        fit_function = self._load_callable(function_path, function_name)
        y_array = self._resolve_tracked_array(y)
        if x is None:
            x_data = np.arange(len(y_array), dtype=float)
            x_name = None
        else:
            x_array = self._resolve_tracked_array(x)
            x_data = np.asarray(x_array, dtype=float)
            x_name = x_array.name
        y_data = np.asarray(y_array, dtype=float)
        if x_range:
            lower, upper = x_range
            mask = np.ones_like(x_data, dtype=bool)
            if lower is not None:
                mask &= x_data >= lower
            if upper is not None:
                mask &= x_data <= upper
            x_data = x_data[mask]
            y_data = y_data[mask]
        model = lmfit.Model(fit_function)
        fit_params = model.make_params()
        for name, info in (params or {}).items():
            if name in fit_params:
                fit_params[name].set(
                    value=info.get("value"),
                    vary=info.get("vary", True),
                    min=info.get("min", -np.inf),
                    max=info.get("max", np.inf),
                )
        fit_wave_name = result_name
        if preview:
            fit_values = np.asarray(model.eval(params=fit_params, x=x_data), dtype=float)
            summary = {
                "kind": "fit_preview",
                "function_name": function_name,
                "function_path": function_path,
                "best_values": {name: float(parameter.value) for name, parameter in fit_params.items()},
                "x_name": x_name,
                "y_name": y_array.name,
            }
        else:
            result = model.fit(y_data, fit_params, x=x_data)
            fit_values = np.asarray(result.best_fit, dtype=float)
            summary = {
                "kind": "fit_result",
                "function_name": function_name,
                "function_path": function_path,
                "chisqr": float(result.chisqr),
                "redchi": float(result.redchi),
                "best_values": {name: float(value) for name, value in result.best_values.items()},
                "x_name": x_name,
                "y_name": y_array.name,
            }
            self.namespace[f"{result_name}_result"] = summary
            if store_residuals:
                residual_name = f"{result_name}_residuals"
                self.namespace[residual_name] = TrackedArray(residual_name, result.residual)
        self.namespace[fit_wave_name] = TrackedArray(fit_wave_name, fit_values)
        if graph:
            figure_id = graph_target or f"{result_name}_graph"
            if graph_target is None or figure_id not in self.figures:
                self.display(y_array.name, x_name, figure_name=figure_id, title=result_name)
            if not self._figure_has_trace(figure_id, fit_wave_name):
                self.append_to_graph(figure_id, fit_wave_name, x_name, label=f"{function_name} fit")
            else:
                for trace in self.figures[figure_id]["traces"]:
                    if trace["y_name"] == fit_wave_name:
                        trace["label"] = f"{function_name} fit"
                self.figures[figure_id]["script_source"] = self._figure_function_source(
                    self.figures[figure_id], figure_id
                )
        self._refresh_all_views()
        return summary

    def record_incoming_shot(self, filepath):
        self.incoming_shots.append({"filepath": str(filepath)})
        self.namespace["last_shot_path"] = str(filepath)
        self.namespace["incoming_shots"] = list(self.incoming_shots)
        return filepath

    def run_hyde_script(self, relative_path, entry_point=None):
        if self.project_root is None:
            raise RuntimeError("No Hyde project is open")
        full_path = Path(self.project_root) / relative_path
        module = self._exec_script_module(full_path)
        if entry_point is not None:
            result = self._invoke_entry_point(getattr(module, entry_point))
            return self._coerce_script_result(result, entry_point)
        entries = discover_script_entries(full_path)
        if len(entries) == 1:
            result = self._invoke_entry_point(getattr(module, entries[0].function_name))
            return self._coerce_script_result(result, entries[0].function_name)
        return module

    def namespace_summary(self):
        return [
            summarize_object(name, value)
            for name, value in sorted(self.namespace.items())
            if not name.startswith("_")
            and name not in HIDDEN_NAMESPACE_NAMES
            and not callable(value)
            and not isinstance(value, types.ModuleType)
        ]

    def figure_replay_source(self, figure_id, function_name):
        figure = self.figures[figure_id]
        return self._figure_function_source(figure, function_name)

    def table_replay_source(self, table_id, function_name):
        table = self.tables[table_id]
        arguments = ", ".join(table["objects"])
        if arguments:
            arguments = f"({arguments})"
        else:
            arguments = "()"
        object_arguments = ", ".join(table["objects"])
        call_arguments = object_arguments
        if call_arguments:
            call_arguments = f"{call_arguments}, title={table['id']!r}"
        else:
            call_arguments = f"title={table['id']!r}"
        lines = [
            "from hyde import *",
            "",
            "@table",
            f"def {function_name}{arguments}:",
            f"    return open_table({call_arguments})",
        ]
        return "\n".join(lines) + "\n"

    def _serialize_object(self, name, value):
        if isinstance(value, TrackedArray):
            return {
                "kind": "wave",
                "name": name,
                "title": value.title,
                "data": np.asarray(value).tolist(),
                "dtype": value.dtype,
                "shape": value.shape,
                "revision": value.revision,
            }
        if isinstance(value, np.ndarray):
            array = np.asarray(value)
            return {
                "kind": "wave",
                "name": name,
                "title": name,
                "data": array.tolist(),
                "dtype": str(array.dtype),
                "shape": list(array.shape),
                "revision": 0,
            }
        if isinstance(value, np.generic):
            value = value.item()
        try:
            serialized = json.loads(json.dumps(value))
        except TypeError:
            serialized = repr(value)
        return {"kind": "json", "value": serialized}

    def _resolve_tracked_array(self, object_or_name):
        if isinstance(object_or_name, TrackedArray):
            return object_or_name
        value = self.namespace[object_or_name]
        if isinstance(value, TrackedArray):
            return value
        if isinstance(value, np.ndarray):
            tracked_array = TrackedArray(object_or_name, value)
            self.namespace[object_or_name] = tracked_array
            return tracked_array
        raise TypeError(f"{object_or_name!r} is not Hyde-managed array-backed data")

    def _refresh_dependents(self, name):
        for figure_id, figure in list(self.figures.items()):
            traces = []
            for trace in figure["traces"]:
                if trace["x_name"] == name or trace["y_name"] == name:
                    continue
                y_array = self._resolve_tracked_array(trace["y_name"])
                if trace["x_name"] is None:
                    x_data = np.arange(len(y_array))
                else:
                    x_data = np.asarray(self._resolve_tracked_array(trace["x_name"]))
                trace["x_data"] = np.asarray(x_data).tolist()
                trace["y_data"] = np.asarray(y_array).tolist()
                trace["revisions"] = self._trace_revisions(trace["x_name"], trace["y_name"])
                traces.append(trace)
            if traces:
                figure["traces"] = traces
            else:
                del self.figures[figure_id]
        for table_id, table in list(self.tables.items()):
            table["objects"] = [entry for entry in table["objects"] if entry != name]
            table["data"].pop(name, None)
            if not table["objects"]:
                del self.tables[table_id]

    def _refresh_all_views(self):
        for figure in self.figures.values():
            for trace in figure["traces"]:
                y_array = self._resolve_tracked_array(trace["y_name"])
                if trace["x_name"] is None:
                    x_data = np.arange(len(y_array))
                else:
                    x_data = np.asarray(self._resolve_tracked_array(trace["x_name"]))
                trace["x_data"] = np.asarray(x_data).tolist()
                trace["y_data"] = np.asarray(y_array).tolist()
                trace["revisions"] = self._trace_revisions(trace["x_name"], trace["y_name"])
            figure["script_source"] = self._figure_function_source(figure, figure["id"])
        for table in self.tables.values():
            table["data"] = {
                name: np.asarray(self._resolve_tracked_array(name)).tolist()
                for name in table["objects"]
            }

    def _trace_revisions(self, x_name, y_name):
        revisions = {}
        if x_name is not None:
            revisions[x_name] = self._resolve_tracked_array(x_name).revision
        revisions[y_name] = self._resolve_tracked_array(y_name).revision
        return revisions

    def _figure_has_trace(self, figure_id, y_name):
        figure = self.figures.get(figure_id)
        if figure is None:
            return False
        return any(trace.get("y_name") == y_name for trace in figure.get("traces", []))

    def _make_trace(
        self,
        y_array,
        x_name,
        x_data,
        label=None,
        style="-",
        marker=None,
        markersize=6.0,
        linewidth=1.5,
    ):
        return {
            "x_name": x_name,
            "y_name": y_array.name,
            "label": label or y_array.name,
            "style": style,
            "color": "",
            "visible": True,
            "marker": marker,
            "markersize": markersize,
            "linewidth": linewidth,
            "gaps": False,
            "x_data": np.asarray(x_data).tolist(),
            "y_data": np.asarray(y_array).tolist(),
            "revisions": self._trace_revisions(x_name, y_array.name),
        }

    def _coerce_script_result(self, result, default_name):
        if isinstance(result, MatplotlibFigure):
            return self._register_matplotlib_figure(result, default_name)
        return result

    def _register_decorated_result(self, _kind, function_name, result):
        return self._coerce_script_result(result, function_name)

    def _register_matplotlib_figure(self, figure, default_name):
        figure_spec = getattr(figure, "_hyde_figure_spec", {})
        figure_id = figure_spec.get("id") or figure.get_label() or default_name or f"figure_{uuid.uuid4().hex[:8]}"
        axes = figure.axes[0] if figure.axes else figure.add_subplot(111)
        traces = []
        metadata_by_index = list(figure_spec.get("traces", []))
        for index, line in enumerate(axes.get_lines()):
            metadata = metadata_by_index[index] if index < len(metadata_by_index) else {}
            x_name = metadata.get("x_name")
            y_name = metadata.get("y_name")
            traces.append(
                {
                    "x_name": x_name,
                    "y_name": y_name,
                    "label": metadata.get("label", line.get_label()),
                    "style": metadata.get("style", line.get_linestyle() or "-"),
                    "color": metadata.get("color", line.get_color() or ""),
                    "visible": metadata.get("visible", line.get_visible()),
                    "marker": metadata.get("marker", line.get_marker() or None),
                    "markersize": metadata.get("markersize", float(line.get_markersize())),
                    "linewidth": metadata.get("linewidth", float(line.get_linewidth())),
                    "gaps": metadata.get("gaps", False),
                    "x_data": np.asarray(line.get_xdata()).tolist(),
                    "y_data": np.asarray(line.get_ydata()).tolist(),
                    "revisions": self._trace_revisions(x_name, y_name) if y_name is not None else {},
                }
            )
        snapshot = {
            "id": figure_id,
            "title": figure_spec.get("title", axes.get_title() or figure_id),
            "size_inches": tuple(float(value) for value in figure.get_size_inches()),
            "traces": traces,
            "axes": {
                "xlabel": figure_spec.get("axes", {}).get("xlabel", axes.get_xlabel()),
                "ylabel": figure_spec.get("axes", {}).get("ylabel", axes.get_ylabel()),
                "xscale": figure_spec.get("axes", {}).get("xscale", axes.get_xscale()),
                "yscale": figure_spec.get("axes", {}).get("yscale", axes.get_yscale()),
                "xgrid": figure_spec.get("axes", {}).get("xgrid", False),
                "ygrid": figure_spec.get("axes", {}).get("ygrid", False),
                "xmin": figure_spec.get("axes", {}).get("xmin"),
                "xmax": figure_spec.get("axes", {}).get("xmax"),
                "ymin": figure_spec.get("axes", {}).get("ymin"),
                "ymax": figure_spec.get("axes", {}).get("ymax"),
            },
        }
        snapshot["script_source"] = self._figure_function_source(snapshot, figure_id)
        self.figures[figure_id] = snapshot
        plt.close(figure)
        return FigureCommandResult(figure_id, snapshot["script_source"])

    def _figure_function_source(self, figure, function_name):
        arguments = self._figure_function_arguments(figure)
        lines = [
            "from hyde import *",
            "import numpy as np",
            "import matplotlib.pyplot as plt",
            "",
            "@figure",
            f"def {function_name}({', '.join(arguments)}):",
            f"    fig = plt.figure({function_name!r})",
            "    fig.clf()",
            "    ax = fig.add_subplot(111)",
        ]
        for index, trace in enumerate(figure["traces"]):
            plot_arguments = [
                self._trace_x_expression(trace),
                self._trace_y_expression(trace),
                f"label={trace['label']!r}",
                f"linestyle={trace.get('style', '-')!r}",
            ]
            if trace.get("color"):
                plot_arguments.append(f"color={trace['color']!r}")
            if trace.get("marker"):
                plot_arguments.append(f"marker={trace['marker']!r}")
            if trace.get("markersize") is not None:
                plot_arguments.append(f"markersize={trace['markersize']!r}")
            if trace.get("linewidth") is not None:
                plot_arguments.append(f"linewidth={trace['linewidth']!r}")
            lines.append(f"    line_{index}, = ax.plot({', '.join(plot_arguments)})")
            if not trace.get("visible", True):
                lines.append(f"    line_{index}.set_visible(False)")
        axes = figure.get("axes", {})
        lines.append(f"    ax.set_xlabel({axes.get('xlabel', '')!r})")
        lines.append(f"    ax.set_ylabel({axes.get('ylabel', '')!r})")
        lines.append(f"    ax.set_title({figure['title']!r})")
        if axes.get("xscale") and axes.get("xscale") != "linear":
            lines.append(f"    ax.set_xscale({axes['xscale']!r})")
        if axes.get("yscale") and axes.get("yscale") != "linear":
            lines.append(f"    ax.set_yscale({axes['yscale']!r})")
        if axes.get("xmin") is not None or axes.get("xmax") is not None:
            lines.append(
                f"    ax.set_xlim(left={axes.get('xmin')!r}, right={axes.get('xmax')!r})"
            )
        if axes.get("ymin") is not None or axes.get("ymax") is not None:
            lines.append(
                f"    ax.set_ylim(bottom={axes.get('ymin')!r}, top={axes.get('ymax')!r})"
            )
        if axes.get("xgrid"):
            lines.append("    ax.grid(True, axis='x')")
        if axes.get("ygrid"):
            lines.append("    ax.grid(True, axis='y')")
        if len(figure["traces"]) > 1:
            lines.append("    ax.legend()")
        lines.append(f"    fig._hyde_figure_spec = {self._figure_metadata(figure, function_name)!r}")
        lines.append("    return fig")
        return "\n".join(lines) + "\n"

    def _figure_metadata(self, figure, figure_id):
        return {
            "id": figure_id,
            "title": figure["title"],
            "axes": dict(figure.get("axes", {})),
            "traces": [
                {
                    "x_name": trace["x_name"],
                    "y_name": trace["y_name"],
                    "label": trace["label"],
                    "style": trace.get("style", "-"),
                    "color": trace.get("color", ""),
                    "visible": trace.get("visible", True),
                    "marker": trace.get("marker"),
                    "markersize": trace.get("markersize", 6.0),
                    "linewidth": trace.get("linewidth", 1.5),
                    "gaps": trace.get("gaps", False),
                }
                for trace in figure["traces"]
            ],
        }

    def _build_export_figure(self, snapshot, size=(6.4, 4.8), color=True):
        figure = plt.figure(snapshot["id"], figsize=size)
        figure.clf()
        axes = figure.add_subplot(111)
        for trace in snapshot["traces"]:
            axes.plot(
                trace["x_data"],
                trace["y_data"],
                label=trace["label"],
                linestyle=trace.get("style", "-"),
                color=(trace.get("color") or None) if color else "black",
                marker=trace.get("marker") or None,
                markersize=trace.get("markersize") or None,
                linewidth=trace.get("linewidth") or None,
            )
        axes_info = snapshot.get("axes", {})
        axes.set_xlabel(axes_info.get("xlabel", "x"))
        axes.set_ylabel(axes_info.get("ylabel", "y"))
        axes.set_title(snapshot["title"])
        if axes_info.get("xscale") and axes_info.get("xscale") != "linear":
            axes.set_xscale(axes_info["xscale"])
        if axes_info.get("yscale") and axes_info.get("yscale") != "linear":
            axes.set_yscale(axes_info["yscale"])
        if axes_info.get("xmin") is not None or axes_info.get("xmax") is not None:
            axes.set_xlim(left=axes_info.get("xmin"), right=axes_info.get("xmax"))
        if axes_info.get("ymin") is not None or axes_info.get("ymax") is not None:
            axes.set_ylim(bottom=axes_info.get("ymin"), top=axes_info.get("ymax"))
        if axes_info.get("xgrid"):
            axes.grid(True, axis="x")
        if axes_info.get("ygrid"):
            axes.grid(True, axis="y")
        if len(snapshot["traces"]) > 1:
            axes.legend()
        return figure

    def _default_figure_size_inches(self):
        return tuple(float(value) for value in plt.rcParams.get("figure.figsize", (6.4, 4.8)))

    def _trace_x_expression(self, trace):
        if trace["x_name"] is None:
            return f"np.arange(len(np.asarray({trace['y_name']})))"
        return f"np.asarray({trace['x_name']})"

    def _trace_y_expression(self, trace):
        return f"np.asarray({trace['y_name']})"

    def _table_object_name(self, object_or_name):
        if isinstance(object_or_name, str):
            return object_or_name
        if hasattr(object_or_name, "name"):
            return object_or_name.name
        raise TypeError(f"{object_or_name!r} is not Hyde-managed array-backed data")

    def _figure_function_arguments(self, figure):
        arguments = []
        seen = set()
        for trace in figure["traces"]:
            for name in (trace.get("x_name"), trace.get("y_name")):
                if name and name not in seen:
                    seen.add(name)
                    arguments.append(name)
        return arguments

    def _invoke_entry_point(self, func):
        signature = inspect.signature(func)
        kwargs = {}
        for name, parameter in signature.parameters.items():
            if parameter.kind not in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                continue
            if name in self.namespace:
                kwargs[name] = self.namespace[name]
                continue
            if parameter.default is inspect._empty:
                raise TypeError(f"Entry point {func.__name__} requires {name!r} in the Hyde namespace")
        return func(**kwargs)

    def _load_master_procedure(self):
        if self.project_root is None:
            return
        master_path = Path(self.project_root) / "procedures" / "master.py"
        if not master_path.exists():
            return
        self._exec_code_in_namespace(master_path, self.namespace)

    def _load_callable(self, path, function_name):
        module = self._exec_script_module(path)
        function = getattr(module, function_name)
        if not callable(function):
            raise TypeError(f"{function_name} in {path} is not callable")
        return function

    def _exec_script_module(self, path):
        path = self._resolve_script_path(path)
        module = types.ModuleType(f"hyde_script_{uuid.uuid4().hex}")
        module.__file__ = str(path)
        module.__dict__.update(self.namespace)
        self._exec_code_in_namespace(path, module.__dict__)
        sys.modules[module.__name__] = module
        return module

    def _resolve_script_path(self, path):
        path = Path(path)
        if not path.is_absolute() and self.project_root is not None:
            path = Path(self.project_root) / path
        return path

    def _exec_code_in_namespace(self, path, namespace):
        path = self._resolve_script_path(path)
        code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
        previous_file = namespace.get("__file__")
        namespace["__file__"] = str(path)
        with self.modulewatcher.lock:
            with self._script_working_directory(path.parent):
                exec(code, namespace, namespace)
        if previous_file is None:
            namespace.pop("__file__", None)
        else:
            namespace["__file__"] = previous_file

    @contextmanager
    def _script_working_directory(self, path):
        cwd = os.getcwd()
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(cwd)


def fit_parameter_defaults(function):
    signature = inspect.signature(function)
    defaults = {}
    parameters = list(signature.parameters.values())[1:]
    for parameter in parameters:
        default = parameter.default if parameter.default is not inspect._empty else 1.0
        defaults[parameter.name] = {
            "value": float(default),
            "vary": True,
        }
    return defaults
