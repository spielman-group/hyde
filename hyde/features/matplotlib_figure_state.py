"""Figure IR authority.

The single owner of figure IR: normalization entry points, validation, action
application, and lowering to matplotlib Python. The state shape it operates on
lives in `matplotlib_figure_schema`.
"""

import copy


from hyde.features.base import ordered_unique
from hyde.features.matplotlib_figure_schema import (
    _AXIS_SIDE_TO_AXIS,
    _MIRROR_SIDE,
    _PRIMARY_SIDE,
    deep_merge_dict,
    default_axis_side_state,
    default_axis_state,
    default_subplot_margins,
    normalize_axis_side_state,
    normalize_axis_state,
    normalize_subplot_margins,
    operand_names,
    operand_to_python,
    sync_legacy_subplot_axis_fields,
)


class FigureIRAuthority:
    feature_name = "figure_ir"

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "settings": {"title": None, "figsize": None},
            "layout": {"kind": "single_subplot", "subplots": []},
            "opaque_nodes": [],
        }

    @classmethod
    def normalize_state(cls, state):
        normalized = copy.deepcopy(cls.default_state())
        if state:
            normalized["feature"] = state.get("feature", normalized["feature"])
            settings = state.get("settings", {})
            if isinstance(settings, dict):
                normalized["settings"].update(settings)
            layout = state.get("layout", {})
            if isinstance(layout, dict):
                normalized["layout"]["kind"] = str(layout.get("kind", normalized["layout"]["kind"]))
                subplots = layout.get("subplots", [])
                normalized["layout"]["subplots"] = [
                    cls._normalize_subplot(subplot, index)
                    for index, subplot in enumerate(subplots)
                ]
            opaque_nodes = state.get("opaque_nodes", [])
            normalized["opaque_nodes"] = [cls._normalize_opaque_node(node) for node in opaque_nodes]
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
            "margins": default_subplot_margins(),
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
                    "subplot_code": str(subplot.get("subplot_code", normalized["subplot_code"])),
                    "legend": bool(subplot.get("legend", normalized["legend"])),
                }
            )
            for field in ("title", "xlabel", "ylabel"):
                value = subplot.get(field)
                normalized[field] = None if value in (None, "") else str(value)
            for field in ("x_limits", "y_limits"):
                value = subplot.get(field)
                normalized[field] = None if value in (None, []) else tuple(value)
            normalized["margins"] = normalize_subplot_margins(subplot.get("margins"))
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
                "x": normalize_axis_state("x", axes.get("x"), legacy_label=normalized["xlabel"], legacy_limits=normalized["x_limits"]),
                "y": normalize_axis_state("y", axes.get("y"), legacy_label=normalized["ylabel"], legacy_limits=normalized["y_limits"]),
            }
            axis_sides = dict(subplot.get("axis_sides", {}) or {})
            normalized["axis_sides"] = {
                side: normalize_axis_side_state(side, axis_sides.get(side))
                for side in ("bottom", "top", "left", "right")
            }
        else:
            normalized["margins"] = normalize_subplot_margins(None)
            normalized["axes"] = {
                "x": normalize_axis_state("x", None),
                "y": normalize_axis_state("y", None),
            }
            normalized["axis_sides"] = {
                side: normalize_axis_side_state(side, None)
                for side in ("bottom", "top", "left", "right")
            }
        return sync_legacy_subplot_axis_fields(normalized)

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
            if margins["left"] is not None and margins["right"] is not None and margins["left"] >= margins["right"]:
                raise ValueError("Subplot left margin must be smaller than right.")
            if margins["bottom"] is not None and margins["top"] is not None and margins["bottom"] >= margins["top"]:
                raise ValueError("Subplot bottom margin must be smaller than top.")
            for axis_name in ("x", "y"):
                axis_state = subplot["axes"][axis_name]
                if axis_state["scale_mode"] not in {"linear", "log", "log2"}:
                    raise ValueError(f"Unsupported {axis_name}-axis scale mode: {axis_state['scale_mode']!r}.")
                if axis_state["range"]["limit_mode"]["min"] not in {"auto", "manual"}:
                    raise ValueError("Axis minimum mode must be 'auto' or 'manual'.")
                if axis_state["range"]["limit_mode"]["max"] not in {"auto", "manual"}:
                    raise ValueError("Axis maximum mode must be 'auto' or 'manual'.")
                limits = axis_state["range"]["limits"]
                if limits is not None:
                    if axis_state["range"]["limit_mode"]["min"] == "manual" and limits[0] is None:
                        raise ValueError("Manual axis minimum requires a numeric limit.")
                    if axis_state["range"]["limit_mode"]["max"] == "manual" and limits[1] is None:
                        raise ValueError("Manual axis maximum requires a numeric limit.")
                    if limits[0] is not None and limits[1] is not None and limits[0] >= limits[1]:
                        raise ValueError("Axis limits must be strictly increasing.")
                    if axis_state["scale_mode"] in {"log", "log2"}:
                        if (limits[0] is not None and limits[0] <= 0) or (limits[1] is not None and limits[1] <= 0):
                            raise ValueError("Log axes require positive limits.")
                if (
                    axis_state["ticks"]["major"]["labels"] is not None
                    and axis_state["ticks"]["major"]["positions"] is not None
                    and len(axis_state["ticks"]["major"]["labels"]) != len(axis_state["ticks"]["major"]["positions"])
                ):
                    raise ValueError("Manual tick labels must match manual positions.")
                if axis_state["ticks"]["direction"] not in {"inside", "outside", "both"}:
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
            subplot["axes"][axis_name]["range"]["limits"] = (float(action.get("min")), float(action.get("max")))
            subplot["axes"][axis_name]["range"]["limit_mode"] = {"min": "manual", "max": "manual"}
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
                axis_state = default_axis_state(axis_name)
            deep_merge_dict(axis_state, action.get("state"))
            subplot["axes"][axis_name] = axis_state
        elif action_type == "set_axis_side_state":
            side = str(action.get("side", ""))
            if side not in _AXIS_SIDE_TO_AXIS:
                raise ValueError(f"Unsupported figure axis side: {side!r}.")
            side_state = copy.deepcopy(subplot["axis_sides"][side])
            if action.get("replace"):
                side_state = default_axis_side_state(side)
            deep_merge_dict(side_state, action.get("state"))
            subplot["axis_sides"][side] = side_state
        elif action_type == "set_subplot_margins":
            margins = copy.deepcopy(subplot["margins"])
            if action.get("replace"):
                margins = default_subplot_margins()
            deep_merge_dict(margins, action.get("state"))
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
                    "alpha", "color", "drawstyle", "linestyle", "linewidth", "marker",
                    "markeredgecolor", "markeredgewidth", "markerfacecolor", "markersize", "visible",
                ):
                    trace["kwargs"].pop(key, None)
            for key in (
                "alpha", "color", "drawstyle", "label", "linestyle", "linewidth", "marker",
                "markeredgecolor", "markeredgewidth", "markerfacecolor", "markersize", "visible",
            ):
                if key in style:
                    trace["kwargs"][key] = style[key]
        elif action_type == "set_trace":
            trace_id = str(action.get("trace_id") or "")
            if not trace_id:
                raise ValueError("Figure trace edits require trace_id.")
            traces = subplot["traces"]
            trace_index = next((index for index, trace in enumerate(traces) if trace["id"] == trace_id), None)
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
        sync_legacy_subplot_axis_fields(subplot)
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
                names.extend(operand_names(trace["x_source"]))
                names.extend(operand_names(trace["y_source"]))
        return tuple(ordered_unique(names))

    @classmethod
    def _lowering_defaults(cls, normalized, context):
        defaults = dict((context or {}).get("figure_defaults", {}) or {})
        default_ir = defaults.get("figure_ir")
        if default_ir is None and ("layout" in defaults or "settings" in defaults):
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
        x_source = operand_to_python(trace["x_source"])
        y_source = operand_to_python(trace["y_source"])
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
        direction_map = {"inside": "in", "outside": "out", "both": "inout"}
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
            default_side_state = None if default_subplot is None else default_subplot["axis_sides"][side]
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
                lines.append(f"ax.spines[{side!r}].set_position(('outward', {side_state['offset']!r}))")
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
                lines.append(f"ax.{position_method}.label.set_linespacing({label['line_spacing']!r})")
            if label["position_mode"] == "manual" and label["position"] is not None:
                coord_name = f"_hyde_{axis_name}_label_coords"
                lines.append(f"{coord_name} = ax.{position_method}.label.get_position()")
                if axis_name == "x":
                    lines.append(f"ax.{position_method}.set_label_coords({label['position']!r}, {coord_name}[1])")
                else:
                    lines.append(f"ax.{position_method}.set_label_coords({coord_name}[0], {label['position']!r})")
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
            lines.append(f"ax.{position_method}.label.set_linespacing({label['line_spacing']!r})")
        if label["position_mode"] == "manual" and label["position"] is not None:
            coord_name = f"_hyde_{axis_name}_label_coords"
            lines.append(f"{coord_name} = ax.{position_method}.label.get_position()")
            if axis_name == "x":
                lines.append(f"ax.{position_method}.set_label_coords({label['position']!r}, {coord_name}[1])")
            else:
                lines.append(f"ax.{position_method}.set_label_coords({coord_name}[0], {label['position']!r})")
        if label["offset"] != default_label["offset"]:
            lines.append(f"ax.{position_method}.labelpad = {label['offset']!r}")
        return lines

    @classmethod
    def _range_lines(cls, axis_name, axis_state, default_axis_state=None):
        if default_axis_state is not None and axis_state["range"] == default_axis_state["range"]:
            return []
        lines = []
        range_state = axis_state["range"]
        limits = range_state["limits"]
        limit_mode = range_state["limit_mode"]
        lower_name, upper_name = (("left", "right") if axis_name == "x" else ("bottom", "top"))
        if limits is not None and limit_mode["min"] == "manual" and limit_mode["max"] == "manual":
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
            default_draw_on_top = any(side_state["draw_on_top"] for side_state in default_subplot["axis_sides"].values())
        current_draw_on_top = any(side_state["draw_on_top"] for side_state in subplot["axis_sides"].values())
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
            lines.append(f"ax.{axis_name}axis.set_major_locator(mticker.FixedLocator({major['positions']!r}))")
            if major["labels"] is not None:
                lines.append(f"ax.{axis_name}axis.set_major_formatter(mticker.FixedFormatter({major['labels']!r}))")
        elif major["mode"] == "manual" and major["step"] is not None:
            needs_ticker = True
            lines.append(f"ax.{axis_name}axis.set_major_locator(mticker.MultipleLocator({major['step']!r}))")
        elif major["count"] is not None:
            needs_ticker = True
            lines.append(f"ax.{axis_name}axis.set_major_locator(mticker.MaxNLocator(nbins={major['count']!r}))")
        if axis_state["ticks"]["minor"]["visible"]:
            needs_ticker = True
            if axis_state["scale_mode"] in {"log", "log2"}:
                base = 2 if axis_state["scale_mode"] == "log2" else 10
                lines.append(f"ax.{axis_name}axis.set_minor_locator(mticker.LogLocator(base={base!r}, subs='auto'))")
            else:
                lines.append(f"ax.{axis_name}axis.set_minor_locator(mticker.AutoMinorLocator())")
        return needs_ticker, lines

    @classmethod
    def _tick_label_style_lines(cls, axis_name, subplot, default_subplot=None):
        lines = []
        axis_accessor = f"ax.{axis_name}axis"
        for side, label_attr in ((_PRIMARY_SIDE[axis_name], "label1"), (_MIRROR_SIDE[axis_name], "label2")):
            side_state = subplot["axis_sides"][side]
            default_side_state = None if default_subplot is None else default_subplot["axis_sides"][side]
            operations = []
            if side_state["tick_label_color"] is not None and (
                default_side_state is None or default_side_state["tick_label_color"] != side_state["tick_label_color"]
            ):
                operations.append(f"_hyde_tick.{label_attr}.set_color({side_state['tick_label_color']!r})")
            rotation = side_state["tick_label_rotation"]
            default_rotation = 0.0 if default_side_state is None else default_side_state["tick_label_rotation"]
            if rotation != default_rotation:
                operations.append(f"_hyde_tick.{label_attr}.set_rotation({rotation!r})")
            if not operations:
                continue
            lines.append(f"for _hyde_tick in {axis_accessor}.get_major_ticks() + {axis_accessor}.get_minor_ticks():")
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
        default_settings = {} if default_ir is None else dict(default_ir.get("settings", {}) or {})
        title = normalized["settings"]["title"]
        figsize = normalized["settings"]["figsize"]
        figure_args = []
        if title and title != default_settings.get("title"):
            figure_args.append(repr(title))
        if figsize is not None and figsize != default_settings.get("figsize"):
            figure_args.append(f"figsize={figsize!r}")
        # A named figure that still exists comes back from plt.figure() with
        # its old contents, and this source replaces a figure rather than
        # drawing over it. matplotlib's own clear kwarg says exactly that in
        # one line, and it calls FigureHyde.clear(), which empties the
        # figure's Hyde bookkeeping with it so what follows is stamped as a
        # first draw. Generated source is read and copied, so it spells the
        # intent the way matplotlib does.
        #
        # An unnamed plt.figure() constructs a new figure on every call, so
        # there is never a previous one to replace and nothing to clear.
        if figure_args:
            figure_args.append("clear=True")
        lines = [f"fig = plt.figure({', '.join(figure_args)})"]
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
        default_margins = {} if default_subplot is None else dict(default_subplot.get("margins", {}) or {})
        for side in ("left", "bottom", "right", "top"):
            value = subplot["margins"].get(side)
            if value is None:
                continue
            if default_subplot is not None and value == default_margins.get(side):
                continue
            margin_kwargs.append(f"{side}={value!r}")
        if margin_kwargs:
            lines.append(f"fig.subplots_adjust({', '.join(margin_kwargs)})")
        if subplot["title"] and (default_subplot is None or subplot["title"] != default_subplot["title"]):
            lines.append(f"ax.set_title({subplot['title']!r})")
        for trace in subplot["traces"]:
            lines.append(
                cls._plot_call(
                    trace,
                    default_style=cls._trace_default_style(trace_styles, subplot["id"], trace["id"]),
                )
            )
        if subplot["legend"] and (default_subplot is None or subplot["legend"] != default_subplot["legend"]):
            lines.append("ax.legend()")
        lines.extend(cls._axis_layer_lines(subplot, default_subplot=default_subplot))
        for axis_name in ("x", "y"):
            axis_state = subplot["axes"][axis_name]
            default_axis_state = None if default_subplot is None else default_subplot["axes"][axis_name]
            lines.extend(cls._scale_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            lines.extend(cls._label_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            lines.extend(cls._range_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            tick_params_line = cls._tick_params_line(axis_name, subplot, default_subplot=default_subplot)
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
            lines.extend(cls._tick_label_style_lines(axis_name, subplot, default_subplot=default_subplot))
            lines.extend(cls._grid_lines(axis_name, axis_state, default_axis_state=default_axis_state))
            lines.extend(cls._zero_line_lines(axis_name, axis_state, default_axis_state=default_axis_state))
        if needs_ticker_import:
            lines.insert(1, "import matplotlib.ticker as mticker")
        for opaque in subplot["opaque_nodes"]:
            if opaque["source"]:
                lines.extend(opaque["source"].splitlines())
        lines.append("fig.show()")
        return "\n".join(lines)


def figure_ir_default_state():
    return FigureIRAuthority.default_state()


def figure_ir_apply_title(figure_ir, title):
    normalized = FigureIRAuthority.normalize_state(figure_ir)
    normalized["settings"]["title"] = None if title in (None, "") else str(title)
    return FigureIRAuthority.validate_state(normalized)


def figure_ir_clear_layout(figure_ir):
    """Drop everything a cleared figure no longer draws.

    A figure keeps its name and its size across a clear, so the settings
    survive and the drawn content does not.
    """
    normalized = FigureIRAuthority.normalize_state(figure_ir)
    normalized["layout"]["subplots"] = []
    normalized["opaque_nodes"] = []
    return FigureIRAuthority.validate_state(normalized)


def default_subplot_layout_state():
    return FigureIRAuthority.validate_state({"layout": {"subplots": [{}]}})["layout"]["subplots"][0]


def merge_defaulted_value(current, default, baseline):
    if isinstance(baseline, dict) and isinstance(current, dict):
        merged = {}
        keys = set(baseline) | set(current) | set(default or {})
        for key in keys:
            merged[key] = merge_defaulted_value(
                current.get(key),
                None if not isinstance(default, dict) else default.get(key),
                baseline.get(key),
            )
        return merged
    if current != baseline:
        return copy.deepcopy(current)
    if default is not None:
        return copy.deepcopy(default)
    return copy.deepcopy(current)


def figure_ir_with_defaults(figure_ir, figure_defaults):
    if figure_ir is None:
        return None
    if not isinstance(figure_defaults, dict):
        return FigureIRAuthority.validate_state(figure_ir)
    merged = FigureIRAuthority.validate_state(figure_ir)
    defaults = FigureIRAuthority.validate_state(figure_defaults)
    baseline_subplot = default_subplot_layout_state()
    default_subplots = {
        subplot["id"]: subplot for subplot in defaults.get("layout", {}).get("subplots", [])
    }
    for subplot in merged.get("layout", {}).get("subplots", []):
        default_subplot = default_subplots.get(subplot["id"])
        if default_subplot is None:
            continue
        for axis_name in ("x", "y"):
            subplot["axes"][axis_name] = merge_defaulted_value(
                subplot["axes"][axis_name],
                default_subplot["axes"][axis_name],
                baseline_subplot["axes"][axis_name],
            )
        for side in ("bottom", "top", "left", "right"):
            subplot["axis_sides"][side] = merge_defaulted_value(
                subplot["axis_sides"][side],
                default_subplot["axis_sides"][side],
                baseline_subplot["axis_sides"][side],
            )
        subplot["margins"] = merge_defaulted_value(
            subplot.get("margins", {}),
            default_subplot.get("margins", {}),
            baseline_subplot.get("margins", {}),
        )
    return merged
