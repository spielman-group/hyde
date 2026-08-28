import copy

from hyde.features.lmfit_features import LmfitCodec
from hyde.user_interface.shared.core import HydeIR


class LmfitIR(HydeIR):
    codec = LmfitCodec

    def __init__(self, *, state=None):
        self._state = (
            self.codec.default_state()
            if state is None
            else self.codec.normalize_state(state)
        )
        self._context = {}
        self.set_commit_command()

    def debug_state(self):
        return {
            "state": self.codec.normalize_state(self._state),
            "context": copy.deepcopy(self._context),
        }

    def validate(self):
        self.codec.validate_state(self._state)
        return self

    def normalized_state(self):
        return self.codec.normalize_state(self._state)

    def present_state(self):
        return self.codec.present_state(self._state, context=self._context)

    def set_context(self, context):
        self._context = copy.deepcopy(context or {})
        return self

    def apply_action(self, action):
        self._state = self.codec.update_state(self._state, action)
        return self

    def set_command(self, command):
        self.apply_action({"type": "set_command", "command": str(command)})
        return self

    def set_commit_command(self):
        self.set_command("commit")
        self.apply_action({"type": "clear", "path": ("settings", "preview_target_name")})
        self.apply_action({"type": "clear", "path": ("settings", "target_name")})
        self.apply_action({"type": "clear", "path": ("settings", "previous_target_name")})
        return self

    def set_preview_command(self, *, preview_target_name):
        self.set_command("preview")
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "preview_target_name"),
                "value": str(preview_target_name),
            }
        )
        self.apply_action({"type": "clear", "path": ("settings", "target_name")})
        self.apply_action({"type": "clear", "path": ("settings", "previous_target_name")})
        return self

    def set_live_command(
        self,
        *,
        previous_target_name,
        restore_store_name,
        missing_sentinel_name,
    ):
        self.set_command("live")
        if previous_target_name:
            self.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "previous_target_name"),
                    "value": str(previous_target_name),
                }
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "previous_target_name")})
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "restore_store_name"),
                "value": str(restore_store_name),
            }
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "missing_sentinel_name"),
                "value": str(missing_sentinel_name),
            }
        )
        self.apply_action({"type": "clear", "path": ("settings", "preview_target_name")})
        self.apply_action({"type": "clear", "path": ("settings", "target_name")})
        return self

    def set_store_target_command(
        self,
        target_name,
        *,
        restore_store_name,
        missing_sentinel_name,
    ):
        self.set_command("store_target")
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "target_name"),
                "value": str(target_name),
            }
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "restore_store_name"),
                "value": str(restore_store_name),
            }
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "missing_sentinel_name"),
                "value": str(missing_sentinel_name),
            }
        )
        self.apply_action({"type": "clear", "path": ("settings", "preview_target_name")})
        self.apply_action({"type": "clear", "path": ("settings", "previous_target_name")})
        return self

    def set_restore_target_command(
        self,
        target_name,
        *,
        restore_store_name,
        missing_sentinel_name,
    ):
        self.set_command("restore_target")
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "target_name"),
                "value": str(target_name),
            }
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "restore_store_name"),
                "value": str(restore_store_name),
            }
        )
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "missing_sentinel_name"),
                "value": str(missing_sentinel_name),
            }
        )
        self.apply_action({"type": "clear", "path": ("settings", "preview_target_name")})
        self.apply_action({"type": "clear", "path": ("settings", "previous_target_name")})
        return self

    def set_x_name(self, independent_var, x_name):
        path = ("settings", "x_names", str(independent_var))
        if x_name:
            self.apply_action({"type": "set", "path": path, "value": x_name})
        else:
            self.apply_action({"type": "clear", "path": path})
        return self

    def set_fit_result_name(self, fit_result_name, *, locked):
        if fit_result_name:
            self.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "fit_result_name"),
                    "value": fit_result_name,
                }
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "fit_result_name")})
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "fit_result_name_locked"),
                "value": bool(locked and fit_result_name),
            }
        )
        return self

    def set_coefficient_field(self, parameter_name, field_name, value):
        path = ("settings", "coefficients", str(parameter_name), str(field_name))
        if field_name == "vary":
            self.apply_action({"type": "set", "path": path, "value": bool(value)})
            return self
        if str(value or "").strip():
            self.apply_action({"type": "set", "path": path, "value": str(value).strip()})
        else:
            self.apply_action({"type": "clear", "path": path})
        return self

    def _python_source(self):
        return str(self.codec.state_to_python(self._state, context=self._context) or "").strip()
