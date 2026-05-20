"""Private registry helpers for kernel-side Hyde procedures definitions."""

from __future__ import annotations

import inspect
import threading

from .execution.ipc import put_parent_message


_REGISTRY_PROTOCOLS = {
    "table": {
        "task": "TABLE_MACROS_RESPONSE",
        "entry_fields": ("name", "args"),
    },
    "figure": {
        "task": "FIGURE_MACROS_RESPONSE",
        "entry_fields": ("name", "args"),
    },
    "fit_function": {
        "task": "FIT_FUNCTIONS_RESPONSE",
        "entry_fields": None,
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


def clear(kind=None):
    with _REGISTRY_LOCK:
        if kind is None:
            kinds = tuple(_REGISTRY_PROTOCOLS)
        else:
            kinds = (_normalize_kind(kind),)
        for registry_kind in kinds:
            _REGISTRIES[registry_kind]["entries"].clear()
            _REGISTRIES[registry_kind]["rejected"].clear()


def _validate_recreation_function(kind, func):
    normalized_kind = _normalize_kind(kind)
    if normalized_kind == "fit_function":
        raise ValueError(f"Unsupported macro kind: {kind!r}.")
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


def _serialized_entries(kind, registry_key):
    normalized_kind = _normalize_kind(kind)
    entry_fields = _REGISTRY_PROTOCOLS[normalized_kind]["entry_fields"]
    with _REGISTRY_LOCK:
        stored_entries = _REGISTRIES[normalized_kind][registry_key]
        return tuple(
            (
                {
                    field: list(entry[field]) if field == "args" else entry[field]
                    for field in entry_fields
                }
                if entry_fields is not None
                else dict(entry)
            )
            for _, entry in sorted(stored_entries.items())
        )


def names(kind):
    return tuple(entry["name"] for entry in _serialized_entries(kind, "entries"))


def serialize_registry(kind):
    normalized_kind = _normalize_kind(kind)
    return {
        "entries": list(_serialized_entries(normalized_kind, "entries")),
        "rejected": list(_serialized_entries(normalized_kind, "rejected")),
    }


def publish_registry(kind=None):
    if kind is None:
        kinds = tuple(_REGISTRY_PROTOCOLS)
    else:
        kinds = (_normalize_kind(kind),)
    for registry_kind in kinds:
        protocol = _REGISTRY_PROTOCOLS[registry_kind]
        try:
            put_parent_message([
                protocol["task"],
                serialize_registry(registry_kind),
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

def register_macro(kind, func):
    normalized_kind, signature = _validate_recreation_function(kind, func)
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
