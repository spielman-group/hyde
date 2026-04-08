from __future__ import annotations

import ast
import functools
from dataclasses import dataclass
from pathlib import Path


HYDE_DECORATOR_NAMES = {
    "figure": "figure",
    "table": "table",
    "fit_function": "fit_function",
    "procedure": "procedure",
}


def _decorate(kind):
    def decorator(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            result = function(*args, **kwargs)
            hook = function.__globals__.get("_hyde_register_result")
            if callable(hook):
                return hook(kind, function.__name__, result)
            return result

        wrapped.__hyde_kind__ = kind
        return wrapped

    return decorator


figure = _decorate("figure")
table = _decorate("table")
fit_function = _decorate("fit_function")
procedure = _decorate("procedure")


@dataclass(frozen=True)
class ScriptEntry:
    path: str
    function_name: str
    kind: str
    title: str
    line_number: int
    parameters: tuple[str, ...] = ()


def _decorator_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return None


def discover_script_entries(path: str | Path):
    path = Path(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    entries = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            name = _decorator_name(decorator)
            kind = HYDE_DECORATOR_NAMES.get(name)
            if kind is None:
                continue
            entries.append(
                ScriptEntry(
                    path=str(path),
                    function_name=node.name,
                    kind=kind,
                    title=node.name.replace("_", " ").title(),
                    line_number=node.lineno,
                    parameters=tuple(
                        argument.arg
                        for argument in (
                            node.args.args[1:] if kind == "fit_function" else node.args.args
                        )
                    ),
                )
            )
            break
    return entries
