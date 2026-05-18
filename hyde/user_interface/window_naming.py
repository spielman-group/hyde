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
