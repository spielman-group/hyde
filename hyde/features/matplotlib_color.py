import ast

from matplotlib import colors as mcolors


def rgba_from_matplotlib_color(value):
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("Color text is empty.")
        try:
            return mcolors.to_rgba(stripped)
        except ValueError:
            literal = ast.literal_eval(stripped)
            return mcolors.to_rgba(literal)
    return mcolors.to_rgba(value)


def normalize_matplotlib_color_text(value, *, allow_auto=False, allow_empty=True):
    text = "" if value is None else str(value).strip()
    if not text:
        return "" if allow_empty else None
    if allow_auto and text.lower() == "auto":
        return "auto"
    try:
        rgba = rgba_from_matplotlib_color(text)
    except Exception:
        return None
    keep_alpha = abs(float(rgba[3]) - 1.0) > 1e-9
    return mcolors.to_hex(rgba, keep_alpha=keep_alpha)
