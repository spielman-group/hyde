# Hyde Architecture & Design Philosophy

## The Central Dogma
The core tenet of Hyde's design is the strict separation of concerns between the **Presentation Layer (GUI Process)** and the **State Layer (Execution Subprocess)**.

1. **The GUI has UX Memory, but no Scientific Memory.** The PyQt MDI application remembers window positions, table viewports, and browser states. It may hold transient, serializable UI-edit state only when that state is sufficient to regenerate Python commands and is fully derived from the authoritative execution state. The GUI does not hold canonical scientific data, arrays, matplotlib objects, or analytical state natively.
2. **The Execution namespace is authoritative.** All named data objects, calculations, live matplotlib figures, and Hyde-owned internal state that must remain scientifically authoritative live inside an independent Python execution process. The GUI does not own that state. Hyde may attach kernel-owned feature state to live runtime objects when that is the narrowest way to keep runtime behavior and recreation behavior aligned.
3. **Metadata-over-Comms and Structured Relays.** GUI viewports that depend on execution metadata receive that metadata over the narrowest existing channel that fits the feature. Python Variables uses Spyder's namespace-view `comm` path. The implemented Table window uses a Hyde-owned `ProcessTree` relay for table-open intents and structured table-data payloads, while still relying on standard Jupyter execution for visible commands. Figure windows use Jupyter `comm` channels for metadata publication and semantic edit actions against kernel-owned figure state.
4. **2-Lane IPC Strategy.**
    - **Lane 1 (Control)**: `zprocess.ProcessTree` handles application-level orchestration (launch, heartbeats, QUIT). Analytical commands do NOT traverse this tree.
    - **Lane 2 (Execution)**: Standard Jupyter ZMQ and `comm` channels handle visible scientific execution, background execution, and namespace metadata. Hyde-specific relays should only extend this model when an existing path does not cleanly fit the feature.
5. **App-level I/O is a GUI responsibility.** Operations such as package saving and loading (`.hy` files) are coordinated by the GUI process, but kernel-state persistence still runs through explicit Hyde commands executed in the kernel.

---

## Technical Constraints & Boundaries

### The IPC Boundary
To the extent possible, IPC uses the `zprocess.ProcessTree` leveraged by other labscript applications. However, for direct frontend-to-kernel execution and output bridging, Hyde relies on standard zero-MQ Jupyter messages (`spyder_kernels` and `qtconsole`). 

Because the architecture relies on the UI sending reproducible commands or semantic edit actions and waiting for structural updates over comm channels, developers are prevented from implementing tightly-coupled frontend-backend manipulations. This forces inherently reproducible user actions.

