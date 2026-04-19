import re

with open("tests/test_project_save_load.py", "r") as f:
    text = f.read()

text = text.replace("save_state", "save_project")
text = text.replace("load_state", "load_project")

with open("tests/test_project_save_load.py", "w") as f:
    f.write(text)

