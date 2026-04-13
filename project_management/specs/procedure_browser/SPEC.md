# Specification: Procedure Browser

The Procedure Browser is a central hub for managing the scientific scripts and environment setup for a Hyde project. It ensures that the kernel state is explicit and reproducible.

## UI Design
- **Container**: An MDI sub-window (accessible via `Windows > Procedures`).
- **View**: A simple list or tree view showing all `.py` files inside the `procedures/` directory of the current `.hy` project.
- **Interactions**:
    - **Single Click**: Selection.
    - **Double Click**: Opens the script in the **default system editor** for that file type (using `QDesktopServices`).
    - **Right Click**: No action currently defined.

## Kernel Initialization Logic
Hyde follows the "Explicit is Better than Implicit" rule by running a `master.py` script on startup.

### `master.py` Requirements
Every project must contain a `procedures/master.py`. It should typically contain:
```python
import hyde
import numpy as np
import matplotlib
matplotlib.use('Hyde') # custom backend
import matplotlib.pyplot as plt
```

### Automation
1. When Hyde starts or a project is loaded, the GUI sends the following sequence to **Lane 2 (Execution)**:
   ```python
   import os
   os.chdir("path/to/project/root")
   with open("procedures/master.py") as f:
       exec(f.read())
   ```
2. This ensures that the global namespace in the Command Window (IPython) is instantly identical to the state defined in the master script.

## Filesystem Monitoring
The Procedure Browser is only a view onto the `procedures/` directory. Tracking changes to
`master.py` and other procedure files, and deciding when the execution namespace must be
re-synchronized, is a core execution feature and must not be owned by the Procedure Browser.

This monitoring should live on the execution side and follow the same style of file tracking
used elsewhere in the suite, specifically `labscript_utils.filewatcher.FileWatcher` as used by
the BLACS connection table plugin.

## Technical Details
- **Path Handling**: The browser is rooted at `procedures/`, and displayed paths are relative to
  that directory.
- **Safety**: If `master.py` is missing, the kernel successfully starts but the GUI should warn the user and offer to create a default template.
