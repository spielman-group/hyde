import logging
import pprint

import hyde


class HydeGuiState:
    codec = None

    def __init__(self):
        if self.codec is None:
            raise ValueError("HydeGuiState subclasses must define a codec.")
        self._state = self.codec.default_state()
        self.configure_defaults()

    def configure_defaults(self):
        """Hook for subclasses to seed local GUI state defaults."""

    def apply_action(self, action):
        self._state = self.codec.update_state(self._state, action)
        return self._state

    def normalized_state(self):
        return self.codec.normalize_state(self._state)

    def validate_state(self):
        return self.codec.validate_state(self._state)

    def python_source(self):
        normalized = self.validate_state()
        source = self.codec.state_to_python(self._state)
        if hyde.HYDE_DEBUG:
            logging.getLogger("hyde").debug(
                "[Hyde state] %s\nstate:\n%s\npython:\n%s",
                type(self).__name__,
                pprint.pformat(normalized, sort_dicts=True),
                source,
            )
        return source
