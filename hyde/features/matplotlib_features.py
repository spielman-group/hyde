import copy
import numbers
from dataclasses import dataclass

from hyde.features.base import (
    FeatureCodec,
    normalize_optional_text,
    ordered_unique,
    set_path,
    sorted_eligible_names,
    valid_python_identifier,
)
from hyde.features.matplotlib_graphics_formats import GRAPHICS_EXPORT_FILETYPES
from hyde.features.matplotlib_figure_schema import (
    TRACE_STYLE_ACTION_KEYS,
    _MIRROR_SIDE,
    _PRIMARY_SIDE,
    operand_to_python,
)
from hyde.features.matplotlib_figure_state import (
    FigureIRAuthority,
)


def patch_empty_choice(value):
    if value in (None, "", "none", "None", " "):
        return "None"
    return str(value)


def patch_can_dispatch_trace_style_edit(source_trace, target_trace):
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


def macro_ready_lines(lines):
    return [line for line in lines if line.strip() != "fig.canvas.draw_idle()"]


def runtime_graphics_export_filetypes():
    """Ask the installed matplotlib what it can export.

    This imports `matplotlib.pyplot` and resolves an interactive backend as a
    side effect, so nothing on a GUI or start-up path may call it. It exists for
    `scripts/regenerate_graphics_formats.py` and the test that detects a stale
    generated table; everything else reads `GRAPHICS_EXPORT_FILETYPES`.
    """
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
    return tuple(ordered_unique(suffixes))


def graphics_export_name_filter(display_label, suffixes):
    patterns = " ".join(f"*{suffix}" for suffix in tuple(suffixes or ()))
    if not patterns:
        patterns = "*"
    return f"{display_label} Files ({patterns})"


