from abc import ABC, abstractmethod


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