### Dynamic State Tracking (The Spyder Pattern)
To achieve "live updates" in the UI (e.g., updating a table when an array changes in the terminal), Hyde implements a variable tracking methodology explicitly modeled after the **Spyder IDE** (https://github.com/spyder-ide/spyder). 
- **Important:** Developers are highly encouraged to reference Spyder's variable explorer architecture and `comm` implementations directly during development.
- The execution subprocess monitors its own namespace for changes.
- When an object modification occurs, it pushes metadata notifications to the GUI over the IPC boundary.
- The GUI figures/tables then selectively request refreshed data to re-render.

---

# Implemented Structure And Planned Extensions

The following sections distinguish between Hyde's implemented structure and the planned extensions that are not yet present in code.

## Package Structure

```
hyde/
├── hyde/                      # Main package
│   ├── __init__.py            # Public exports
│   ├── __main__.py            # CLI entry point / MDI Launch
│   ├── execution/             # Kernel launch and narrow IPC helpers
│   │   ├── __init__.py
│   │   └── kernel_launcher.py
│   └── user_interface/
│       ├── main/
│       │   ├── __init__.py    # Shell infrastructure and lifecycle fan-out
│       │   └── main.ui
│       ├── plugins/           # First-party UI plugins discovered by Hyde
│       │   ├── python_terminal/
│       │   ├── table/
│       │   └── ...
│       ├── plugin_tools.py    # Shared plugin infrastructure
│       └── ...
└── tests/
    ├── test_watchdog.py      # Architecture integration tests
    └── ...
```

## Hyde Package Surface

`import hyde` is valid in the kernel and in project procedures because Hyde is an installable Python package. At present, this package does not expose a broad helper API beyond the package itself.

Anything exposed from `hyde/__init__.py` is part of Hyde's public kernel-facing API.
Public helpers such as `hyde.table(...)` must therefore be added deliberately, not as
incidental re-exports, and they must be documented in a form suitable for generated API
documentation.

The `features/` layer is not the home of the public Hyde runtime API. Instead,
`features/...` is reserved for translation between GUI representations and Python command
strings, and for translating Python command strings or metadata back into GUI-facing
representations.

Across Hyde, "IR" means internal representation or internal state in the same sense as
the existing state-to-Python generation path used by `features/...` today. The table
feature is the reference example. IR is not globally synonymous with kernel-owned
state; depending on the feature, that internal state may live in the GUI or the kernel.
For figures specifically, the PRD chooses a figure-local IR attached to the live kernel
`Figure` so figure runtime truth and recreation/editability truth stay aligned.

When Hyde-specific helper functions are added, they should be exposed deliberately through
the Hyde package surface rather than through ad hoc GUI-only hooks. The table feature is
the first implemented example of this pattern, with `hyde.table(...)` serving as the
kernel-facing entry point for table creation/appending and the recreation decorator used
to register saved table macros. Project persistence now follows the same pattern with
public `hyde.save_project(...)` and `hyde.load_project(...)` helpers.

## Project and Persistence

A Hyde project is a directory package with `.hy` suffix:

```
example.hy/
├── manifest.toml   # Package metadata, object registry
├── session.toml    # Session state
├── terminal/
│   └── history.py  # Command history
├── procedures/     # Python scripts
│   ├── __init__.py  # Mandatory package initialization script
│   └── helpers.py   # Additional procedure modules
└── data/           # Saved kernel object data
```

### Explicit Initialization & Synchronization
To ensure "Explicit is better than Implicit," Hyde enforces a strict initialization sequence:
1. **No-Project Startup**: On startup without a CLI project path, the GUI enters an explicit no-project state. The kernel is running and `import hyde` has already been performed with `hyde.HYDE_GUI = True`, but no project is active yet.
2. **Authoritative Project Load**: Visible project activation uses `hyde.load_project(...)` in the kernel. That public command clears `hyde.HYDE_PROJECT_DIR`, signals the GUI into no-project state, resets the kernel namespace to Hyde's clean baseline, bootstraps `procedures/__init__.py`, restores saved objects, and then signals GUI project activation.
3. **Project-Switch Reset**: Loading any `.hy` project, including reloading the current one, resets the kernel namespace back to Hyde's clean baseline for that session before the new project's procedures and saved objects are restored.
4. **Kernel-State Restore**: During `hyde.load_project(...)`, persisted kernel objects are restored after `procedures/__init__.py` runs so saved objects override same-name procedure outputs.
5. **GUI Session Restore**: After the kernel reports successful project load, the GUI restores `main_window` state and then broadcasts the loaded `session.toml` payload to plugins. Each plugin restores its own saved windows, filters, and other GUI session state from that payload. If the session file is malformed or missing, the GUI warns and continues with kernel-state restore already complete.
6. **Procedure Reload**: Monitoring of `procedures/__init__.py` and other procedure files is a GUI-process responsibility. The GUI owns `labscript_utils.filewatcher.FileWatcher` and dispatches the canonical package initialization path through a lightweight runtime-helper thread when watched `.py` files change.

### Procedure Browser
The **Procedure Browser** (an MDI window) provides the primary UI for managing these scripts. It lists the contents of the `procedures/` directory and allows the user to open scripts in their system's default editor via double-click.

- Paths inside the package are relative for portability
- The Procedure Browser is rooted at `procedures/`, so displayed entries are relative to that directory
- `manifest.toml` records package version and the saved-object registry
- `session.toml` records restorable GUI session state, with plugin-owned payloads merged into one file by the shell
- in-place project saves rewrite the current saved state rather than preserving an older synchronized copy
- Scripts are plain `.py` files
- Array data is stored in numpy format (`.npy`) when the saved object is an ndarray
- Other saveable objects use pickle fallback (`.pkl`)
- `terminal/history.py` stores visible command history only
- Human-readable settings use TOML or Python-literal history files

## IPC: The 2-Process Model

Hyde operates across two distinct processes plus one GUI-owned helper thread to ensure the GUI remains responsive and the scientific state remains authoritative and isolated:

1. **Main Process (GUI):** Owns the `QMdiArea`, the `ProcessTree.instance()`, the visible Python Terminal, the `FileWatcher`, the plugin-managed lyse-compatible `ZMQServer`, and the runtime-helper queue/thread.
2. **The Kernel (spyder_kernels):** The isolated IPython engine and the authoritative Python namespace.

### Communication Lanes
- **Lane 1 (Control):** `zprocess.ProcessTree` handles application-level orchestration between the GUI and the kernel, along with narrow Hyde-owned relays such as table-open intents and structured table-data payloads.
- **Lane 2 (Execution):** Standard Jupyter ZMQ sockets and `comm` channels bridge the GUI directly to the Kernel for visible execution, background execution, and namespace metadata updates.

## Execution

The execution subprocess runs in a separate Python process using the `spyder_kernels` Jupyter kernel. This provides:
- Full IPython functionality
- Namespace tracking for Python Variables
- Spyder namespace-view support for Python Variables
- Mature, well-tested architecture

The `hyde/execution/kernel_launcher.py` entrypoint is the managed `ProcessTree` child and starts Spyder's kernel startup code in-process. Hyde does not insert a separate controller or launcher-shim process between the GUI and the real kernel.

Most GUI-originated execution reaches the kernel as raw Python code over standard
Jupyter execution channels. The explicit exception is routine figure-window editing,
which uses a private semantic Jupyter `comm` protocol against kernel-owned figure state
rather than ad hoc Python snippets.

## Tracking of Changed Objects

Dynamic update of figures and tables (and possibly other elements) requires tracking of changes to objects in the execution namespace.

Agents implementing this should look at existing solutions such as Spyder, which includes a variable explorer with dynamic updates. Their GitHub is at https://github.com/spyder-ide/spyder. Their website is at https://www.spyder-ide.org.

Agents are encouraged to explore and copy existing solutions, and use existing Python libraries rather than reinventing solutions.

### Plugin and Support Module Structure

First-party Hyde plugins live under `hyde.user_interface.plugins/` and are the only
packages discovered by the plugin manager. Shell code and non-plugin support modules
remain outside that namespace.

```
user_interface/
├── main/                    # Shell infrastructure
│   ├── __init__.py
│   ├── project_state.py     # Shell-owned session persistence helpers
│   └── runtime_helper.py    # GUI-owned runtime queue/thread helper
├── plugins/
│   └── window_name/
│       ├── __init__.py      # Plugin entrypoint
│       └── window_name.ui   # Qt Designer file when needed
├── plugin_tools.py          # Shared plugin infrastructure
└── ...
```

## Widget Types

- **MDI Children**: Figures, tables, browsers in QMdiArea
- **Dialogs**: Modal dialogs for editing operations
- **Drop down menus**: 

### Python Terminal

The Python Terminal uses the `spyder_kernels` Jupyter kernel, with the frontend provided by qtconsole's RichJupyterWidget embedded in the main window.

The user should experience it as a direct "window" to the execution subprocess kernel.

It provides:
- Tab completion
- Up arrow/down arrow to scroll through command history
- syntax highlighting
- ... all other expected IPython behaviors
- `quit`, `quit()`, `exit`, and `exit()` mapped to `hyde.quit()` while `hyde.HYDE_GUI` is true, so terminal-driven quit follows Hyde's orderly GUI shutdown path rather than killing the kernel directly

Unlike Igor Pro, there is no separate command entry box at the bottom, and no line numbers other than what IPython typically generates.

Using spyder_kernels provides:
- Proper namespace tracking for Python Variables
- A standard Jupyter execution environment
- Mature, well-tested architecture

## Figures

First-class `@hyde.figure` figures use the live kernel-side matplotlib `Figure` as the
runtime truth. For those first-class figures, Hyde maintains a strict 1:1 relation
between:

- the matplotlib global registry key
- the live kernel-side `Figure`
- the GUI `FigureWindow`

Non-decorated matplotlib figures remain ordinary kernel-side figures. They do not
enter Hyde's GUI window system in this deployment and do not acquire a GUI
`FigureWindow`.

The GUI figure window is a viewport and event source only. It may own window geometry,
focus, visibility, and transient UI state needed to emit a semantic edit request. It
does not own canonical plot structure, arrays, scientific data, or matplotlib artist
truth.

Figure recreation and GUI editability use a figure-specific IR attached directly to the
live figure, for example `fig._hyde_ir`. This figure IR is the figure feature's
internal representation/internal state in the same sense that table state participates
in the existing state-to-Python path. The figure-specific choice in this PRD is that
this IR is kernel-owned and figure-local rather than GUI-owned.

Hyde also maintains figure-local auxiliary artifacts such as:

- `fig._hyde_command_log`
- `fig._hyde_source_artifact`
- `fig._hyde_ast_artifact`

These artifacts support diagnostics, validation, and future tooling, but they are not
authoritative once the figure exists.

Only first-class `@hyde.figure` figures render into native MDI figure windows in this
deployment. The first-class recreatable and editable figures in this design are those
created through `@hyde.figure`.

That means:

- first-class `@hyde.figure` figures are guaranteed to have a canonical figure IR
- non-decorated figures remain outside Hyde's window system for now
- any future promotion of a non-decorated figure into a first-class Hyde figure is a
  separate concern from the base architecture

`@hyde.figure` decorates an ordinary Python function that builds a matplotlib figure
using standard matplotlib code. The decorated call must create exactly one first-class
Hyde figure. It may return that figure explicitly, or Hyde may resolve it from the
decorated build session through the instrumented backend and registry.

Routine GUI figure editing uses semantic Jupyter `comm` actions, not GUI-generated
Python snippets. The kernel receives a figure edit action, resolves the target figure
from registry identity, mutates the authoritative figure IR on that figure, applies the
corresponding live matplotlib mutation when practical, and redraws. Direct live
mutation is preferred for edits such as titles, labels, limits, legend toggles, and
trace styling. Hyde may regenerate the figure from the IR for edits that are
semantically simple but operationally awkward to patch live.

Saved figure recreation macros are generated from the authoritative figure IR only and
lower back to standard object-oriented matplotlib Python. They follow the same bounded
macro pattern already used for tables: source is written into `procedures/__init__.py`,
the procedures reload path runs, the graph-macro registry is republished, and
`Windows -> Graph Macros` is rebuilt.

## Message Protocol

Incoming message handling replicates the protocol defined in the `lyse` project. In
particular, the GUI owns a lyse-compatible remote listener on the existing
`ports.lyse` labconfig entry. Its handler normalizes incoming agnostic-path
payloads and queues them into the runtime helper, which translates them
into visible kernel execution of `remote(...)`.

## Execution Helpers

Most Hyde GUI actions generate complete Python statements using underlying libraries
(matplotlib, lmfit) rather than wrapping them in custom helper functions.

For example, when the user asks to display data, Hyde does not call a `display()` function. Instead, Hyde generates the explicit object-oriented matplotlib code that creates the figure, such as:
```python
fig = plt.figure()
gs = fig.add_gridspec(...)
ax = fig.add_subplot(gs[0, 0])
ax.plot(x, y)
```

Routine figure-window editing is the deliberate exception. Once a first-class
`@hyde.figure` figure exists, GUI edits target the kernel-owned figure IR over semantic
Jupyter `comm` actions, and Hyde lowers that IR back to standard matplotlib Python when
it generates saved recreation macros or performs explicit regenerate-from-IR debugging.

If Hyde-specific helper functions are introduced later for capabilities not provided by the underlying scientific libraries, those helpers should be added to the Hyde package explicitly and documented at the time they are implemented.

## Default Procedures

New projects include a `procedures/__init__.py` that establishes the baseline environment. It must contain:

```python
import hyde
import numpy as np
import matplotlib
matplotlib.use('Hyde')
import matplotlib.pyplot as plt
import lmfit        # For curve fitting
```

This ensures that any researcher opening the project instantly understands how the scientific namespace is configured.