def graphics_export_formats(filetypes=None):
    """Export formats Hyde offers, ordered pdf, png, then alphabetically.

    Reads the generated table by default rather than querying matplotlib, so
    this is safe to call while building menus at start-up.
    """
    resolved_filetypes = (
        dict(GRAPHICS_EXPORT_FILETYPES) if filetypes is None else dict(filetypes)
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


# Clipboard representation per matplotlib output format. A format absent from
# this mapping has no clipboard representation at all: `raw` and `rgba` are raw
# buffers with no MIME type, and `svgz` is gzipped SVG that no application
# pastes, superseded by `svg`.
# Only the formats Hyde actually publishes to a clipboard. Every other raster
# encoding pastes identically, because the platform republishes the image rather
# than the encoding it was handed.
GRAPHICS_CLIPBOARD_MIME_TYPES = {
    "pdf": "application/pdf",
    "svg": "image/svg+xml",
    "png": "image/png",
    # LaTeX source, carried as text rather than as an image.
    "pgf": "text/plain",
}


@dataclass(frozen=True)
class ClipboardRepresentation:
    """One kind of thing a clipboard can carry a figure as.

    A clipboard distinguishes representations, not file formats: the receiving
    application asks for a picture or a drawing or some text, and every raster
    encoding answers the first question identically. `output_format` is which
    matplotlib format serves the representation, which is Hyde's choice and not
    something a user picks.
    """

    key: str
    display_label: str
    output_format: str


GRAPHICS_CLIPBOARD_REPRESENTATIONS = (
    ClipboardRepresentation("vector", "Vector", "pdf"),
    ClipboardRepresentation("image", "Image", "png"),
    ClipboardRepresentation("latex", "LaTeX", "pgf"),
)


def graphics_clipboard_representations():
    """The representations a figure can be copied as, in menu order."""
    return GRAPHICS_CLIPBOARD_REPRESENTATIONS


def graphics_clipboard_representation(key):
    """Return the named representation, or None if there is no such thing."""
    normalized_key = str(key or "").strip().lower()
    for representation in GRAPHICS_CLIPBOARD_REPRESENTATIONS:
        if representation.key == normalized_key:
            return representation
    return None


def clipboard_mime_type_for_format(output_format):
    """Return the clipboard MIME type for a format, or None if it has none."""
    normalized_format = str(output_format or "").strip().lower()
    return GRAPHICS_CLIPBOARD_MIME_TYPES.get(normalized_format)


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


class FigureGraphicsExportModel:
    feature_name = "figure_graphics_export"

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
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
            set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            set_path(normalized, action["path"], None)
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
            return savefig_source
        width, height = settings["size_inches"]
        return "\n".join(
            [
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
    del figure_name
    return MatplotlibCodec.state_to_python(
        {
            "feature": MatplotlibCodec.figure_graphics_export_feature,
            "settings": {
                "figure_name": None,
                "output_path": output_path,
                "output_format": output_format,
                "dpi": dpi,
                "transparent": transparent,
                "size_inches": size_inches,
            }
        }
    )


class FigurePatchModel:
    feature_name = "figure_patch"

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "settings": {
                "figure_name": None,
                "source_state": None,
                "target_state": None,
                "refresh_trace_ids": (),
                "refresh_legend": True,
            },
            "items": [],
            "ui": {},
        }

    @classmethod
    def normalize_state(cls, state):
        normalized = copy.deepcopy(cls.default_state())
        if state:
            normalized["feature"] = state.get("feature", normalized["feature"])
            settings = state.get("settings", {})
            if isinstance(settings, dict):
                normalized["settings"].update(settings)
            normalized["items"] = list(state.get("items", []))
            ui = state.get("ui", {})
            normalized["ui"] = dict(ui) if isinstance(ui, dict) else {}
        settings = normalized["settings"]
        figure_name = settings.get("figure_name")
        settings["figure_name"] = None if figure_name in (None, "") else str(figure_name)
        settings["source_state"] = (
            None if settings.get("source_state") is None else copy.deepcopy(settings["source_state"])
        )
        settings["target_state"] = (
            None if settings.get("target_state") is None else copy.deepcopy(settings["target_state"])
        )
        settings["refresh_trace_ids"] = tuple(
            str(trace_id) for trace_id in tuple(settings.get("refresh_trace_ids") or ())
        )
        settings["refresh_legend"] = bool(settings.get("refresh_legend", True))
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")
        settings = normalized["settings"]
        if settings["source_state"] is None:
            raise ValueError("Figure patch requires settings.source_state.")
        if settings["target_state"] is None:
            raise ValueError("Figure patch requires settings.target_state.")
        MatplotlibCodec.validate_state(settings["source_state"])
        MatplotlibCodec.validate_state(settings["target_state"])
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")
        if action_type == "set":
            set_path(normalized, action["path"], copy.deepcopy(action["value"]))
        elif action_type == "clear":
            set_path(normalized, action["path"], None)
        else:
            raise ValueError(f"Unsupported figure patch action: {action_type!r}.")
        return cls.normalize_state(normalized)

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        settings = normalized["settings"]
        return figure_patch_source(
            settings["source_state"],
            settings["target_state"],
            refresh_trace_ids=settings["refresh_trace_ids"],
            refresh_legend=settings["refresh_legend"],
        )


class FigureCommandModel:
    feature_name = "figure_command"
    _valid_commands = {
        "create",
        "close",
    }

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "settings": {
                "command": "create",
                "title": None,
                "x_name": None,
                "figsize": None,
                "subplot_code": "111",
                "figure_number": None,
                "figure_name": None,
                "use_bound_values": False,
            },
            "items": [],
            "ui": {},
        }

    @classmethod
    def normalize_state(cls, state):
        normalized = copy.deepcopy(cls.default_state())
        if state:
            normalized["feature"] = state.get("feature", normalized["feature"])
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
        figure_name = settings.get("figure_name")
        settings["figure_name"] = (
            None if figure_name in (None, "") else str(figure_name)
        )
        settings["use_bound_values"] = bool(settings.get("use_bound_values", False))
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
            set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            set_path(normalized, action["path"], None)
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
        return tuple(ordered_unique(names))

    @classmethod
    def state_to_python(cls, state, context=None):
        del context
        normalized = cls.validate_state(state)
        command = normalized["settings"]["command"]
        if command == "create":
            return "\n".join(cls._creation_lines(normalized))
        if command == "close":
            return f"plt.close({normalized['settings']['figure_number']})"
        raise ValueError(f"Unsupported figure command: {command!r}.")

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        del context
        normalized = cls.validate_state(state)
        parameters = list(cls.tracked_names(normalized))
        body_lines = macro_ready_lines(cls._creation_lines(normalized))
        body = "\n".join(f"    {line}" for line in body_lines)
        return (
            f"def {macro_name}({', '.join(parameters)}):\n"
            f"{body}\n"
            "    return fig\n"
        )
def apply_figure_state(figure, state, namespace):
    normalized = MatplotlibCodec.normalize_state(state)
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


class MatplotlibCodec(FeatureCodec):
    feature_name = "matplotlib"
    figure_command_feature = "figure_command"
    figure_ir_feature = "figure_ir"
    figure_patch_feature = FigurePatchModel.feature_name
    figure_graphics_export_feature = FigureGraphicsExportModel.feature_name

    @classmethod
    def default_state(cls, feature=None):
        feature_kind = cls._feature_kind(feature=feature)
        model = cls._model_for_feature(feature_kind)
        return cls._canonicalize_feature(model.default_state(), feature_kind)

    @classmethod
    def normalize_state(cls, state):
        feature_kind = cls._feature_kind(state)
        model = cls._model_for_feature(feature_kind)
        return cls._canonicalize_feature(
            model.normalize_state(cls._delegate_state(feature_kind, state)),
            feature_kind,
        )

    @classmethod
    def validate_state(cls, state):
        feature_kind = cls._feature_kind(state)
        model = cls._model_for_feature(feature_kind)
        return cls._canonicalize_feature(
            model.validate_state(cls._delegate_state(feature_kind, state)),
            feature_kind,
        )

    @classmethod
    def update_state(cls, state, action):
        feature_kind = cls._feature_kind(state)
        model = cls._model_for_feature(feature_kind)
        return cls._canonicalize_feature(
            model.update_state(cls._delegate_state(feature_kind, state), action),
            feature_kind,
        )

    @classmethod
    def state_to_python(cls, state, context=None):
        feature_kind = cls._feature_kind(state)
        model = cls._model_for_feature(feature_kind)
        return model.state_to_python(cls._delegate_state(feature_kind, state), context=context)

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        feature_kind = cls._feature_kind(state)
        model = cls._model_for_feature(feature_kind)
        if not hasattr(model, "state_to_macro_source"):
            raise NotImplementedError(
                f"{model.__name__} does not support macro source generation."
            )
        return model.state_to_macro_source(
            cls._delegate_state(feature_kind, state),
            macro_name,
            context=context,
        )

    @classmethod
    def tracked_names(cls, state):
        feature_kind = cls._feature_kind(state)
        model = cls._model_for_feature(feature_kind)
        return model.tracked_names(cls._delegate_state(feature_kind, state))

    @classmethod
    def _normalize_subplot(cls, subplot, index):
        return FigureIRAuthority._normalize_subplot(subplot, index)

    @classmethod
    def _normalize_trace(cls, trace, index):
        return FigureIRAuthority._normalize_trace(trace, index)

    @classmethod
    def _resolve_subplot(cls, normalized, subplot_id):
        return FigureIRAuthority._resolve_subplot(normalized, subplot_id)

    @classmethod
    def _plot_call(cls, trace, default_style=None):
        return FigureIRAuthority._plot_call(trace, default_style=default_style)

    @classmethod
    def _feature_kind(cls, state=None, *, feature=None):
        candidate = feature
        if candidate in (None, "") and isinstance(state, dict):
            candidate = state.get("feature")
        if candidate == "figure":
            raise ValueError(
                "Ambiguous matplotlib feature 'figure'; use 'figure_command' or "
                "'figure_ir'."
            )
        if candidate == cls.figure_command_feature:
            return cls.figure_command_feature
        if candidate == cls.figure_ir_feature:
            return cls.figure_ir_feature
        if candidate == cls.figure_patch_feature:
            return cls.figure_patch_feature
        if candidate == cls.figure_graphics_export_feature:
            return cls.figure_graphics_export_feature
        if isinstance(state, dict):
            settings = dict(state.get("settings", {}) or {})
            if "layout" in state or "opaque_nodes" in state:
                return cls.figure_ir_feature
            if "source_state" in settings or "target_state" in settings:
                return cls.figure_patch_feature
            if any(
                key in settings
                for key in ("output_path", "output_format", "dpi", "transparent", "size_inches")
            ):
                return cls.figure_graphics_export_feature
            if any(
                key in settings
                for key in (
                    "command",
                    "x_name",
                    "subplot_code",
                    "figure_number",
                    "figure_name",
                    "use_bound_values",
                )
            ) or "items" in state:
                return cls.figure_command_feature
        return cls.figure_command_feature

    @classmethod
    def _model_for_feature(cls, feature_kind):
        if feature_kind == cls.figure_command_feature:
            return FigureCommandModel
        if feature_kind == cls.figure_ir_feature:
            return FigureIRAuthority
        if feature_kind == cls.figure_patch_feature:
            return FigurePatchModel
        if feature_kind == cls.figure_graphics_export_feature:
            return FigureGraphicsExportModel
        raise ValueError(f"Unsupported matplotlib feature kind: {feature_kind!r}.")

    @classmethod
    def _delegate_state(cls, feature_kind, state):
        candidate = copy.deepcopy(state) if state is not None else None
        if candidate is None:
            return None
        model = cls._model_for_feature(feature_kind)
        candidate["feature"] = model.feature_name
        return candidate

    @classmethod
    def _canonicalize_feature(cls, state, feature_kind):
        normalized = copy.deepcopy(state)
        normalized["feature"] = feature_kind
        return normalized


def figure_ir_from_live_state(state):
    normalized = MatplotlibCodec.validate_state(state)
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
    ir = MatplotlibCodec.default_state(feature=MatplotlibCodec.figure_ir_feature)
    ir["settings"]["title"] = title
    ir["settings"]["figsize"] = normalized["settings"]["figsize"]
    ir["layout"]["subplots"] = [subplot]
    return MatplotlibCodec.validate_state(ir)


def figure_ir_append_trace(figure_ir, trace):
    normalized = MatplotlibCodec.normalize_state(figure_ir)
    if not normalized["layout"]["subplots"]:
        normalized["layout"]["subplots"].append(MatplotlibCodec._normalize_subplot({}, 0))
    subplot = normalized["layout"]["subplots"][0]
    trace_index = len(subplot["traces"])
    subplot["traces"].append(MatplotlibCodec._normalize_trace(trace, trace_index))
    subplot["legend"] = len(subplot["traces"]) > 1
    return MatplotlibCodec.validate_state(normalized)


def figure_patch_subplot(state, subplot_id):
    subplots = list(dict(state or {}).get("layout", {}).get("subplots", []) or [])
    if not subplots:
        raise ValueError("Figure IR does not contain any subplots.")
    if subplot_id in (None, ""):
        return subplots[0]
    for subplot in subplots:
        if subplot.get("id") == str(subplot_id):
            return subplot
    raise ValueError(f"Unknown figure subplot id: {subplot_id!r}.")


def figure_patch_reset_color(target, default_expr):
    return repr(target) if target is not None else default_expr


def figure_patch_label_lines(axis_name, source_axis_state, target_axis_state):
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
        color_value = figure_patch_reset_color(
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


def figure_patch_range_lines(axis_name, source_axis_state, target_axis_state):
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


def figure_patch_tick_params_lines(axis_name, source_subplot, target_subplot):
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


def figure_patch_spine_lines(axis_name, source_subplot, target_subplot):
    lines = []
    for side in (_PRIMARY_SIDE[axis_name], _MIRROR_SIDE[axis_name]):
        source_side = source_subplot["axis_sides"][side]
        target_side = target_subplot["axis_sides"][side]
        if source_side["spine_visible"] != target_side["spine_visible"]:
            lines.append(f"ax.spines[{side!r}].set_visible({target_side['spine_visible']!r})")
        if source_side["spine_color"] != target_side["spine_color"]:
            color_value = figure_patch_reset_color(
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


def figure_patch_tick_locator_lines(axis_name, source_axis_state, target_axis_state):
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


def figure_patch_tick_label_style_lines(axis_name, source_subplot, target_subplot):
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
            color_value = figure_patch_reset_color(
                target_side["tick_label_color"],
                default_color_expr,
            )
            lines.append(f"    _hyde_tick.{label_attr}.set_color({color_value})")
        if rotation_changed:
            lines.append(f"    _hyde_tick.{label_attr}.set_rotation({target_side['tick_label_rotation']!r})")
    return lines


def figure_patch_grid_lines(axis_name, source_axis_state, target_axis_state):
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


def figure_patch_zero_line_lines(axis_name, source_axis_state, target_axis_state):
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


def figure_patch_trace_lines(source_trace, target_trace, *, trace_index):
    if not patch_can_dispatch_trace_style_edit(source_trace, target_trace):
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
        "marker": lambda value: f"line.set_marker({patch_empty_choice(value)!r})",
        "markersize": lambda value: f"line.set_markersize({value!r})",
        "markerfacecolor": lambda value: f"line.set_markerfacecolor({value!r})",
        "markeredgecolor": lambda value: f"line.set_markeredgecolor({value!r})",
        "markeredgewidth": lambda value: f"line.set_markeredgewidth({value!r})",
        "linestyle": lambda value: f"line.set_linestyle({patch_empty_choice(value)!r})",
        "linewidth": lambda value: f"line.set_linewidth({value!r})",
        "label": lambda value: f"line.set_label({value!r})",
    }
    for key in changed_keys:
        lines.append(setter_lines[key](target_kwargs.get(key)))
    return lines


def figure_patch_remove_trace_lines(trace_id):
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


def figure_patch_add_trace_lines(trace):
    arguments = []
    x_source = operand_to_python(trace["x_source"])
    y_source = operand_to_python(trace["y_source"])
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
    refresh_trace_ids=(),
    refresh_legend=True,
):
    source = copy.deepcopy(source_state)
    target = copy.deepcopy(target_state)
    source_subplot = figure_patch_subplot(source, None)
    target_subplot = figure_patch_subplot(target, None)
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
        lines.extend(figure_patch_label_lines(axis_name, source_axis_state, target_axis_state))
        lines.extend(figure_patch_range_lines(axis_name, source_axis_state, target_axis_state))
        tick_param_lines = figure_patch_tick_params_lines(axis_name, source_subplot, target_subplot)
        lines.extend(tick_param_lines)
        lines.extend(figure_patch_spine_lines(axis_name, source_subplot, target_subplot))
        locator_lines = figure_patch_tick_locator_lines(axis_name, source_axis_state, target_axis_state)
        if locator_lines:
            needs_ticker = True
            lines.extend(locator_lines)
        lines.extend(figure_patch_tick_label_style_lines(axis_name, source_subplot, target_subplot))
        lines.extend(figure_patch_grid_lines(axis_name, source_axis_state, target_axis_state))
        lines.extend(figure_patch_zero_line_lines(axis_name, source_axis_state, target_axis_state))

    trace_lines = []
    legend_changed = source_subplot["legend"] != target_subplot["legend"]
    source_traces = {trace["id"]: trace for trace in source_subplot.get("traces", [])}
    target_traces = {trace["id"]: trace for trace in target_subplot.get("traces", [])}
    for source_trace in source_subplot.get("traces", []):
        if source_trace["id"] in target_traces:
            continue
        legend_changed = True
        trace_lines.extend(figure_patch_remove_trace_lines(source_trace["id"]))
    for index, target_trace in enumerate(target_subplot.get("traces", [])):
        source_trace = source_traces.get(target_trace["id"])
        if source_trace is None:
            legend_changed = True
            trace_lines.extend(figure_patch_add_trace_lines(target_trace))
            continue
        lowered = figure_patch_trace_lines(source_trace, target_trace, trace_index=index)
        if lowered:
            legend_changed = True
            trace_lines.extend(lowered)
            continue
        if source_trace != target_trace:
            legend_changed = True
            trace_lines.extend(figure_patch_remove_trace_lines(target_trace["id"]))
            trace_lines.extend(figure_patch_add_trace_lines(target_trace))
            continue
        if target_trace["id"] in refresh_trace_ids:
            trace_lines.extend(figure_patch_remove_trace_lines(target_trace["id"]))
            trace_lines.extend(figure_patch_add_trace_lines(target_trace))
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
    return "\n".join(prelude + lines + ["fig.canvas.draw_idle()"])


