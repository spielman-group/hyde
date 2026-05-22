from __future__ import annotations

import ast
import keyword
import os
import tempfile


class CurveFitCatalogError(ValueError):
    """Raised when the Curve Fit catalog cannot scaffold a new fit function."""


def validate_fit_function_name(name):
    candidate = (name or "").strip()
    if not candidate:
        raise CurveFitCatalogError("A function name is required.")
    if not candidate.isidentifier() or keyword.iskeyword(candidate):
        raise CurveFitCatalogError(
            "Fit function names must be valid Python identifiers."
        )
    return candidate


def _top_level_function_names(text):
    try:
        tree = ast.parse(text or "")
    except SyntaxError as exc:
        raise CurveFitCatalogError(
            "Unable to parse procedures/__init__.py."
        ) from exc
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def inspect_fit_function_conflict(path, name):
    candidate = validate_fit_function_name(name)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if candidate in _top_level_function_names(text):
        return candidate
    return None


def fit_function_scaffold_source(name):
    candidate = validate_fit_function_name(name)
    return (
        '@hyde.fit_function(independent_vars=("x",))\n'
        f"def {candidate}(x, c0):\n"
        "    return c0 * x\n"
    )


def write_fit_function_scaffold(path, name):
    candidate = validate_fit_function_name(name)
    if inspect_fit_function_conflict(path, candidate) is not None:
        raise CurveFitCatalogError(
            f"{candidate} already exists in procedures/__init__.py."
        )

    text = ""
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()

    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    updated = text + fit_function_scaffold_source(candidate)

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix="hyde-fit-function-",
        suffix=".py",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return updated
