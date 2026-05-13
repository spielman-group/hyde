def _numbered_suffix(prefix, name):
    text = str(name)
    if not text.startswith(prefix):
        return None
    suffix = text[len(prefix) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def resolve_requested_name(prefix, existing_names, requested_name=None):
    existing = {str(name) for name in existing_names}
    requested = None if requested_name in (None, "") else str(requested_name)
    if requested and requested not in existing:
        return requested
    current = 0
    if requested:
        suffix = _numbered_suffix(prefix, requested)
        if suffix is not None:
            current = suffix + 1
    candidate = f"{prefix}{current}"
    while candidate in existing:
        current += 1
        candidate = f"{prefix}{current}"
    return candidate


def bind_stable_window_name(subwindow, name):
    stable_name = str(name)
    subwindow.setObjectName(stable_name)
    return stable_name


def stable_window_name(subwindow, fallback=None):
    if subwindow is None:
        return None if fallback is None else str(fallback)
    object_name = str(subwindow.objectName() or "").strip()
    if object_name:
        return object_name
    return None if fallback is None else str(fallback)


def window_title(stable_name, title_suffix=None, warning_text=None):
    stable_name = str(stable_name)
    suffix_text = str(title_suffix).strip() if title_suffix is not None else ""
    suffix = suffix_text
    base_title = stable_name if not suffix else f"{stable_name}: {suffix}"
    warning = str(warning_text).strip() if warning_text is not None else ""
    if warning:
        return f"{base_title} [{warning}]"
    return base_title
