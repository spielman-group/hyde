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
The Procedure Browser must implement a `QFileSystemWatcher` on the `procedures/` directory to automatically update the view when files are added, removed, or renamed outside of Hyde.

## Technical Details
- **Path Handling**: All paths displayed are relative to the project root.
- **Safety**: If `master.py` is missing, the kernel successfully starts but the GUI should warn the user and offer to create a default template.
