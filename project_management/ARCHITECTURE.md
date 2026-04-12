# Hyde Architecture & Design Philosophy

## The Central Dogma
The core tenet of Hyde's design is the strict separation of concerns between the **Presentation Layer (GUI Process)** and the **State Layer (Execution Subprocess)**.

1. **The GUI has UX Memory, but no Scientific Memory.** The PyQt MDI application remembers window positions, table viewports, and browser states. It may also hold intermediate data structures (e.g., dicts representing a figure's editable state), but this state must be fully determined by the underlying Python code and is only used to regenerate updated Python commands. The GUI does not hold the actual array data or manipulate python/matplotlib objects natively.
2. **The Execution namespace is authoritative.** All named data objects, calculations, and plotting configurations live inside an independent Python execution process. The kernel should remain completely agnostic of Hyde's internal GUI representations; it simply executes standard Matplotlib code.
3. **The Metadata Mirror Model.** For scientific visualization (figures, tables), the Kernel process provides the authoritative raw data and metadata (state), but remains agnostic of windowing. The GUI process receives this metadata via `comm` channels and performs its own local rendering using its own Matplotlib/UI installation.
    - **Pros**: Zero "UI weight" in the kernel; highly responsive GUI-side interactivity; low bandwidth for most operations.
    - **Cons**: Requires state-synchronization logic for the "managed subset" of features.
4. **2-Lane IPC Strategy.**
    - **Lane 1 (Control)**: `zprocess.ProcessTree` handles application-level orchestration (launch, heartbeats, QUIT). Analytical commands do NOT traverse this tree.
    - **Lane 2 (Execution)**: Standard Jupyter ZMQ and `comm` channels handle all scientific traffic, including code execution, figure metadata/rendering, and scientific state synchronization.
5. **App-level I/O is a GUI responsibility.** Operations such as package saving and loading (`.hy` files) are managed natively by the GUI process.

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
├── procedures/     # Python scripts
│   └── master.py   # Mandatory entry point script
├── data/           # Array data
├── figures/        # Figure scripts
└── tables/         # Table data
```

### Explicit Initialization & Synchronization
To ensure "Explicit is better than Implicit," Hyde enforces a strict initialization sequence:
1. **Bootstrap**: Upon startup or project load, the GUI ensures a project structure exists.
2. **Master Execution**: The GUI automatically executes `master.py` in the kernel namespace to establish the environment.
3. **Run-on-Save**: The GUI monitors `master.py` for changes. Whenever it is saved, the script is re-executed in the kernel, ensuring the interactive session remains synchronized with the code.

### Procedure Browser
The **Procedure Browser** (an MDI window) provides the primary UI for managing these scripts. It lists the contents of the `procedures/` directory and allows the user to open scripts in their system's default editor via double-click.

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
- **Lane 2 (Execution):** Standard Jupyter ZMQ sockets and `comm` channels bridge the GUI directly to the Kernel for all scientific traffic (execution, figures, and metadata updates).

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

### Implementation Approach: The Metadata Mirror

Hyde implements a local-rendering "mirror" strategy to ensure the GUI is interactive while the kernel remains headless.

1. **Kernel Bridge (`backend_hyde`)**: A custom Matplotlib backend subclassed from `matplotlib.backend_bases.FigureCanvasBase`. 
   - It captures `draw()` and `show()` calls.
   - It extracts a serializable metadata snapshot of the figure (the "Managed Subset": axes, labels, data) and emits it over a Jupyter `comm` channel.
   - It does NOT instantiate any PyQt widgets or enter a GUI event loop.

2. **GUI Figure Window (`hyde.user_interface.figure_window`)**:
   - Maintains its own local `matplotlib.backends.backend_qtagg.FigureCanvasQTAgg`.
   - Listens for `comm` updates and synchronizes its local `Figure` object with the state received from the kernel.
   - Handles `pick_event` and mouse clicks natively to spawn Hyde dialogs (e.g. Axis Editor).

3. **String Factory**: Changes made in the GUI generate Python strings (e.g. `plt.title(...)`) sent back to the kernel to maintain the authoritative scientific state.

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

New projects include a `procedures/master.py` that establishes the baseline environment. It must contain:

```python
import hyde         # Hyde-specific functions (e.g. open_table)
import numpy as np 
import matplotlib
# matplotlib.use('Hyde')  # Explicitly set the Hyde backend (when implemented)
import matplotlib.pyplot as plt 
import lmfit        # For curve fitting
```

This ensures that any researcher opening the project instantly understands how the scientific namespace is configured.
