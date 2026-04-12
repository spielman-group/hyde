# Hyde Architecture & Design Philosophy

## The Central Dogma
The core tenet of Hyde's design is the strict separation of concerns between the **Presentation Layer (GUI Process)** and the **State Layer (Execution Subprocess)**.

1. **The GUI has UX Memory, but no Scientific Memory.** The PyQt MDI application remembers window positions, table viewports, and browser states. It may also hold intermediate data structures (e.g., dicts representing a figure's editable state), but this state must be fully determined by the underlying Python code and is only used to regenerate updated Python commands. The GUI does not hold the actual array data or manipulate python/matplotlib objects natively.
2. **The Execution namespace is authoritative.** All named data objects, calculations, and plotting configurations live inside an independent Python execution process (powered by a Jupyter/IPython kernel).
3. **The kernel is not hidden.** The GUI features a "Command Window" as a direct front-end to the execution shell. Virtually every GUI-generated action that creates a *durable* change to the data's state will construct chunks of human-readable Python code as strings, and these strings will be executed and displayed in the Command Window. Temporary "live updates" (e.g., dragging a fit slider) are exempt from spamming the history.
4. **App-level I/O is a GUI responsibility.** Operations such as package saving and loading (`.hy` files) are managed natively by the GUI process.

---

## Technical Constraints & Boundaries

### The IPC Boundary
To the extent possible, IPC uses the `zprocess.ProcessTree` leveraged by other labscript applications. However, for direct frontend-to-kernel execution and output bridging, Hyde relies on standard zero-MQ Jupyter messages (`spyder_kernels` and `qtconsole`). 

Because the architecture relies on the UI sending code strings and waiting for structural updates over comm channels, developers are prevented from implementing tightly-coupled frontend-backend manipulations. This forces inherently reproducible user actions.

### Dynamic State Tracking (The Spyder Pattern)
To achieve "live updates" in the UI (e.g., updating a table when an array changes in the terminal), Hyde implements a variable tracking methodology explicitly modeled after the **Spyder IDE** (https://github.com/spyder-ide/spyder). 
- **Important:** Developers are highly encouraged to reference Spyder's variable explorer architecture and `comm` implementations directly during development.
- The execution subprocess monitors its own namespace for changes.
- When an object modification occurs, it pushes metadata notifications to the GUI over the IPC boundary.
- The GUI figures/tables then selectively request refreshed data to re-render.

---

# Draft Implementation Proposals

The following sections define the draft architectural patterns and specific structural decisions that will guide implementation through Phase II and beyond.

## Package Structure

```
hyde/
├── hyde/                      # Main package
│   ├── __init__.py            # Public exports
│   ├── __main__.py            # CLI entry point / MDI Launch
│   ├── execution/             # Backend Control Layer
│   │   ├── __init__.py
│   │   └── execution_controller.py # The Watchdog Process
│   ├── features/              # Feature implementations
│   │   ├── __init__.py
│   │   ├── lmfit_features.py
│   │   ├── matplotlib_features.py
│   │   └── ....
│   └── user_interface/       # Per-window packages
│       ├── main/
│       │   ├── __init__.py
│       │   └── main.ui
│       ├── command_window/
│       │   └── __init__.py    # RichJupyterWidget bridge
│       └── ...
└── tests/
    ├── test_watchdog.py      # Architecture integration tests
    └── ...
```

## Feature implementations

The overall function of the Hyde GUI is to provide easy access to specific underlying Python packages, starting with matplotlib and lmfit. Each file in `features` interfaces with a specific Python package.

The expected interface centers on dialog boxes that define behavior and result in an output string (possibly multiline) that will be sent to a Python process and executed line-by-line. Thus the dialogs define a state and the `..._features.py` files convert such a state to a valid set of Python commands.

## Project and Persistence

A Hyde project is a directory package with `.hy` suffix:

```
example.hy/
├── manifest.toml   # Package metadata, object registry
├── session.toml    # Session state
├── terminal/
│   └── history.py  # Command history
├── procedures/     # Procedures and scripts (including master.py)
├── data/           # Array data
├── figures/        # Figure scripts
└── tables/         # Table data
```

- Paths inside the package are relative for portability
- `manifest.toml` records package version, saved layout, object registry
- `session.toml` records open windows, current state
- Scripts are plain `.py` files
- Array data is stored in numpy format (`.npy`)
- Human-readable settings use TOML or JSON

## IPC: The 3-Process Model

Hyde operates across three distinct processes to ensure the GUI remains responsive and the scientific state remains authoritative and isolated:

1. **Main Process (GUI):** Owns the `QMdiArea`, the `ProcessTree.instance()`, and the `JupyterClient` sockets.
2. **Execution Controller (Watchdog):** A child process launched via `zprocess`. It monitors the kernel lifecycle and reports `KERNEL_READY` / `KERNEL_CRASHED` alerts.
3. **The Kernel (spyder_kernels):** The isolated IPython engine.

### Communication Lanes
- **Lane 1 (Control):** `zprocess.ProcessTree` handles application-level orchestration between the GUI and the Watchdog.
- **Lane 2 (Data):** Standard Jupyter ZMQ sockets bridge the GUI directly to the Kernel for execution and figure/table metadata updates.

## Execution

The execution subprocess runs in a separate Python process using the `spyder_kernels` Jupyter kernel. This provides:
- Full IPython functionality
- Namespace tracking for data browser
- Comm-based notifications for live figure/table refresh
- Mature, well-tested architecture

The GUI sends raw Python code to the kernel for execution - there is no special GUI-to-kernel protocol.

## Tracking of Changed Objects

Dynamic update of figures and tables (and possibly other elements) requires tracking of changes to objects in the execution namespace.

Agents implementing this should look at existing solutions such as Spyder, which includes a variable explorer with dynamic updates. Their GitHub is at https://github.com/spyder-ide/spyder. Their website is at https://www.spyder-ide.org.

Agents are encouraged to explore and copy existing solutions, and use existing Python libraries rather than reinventing solutions.

### Per-GUI element/window package structure

Each window in its own subdirectory under `user_interface/`:

```
window_name/
├── __init__.py   # Loads .ui, defines widget class
└── window_name.ui     # Qt Designer file
```

Main window also lives in a subdirectory.

## Widget Types

- **MDI Children**: Figures, tables, browsers in QMdiArea
- **Dialogs**: Modal dialogs for editing operations
- **Drop down menus**: 

### Command Window

The command window uses the `spyder_kernels` Jupyter kernel, with the frontend provided by qtconsole's RichJupyterWidget embedded in the main window.

The user should experience it as a direct "window" to the execution subprocess kernel.

It provides:
- Tab completion
- Up arrow/down arrow to scroll through command history
- syntax highlighting
- ... all other expected IPython behaviors

Unlike Igor Pro, there is no separate command entry box at the bottom, and no line numbers other than what IPython typically generates.

Using spyder_kernels provides:
- Proper namespace tracking for the data browser
- Comm-based change notifications for live figure refresh
- Matplotlib backend integration
- Mature, well-tested architecture

## Figures

Figures are generated by matplotlib and captured by Hyde to be displayed as MDI windows. This is implemented by writing a custom matplotlib backend.

### Implementation Approach

The custom backend will be derived from `matplotlib.backends.backend_qtagg`, **not** built from scratch on `matplotlib.backend_bases`. Subclassing `FigureCanvasQTAgg` and `FigureManagerQT` gives us the entire Qt/Agg rendering pipeline, mouse/keyboard event translation, and the standard `NavigationToolbar2QT` for free.

The primary customization points are:

1. **`FigureManagerHyde(FigureManagerQT)`**: Override `show()` to route the figure canvas into the GUI's `QMdiArea` as a sub-window instead of opening a standalone `QMainWindow`. The manager will send a metadata notification to the GUI over a Jupyter `comm` channel so the GUI can create the MDI wrapper.

2. **`FigureCanvasHyde(FigureCanvasQTAgg)`**: Minimal subclass, primarily to register the custom backend. May override `destroy()` to coordinate MDI sub-window cleanup.

3. **Backend registration**: The kernel will be configured to use this backend via `matplotlib.use('module://hyde.features.matplotlib_backend')` in the default procedure imports.

This approach provides full interactivity (pan, zoom, pick events) with minimal custom code. Static-image fallback (inline PNG/SVG) is deliberately not pursued — the goal is native interactive figures embedded in the MDI workspace.

## Message Protocol

Incoming message handling replicates the protocol defined in the `lyse` project.

## Execution Helpers

The GUI generates complete Python statements using underlying libraries (matplotlib, lmfit) rather than wrapping them in custom helper functions.

For example, when the user asks to display data, Hyde does not call a `display()` function. Instead, Hyde generates the explicit object-oriented matplotlib code that creates the figure, such as:
```python
fig = plt.figure()
gs = fig.add_gridspec(...)
ax = fig.add_subplot(gs[0, 0])
ax.plot(x, y)
```

The runtime provides only functions that are not present in the supported libraries, for example:
- `open_table(...)`: Open a table view (not provided by a supported library)

This ensures all GUI actions generate the same Python code that could be written manually in the terminal.

## Default Procedures

New projects include `procedures/master.py` which must contain:
```python
from hyde import *
import numpy as np
import matplotlib.pyplot as plt
# code to set custom hyde backend
import lmfit
```

This required set of imports will grow as more libraries are added.
