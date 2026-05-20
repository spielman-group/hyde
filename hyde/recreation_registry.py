"""Private registry helpers for kernel-side Hyde procedures definitions."""

from __future__ import annotations

import inspect
import threading

from .execution.ipc import put_parent_message


_REGISTRY_PROTOCOLS = {
    "table": {
        "task": "TABLE_MACROS_RESPONSE",
    },
    "figure": {
        "task": "FIGURE_MACROS_RESPONSE",
    },
    "fit_function": {
        "task": "FIT_FUNCTIONS_RESPONSE",
    },
}
_REGISTRIES = {
    kind: {
        "entries": {},
        "rejected": {},
    }
    for kind in _REGISTRY_PROTOCOLS
}
_REGISTRY_LOCK = threading.RLock()


def _normalize_kind(kind):
    candidate = str(kind or "").strip().lower()
    if candidate not in _REGISTRY_PROTOCOLS:
        raise ValueError(f"Unsupported registry kind: {kind!r}.")
    return candidate


def _normalize_macro_kind(kind):
    candidate = _normalize_kind(kind)
    if candidate == "fit_function":
        raise ValueError(f"Unsupported macro kind: {kind!r}.")
    return candidate


def _set_registry_entry(kind, name, entry):
    normalized_kind = _normalize_kind(kind)
    with _REGISTRY_LOCK:
        _REGISTRIES[normalized_kind]["entries"][str(name)] = dict(entry)


def _remove_registry_entry(kind, name):
    normalized_kind = _normalize_kind(kind)
    with _REGISTRY_LOCK:
        _REGISTRIES[normalized_kind]["entries"].pop(str(name), None)


def _set_registry_rejection(kind, name, entry):
    normalized_kind = _normalize_kind(kind)
    with _REGISTRY_LOCK:
        _REGISTRIES[normalized_kind]["rejected"][str(name)] = dict(entry)


def _remove_registry_rejection(kind, name):
    normalized_kind = _normalize_kind(kind)
    with _REGISTRY_LOCK:
        _REGISTRIES[normalized_kind]["rejected"].pop(str(name), None)


def _clear_registry(kind=None):
    with _REGISTRY_LOCK:
        if kind is None:
            kinds = tuple(_REGISTRY_PROTOCOLS)
        else:
            kinds = (_normalize_kind(kind),)
        for registry_kind in kinds:
            _REGISTRIES[registry_kind]["entries"].clear()
            _REGISTRIES[registry_kind]["rejected"].clear()


def _registry_names(kind):
    normalized_kind = _normalize_kind(kind)
    with _REGISTRY_LOCK:
        return tuple(sorted(_REGISTRIES[normalized_kind]["entries"]))


def _registry_entries(kind):
    normalized_kind = _normalize_kind(kind)
    with _REGISTRY_LOCK:
        return tuple(
            dict(_REGISTRIES[normalized_kind]["entries"][name])
            for name in sorted(_REGISTRIES[normalized_kind]["entries"])
        )


def _rejected_registry_entries(kind):
    normalized_kind = _normalize_kind(kind)
    with _REGISTRY_LOCK:
        return tuple(
            dict(_REGISTRIES[normalized_kind]["rejected"][name])
            for name in sorted(_REGISTRIES[normalized_kind]["rejected"])
        )


def _validate_macro_function(kind, func):
    normalized_kind = _normalize_macro_kind(kind)
    if not callable(func):
        raise TypeError(
            f"{normalized_kind.title()} recreation decorators must wrap a callable."
        )
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{normalized_kind.title()} recreation decorators require a Python function."
        ) from exc
    for parameter in signature.parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            raise TypeError(
                f"@hyde.{normalized_kind} recreation macros only support positional parameters."
            )
    return normalized_kind, signature


def register_macro(kind, func):
    normalized_kind, signature = _validate_macro_function(kind, func)
    _set_registry_entry(
        normalized_kind,
        func.__name__,
        {
            "name": func.__name__,
            "func": func,
            "args": list(signature.parameters),
        },
    )
    return func


def clear_macros(kind=None):
    if kind is None:
        for macro_kind in ("table", "figure"):
            _clear_registry(macro_kind)
        return
    _clear_registry(_normalize_macro_kind(kind))


def macro_names(kind):
    return _registry_names(_normalize_macro_kind(kind))


