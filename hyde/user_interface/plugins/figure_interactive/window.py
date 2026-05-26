import base64
import copy
from dataclasses import dataclass, replace as dataclass_replace
import logging
import re

from qtutils import inmain_decorator
from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.matplotlib_features import (
    MatplotlibCodec,
    figure_graphics_export_command_source,
    figure_ir_apply_title,
    figure_ir_default_state,
    figure_patch_source,
    macro_ready_lines,
)
from hyde.user_interface.base_hyde_widgets import HydeInteractiveWidget
from hyde.user_interface.shared.core import HydeIR, HydeIRDiff
from hyde.user_interface.shared.figure import (
    FigureDisplayHelper,
    figure_ir_with_defaults,
    supported_trace_style_state,
    trace_style_defaults_by_subplot,
)
from hyde.user_interface.shared.plugin import (
    apply_saveable_window_state,
)
from hyde.user_interface.shared.project import MacroStoreError

LOGGER = logging.getLogger("hyde")
_DEFAULT_FIGURE_LABEL_RE = re.compile(r"^Figure\s+(\d+)$")


def _canonicalize_figure_window_name(name, fallback_number):
    text = str(name or "").strip()
    if not text:
        return f"Figure{int(fallback_number)}"
    match = _DEFAULT_FIGURE_LABEL_RE.fullmatch(text)
    if match is not None:
        return f"Figure{match.group(1)}"
    return text


def _normalize_optional_text(value):
    if value in (None, ""):
        return None
    return str(value)


def _normalize_figure_number(value):
    if value in (None, ""):
        return None
    return int(value)


def _normalize_size_inches(value):
    if value in (None, ""):
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("Figure export size_inches must be a length-2 sequence.")
    normalized = (float(value[0]), float(value[1]))
    if normalized[0] <= 0 or normalized[1] <= 0:
        raise ValueError("Figure export size_inches values must be positive.")
    return normalized


def _normalize_figure_defaults(value):
    if not isinstance(value, dict):
        return None
    return copy.deepcopy(dict(value))


def _normalize_optional_mapping(value):
    if not isinstance(value, dict):
        return {}
    return copy.deepcopy(dict(value))


def _normalize_figure_state(value):
    candidate = figure_ir_default_state() if value is None else copy.deepcopy(value)
    return MatplotlibCodec.validate_state(candidate)


