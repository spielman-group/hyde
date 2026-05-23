class ExampleCodec:
    """
    Template feature-layer codec.

    Put validation and command lowering here, not in the dialog.

    If the plugin owns a Python package or domain surface, this module is the place to
    import and lower that package-specific behavior.

    If the plugin uses a package owned elsewhere, replace this module with calls into
    the existing `hyde.features/..._features.py` owner rather than duplicating logic.
    """

    def validate_state(self, state):
        target_name = str(state.get("target_name") or "").strip()
        if not target_name:
            return {"valid": False, "message": "Choose a target name."}
        return {"valid": True, "message": ""}

    def state_to_python(self, state):
        target_name = str(state.get("target_name") or "").strip()
        enabled = bool(state.get("enabled"))
        return "\n".join(
            [
                f"{target_name} = {target_name}",
                f"{target_name}.enabled = {enabled!r}",
            ]
        )
