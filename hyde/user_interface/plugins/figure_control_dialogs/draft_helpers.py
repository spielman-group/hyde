import copy


def normalize_empty_choice(value):
    if value in (None, "", "none", "None", " "):
        return "None"
    return str(value)


class FigureControlDraftTracker:
    def __init__(self):
        self.current_states = {}
        self._opening_states = {}
        self._revert_states = {}

    def seed(self, key, opening_state, revert_state=None):
        key = str(key)
        opening_copy = copy.deepcopy(opening_state)
        self._opening_states[key] = opening_copy
        self._revert_states[key] = copy.deepcopy(
            opening_state if revert_state is None else revert_state
        )
        self.current_states[key] = copy.deepcopy(opening_state)
        return self.current_states[key]

    def replace(self, key, state):
        key = str(key)
        self.current_states[key] = copy.deepcopy(state)
        return self.current_states[key]

    def update(self, key, patch):
        key = str(key)
        self.current_states[key].update(copy.deepcopy(patch))
        return self.current_states[key]

    def has_changes(self, key):
        key = str(key)
        return self.current_states[key] != self._opening_states[key]

    def changed_keys(self):
        return sorted(key for key in self.current_states if self.has_changes(key))

    def revert_state(self, key):
        key = str(key)
        return copy.deepcopy(self._revert_states[key])
