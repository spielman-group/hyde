def _numbered_suffix(prefix, name, *, omit_zero=False):
    text = str(name)
    if omit_zero and text == prefix:
        return 0
    if not text.startswith(prefix):
        return None
    suffix = text[len(prefix) :]
    if omit_zero:
        if not suffix.startswith("_"):
            return None
        suffix = suffix[1:]
    if not suffix.isdigit():
        return None
    return int(suffix)


def resolve_requested_name(prefix, existing_names, requested_name=None, *, omit_zero=False):
    existing = {str(name) for name in existing_names}
    requested = None if requested_name in (None, "") else str(requested_name)
    if requested and requested not in existing:
        return requested
    current = 0
    if requested:
        suffix = _numbered_suffix(prefix, requested, omit_zero=omit_zero)
        if suffix is not None:
            current = suffix + 1
    candidate = prefix if omit_zero and current == 0 else _candidate_name(prefix, current, omit_zero=omit_zero)
    while candidate in existing:
        current += 1
        candidate = _candidate_name(prefix, current, omit_zero=omit_zero)
    return candidate


def _candidate_name(prefix, index, *, omit_zero=False):
    if omit_zero and index == 0:
        return str(prefix)
    if omit_zero:
        return f"{prefix}_{index}"
    return f"{prefix}{index}"
