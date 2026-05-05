"""Private recreation registry helpers for kernel-side saveable windows."""

from __future__ import annotations

import inspect
import threading

from labscript_utils.ls_zprocess import ProcessTree


_VALID_KINDS = ("table", "figure")
_WINDOW_MACROS = {kind: {} for kind in _VALID_KINDS}
_WINDOW_MACROS_LOCK = threading.RLock()


def _normalize_kind(kind):
    candidate = str(kind or "").strip().lower()
    if candidate not in _VALID_KINDS:
        raise ValueError(f"Unsupported window macro kind: {kind!r}.")
    return candidate


def _validate_macro_function(kind, func):
    normalized_kind = _normalize_kind(kind)
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
    return signature


def register_window_macro(kind, func):
    normalized_kind = _normalize_kind(kind)
    signature = _validate_macro_function(normalized_kind, func)
    with _WINDOW_MACROS_LOCK:
        _WINDOW_MACROS[normalized_kind][func.__name__] = {
            "func": func,
            "args": list(signature.parameters),
        }
    return func


def clear_window_macros(kind=None):
    with _WINDOW_MACROS_LOCK:
        if kind is None:
            for macro_kind in _VALID_KINDS:
                _WINDOW_MACROS[macro_kind].clear()
            return
        _WINDOW_MACROS[_normalize_kind(kind)].clear()


def window_macro_names(kind):
    normalized_kind = _normalize_kind(kind)
    with _WINDOW_MACROS_LOCK:
        return tuple(sorted(_WINDOW_MACROS[normalized_kind]))


def window_macro_entries(kind):
    normalized_kind = _normalize_kind(kind)
    with _WINDOW_MACROS_LOCK:
        return tuple(
            {
                "name": name,
                "args": list(_WINDOW_MACROS[normalized_kind][name]["args"]),
            }
            for name in sorted(_WINDOW_MACROS[normalized_kind])
        )


def serialize_window_macro_registry(kind):
    normalized_kind = _normalize_kind(kind)
    return {
        "kind": normalized_kind,
        "macros": list(window_macro_entries(normalized_kind)),
    }


def publish_window_macro_registry(kind):
    normalized_kind = _normalize_kind(kind)
    try:
        tree = ProcessTree.instance()
        if tree is None or not hasattr(tree, "to_parent"):
            return
        tree.to_parent.put(
            [
                "WINDOW_MACROS_RESPONSE",
                serialize_window_macro_registry(normalized_kind),
            ]
        )
    except Exception:
        pass


def register_table_macro(func):
    return register_window_macro("table", func)


def clear_table_macros():
    clear_window_macros("table")


def table_macro_names():
    return window_macro_names("table")


def table_macro_entries():
    return window_macro_entries("table")


def serialize_table_macro_registry():
    return serialize_window_macro_registry("table")


def publish_table_macro_registry():
    publish_window_macro_registry("table")


def register_figure_macro(func):
    return register_window_macro("figure", func)


def clear_figure_macros():
    clear_window_macros("figure")


def figure_macro_names():
    return window_macro_names("figure")


def figure_macro_entries():
    return window_macro_entries("figure")


def serialize_figure_macro_registry():
    return serialize_window_macro_registry("figure")


def publish_figure_macro_registry():
    publish_window_macro_registry("figure")