def _ensure_single_creation_subplot(figure_state):
    subplots = figure_state["layout"]["subplots"]
    if subplots:
        return subplots[0]
    subplot = {
        "id": "subplot0",
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
    figure_state["layout"]["subplots"] = [subplot]
    return subplot


def _figure_hyde_refresh_source(figure_name, *, use_bound_values=False):
    return (
        f"fig = hyde.get_figure({str(figure_name)!r})\n"
        f"hyde.refresh_figure(fig, use_bound_values={bool(use_bound_values)!r})"
    )


def _publish_figure_macros_source():
    return "hyde.recreation_registry.publish_registry('figure')"


def _figure_lookup_prelude_lines(figure_name, *, include_axes=False):
    lines = [f"fig = hyde.get_figure({str(figure_name)!r})"]
    if include_axes:
        lines.append("ax = fig.axes[0]")
    return lines


def _prepend_python_prelude(source, prelude_lines):
    lines = [str(line) for line in str(source or "").splitlines()]
    if not lines:
        return ""
    import_lines = []
    while lines and (
        lines[0].startswith("import ") or lines[0].startswith("from ")
    ):
        import_lines.append(lines.pop(0))
    return "\n".join(import_lines + list(prelude_lines) + lines)


def _figure_lookup_source(figure_name, source, *, include_axes=False):
    return _prepend_python_prelude(
        source,
        _figure_lookup_prelude_lines(figure_name, include_axes=include_axes),
    )


def _remove_only_trace_ids(source_state, target_state, *, refresh_trace_ids=()):
    if refresh_trace_ids:
        return ()
    source = MatplotlibCodec.validate_state(source_state)
    target = MatplotlibCodec.validate_state(target_state)
    source_subplots = list(source.get("layout", {}).get("subplots", ()) or ())
    target_subplots = list(target.get("layout", {}).get("subplots", ()) or ())
    if len(source_subplots) != 1 or len(target_subplots) != 1:
        return ()
    source_subplot = source_subplots[0]
    target_subplot = target_subplots[0]

    source_without_traces = dict(source_subplot)
    source_without_traces["traces"] = ()
    target_without_traces = dict(target_subplot)
    target_without_traces["traces"] = ()
    if source_without_traces != target_without_traces:
        return ()

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
            return ()
    if target_traces or not removed_trace_ids:
        return ()
    return tuple(removed_trace_ids)


def _figure_remove_traces_source(figure_name, trace_ids):
    joined_ids = ", ".join(repr(str(trace_id)) for trace_id in tuple(trace_ids or ()))
    return "\n".join(
        _figure_lookup_prelude_lines(figure_name)
        + [f"hyde.remove_traces(fig, {joined_ids})"]
    )


def _decorate_figure_source(
    body_lines,
    *,
    decorator,
    function_name,
    parameters,
    invoke=False,
    delete_after=False,
):
    lines = [str(decorator), f"def {function_name}({', '.join(parameters)}):"]
    lines.extend(f"    {line}" for line in body_lines)
    if invoke:
        lines.append(f"{function_name}({', '.join(parameters)})")
    if delete_after:
        lines.append(f"del {function_name}")
    return "\n".join(lines)


@dataclass(frozen=True)
class FigureIR(HydeIR):
    figure_state: dict | None = None
    figure_defaults: dict | None = None
    resolved_axis_limits: dict | None = None
    trace_styles: dict | None = None
    command: str = "create"
    figure_name: str | None = None
    figure_number: int | None = None
    use_bound_values: bool = False
    creation_x_name: str | None = None
    output_path: str | None = None
    output_format: str = "pdf"
    dpi: int = 300
    transparent: bool = False
    size_inches: tuple[float, float] | None = None

    VALID_COMMANDS = frozenset(
        {"create", "refresh", "publish_figure_macros", "close", "save_graphics"}
    )

    def __post_init__(self):
        object.__setattr__(self, "figure_state", _normalize_figure_state(self.figure_state))
        object.__setattr__(self, "figure_defaults", _normalize_figure_defaults(self.figure_defaults))
        object.__setattr__(
            self,
            "resolved_axis_limits",
            _normalize_optional_mapping(self.resolved_axis_limits),
        )
        object.__setattr__(
            self,
            "trace_styles",
            _normalize_optional_mapping(self.trace_styles),
        )
        object.__setattr__(self, "command", str(self.command or "create"))
        object.__setattr__(self, "figure_name", _normalize_optional_text(self.figure_name))
        object.__setattr__(self, "figure_number", _normalize_figure_number(self.figure_number))
        object.__setattr__(self, "use_bound_values", bool(self.use_bound_values))
        object.__setattr__(self, "creation_x_name", _normalize_optional_text(self.creation_x_name))
        object.__setattr__(self, "output_path", _normalize_optional_text(self.output_path))
        object.__setattr__(self, "output_format", str(self.output_format or "pdf"))
        object.__setattr__(self, "dpi", int(self.dpi))
        object.__setattr__(self, "transparent", bool(self.transparent))
        object.__setattr__(self, "size_inches", _normalize_size_inches(self.size_inches))

    @classmethod
    def from_snapshot(cls, snapshot):
        snapshot = dict(snapshot or {})
        figure_state = snapshot.get("figure_ir")
        if figure_state is None:
            return None
        return cls(
            figure_state=figure_state,
            figure_defaults=snapshot.get("figure_defaults"),
            resolved_axis_limits=snapshot.get("resolved_axis_limits"),
            trace_styles=snapshot.get("trace_styles"),
        )

    def debug_state(self):
        return {
            "figure_defaults": copy.deepcopy(self.figure_defaults),
            "resolved_axis_limits": copy.deepcopy(self.resolved_axis_limits),
            "trace_styles": copy.deepcopy(self.trace_styles),
            "command": self.command,
            "figure_name": self.figure_name,
            "figure_number": self.figure_number,
            "use_bound_values": self.use_bound_values,
            "creation_x_name": self.creation_x_name,
            "output_path": self.output_path,
            "output_format": self.output_format,
            "dpi": self.dpi,
            "transparent": self.transparent,
            "size_inches": self.size_inches,
            "figure_state": copy.deepcopy(self.figure_state),
        }

    def validate(self):
        if self.command not in self.VALID_COMMANDS:
            raise ValueError(f"Unsupported figure command: {self.command!r}.")
        if self.command == "refresh" and not self.figure_name:
            raise ValueError("Figure refresh requires figure_name.")
        if self.command == "close" and self.figure_number is None:
            raise ValueError("Figure close requires figure_number.")
        if self.command == "save_graphics":
            if not self.figure_name:
                raise ValueError("Figure save_graphics requires figure_name.")
            if not self.output_path:
                raise ValueError("Figure save_graphics requires output_path.")
            if self.dpi <= 0:
                raise ValueError("Figure save_graphics requires a positive dpi.")
        return self

    def normalized_state(self):
        return copy.deepcopy(self.figure_state)

    def tracked_names(self):
        return tuple(MatplotlibCodec.tracked_names(self.figure_state))

    def default_macro_name(self):
        return self.figure_state["settings"]["title"] or "Figure"

    def with_title(self, title):
        return dataclass_replace(
            self,
            figure_state=figure_ir_apply_title(self.figure_state, title),
            command="create",
        )

    def x_name(self):
        subplot = _ensure_single_creation_subplot(self.normalized_state())
        for trace in subplot["traces"]:
            source = trace.get("x_source")
            if isinstance(source, dict) and source.get("kind") == "name":
                return str(source["value"])
        return self.creation_x_name

    def with_x_name(self, x_name):
        updated = self.normalized_state()
        subplot = _ensure_single_creation_subplot(updated)
        normalized_x_name = _normalize_optional_text(x_name)
        operand = (
            None
            if normalized_x_name is None
            else {"kind": "name", "value": normalized_x_name}
        )
        for trace in subplot["traces"]:
            trace["x_source"] = copy.deepcopy(operand)
        return dataclass_replace(
            self,
            figure_state=updated,
            command="create",
            creation_x_name=normalized_x_name,
        )

    def with_items(self, names):
        updated = self.normalized_state()
        subplot = _ensure_single_creation_subplot(updated)
        x_name = self.x_name()
        subplot["traces"] = [
            {
                "id": f"trace{index}",
                "kind": "line",
                "x_source": (
                    None
                    if x_name in (None, "")
                    else {"kind": "name", "value": str(x_name)}
                ),
                "y_source": {"kind": "name", "value": str(name)},
                "kwargs": {"label": str(name)},
            }
            for index, name in enumerate(tuple(names or ()))
            if str(name)
        ]
        subplot["legend"] = len(subplot["traces"]) > 1
        return dataclass_replace(
            self,
            figure_state=updated,
            command="create",
            creation_x_name=x_name,
        )

    def with_figsize(self, width, height):
        updated = self.normalized_state()
        updated["settings"]["figsize"] = (float(width), float(height))
        return dataclass_replace(self, figure_state=updated, command="create")

    def with_refresh_figure(self, figure_name, *, use_bound_values=False):
        return dataclass_replace(
            self,
            command="refresh",
            figure_name=str(figure_name),
            use_bound_values=bool(use_bound_values),
        )

    def with_publish_figure_macros(self):
        return dataclass_replace(
            self,
            command="publish_figure_macros",
            figure_name=None,
            figure_number=None,
            use_bound_values=False,
        )

    def with_close_figure(self, figure_number):
        return dataclass_replace(
            self,
            command="close",
            figure_number=int(figure_number),
            figure_name=None,
            use_bound_values=False,
        )

    def with_save_graphics(
        self,
        output_path,
        *,
        figure_name=None,
        output_format="pdf",
        dpi=300,
        transparent=False,
        size_inches=None,
    ):
        resolved_figure_name = self.figure_name
        if figure_name not in (None, ""):
            resolved_figure_name = str(figure_name)
        if resolved_figure_name in (None, ""):
            resolved_figure_name = self.default_macro_name()
        return dataclass_replace(
            self,
            command="save_graphics",
            figure_name=resolved_figure_name,
            figure_number=None,
            use_bound_values=False,
            output_path=output_path,
            output_format=output_format,
            dpi=dpi,
            transparent=transparent,
            size_inches=size_inches,
        )

    def creation_body_lines(self):
        context = {}
        if self.figure_defaults is not None:
            context["figure_defaults"] = self.figure_defaults
        figure_state = self.normalized_state()
        _ensure_single_creation_subplot(figure_state)
        return MatplotlibCodec.state_to_python(
            figure_state,
            context=context or None,
        ).splitlines()

    def recreation_function_source(self, macro_name, *, name=None, register=True):
        figure_state = self.normalized_state()
        _ensure_single_creation_subplot(figure_state)
        if name not in (None, ""):
            figure_state = figure_ir_apply_title(figure_state, name)
        context = {}
        if self.figure_defaults is not None:
            context["figure_defaults"] = self.figure_defaults
        body_lines = macro_ready_lines(
            MatplotlibCodec.state_to_python(
                figure_state,
                context=context or None,
            ).splitlines()
        )
        return _decorate_figure_source(
            body_lines,
            decorator="@hyde.figure" if register else "@hyde.figure(register=False)",
            function_name=str(macro_name),
            parameters=MatplotlibCodec.tracked_names(figure_state),
        )

    def macro_source(self, macro_name):
        return self.recreation_function_source(macro_name)

    def current_diff(self, current_ir=None):
        resolved_current = self if current_ir is None else current_ir
        return FigureIRDiff.from_irs(self, resolved_current)

    def preview_source(self):
        context = {}
        if self.figure_defaults is not None:
            context["figure_defaults"] = self.figure_defaults
        return MatplotlibCodec.state_to_python(
            self._dispatched_state(),
            context=context or None,
        )

    def effective_state(self):
        return figure_ir_with_defaults(self._dispatched_state(), self.figure_defaults)

    def figure_title(self):
        return self.figure_state["settings"]["title"]

    def figure_size(self):
        return copy.deepcopy(self.figure_state["settings"]["figsize"])

    def subplot_ids(self):
        return tuple(
            subplot["id"] for subplot in self.figure_state["layout"]["subplots"]
        )

    def subplot_title(self, subplot_id=None):
        return self._subplot(subplot_id)["title"]

    def legend_visible(self, subplot_id=None):
        return bool(self._subplot(subplot_id)["legend"])

    def axis_label(self, axis, subplot_id=None):
        return self.axis_value(axis, "label", "text", subplot_id=subplot_id)

    def axis_limits(self, axis, subplot_id=None):
        return self.axis_value(axis, "range", "limits", subplot_id=subplot_id)

    def axis_limit_mode(self, axis, subplot_id=None):
        return self.axis_value(axis, "range", "limit_mode", subplot_id=subplot_id)

    def axis_scale(self, axis, subplot_id=None):
        return self.axis_value(axis, "scale_mode", subplot_id=subplot_id)

    def axis_value(self, axis, *path, subplot_id=None, default=None):
        value = self._value_from_path(
            self._effective_axis_state(axis, subplot_id),
            path,
            default=default,
        )
        return copy.deepcopy(value)

    def axis_side_value(self, side, *path, subplot_id=None, default=None):
        value = self._value_from_path(
            self._effective_axis_side_state(side, subplot_id),
            path,
            default=default,
        )
        return copy.deepcopy(value)

    def subplot_margin(self, side, *, subplot_id=None, default=None):
        subplot = self._effective_subplot(subplot_id)
        return copy.deepcopy(subplot.get("margins", {}).get(str(side), default))

    def resolved_limits(self, axis, subplot_id=None):
        subplot_id = self._resolve_subplot_id(subplot_id)
        return copy.deepcopy(
            self.resolved_axis_limits.get(subplot_id, {}).get(
                self._normalize_axis_name(axis)
            )
        )

    def trace_ids(self, subplot_id=None):
        return tuple(trace["id"] for trace in self._subplot(subplot_id)["traces"])

    def trace(self, trace_id, subplot_id=None):
        return copy.deepcopy(self._trace(trace_id, subplot_id))

    def trace_style(self, trace_id, name, subplot_id=None, default=None):
        trace_key = self._trace_style_key(trace_id, subplot_id)
        trace_style_states = self._trace_style_states_for_state(self.figure_state)
        if trace_key in trace_style_states:
            return copy.deepcopy(trace_style_states[trace_key].get(str(name), default))
        trace = self._trace(trace_id, subplot_id)
        return copy.deepcopy(trace["kwargs"].get(str(name), default))

    def supported_trace_records(self):
        return FigureDisplayHelper().supported_trace_records(self.figure_state)

    def has_supported_traces(self):
        return bool(self.supported_trace_records())

    def set_figure_title(self, title, *, subplot_id=None):
        del subplot_id
        return dataclass_replace(
            self,
            figure_state=self._update_state({"type": "set_figure_title", "title": title}),
        )

    def set_subplot_title(self, title, *, subplot_id=None):
        return dataclass_replace(
            self,
            figure_state=self._update_state(
                {
                    "type": "set_subplot_title",
                    "subplot_id": self._resolve_subplot_id(subplot_id),
                    "title": title,
                }
            ),
        )

    def set_legend_visible(self, visible, *, subplot_id=None):
        return dataclass_replace(
            self,
            figure_state=self._update_state(
                {
                    "type": "set_legend_visible",
                    "subplot_id": self._resolve_subplot_id(subplot_id),
                    "visible": bool(visible),
                }
            ),
        )

    def set_axis_label(self, axis, label, *, subplot_id=None):
        updated_state = self._update_state(
            {
                "type": "set_axis_label",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "axis": self._normalize_axis_name(axis),
                "label": label,
            }
        )
        return dataclass_replace(self, figure_state=updated_state)

    def set_axis_limits(self, axis, minimum, maximum, *, subplot_id=None):
        updated_state = self._update_state(
            {
                "type": "set_axis_limits",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "axis": self._normalize_axis_name(axis),
                "min": minimum,
                "max": maximum,
            }
        )
        return dataclass_replace(self, figure_state=updated_state)

    def set_xlim(self, left, right, *, subplot_id=None):
        return self.set_axis_limits("x", left, right, subplot_id=subplot_id)

    def set_ylim(self, bottom, top, *, subplot_id=None):
        return self.set_axis_limits("y", bottom, top, subplot_id=subplot_id)

    def set_axis_state(self, axis, state, *, subplot_id=None, replace=False):
        updated_state = self._update_state(
            {
                "type": "set_axis_state",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "axis": self._normalize_axis_name(axis),
                "state": copy.deepcopy(state),
                "replace": bool(replace),
            }
        )
        return dataclass_replace(self, figure_state=updated_state)

    def set_axis_side_state(self, side, state, *, subplot_id=None, replace=False):
        updated_state = self._update_state(
            {
                "type": "set_axis_side_state",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "side": self._normalize_side_name(side),
                "state": copy.deepcopy(state),
                "replace": bool(replace),
            }
        )
        return dataclass_replace(self, figure_state=updated_state)

    def set_subplot_margins(self, *, subplot_id=None, replace=False, **state):
        updated_state = self._update_state(
            {
                "type": "set_subplot_margins",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "state": copy.deepcopy(state),
                "replace": bool(replace),
            }
        )
        return dataclass_replace(self, figure_state=updated_state)

    def subplots_adjust(
        self,
        *,
        left=None,
        bottom=None,
        right=None,
        top=None,
        subplot_id=None,
        replace=False,
    ):
        state = {
            key: value
            for key, value in (
                ("left", left),
                ("bottom", bottom),
                ("right", right),
                ("top", top),
            )
            if value is not None
        }
        return self.set_subplot_margins(
            subplot_id=subplot_id,
            replace=replace,
            **state,
        )

    def set_trace_style(
        self,
        trace_id,
        *,
        subplot_id=None,
        replace=False,
        style=None,
        **kwargs,
    ):
        merged_style = dict(style or {})
        merged_style.update(kwargs)
        updated_state = self._update_state(
            {
                "type": "set_trace_style",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "trace_id": str(trace_id),
                "style": merged_style,
                "replace": bool(replace),
            }
        )
        return dataclass_replace(self, figure_state=updated_state)

    def set_trace(self, trace_id, trace=None, *, subplot_id=None):
        updated_state = self._update_state(
            {
                "type": "set_trace",
                "subplot_id": self._resolve_subplot_id(subplot_id),
                "trace_id": str(trace_id),
                "trace": copy.deepcopy(trace),
            }
        )
        return dataclass_replace(self, figure_state=updated_state)

    def remove_trace(self, trace_id, *, subplot_id=None):
        return self.set_trace(trace_id, None, subplot_id=subplot_id)

    def remove_traces(self, trace_ids, *, subplot_id=None):
        updated_ir = self
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        normalized_ids = {
            str(trace_id)
            for trace_id in tuple(trace_ids or ())
            if str(trace_id or "").strip()
        }
        for trace_id in tuple(self.trace_ids(resolved_subplot_id)):
            if trace_id not in normalized_ids:
                continue
            updated_ir = updated_ir.remove_trace(
                trace_id,
                subplot_id=resolved_subplot_id,
            )
        return updated_ir

    def attribute_path_trace(
        self,
        component,
        *,
        subplot_id=None,
        trace_id=None,
        id_suffix="",
        root_names=(),
    ):
        entry = self._find_attribute_path_trace(
            component,
            subplot_id=subplot_id,
            trace_id=trace_id,
            id_suffix=id_suffix,
            root_names=root_names,
        )
        return copy.deepcopy(entry)

    def set_attribute_path_lines(
        self,
        display_name=None,
        *,
        components=(),
        root_name=None,
        x_name=None,
        subplot_id=None,
        owner_root_names=(),
    ):
        updated_ir = self
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        normalized_display_name = self._normalize_optional_text(display_name)
        normalized_root_name = (
            self._normalize_optional_text(root_name) or normalized_display_name
        )
        normalized_owner_roots = self._normalized_root_names(
            owner_root_names,
            normalized_display_name,
            normalized_root_name,
        )
        for component_spec in self._normalized_attribute_path_components(components):
            current_entry = updated_ir._find_attribute_path_trace(
                component_spec["path"],
                subplot_id=resolved_subplot_id,
                id_suffix=component_spec["id_suffix"],
                root_names=normalized_owner_roots,
            )
            if not component_spec["visible"] or normalized_display_name is None:
                if current_entry is not None:
                    updated_ir = updated_ir.set_trace(
                        current_entry["trace_id"],
                        None,
                        subplot_id=resolved_subplot_id,
                    )
                continue
            desired_trace_id = f"{normalized_display_name}{component_spec['id_suffix']}"
            if (
                current_entry is not None
                and current_entry["trace_id"] != desired_trace_id
            ):
                updated_ir = updated_ir.set_trace(
                    current_entry["trace_id"],
                    None,
                    subplot_id=resolved_subplot_id,
                )
            updated_ir = updated_ir.set_trace(
                desired_trace_id,
                updated_ir._attribute_path_line_trace(
                    trace_id=desired_trace_id,
                    root_name=normalized_root_name,
                    path=component_spec["path"],
                    x_name=x_name,
                    label=component_spec["label"],
                    style=component_spec["style"],
                ),
                subplot_id=resolved_subplot_id,
            )
        return updated_ir

    def _update_state(self, action):
        return MatplotlibCodec.update_state(self.figure_state, action)

    def _trace_style_states_for_state(self, state):
        trace_style_states = {}
        trace_style_defaults = trace_style_defaults_by_subplot(self.figure_defaults)
        live_trace_styles = copy.deepcopy(self.trace_styles) or {}
        for index, record in enumerate(FigureDisplayHelper().supported_trace_records(state)):
            trace_key = (record["subplot_id"], record["trace_id"])
            default_trace = trace_style_defaults.get(record["subplot_id"], {}).get(
                record["trace_id"]
            )
            live_style = live_trace_styles.get(record["subplot_id"], {}).get(
                record["trace_id"]
            )
            trace_style_states[trace_key] = supported_trace_style_state(
                record["trace"],
                index=index,
                default_trace=default_trace,
                live_style=live_style,
            )
        return trace_style_states

    def _dispatched_state(self):
        dispatch_state = copy.deepcopy(self.figure_state)
        for (subplot_id, trace_id), style in self._trace_style_states_for_state(
            self.figure_state
        ).items():
            dispatch_state = MatplotlibCodec.update_state(
                dispatch_state,
                {
                    "type": "set_trace_style",
                    "subplot_id": subplot_id,
                    "trace_id": trace_id,
                    "style": copy.deepcopy(style),
                    "replace": True,
                },
            )
        return dispatch_state

    def _subplot(self, subplot_id=None):
        resolved_id = self._resolve_subplot_id(subplot_id)
        for subplot in self.figure_state["layout"]["subplots"]:
            if subplot["id"] == resolved_id:
                return subplot
        raise ValueError(f"Unknown figure subplot id: {resolved_id!r}.")

    def _effective_subplot(self, subplot_id=None):
        resolved_id = self._resolve_subplot_id(subplot_id)
        for subplot in self.effective_state()["layout"]["subplots"]:
            if subplot["id"] == resolved_id:
                return subplot
        raise ValueError(f"Unknown figure subplot id: {resolved_id!r}.")

    def _effective_axis_state(self, axis, subplot_id=None):
        return self._effective_subplot(subplot_id)["axes"][self._normalize_axis_name(axis)]

    def _effective_axis_side_state(self, side, subplot_id=None):
        return self._effective_subplot(subplot_id)["axis_sides"][
            self._normalize_side_name(side)
        ]

    def _trace(self, trace_id, subplot_id=None):
        for trace in self._subplot(subplot_id)["traces"]:
            if trace["id"] == str(trace_id):
                return trace
        raise ValueError(f"Unknown figure trace id: {trace_id!r}.")

    def _trace_style_key(self, trace_id, subplot_id=None):
        return (self._resolve_subplot_id(subplot_id), str(trace_id))

    def _find_attribute_path_trace(
        self,
        component,
        *,
        subplot_id=None,
        trace_id=None,
        id_suffix="",
        root_names=(),
    ):
        resolved_subplot_id = self._resolve_subplot_id(subplot_id)
        normalized_path = self._normalize_attribute_path(component)
        normalized_suffix = str(id_suffix or "")
        normalized_roots = self._normalized_root_names(root_names)
        subplot = self._subplot(resolved_subplot_id)

        def matches(candidate_trace_id):
            candidate_trace = None
            for trace in subplot["traces"]:
                if trace["id"] == str(candidate_trace_id):
                    candidate_trace = trace
                    break
            if not isinstance(candidate_trace, dict):
                return None
            y_source = dict(candidate_trace.get("y_source") or {})
            if y_source.get("kind") != "attribute_path":
                return None
            path = tuple(str(value) for value in y_source.get("path", ()))
            if path != normalized_path:
                return None
            root = dict(y_source.get("root") or {})
            if root.get("kind") != "name":
                return None
            display_name = self._attribute_path_display_name(
                candidate_trace_id,
                normalized_suffix,
            )
            if display_name is None:
                return None
            root_name = self._normalize_optional_text(root.get("value"))
            if (
                normalized_roots
                and root_name not in normalized_roots
                and display_name not in normalized_roots
            ):
                return None
            return {
                "trace_id": str(candidate_trace_id),
                "trace": copy.deepcopy(candidate_trace),
                "display_name": display_name,
                "root_name": root_name,
            }

        if trace_id:
            matched = matches(trace_id)
            if matched is not None:
                return matched
        for trace in subplot["traces"]:
            matched = matches(trace["id"])
            if matched is not None:
                return matched
        return None

    def _normalized_attribute_path_components(self, components):
        normalized = []
        for component in tuple(components or ()):
            component_state = dict(component or {})
            normalized.append(
                {
                    "path": self._normalize_attribute_path(
                        component_state.get("path", component_state.get("component"))
                    ),
                    "visible": bool(component_state.get("visible", True)),
                    "id_suffix": str(component_state.get("id_suffix") or ""),
                    "label": component_state.get("label"),
                    "style": copy.deepcopy(component_state.get("style") or {}),
                }
            )
        return normalized

    def _normalize_attribute_path(self, component):
        if isinstance(component, (tuple, list)):
            path = tuple(
                str(value) for value in component if str(value or "").strip()
            )
        else:
            normalized = self._normalize_optional_text(component)
            path = () if normalized is None else (normalized,)
        if not path:
            raise ValueError("Attribute-path trace component path cannot be empty.")
        return path

    def _attribute_path_display_name(self, trace_id, id_suffix):
        normalized_trace_id = self._normalize_optional_text(trace_id)
        if normalized_trace_id is None:
            return None
        normalized_suffix = str(id_suffix or "")
        if normalized_suffix:
            if not normalized_trace_id.endswith(normalized_suffix):
                return None
            display_name = normalized_trace_id[: -len(normalized_suffix)]
            return display_name or None
        return normalized_trace_id

    def _normalized_root_names(self, root_names, *extra_root_names):
        normalized = set()
        for root_name in tuple(root_names or ()) + tuple(extra_root_names):
            normalized_root = self._normalize_optional_text(root_name)
            if normalized_root is not None:
                normalized.add(normalized_root)
        return normalized

    def _normalize_optional_text(self, value):
        text = str(value or "").strip()
        return text or None

    def _attribute_path_line_trace(
        self,
        *,
        trace_id,
        root_name,
        path,
        x_name,
        label,
        style,
    ):
        trace_kwargs = dict(style or {})
        normalized_label = self._normalize_optional_text(label)
        if normalized_label is not None:
            trace_kwargs["label"] = normalized_label
        normalized_x_name = self._normalize_optional_text(x_name)
        return {
            "id": str(trace_id),
            "kind": "line",
            "x_source": (
                None
                if normalized_x_name is None
                else {"kind": "name", "value": normalized_x_name}
            ),
            "y_source": {
                "kind": "attribute_path",
                "root": {"kind": "name", "value": str(root_name)},
                "path": [str(value) for value in path],
            },
            "kwargs": trace_kwargs,
        }

    def _resolve_subplot_id(self, subplot_id):
        if subplot_id not in (None, ""):
            return str(subplot_id)
        subplot_ids = self.subplot_ids()
        if not subplot_ids:
            raise ValueError("Figure IR does not contain any subplots.")
        return subplot_ids[0]

    def _normalize_axis_name(self, axis):
        axis_name = str(axis or "")
        if axis_name not in {"x", "y"}:
            raise ValueError("Figure IR axis must be 'x' or 'y'.")
        return axis_name

    def _normalize_side_name(self, side):
        side_name = str(side or "")
        if side_name not in {"bottom", "top", "left", "right"}:
            raise ValueError(f"Unsupported axis side: {side_name!r}.")
        return side_name

    def _value_from_path(self, value, path, *, default=None):
        if not path:
            return copy.deepcopy(value)
        current = value
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return copy.deepcopy(default)
            current = current[key]
        return current

    def _python_source(self):
        if self.command == "create":
            return _decorate_figure_source(
                self.creation_body_lines(),
                decorator="@hyde.figure(register=False)",
                function_name="_hyde_figure",
                parameters=self.tracked_names(),
                invoke=True,
                delete_after=True,
            )
        if self.command == "refresh":
            return _figure_hyde_refresh_source(
                self.figure_name,
                use_bound_values=self.use_bound_values,
            )
        if self.command == "publish_figure_macros":
            return _publish_figure_macros_source()
        if self.command == "save_graphics":
            return _figure_lookup_source(
                self.figure_name,
                figure_graphics_export_command_source(
                    self.figure_name,
                    self.output_path,
                    output_format=self.output_format,
                    dpi=self.dpi,
                    transparent=self.transparent,
                    size_inches=self.size_inches,
                ),
            )
        return f"plt.close({self.figure_number})"


@dataclass(frozen=True)
class FigureIRDiff(FigureIR, HydeIRDiff):
    initial_figure_state: dict | None = None
    initial_figure_defaults: dict | None = None
    refresh_trace_ids: tuple[str, ...] = ()
    refresh_legend: bool = True

    def __post_init__(self):
        super().__post_init__()
        object.__setattr__(
            self,
            "initial_figure_state",
            _normalize_figure_state(self.initial_figure_state),
        )
        object.__setattr__(
            self,
            "initial_figure_defaults",
            _normalize_figure_defaults(self.initial_figure_defaults),
        )
        object.__setattr__(
            self,
            "refresh_trace_ids",
            tuple(str(trace_id) for trace_id in (self.refresh_trace_ids or ()) if str(trace_id)),
        )
        object.__setattr__(self, "refresh_legend", bool(self.refresh_legend))

    @classmethod
    def from_irs(cls, initial_ir, current_ir):
        return cls(
            figure_state=current_ir.figure_state,
            figure_defaults=current_ir.figure_defaults,
            resolved_axis_limits=current_ir.resolved_axis_limits,
            trace_styles=current_ir.trace_styles,
            command=current_ir.command,
            figure_name=current_ir.figure_name,
            figure_number=current_ir.figure_number,
            use_bound_values=current_ir.use_bound_values,
            creation_x_name=current_ir.creation_x_name,
            output_path=current_ir.output_path,
            output_format=current_ir.output_format,
            dpi=current_ir.dpi,
            transparent=current_ir.transparent,
            size_inches=current_ir.size_inches,
            initial_figure_state=initial_ir.figure_state,
            initial_figure_defaults=initial_ir.figure_defaults,
        )

    def as_patch(self, figure_name, *, refresh_trace_ids=(), refresh_legend=True):
        return dataclass_replace(
            self,
            command="patch",
            figure_name=str(figure_name),
            refresh_trace_ids=tuple(refresh_trace_ids or ()),
            refresh_legend=bool(refresh_legend),
        )

    def debug_state(self):
        state = super().debug_state()
        state.update(
            {
                "initial_figure_state": copy.deepcopy(self.initial_figure_state),
                "initial_figure_defaults": copy.deepcopy(self.initial_figure_defaults),
                "refresh_trace_ids": list(self.refresh_trace_ids),
                "refresh_legend": self.refresh_legend,
            }
        )
        return state

    def validate(self):
        if self.command == "patch":
            if self.initial_figure_state is None or self.figure_state is None:
                raise ValueError("Figure patch diff requires both initial and current state.")
            if not self.figure_name:
                raise ValueError("Figure patch diff requires figure_name.")
            return self
        return super().validate()

    def _python_source(self):
        if self.command == "patch":
            removed_trace_ids = _remove_only_trace_ids(
                self.initial_figure_state,
                self.figure_state,
                refresh_trace_ids=self.refresh_trace_ids,
            )
            if removed_trace_ids:
                return _figure_remove_traces_source(
                    self.figure_name,
                    removed_trace_ids,
                )
            return _figure_lookup_source(
                self.figure_name,
                figure_patch_source(
                    self.initial_figure_state,
                    self.figure_state,
                    refresh_trace_ids=self.refresh_trace_ids,
                    refresh_legend=self.refresh_legend,
                ),
                include_axes=True,
            )
        return super()._python_source()


class FigureSnapshotState:
    def __init__(
        self,
        default_macro_name="Figure",
        call_source=None,
        save_error=None,
        figure_size=None,
        tracked_names=None,
        figure_ir=None,
        figure_defaults=None,
        resolved_axis_limits=None,
        trace_styles=None,
    ):
        self._default_macro_name = default_macro_name or "Figure"
        self._tracked_names = ()
        self._figure_ir = None
        self._figure_defaults = None
        self._call_source = None
        self._save_error = None
        self._figure_size = None
        self._trace_styles = {}
        self.update(
            default_macro_name=default_macro_name,
            call_source=call_source,
            save_error=save_error,
            figure_size=figure_size,
            tracked_names=tracked_names,
            figure_ir=figure_ir,
            figure_defaults=figure_defaults,
            resolved_axis_limits=resolved_axis_limits,
            trace_styles=trace_styles,
        )

    def update(
        self,
        default_macro_name=None,
        call_source=None,
        save_error=None,
        figure_size=None,
        tracked_names=None,
        figure_ir=None,
        figure_defaults=None,
        resolved_axis_limits=None,
        trace_styles=None,
    ):
        self._figure_ir = copy.deepcopy(figure_ir)
        self._figure_defaults = _normalize_figure_defaults(figure_defaults)
        self._resolved_axis_limits = copy.deepcopy(resolved_axis_limits) or {}
        if default_macro_name:
            self._default_macro_name = str(default_macro_name)
        elif self._figure_ir is not None:
            title = MatplotlibCodec.validate_state(self._figure_ir)["settings"]["title"]
            if title:
                self._default_macro_name = title
        self._call_source = call_source
        if not self._call_source and self._figure_ir is not None:
            current_ir = FigureIR(
                figure_state=self._figure_ir,
                figure_defaults=self._figure_defaults,
            )
            self._call_source = current_ir.python_source(log=False)
        if tracked_names:
            self._tracked_names = tuple(tracked_names)
        elif self._figure_ir is not None:
            self._tracked_names = FigureIR(
                figure_state=self._figure_ir,
                figure_defaults=self._figure_defaults,
            ).tracked_names()
        else:
            self._tracked_names = ()
        self._save_error = save_error
        self._figure_size = None if figure_size is None else tuple(figure_size)
        self._trace_styles = copy.deepcopy(trace_styles) or {}

    def default_macro_name(self):
        return self._default_macro_name

    def call_source(self):
        return self._call_source

    def figure_size(self):
        return self._figure_size

    def tracked_names(self):
        return self._tracked_names

    def figure_ir(self):
        return copy.deepcopy(self._figure_ir)

    def figure_defaults(self):
        return copy.deepcopy(self._figure_defaults)

    def resolved_axis_limits(self):
        return copy.deepcopy(self._resolved_axis_limits)

    def has_save_warning(self):
        return bool(self._save_error)

    def window_warning_text(self):
        if not self._save_error:
            return None
        if "unsupported" in str(self._save_error).lower():
            return "Unsupported Feature"
        return "Macro Incomplete"

    def window_warning_message(self):
        warning_text = self.window_warning_text()
        if warning_text is None:
            return ""
        return f"{warning_text}: {self._save_error}"

    def trace_styles(self):
        return copy.deepcopy(self._trace_styles)

    def macro_source(self, macro_name, figure_title=None):
        if self._save_error and self._figure_ir is None:
            raise MacroStoreError(self._save_error)
        if self._figure_ir is not None:
            return FigureIR(
                figure_state=self._figure_ir,
                figure_defaults=self._figure_defaults,
            ).recreation_function_source(
                macro_name,
                name=figure_title,
            )
        if not self._call_source:
            raise MacroStoreError("This figure does not have a saveable recreation macro yet.")
        body = "\n".join(f"    {line}" for line in self._call_source.splitlines())
        return (
            "@hyde.figure\n"
            f"def {macro_name}():\n"
            f"{body}\n"
            "    return fig\n"
        )
class FigureWindow(HydeInteractiveWidget):
    REFRESH_TIMEOUT_MS = 5000
    CLOSE_TIMEOUT_MS = 5000

    def __init__(self, figure_number, services=None, parent=None):
        self.figure_number = int(figure_number)
        self.figure_display_helper = FigureDisplayHelper()
        super().__init__(
            services=services,
            initial_window_name=f"Figure{self.figure_number}",
            parent=parent,
        )
        self._closed = False
        self._kernel_close_in_progress = False
        self._closing_from_kernel = False
        self._pixmap = None
        self._initial_size_applied = False
        self._pending_window_pos = None
        self._pending_window_state = None
        self._refresh_in_flight = False
        self._refresh_requested = False
        self._refresh_timeout_timer = QtCore.QTimer(self)
        self._refresh_timeout_timer.setSingleShot(True)
        self._refresh_timeout_timer.timeout.connect(self._on_refresh_timeout)
        self._resize_redraw_timer = QtCore.QTimer(self)
        self._resize_redraw_timer.setSingleShot(True)
        self._resize_redraw_timer.timeout.connect(self._on_resize_redraw_timeout)
        self._close_timeout_timer = QtCore.QTimer(self)
        self._close_timeout_timer.setSingleShot(True)
        self._close_timeout_timer.timeout.connect(self._on_close_timeout)
        self.snapshot_state = FigureSnapshotState(
            default_macro_name=f"Figure{self.figure_number}"
        )

        content = QtWidgets.QWidget(self.ui.content_widget)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.warning_label = QtWidgets.QLabel(content)
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        self.warning_label.setStyleSheet(
            "QLabel {"
            " background: #fff3cd;"
            " color: #5c4400;"
            " border: 1px solid #e0c46c;"
            " border-radius: 4px;"
            " padding: 6px 8px;"
            "}"
        )
        layout.addWidget(self.warning_label)
        self.image_label = QtWidgets.QLabel(content)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setMinimumSize(240, 180)
        self.image_label.setBackgroundRole(QtGui.QPalette.Base)
        self.image_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        layout.addWidget(self.image_label)
        self.mount_child_widget(content)

        python_variables_service = self.services.get("namespace_view_service")
        if python_variables_service is not None:
            python_variables_service.connect_namespace_view_updated(
                self._on_namespace_view_updated
            )

    def bind_subwindow(self, subwindow, stable_name=None):
        resolved_name = _canonicalize_figure_window_name(
            stable_name
            if stable_name is not None
            else self.read_subwindow_identifier(subwindow),
            self.figure_number,
        )
        super().bind_subwindow(subwindow, stable_name=resolved_name)

    @property
    def current_ir(self):
        return self.widget_ir

    def update_payload(self, payload):
        snapshot = dict(payload.get("snapshot", {}) or {})
        self.widget_ir = FigureIR.from_snapshot(snapshot)
        self.snapshot_state.update(
            default_macro_name=snapshot.get("default_macro_name"),
            call_source=snapshot.get("call_source"),
            save_error=snapshot.get("save_error"),
            figure_size=snapshot.get("figure_size"),
            tracked_names=snapshot.get("tracked_names"),
            figure_ir=snapshot.get("figure_ir"),
            figure_defaults=snapshot.get("figure_defaults"),
            resolved_axis_limits=snapshot.get("resolved_axis_limits"),
            trace_styles=snapshot.get("trace_styles"),
        )
        if self._subwindow is not None:
            self._subwindow.setWindowTitle(
                self._visible_window_title()
            )
        warning_message = self.snapshot_state.window_warning_message()
        self.warning_label.setVisible(bool(warning_message))
        self.warning_label.setText(warning_message)
        self._tracked_namespace_state = self.current_tracked_namespace_state()

        image_base64 = payload.get("image_png_base64")
        if image_base64:
            png_bytes = base64.b64decode(image_base64.encode("ascii"))
            image = QtGui.QImage.fromData(png_bytes, "PNG")
            if not image.isNull():
                self._pixmap = QtGui.QPixmap.fromImage(image)
                self._clear_refresh_in_flight()
                self._update_scaled_pixmap()
                if not self._initial_size_applied:
                    self._apply_initial_subwindow_size()
                    self._initial_size_applied = True
                    self._apply_pending_window_state()
                if self._refresh_requested and not self._closed:
                    self._refresh_requested = False
                    self.refresh_figure()
        elif not self._initial_size_applied and self.snapshot_state.figure_size() is not None:
            self._apply_initial_subwindow_size()
            self._initial_size_applied = True
            self._apply_pending_window_state()

    def apply_window_metadata(self, metadata):
        metadata = dict(metadata or {})
        self.apply_window_pos(metadata.get("window_pos"))
        self.apply_window_state(metadata.get("window_state"))

    def apply_window_pos(self, window_pos):
        if self._subwindow is None or not window_pos or len(window_pos) != 2:
            return
        normalized = (int(window_pos[0]), int(window_pos[1]))
        if not self._initial_size_applied:
            self._pending_window_pos = normalized
        self._subwindow.move(*normalized)
        self._remember_subwindow_geometry()

    def apply_window_state(self, window_state):
        if self._subwindow is None or window_state is None:
            return
        if not self._initial_size_applied:
            self._pending_window_state = window_state
            return
        apply_saveable_window_state(self._subwindow, window_state)

    def _apply_pending_window_state(self):
        if self._subwindow is None:
            return
        if self._pending_window_pos is not None:
            self._subwindow.move(*self._pending_window_pos)
            self._pending_window_pos = None
        if self._pending_window_state is not None:
            apply_saveable_window_state(self._subwindow, self._pending_window_state)
            self._pending_window_state = None

    def _apply_initial_subwindow_size(self):
        if self._subwindow is None:
            return
        figure_size = self.snapshot_state.figure_size()
        if figure_size is None:
            if self._pixmap is None:
                return
            target_size = self._pixmap.size()
        else:
            target_size = QtCore.QSize(*figure_size)
        frame_size = self._subwindow.size() - self._subwindow.contentsRect().size()
        mdi_area = self._subwindow.mdiArea()
        if mdi_area is not None:
            viewport_size = mdi_area.viewport().size()
            available_size = QtCore.QSize(
                max(160, viewport_size.width() - max(0, frame_size.width())),
                max(120, viewport_size.height() - max(0, frame_size.height())),
            )
            if (
                target_size.width() > available_size.width()
                or target_size.height() > available_size.height()
            ):
                target_size.scale(available_size, QtCore.Qt.KeepAspectRatio)
        self._subwindow.resize(
            target_size.width() + max(0, frame_size.width()),
            target_size.height() + max(0, frame_size.height()),
        )
        self._remember_subwindow_geometry()

    def _update_scaled_pixmap(self):
        if self._pixmap is None:
            self.image_label.clear()
            return
        label_size = self.image_label.contentsRect().size()
        if label_size.isEmpty():
            return
        scaled = self._pixmap.scaled(
            label_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled_pixmap()
        if not self._closed:
            self._resize_redraw_timer.start(150)

    def contextMenuEvent(self, event):
        if not self.activate_popup_menu("figure", event.globalPos()):
            return super().contextMenuEvent(event)

    def request_resize_redraw(self, width=None, height=None):
        if width is None or height is None:
            target_size = self.image_label.contentsRect().size()
            width = target_size.width()
            height = target_size.height()
        if int(width) <= 0 or int(height) <= 0:
            return False
        return self.request_figure_action(
            {
                "type": "resize_redraw",
                "width": int(width),
                "height": int(height),
            }
        )

    def request_figure_action(self, action):
        figure_action_service = self.services.get("figure_action_service")
        if figure_action_service is None:
            return False
        return bool(
            figure_action_service.request_figure_action(
                self.figure_number,
                dict(action or {}),
            )
        )

    def figure_ir(self):
        if self.current_ir is None:
            return None
        return self.current_ir.normalized_state()

    def figure_defaults(self):
        if self.current_ir is None:
            return self.snapshot_state.figure_defaults()
        return copy.deepcopy(self.current_ir.figure_defaults)

    def resolved_axis_limits(self):
        return self.snapshot_state.resolved_axis_limits()

    def trace_styles(self):
        return self.snapshot_state.trace_styles()

    def has_figure_ir(self):
        return self.figure_ir() is not None

    def can_request_figure_actions(self):
        return self.services.get("figure_action_service") is not None

    def is_editable_figure_ready(self):
        return self.has_figure_ir()

    def supported_trace_records(self):
        return self.figure_display_helper.supported_trace_records(self.figure_ir())

    def has_supported_traces(self):
        return bool(self.supported_trace_records())

    def _visible_title_name(self):
        if self.current_ir is not None:
            return self.current_ir.default_macro_name()
        return self.snapshot_state.default_macro_name() or self.window_handle()

    def _visible_trace_title_suffix(self):
        return ", ".join(
            record["display_name"] for record in self.supported_trace_records()
        )

    def _visible_window_title(self):
        return self.formatted_window_title(
            title_name=self._visible_title_name(),
            title_suffix=self._visible_trace_title_suffix(),
            warning_text=self.snapshot_state.window_warning_text(),
        )

    def request_regenerate_from_ir(self):
        if not self.has_figure_ir():
            return False
        return self._execute_refresh_command(use_bound_values=True)

    @inmain_decorator()
    def _on_resize_redraw_timeout(self):
        if self._closed:
            return
        if not self._initial_size_applied:
            return
        self.request_resize_redraw()

    def tracked_namespace_names(self):
        if self.current_ir is not None:
            return self.current_ir.tracked_names()
        return self.snapshot_state.tracked_names()

    def refresh_figure(self):
        if self._closed:
            return False
        if not self.snapshot_state.tracked_names():
            return False
        if self._refresh_in_flight:
            self._refresh_requested = True
            return False
        if not self.has_figure_ir():
            return False
        self._refresh_in_flight = True
        self._refresh_requested = False
        requested = self._execute_refresh_command(use_bound_values=False)
        if requested:
            self._refresh_timeout_timer.start(self.REFRESH_TIMEOUT_MS)
            return True
        self._clear_refresh_in_flight()
        return False

    def _execute_refresh_command(self, *, use_bound_values):
        figure_name = (
            self.current_ir.default_macro_name()
            if self.current_ir is not None
            else self.snapshot_state.default_macro_name() or self.window_handle()
        )
        command_ir = (
            FigureIR()
            if self.current_ir is None
            else self.current_ir
        )
        return self.execute_hidden_command(
            command_ir.with_refresh_figure(
                figure_name,
                use_bound_values=use_bound_values,
            ).python_source(log=False)
        )

    def _clear_refresh_in_flight(self):
        self._refresh_timeout_timer.stop()
        self._refresh_in_flight = False

    @inmain_decorator()
    def _on_refresh_timeout(self):
        if self._closed or not self._refresh_in_flight:
            return
        self._clear_refresh_in_flight()
        if self._refresh_requested and not self._closed:
            self._refresh_requested = False
            self.refresh_figure()

    def _on_namespace_view_updated(self, view):
        if self._closed:
            return
        if not self.update_tracked_namespace_state(view or {}):
            return
        self.refresh_figure()

    def close_from_kernel(self):
        if self._closed or self._closing_from_kernel:
            return
        LOGGER.debug(
            "Figure window %s received kernel close confirmation.",
            self.figure_number,
        )
        self._close_timeout_timer.stop()
        self._kernel_close_in_progress = False
        self._closing_from_kernel = True
        if self._subwindow is not None:
            self._subwindow.close()
        else:
            self.close()

    def force_close(self):
        self._closing_from_kernel = True
        self._kernel_close_in_progress = False
        self.close_from_kernel()

    def saveable_default_macro_name(self):
        if self.current_ir is not None:
            return self.current_ir.default_macro_name()
        return self.snapshot_state.default_macro_name()

    def saveable_decorator_name(self):
        return "@hyde.figure"

    def macro_definition_source(self, macro_name, *, handle):
        if self.current_ir is not None:
            return self.current_ir.recreation_function_source(
                macro_name,
                name=handle,
            )
        return self.snapshot_state.macro_source(macro_name, figure_title=handle)

    def session_restore_definition_source(self, handle):
        if self.current_ir is not None:
            return self.current_ir.recreation_function_source(
                handle,
                name=handle,
                register=False,
            )
        return self.snapshot_state.macro_source(handle, figure_title=handle)

    def session_restore_warning(self):
        message = self.snapshot_state.window_warning_message()
        if not message:
            return None
        return f"{self.window_handle()}: {message}"

    def session_restore_arguments(self):
        if self.current_ir is not None:
            return self.current_ir.tracked_names()
        return self.snapshot_state.tracked_names()

    def macro_window_metadata(self, geometry, window_state):
        return {
            "window_pos": None if geometry is None else tuple(geometry[:2]),
            "window_state": None if window_state == "minimized" else window_state,
        }

    def session_restore_window_metadata(self, geometry, window_state):
        if geometry is None:
            return None
        return {
            "window_pos": tuple(geometry[:2]),
            "window_state": window_state,
        }

    def closeEvent(self, event):
        if self._kernel_close_in_progress:
            LOGGER.debug(
                "Figure window %s ignored duplicate close while waiting for kernel confirmation.",
                self.figure_number,
            )
            event.ignore()
            return
        return super().closeEvent(event)

    def is_close_complete(self):
        return self._closed or self._closing_from_kernel

    def complete_interactive_close(self, event):
        self._closed = True
        self._disconnect_namespace_updates()
        return super().complete_interactive_close(event)

    def finalize_interactive_close(self, event):
        get_shutting_down = self.service("get_shutting_down")
        if get_shutting_down is not None and get_shutting_down():
            self.complete_interactive_close(event)
            return
        self._kernel_close_in_progress = True
        command_ir = FigureIR() if self.current_ir is None else self.current_ir
        if not self.execute_hidden_command(
            command_ir.with_close_figure(self.figure_number).python_source(log=False)
        ):
            self._kernel_close_in_progress = False
            LOGGER.warning(
                "Figure window %s failed to queue kernel close command.",
                self.figure_number,
            )
            event.ignore()
            return
        LOGGER.debug(
            "Figure window %s queued kernel close command and is awaiting confirmation.",
            self.figure_number,
        )
        self._close_timeout_timer.start(self.CLOSE_TIMEOUT_MS)
        event.ignore()

    @inmain_decorator()
    def _on_close_timeout(self):
        if self._closed:
            return
        LOGGER.warning(
            "Figure window %s close confirmation timed out; window remains open.",
            self.figure_number,
        )
        self._kernel_close_in_progress = False

    def _disconnect_namespace_updates(self):
        self._refresh_timeout_timer.stop()
        self._resize_redraw_timer.stop()
        self._close_timeout_timer.stop()
        try:
            python_variables_service = self.services.get("namespace_view_service")
            if python_variables_service is not None:
                python_variables_service.disconnect_namespace_view_updated(
                    self._on_namespace_view_updated
                )
        except Exception:
            pass
