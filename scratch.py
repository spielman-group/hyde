import re

with open("hyde/user_interface/main/__init__.py", "r") as f:
    text = f.read()

# Remove offer_to_create_procedures_init
text = re.sub(r'    def offer_to_create_procedures_init\(self\):\n        pass # Now managed gracefully by kernel new_project\n', '', text)
# Remove write_default_procedures_init
text = re.sub(r'    def write_default_procedures_init\(self\):\n        pass\n', '', text)
# Remove maybe_trigger_project_state_load
text = re.sub(r'    def maybe_trigger_project_state_load\(self\):\n        pass # Now driven entirely by kernel IPC, we no longer artificially try to inject load strings\n', '', text)
# Remove prompt_for_save_as_project (already not used anywhere! wait, is it? save_project_as uses it!)
# Let me check if prompt_for_save_as_project is used.

with open("hyde/user_interface/main/__init__.py", "w") as f:
    f.write(text)
