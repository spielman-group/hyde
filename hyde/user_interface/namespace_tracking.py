from __future__ import annotations


def _freeze_value(value):
    if isinstance(value, dict):
        return tuple(
            (str(key), _freeze_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_value(item) for item in value))
    return value


def tracked_namespace_signature(view, names):
    tracked = []
    view = dict(view or {})
    for name in names:
        metadata = dict(view.get(name, {}) or {})
        tracked.append((name, _freeze_value(metadata)))
    return tuple(tracked)
