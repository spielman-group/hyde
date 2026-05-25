import keyword
from abc import ABC, abstractmethod


def coerce_path(path):
    return tuple(path or ())


def set_path(state, path, value):
    target = state
    path = coerce_path(path)
    for key in path[:-1]:
        next_target = target.get(key)
        if next_target is None:
            next_target = {}
            target[key] = next_target
        elif not isinstance(next_target, dict):
            raise KeyError(f"Cannot descend through non-mapping path segment {key!r}.")
        target = next_target
    target[path[-1]] = value


def ordered_unique(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_optional_text(value):
    text = str(value or "").strip()
    return None if not text else text


def ordered_unique_text(values):
    normalized_values = []
    for value in values:
        normalized_text = normalize_optional_text(value)
        if normalized_text is None:
            continue
        normalized_values.append(normalized_text)
    return ordered_unique(normalized_values)


def valid_python_identifier(text):
    normalized_text = normalize_optional_text(text)
    if normalized_text is None:
        return False
    return normalized_text.isidentifier() and not keyword.iskeyword(normalized_text)


class FeatureCodec(ABC):
    feature_name = None
    state_version = 1

    @classmethod
    @abstractmethod
    def default_state(cls):
        """Return a fresh canonical state object."""

    @classmethod
    @abstractmethod
    def normalize_state(cls, state):
        """Return canonicalized state with defaults filled."""

    @classmethod
    @abstractmethod
    def validate_state(cls, state):
        """Validate state or raise ValueError."""

    @classmethod
    @abstractmethod
    def update_state(cls, state, action):
        """Apply an action and return canonicalized state."""

    @classmethod
    @abstractmethod
    def state_to_python(cls, state, context=None):
        """Lower canonical state to standard Python source."""

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        """Lower canonical state to recreation macro source when supported."""
        # Keep the base macro hook even when only a subset of features use it:
        # recreation-capable states should expose one shared codec interface.
        del state, macro_name, context
        raise NotImplementedError(f"{cls.__name__} does not support macro source generation.")
