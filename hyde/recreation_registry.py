"""Private recreation registry helpers for kernel-side saveable windows."""

from __future__ import annotations

import inspect
import threading

from labscript_utils.ls_zprocess import ProcessTree


_TABLE_MACROS = {}
_TABLE_MACROS_LOCK = threading.RLock()


def _validate_table_macro_function(func):
    if not callable(func):
        raise TypeError("Table recreation decorators must wrap a callable.")
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError) as exc:
        raise TypeError("Table recreation decorators require a Python function.") from exc
    for parameter in signature.parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            raise TypeError(
                "@hyde.table recreation macros only support positional parameters."
            )
    return signature


def register_table_macro(func):
    signature = _validate_table_macro_function(func)
    with _TABLE_MACROS_LOCK:
        _TABLE_MACROS[func.__name__] = {
            "func": func,
            "args": list(signature.parameters),
        }
    return func


def clear_table_macros():
    with _TABLE_MACROS_LOCK:
        _TABLE_MACROS.clear()


def table_macro_names():
    with _TABLE_MACROS_LOCK:
        return tuple(sorted(_TABLE_MACROS))


def table_macro_entries():
    with _TABLE_MACROS_LOCK:
        return tuple(
            {
                "name": name,
                "args": list(_TABLE_MACROS[name]["args"]),
            }
            for name in sorted(_TABLE_MACROS)
        )


def serialize_table_macro_registry():
    return {
        "kind": "table",
        "macros": list(table_macro_entries()),
    }


def publish_table_macro_registry():
    try:
        tree = ProcessTree.instance()
        if tree is None or not hasattr(tree, "to_parent"):
            return
        tree.to_parent.put([
            "WINDOW_MACROS_RESPONSE",
            serialize_table_macro_registry(),
        ])
    except Exception:
        pass
