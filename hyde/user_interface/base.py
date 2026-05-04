import logging
import pprint

import hyde
from hyde.features.hyde_features import MutationCodec, RuntimeCommandCodec


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

    def macro_source(self, macro_name):
        normalized = self.validate_state()
        # Keep the shared macro hook in the base API so feature states can expose
        # recreation-source generation through the same interface as python_source().
        source = self.codec.state_to_macro_source(self._state, macro_name)
        if hyde.HYDE_DEBUG:
            logging.getLogger("hyde").debug(
                "[Hyde state] %s\nstate:\n%s\npython:\n%s",
                type(self).__name__,
                pprint.pformat(normalized, sort_dicts=True),
                source,
            )
        return source


class MutationState(HydeGuiState):
    # Keep MutationState in the shared base module because it is a reusable
    # cross-feature GUI state, not a table-owned specialization.
    codec = MutationCodec

    def set_command(self, command):
        self.apply_action({"type": "set_command", "command": command})

    def set_edit_value(self, var_name, index, value_text):
        self.set_command("edit_value")
        self.apply_action({"type": "set", "path": ("settings", "var_name"), "value": var_name})
        self.apply_action({"type": "set", "path": ("settings", "index"), "value": index})
        self.apply_action({"type": "set", "path": ("settings", "value_text"), "value": value_text})
        self.apply_action({"type": "clear", "path": ("settings", "indices")})

    def set_append_value(self, var_name, value_text):
        self.set_command("append_value")
        self.apply_action({"type": "set", "path": ("settings", "var_name"), "value": var_name})
        self.apply_action({"type": "set", "path": ("settings", "value_text"), "value": value_text})
        self.apply_action({"type": "clear", "path": ("settings", "index")})
        self.apply_action({"type": "clear", "path": ("settings", "indices")})

    def set_create_array(self, value_text, existing_names):
        new_name = self.codec.suggest_new_array_name(existing_names, value_text)
        self.set_command("create_array")
        self.apply_action({"type": "set", "path": ("settings", "var_name"), "value": new_name})
        self.apply_action({"type": "set", "path": ("settings", "value_text"), "value": value_text})
        self.apply_action(
            {"type": "set", "path": ("settings", "existing_names"), "value": list(existing_names)}
        )
        self.apply_action({"type": "clear", "path": ("settings", "index")})
        self.apply_action({"type": "clear", "path": ("settings", "indices")})
        return new_name

    def set_delete_indices(self, var_name, indices):
        self.set_command("delete_indices")
        self.apply_action({"type": "set", "path": ("settings", "var_name"), "value": var_name})
        self.apply_action({"type": "set", "path": ("settings", "indices"), "value": list(indices)})
        self.apply_action({"type": "clear", "path": ("settings", "index")})
        self.apply_action({"type": "clear", "path": ("settings", "value_text")})

    def set_delete_name(self, var_name):
        self.set_command("delete_name")
        self.apply_action(
            {"type": "set", "path": ("settings", "var_name"), "value": var_name}
        )
        self.apply_action({"type": "clear", "path": ("settings", "index")})
        self.apply_action({"type": "clear", "path": ("settings", "indices")})
        self.apply_action({"type": "clear", "path": ("settings", "value_text")})


class RuntimeCommandState(HydeGuiState):
    codec = RuntimeCommandCodec

    def set_command(self, command):
        self.apply_action({"type": "set_command", "command": command})

    def set_reload_procedures(
        self,
        project_dir,
        hyde_source_root,
        *,
        reset_namespace=False,
    ):
        self.set_command("reload_procedures")
        self.apply_action(
            {"type": "set", "path": ("settings", "project_dir"), "value": project_dir}
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "hyde_source_root"),
                "value": hyde_source_root,
            }
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "reset_namespace"),
                "value": bool(reset_namespace),
            }
        )
        self.apply_action({"type": "clear", "path": ("settings", "request_filepath")})

    def set_remote_request(self, request_filepath):
        self.set_command("remote_request")
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "request_filepath"),
                "value": request_filepath,
            }
        )
        self.apply_action({"type": "clear", "path": ("settings", "project_dir")})
        self.apply_action(
            {"type": "clear", "path": ("settings", "hyde_source_root")}
        )

    def set_callable_invocation(self, callable_name, args):
        self.set_command("callable_invocation")
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "callable_name"),
                "value": callable_name,
            }
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "callable_args"),
                "value": list(args or []),
            }
        )
        self.apply_action({"type": "clear", "path": ("settings", "project_dir")})
        self.apply_action(
            {"type": "clear", "path": ("settings", "hyde_source_root")}
        )
        self.apply_action(
            {"type": "clear", "path": ("settings", "request_filepath")}
        )
