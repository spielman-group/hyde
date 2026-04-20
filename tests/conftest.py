import os
import sys


# Suppress labscript's Tk error dialog during automated tests, including in
# spawned Hyde child processes that inherit this environment.
os.environ.setdefault("HYDE_DISABLE_LABSCRIPT_ERROR_DIALOGS", "1")
sys.excepthook = sys.__excepthook__
