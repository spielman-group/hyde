"""Private registry helpers for kernel-side Hyde procedures definitions."""

from __future__ import annotations

import inspect
import threading
import textwrap

from .execution.ipc import put_parent_message


_PUBLIC_KINDS = ("table", "figure", "fit_function")
_MACRO_TASKS = {
    "table": "TABLE_MACROS_RESPONSE",
    "figure": "FIGURE_MACROS_RESPONSE",
}
_FIT_FUNCTION_TASK = "FIT_FUNCTIONS_RESPONSE"
_MACRO_REGISTRIES = {kind: {} for kind in _MACRO_TASKS}
_FIT_FUNCTION_CATALOG = {
    "entries": {},
    "rejected": {},
}
_REGISTRY_LOCK = threading.RLock()


def _normalize_kind(kind):
    candidate = str(kind or "").strip().lower()
    if candidate not in _PUBLIC_KINDS:
        raise ValueError(f"Unsupported registry kind: {kind!r}.")
    return candidate


def _normalize_macro_kind(kind):
    normalized_kind = _normalize_kind(kind)
    if normalized_kind not in _MACRO_TASKS:
        raise ValueError(f"Unsupported macro kind: {kind!r}.")
    return normalized_kind


def _registry_kinds(kind=None):
    if kind is None:
        return _PUBLIC_KINDS
    return (_normalize_kind(kind),)


def _registry_task(kind):
    if kind == "fit_function":
        return _FIT_FUNCTION_TASK
    return _MACRO_TASKS[kind]


def _set_macro_entry(kind, name, entry):
    normalized_kind = _normalize_macro_kind(kind)
    with _REGISTRY_LOCK:
        _MACRO_REGISTRIES[normalized_kind][str(name)] = dict(entry)


def _set_fit_function_entry(name, entry):
    with _REGISTRY_LOCK:
        _FIT_FUNCTION_CATALOG["entries"][str(name)] = dict(entry)


def _remove_fit_function_entry(name):
    with _REGISTRY_LOCK:
        _FIT_FUNCTION_CATALOG["entries"].pop(str(name), None)


def _set_fit_function_rejection(name, entry):
    with _REGISTRY_LOCK:
        _FIT_FUNCTION_CATALOG["rejected"][str(name)] = dict(entry)


def _remove_fit_function_rejection(name):
    with _REGISTRY_LOCK:
        _FIT_FUNCTION_CATALOG["rejected"].pop(str(name), None)


def clear(kind=None):
    with _REGISTRY_LOCK:
        for registry_kind in _registry_kinds(kind):
            if registry_kind == "fit_function":
                _FIT_FUNCTION_CATALOG["entries"].clear()
                _FIT_FUNCTION_CATALOG["rejected"].clear()
            else:
                _MACRO_REGISTRIES[registry_kind].clear()


def _validate_recreation_function(kind, func):
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


def _serialized_macro_entries(kind, registry_key):
    if registry_key != "entries":
        return ()
    with _REGISTRY_LOCK:
        stored_entries = _MACRO_REGISTRIES[kind]
        return tuple(
            {
                "name": entry["name"],
                "args": list(entry["args"]),
            }
            for _, entry in sorted(stored_entries.items())
        )


def _serialized_fit_function_entries(registry_key):
    with _REGISTRY_LOCK:
        stored_entries = _FIT_FUNCTION_CATALOG[registry_key]
        return tuple(dict(entry) for _, entry in stored_entries.items())


def _serialized_entries(kind, registry_key):
    normalized_kind = _normalize_kind(kind)
    if normalized_kind == "fit_function":
        return _serialized_fit_function_entries(registry_key)
    return _serialized_macro_entries(normalized_kind, registry_key)


def names(kind):
    return tuple(entry["name"] for entry in _serialized_entries(kind, "entries"))


def serialize_registry(kind):
    normalized_kind = _normalize_kind(kind)
    return {
        "entries": list(_serialized_entries(normalized_kind, "entries")),
        "rejected": list(_serialized_entries(normalized_kind, "rejected")),
    }


def publish_registry(kind=None):
    for registry_kind in _registry_kinds(kind):
        try:
            put_parent_message([
                _registry_task(registry_kind),
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
    return getattr(func, "__module__", None) in {"procedures", "hyde"}


def _fit_function_callable_ref(func):
    module_name = str(getattr(func, "__module__", "") or "")
    if module_name == "hyde":
        return f"hyde.{func.__name__}"
    return func.__name__


def _fit_function_source_text(func):
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError):
        return ""
    lines = textwrap.dedent(source).splitlines()
    while lines and lines[0].lstrip().startswith("@"):
        lines.pop(0)
    return "\n".join(lines).strip()


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
        "callable_ref": _fit_function_callable_ref(func),
        "source_text": _fit_function_source_text(func),
        "independent_vars": list(independent_var_names),
        "parameters": list(coefficients),
    }
    _set_fit_function_entry(func.__name__, entry)
    _remove_fit_function_rejection(func.__name__)
    return func


def reject_fit_function(func, *, reason):
    if not callable(func):
        return func
    _remove_fit_function_entry(func.__name__)
    _set_fit_function_rejection(
        func.__name__,
        {
            "name": func.__name__,
            "reason": str(reason),
        },
    )
    return func


def register_macro(kind, func):
    normalized_kind, signature = _validate_recreation_function(kind, func)
    _set_macro_entry(
        normalized_kind,
        func.__name__,
        {
            "name": func.__name__,
            "func": func,
            "args": list(signature.parameters),
        },
    )
    return func
