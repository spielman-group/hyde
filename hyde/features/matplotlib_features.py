import copy
import numbers

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
    raise ValueError(f"Unsupported figure operand kind: {kind!r}.")


def _operand_names(operand):
    if operand is None:
        return []
    if operand.get("kind") == "name":
        return [operand["value"]]
    return []


def _macro_ready_lines(lines):
    return [line for line in lines if line.strip() != "fig.canvas.draw_idle()"]


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

        if command == "create" and not normalized["items"]:
            raise ValueError("Figure creation requires at least one plotted object.")
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
            return "hyde.recreation_registry.publish_figure_macro_registry()"
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
            "xlabel": None,
            "ylabel": None,
            "x_limits": None,
            "y_limits": None,
            "legend": False,
            "traces": [],
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
            normalized["traces"] = [
                cls._normalize_trace(trace, trace_index)
                for trace_index, trace in enumerate(subplot.get("traces", []))
            ]
            normalized["opaque_nodes"] = [
                cls._normalize_opaque_node(node)
                for node in subplot.get("opaque_nodes", [])
            ]
        return normalized

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
            axis = str(action.get("axis", ""))
            if axis not in {"x", "y"}:
                raise ValueError("Figure axis limit edits require axis='x' or axis='y'.")
            limits = (action.get("min"), action.get("max"))
            subplot[f"{axis}_limits"] = limits
        elif action_type == "set_axis_label":
            axis = str(action.get("axis", ""))
            if axis not in {"x", "y"}:
                raise ValueError("Figure axis label edits require axis='x' or axis='y'.")
            subplot[f"{axis}label"] = None if action.get("label") in (None, "") else str(action.get("label"))
        elif action_type in {"set_subplot_title", "set_figure_title"}:
            title = None if action.get("title") in (None, "") else str(action.get("title"))
            subplot["title"] = title
            normalized["settings"]["title"] = title
        elif action_type == "set_legend_visible":
            subplot["legend"] = bool(action.get("visible"))
        elif action_type == "set_trace_style":
            trace = cls._resolve_trace(subplot, action.get("trace_id"))
            style = dict(action.get("style", {}) or {})
            for key in ("color", "marker", "linestyle", "linewidth", "label"):
                if key in style:
                    trace["kwargs"][key] = style[key]
        else:
            raise ValueError(f"Unsupported figure IR action: {action_type!r}.")

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
    def _plot_call(cls, trace):
        arguments = []
        x_source = _operand_to_python(trace["x_source"])
        y_source = _operand_to_python(trace["y_source"])
        if x_source:
            arguments.append(x_source)
        arguments.append(y_source)
        kwargs = ", ".join(
            f"{name}={value!r}"
            for name, value in trace["kwargs"].items()
            if value is not None
        )
        if kwargs:
            arguments.append(kwargs)
        return f"ax.plot({', '.join(arguments)})"

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        title = normalized["settings"]["title"]
        figsize = normalized["settings"]["figsize"]
        figure_args = []
        if title:
            figure_args.append(repr(title))
        if figsize is not None:
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
        lines.append(f"ax = fig.add_subplot({subplot['subplot_code']})")
        if subplot["title"]:
            lines.append(f"ax.set_title({subplot['title']!r})")
        if subplot["xlabel"]:
            lines.append(f"ax.set_xlabel({subplot['xlabel']!r})")
        if subplot["ylabel"]:
            lines.append(f"ax.set_ylabel({subplot['ylabel']!r})")
        for trace in subplot["traces"]:
            lines.append(cls._plot_call(trace))
        if subplot["legend"]:
            lines.append("ax.legend()")
        if subplot["x_limits"] is not None:
            lines.append(f"ax.set_xlim({subplot['x_limits'][0]!r}, {subplot['x_limits'][1]!r})")
        if subplot["y_limits"] is not None:
            lines.append(f"ax.set_ylim({subplot['y_limits'][0]!r}, {subplot['y_limits'][1]!r})")
        for opaque in subplot["opaque_nodes"]:
            if opaque["source"]:
                lines.extend(opaque["source"].splitlines())
        lines.append("fig.show()")
        return "\n".join(lines)

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        del context
        normalized = cls.validate_state(state)
        parameters = ", ".join(cls.tracked_names(normalized))
        body_lines = _macro_ready_lines(cls.state_to_python(normalized).splitlines())
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
        "title": title,
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
    if normalized["layout"]["subplots"]:
        normalized["layout"]["subplots"][0]["title"] = normalized["settings"]["title"]
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
