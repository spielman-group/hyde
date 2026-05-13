def next_numbered_name(prefix, existing_names, counter=0):
    existing = {str(name) for name in existing_names}
    current = int(counter)
    candidate = f"{prefix}{current}"
    while candidate in existing:
        current += 1
        candidate = f"{prefix}{current}"
    return candidate, current + 1


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


def window_title(stable_name, title=None, detail_text=None, warning_text=None):
    stable_name = str(stable_name)
    title_text = str(title).strip() if title is not None else ""
    detail = str(detail_text).strip() if detail_text is not None else ""
    suffix = ""
    if title_text:
        suffix = title_text
    elif detail:
        suffix = detail
    base_title = stable_name if not suffix else f"{stable_name}: {suffix}"
    warning = str(warning_text).strip() if warning_text is not None else ""
    if warning:
        return f"{base_title} [{warning}]"
    return base_title