def macro_entries(kind):
    normalized_kind = _normalize_macro_kind(kind)
    return tuple(
        {
            "name": entry["name"],
            "args": list(entry["args"]),
        }
        for entry in _registry_entries(normalized_kind)
    )


def serialize_registry(kind):
    normalized_kind = _normalize_kind(kind)
    return {
        "entries": list(
            macro_entries(normalized_kind)
            if normalized_kind in ("table", "figure")
            else _registry_entries(normalized_kind)
        ),
        "rejected": list(_rejected_registry_entries(normalized_kind)),
    }


def publish_registry(kind):
    normalized_kind = _normalize_kind(kind)
    protocol = _REGISTRY_PROTOCOLS[normalized_kind]
    try:
        put_parent_message([
            protocol["task"],
            serialize_registry(normalized_kind),
        ])
    except Exception:
        pass


def _coerce_independent_vars(independent_vars):
    values = tuple(str(name) for name in tuple(independent_vars or ()))
    if not values:
        raise TypeError("@hyde.fit_function requires at least one independent variable.")
    for name in values:
        if not name.isidentifier():
            raise TypeError(
                "@hyde.fit_function independent_vars must contain valid Python identifiers."
            )
    if len(set(values)) != len(values):
        raise TypeError("@hyde.fit_function independent_vars must be unique.")
    return values


def _is_project_defined_fit_function(func):
    return getattr(func, "__module__", None) == "procedures"


def register_fit_function(func, *, independent_vars):
    if not callable(func):
        raise TypeError("@hyde.fit_function must wrap a callable.")
    if not _is_project_defined_fit_function(func):
        return func
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError) as exc:
        raise TypeError("@hyde.fit_function requires a Python function.") from exc
    independent_var_names = _coerce_independent_vars(independent_vars)
    parameters = list(signature.parameters.values())
    if len(parameters) < len(independent_var_names) + 1:
        raise TypeError(
            "@hyde.fit_function requires explicitly named coefficient parameters."
        )
    parameter_names = []
    for parameter in parameters:
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise TypeError("@hyde.fit_function does not support *args or **kwargs.")
        if parameter.kind != inspect.Parameter.POSITIONAL_OR_KEYWORD:
            raise TypeError(
                "@hyde.fit_function only supports explicitly named positional parameters."
            )
        parameter_names.append(parameter.name)
    if tuple(parameter_names[: len(independent_var_names)]) != independent_var_names:
        raise TypeError(
            "@hyde.fit_function parameters must begin with the declared independent_vars in order."
        )
    coefficients = parameter_names[len(independent_var_names) :]
    if not coefficients:
        raise TypeError(
            "@hyde.fit_function requires at least one explicitly named coefficient parameter."
        )
    entry = {
        "name": func.__name__,
        "independent_vars": list(independent_var_names),
        "parameters": list(coefficients),
    }
    _set_registry_entry("fit_function", func.__name__, entry)
    _remove_registry_rejection("fit_function", func.__name__)
    return func


def reject_fit_function(func, *, reason):
    if not callable(func):
        return func
    _remove_registry_entry("fit_function", func.__name__)
    _set_registry_rejection(
        "fit_function",
        func.__name__,
        {
            "name": func.__name__,
            "reason": str(reason),
        },
    )
    return func


def clear_fit_functions():
    _clear_registry("fit_function")


def fit_function_entries():
    return _registry_entries("fit_function")


def rejected_fit_function_entries():
    return _rejected_registry_entries("fit_function")


def serialize_fit_function_registry():
    return serialize_registry("fit_function")


def publish_fit_function_registry():
    publish_registry("fit_function")


def register_table_macro(func):
    return register_macro("table", func)


def clear_table_macros():
    clear_macros("table")


def table_macro_names():
    return macro_names("table")


def table_macro_entries():
    return macro_entries("table")


def serialize_table_macro_registry():
    return serialize_registry("table")


def publish_table_macro_registry():
    publish_registry("table")


def register_figure_macro(func):
    return register_macro("figure", func)


def clear_figure_macros():
    clear_macros("figure")


def figure_macro_names():
    return macro_names("figure")


def figure_macro_entries():
    return macro_entries("figure")


def serialize_figure_macro_registry():
    return serialize_registry("figure")


def publish_figure_macro_registry():
    publish_registry("figure")
