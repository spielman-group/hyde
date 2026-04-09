# Hyde Specification

## Purpose

Hyde is a standalone labscript-suite application for Pythonic, Igor-Pro-like analysis and plotting.

Hyde is not an experiment-control application. It does not own the shot queue, does not perform instrument control, and does not replace `runmanager` or `blacs`.

Hyde must feel like a single PyQt MDI application where figures, tables, terminals, and related GUI elements all live inside one main window. The application state must be saved on shutdown and restored on the next launch.

Hyde is intended to be an optional replacement for `lyse` while remaining compatible with the suite messaging path used by `runmanager` and `blacs`.

## Product Goals

The first release of Hyde must provide:

- A portable project package format that can be shared between macOS, Windows, and Linux.
- A Python terminal based on IPython.
- A GUI that generates Python code for analysis and figure construction.
- A figure system based on matplotlib.
- Tables that can edit underlying data.
- Saved figures and scripts that can be reopened and rerun.
- Live figure refresh when underlying data changes.
- Menu-driven commands that are implemented by entering Python into the terminal.
- Incoming message compatibility with the messages currently sent to `lyse`.

## Non-Goals

Hyde v1 does not need to provide:

- Experiment scripting.
- Instrument control.
- Shot queue ownership.
- Direct labscript shot-file parsing in the core package.
- Igor Pro backward compatibility.
- Legacy Igor import tools.
- A plugin system comparable to Igor XOPs.
- A built-in debugger.
- A notebook/report area.
- Reusable parameter-control panels inside Hyde itself.

External tools or user code may add these capabilities later, but they are not part of Hyde core v1.

## Architecture

Hyde must be built on the existing Qt compatibility layer used by the labscript suite. Do not import a raw Qt binding directly in application code.

Hyde must use a single top-level `QMainWindow` with an MDI area for figures, tables, and other child windows. All browsers and command interfaces must also be ordinary MDI child windows confined inside the main window.

Hyde must separate the GUI from execution. User code and GUI-generated code run in a separate Python process, not in the Qt GUI process. The GUI process is responsible for presenting state, dispatching code, and reacting to execution results.

The execution process must act as the authoritative session namespace.

See [`hyde/ARCHITECTURE.md`](hyde/ARCHITECTURE.md) for detailed code organization, module structure, IPC mechanism, and implementation patterns.

Supplementary UI requirements and screenshot references live in [`specifications/UI_SPEC.md`](specifications/UI_SPEC.md).

## Package Format

The canonical Hyde project is a directory package with a `.hy` suffix.

Every Hyde package must contain a master procedure in `procedures/master.py`.

See [`hyde/ARCHITECTURE.md`](hyde/ARCHITECTURE.md) for detailed package format, storage rules, and serialization.

## Data Model

Hyde v1 uses a flat namespace. Named objects in Hyde correspond to Python objects in the execution process.

See [`hyde/ARCHITECTURE.md`](hyde/ARCHITECTURE.md) for implementation details on data tracking and change notifications.

## Data Browser

Hyde must provide a data browser window or panel that exposes the current session namespace.

Requirements:

- The browser must show named data objects in the execution namespace.
- The browser must support selecting one or more objects.
- The browser must show a concise selection summary for the current selection.
- The browser must provide a filter or visibility control for object categories.
- The browser must be the primary entry point for opening tables and creating figures from existing data.
- Context-menu or button actions from the browser must generate the same Python commands that could be entered manually in the terminal.
- The browser must provide an object-inspection area showing type, value or shape, and other useful metadata for the current selection.
- The browser must provide a preview area when the selected object has a natural visual preview.
- The browser context menu must include actions equivalent to Display, Edit, Append to Graph, Append to Table, Copy Full Path, Delete Object, and Show Where Object Is Used.
- Some context-menu entries may be disabled for incompatible object types.
- When multiple compatible data objects are selected, Hyde should present them in one combined table window rather than splitting them into separate per-object table windows.

The browser does not need to implement Igor-style data folders in v1, but it must present a navigable namespace view that matches the flat execution model.

## Persistence and State

Hyde must save the full session state on shutdown.

Saved state must include:

- Open figures.
- Figure scripts.
- Table contents.
- Named data objects.
- Window layout and geometry.
- Terminal history.
- The current project package path.
- The current message-handler configuration.
- The registry of saved figure scripts and package procedures.

Saved state must be enough to reopen the application with the same visible windows and the same underlying analysis state.

The save model must preserve all three of these kinds of information:

- Script source.
- Object state.
- Data snapshots.

## GUI-Generated Code

All GUI-generated actions must become Python commands that execute in the terminal.

Requirements:
- Every action that constructs a figure, edits a table, or modifies a named object must be represented as Python code.
- That code must be visible and replayable.
- When a figure window is closed, Hyde must prompt the user to save the figure as a final script.

See [`hyde/ARCHITECTURE.md`](hyde/ARCHITECTURE.md) for implementation details on how GUI actions generate Python code.

## Procedure Browser

Hyde must provide a browser view for the `.py` files currently living in the `.hy` directory structure.

Requirements:

- The browser must list all `.py` files stored in the package tree.
- The browser must support opening a selected script in an external editor.
- The browser should support rerunning a selected script when the script is meant to be executable from Hyde.
- Saved figure scripts should appear in this browser.
- Package procedures and saved figure scripts should be surfaced in menus by name.
- The browser should make clear where a file lives in the `.hy` tree.

This browser is a file browser for package scripts, not an in-app code editor. It is the equivalent of the Igor procedure browser in the first release, even if the implementation is simpler.

Hyde should provide a small standard import for script annotations, for example `from hyde import *` or an equivalent explicit import that exposes annotation decorators.

Hyde should support lightweight annotations on Python definitions to classify script entry points.

Examples:

- `@figure` marks a `def` statement as a figure-recreation or figure-construction entry point.
- `@table` marks a `def` statement as a table-construction or table-editing entry point.
- `@fit_function` marks a `def` statement as a fit-function entry point.
- `@procedure` marks a `def` statement as a package-level procedure entry point.

These annotations are metadata, not a new language. The source remains ordinary Python, and the annotated file is still opened in an external editor when selected.
The set of recognized annotations should be small, explicit, and extensible over time.

## Curve Fitting

Hyde must provide a curve-fitting workflow built on `lmfit` and exposed through a GUI dialog.

The fitting workflow must be scriptable and must generate Python code that can be run in the terminal.

Requirements:

- The fit dialog must support a `Function and Data` tab for selecting the fit model, Y data, and X data.
- The fit dialog must support a `Data Options` tab for fit range, cursors, weighting, and data masking.
- The fit dialog must support a `Coefficients` tab for coefficient names, initial guesses, hold flags, coefficient storage, and fit-function selection.
- The fit dialog must support an `Output Options` tab for destination, residuals, confidence/error analysis, text-box output, and graph output.
- The fit dialog must provide buttons equivalent to `Do It`, `To Cmd Line`, `To Clip`, `Graph Now`, `Help`, and `Cancel`.
- The fit dialog must support equation/command display.
- The fit dialog must allow the user to define or select a new fit function.
- Editing a fit function must open the underlying `.py` file in an external editor.

Fit-function requirements:

- Fit functions must be ordinary Python functions.
- Fit functions must be stored as `.py` files inside the `.hy` package tree.
- The `@fit_function` annotation should identify fit-function definitions for Hyde.
- The procedure browser must list those `.py` files so fit functions are discoverable.
- Fit function definitions must be reusable outside the GUI.
- The GUI must not invent a separate fit-function language.

Output requirements:

- Fit execution must create analyzable Python objects and, where appropriate, new arrays or tables in the Hyde namespace.
- Fit execution must optionally create a graph or text output when requested.
- The generated fit commands must be visible in the terminal and replayable later.

Implementation note:

- Hyde does not need to copy Igor's exact tab layout or widget styling.
- Hyde does need to expose the same functional categories in a Pythonic way.
- The curve-fitting action should be surfaced from the `Analysis` menu in the main window.

## Figures

Hyde must support:

- 2D plotting.
- Scatter and line plots.
- `imshow`.
- Multi-axis figures.
- Grid-based layouts built on matplotlib `gridspec`.
- Legends.
- Annotations.
- Color bars.
- Linked axes.
- Gridspec-based figure composition inside the figure editor workflow, not as a separate layout editor.

Figure requirements:

- Each figure must have a stable name.
- Each figure must live as an MDI child window.
- The figure must be reachable from a menu by name.
- The figure must be backed by a Python script.
- The `@figure` annotation should identify figure-construction or figure-recreation definitions for Hyde.
- Reopening a saved figure must restore the figure and its script.
- Export to PDF is required.
- Any other export format supported by matplotlib may be exposed as available.

Refresh rules:

- A figure must refresh when its underlying data changes.
- A figure must not refresh merely because its script text changed.
- A script change only becomes visible when the user explicitly reruns the figure or otherwise requests regeneration.

The data-change refresh behavior must be based on the Hyde-managed data wrapper and its change notifications.

## Tables

Hyde must provide editable table views for underlying data.

Requirements:

- Tables must be MDI child windows.
- Tables must be able to show and edit Hyde-managed data objects.
- Tables must be creatable from the data browser selection.
- Tables must reflect the named data object they were created from.
- Table edits must write back into the underlying data object.
- Table edits must trigger dependent figure refreshes.
- The table system should feel comparable to a Spyder-style object inspector/table editor.
- If a browser action creates multiple tables, each table must remain independently named and reopenable.

Tables in v1 do not need to support every possible nested Python object as a spreadsheet. Focus on arrays and simple tabular structures that are useful for analysis workflows.

## Message Handling

Hyde must accept the same incoming messages that are currently directed to `lyse` from `runmanager` or `blacs`.

Requirements:

- Message compatibility must be treated as a first-class integration requirement.
- The exact transport is an implementation detail, but the message payloads and endpoint behavior must be compatible with the current suite path.
- On receipt of a compatible message, Hyde must raise or activate itself and route the message into the terminal-side handler path.
- Hyde must expose a single clear hook for mapping incoming messages to actions.
- The default v1 handler should expose the raw message to the terminal process so users can inspect it and act on it immediately.

Hyde does not need to own queue behavior or parse labscript shot structure as part of the core package.

## External Editing

Hyde does not need a built-in code editor in v1.

Selecting a script in Hyde must open that file in an external editor, consistent with the rest of the labscript suite.

Hyde should not reimplement text editing, syntax highlighting, or file-save workflows for scripts that live in the project package.

## Extensibility

Hyde does not expose a plugin system in v1.

The extension mechanism is standard Python:

- User scripts.
- User modules.
- Standard scientific libraries.
- Optional acceleration libraries such as numba.

Hyde must be able to use Python scientific libraries directly, including numpy, matplotlib, and lmfit.

## Labscript Integration Boundaries

Hyde is part of the labscript suite, but its core package should remain focused on analysis and plotting.

Core package boundaries:

- No shot queue ownership.
- No instrument control.
- No direct labscript shot parsing.
- No migration layer for Igor Pro.
- No compatibility layer for existing Igor scripts or data files.

User-space code may later build higher-level labscript integrations on top of Hyde.

## User Interface

The main window should provide at least these UI concepts:

- File menu for package open/save/export.
- Analysis menu containing curve fitting.
- Window or Figures menu listing all named figures.
- A data browser showing the live execution namespace.
- A procedure browser for saved scripts and figure recreation scripts.
- Browser actions for table creation and figure creation.
- Table views for opened data objects.
- Command window for direct Python execution.
- A way to restore, raise, and focus any live figure by selecting its name.

The `Window` menu should provide at least:

- `New Graph...`
- `New Table...`
- `New Python script...`
- `Command window`
- `Script browser`

The data browser should also be reachable from the `Data` menu.

The browser and terminal should feel coordinated: browser actions should be reproducible as terminal commands, and terminal changes should be reflected back into the browser.

The UI should feel like a Pythonic scientific workstation rather than a general-purpose office app.

## Acceptance Criteria

Hyde v1 is complete only when all of the following are true:

- A user can create or open a `.hy` package.
- A user can start a separate IPython terminal and run Python commands.
- A user can generate a figure from the GUI and see the equivalent Python code.
- A user can reopen the figure later from the menu.
- A user can edit underlying data in a table and see dependent figures refresh.
- A figure does not refresh merely because its script text changed.
- The application saves and restores the full session state on shutdown and restart.
- Incoming messages compatible with `lyse` are received and routed to Hyde.
- The package can be copied between macOS, Windows, and Linux and still open.

## Implementation Guidance

Use the smallest design that satisfies the above requirements.

Prefer these choices:

- Existing labscript-suite Qt compatibility over direct Qt imports.
- Existing suite messaging infrastructure over new transport code.
- Plain Python scripts over a custom scripting language.
- Portable file formats over opaque binary state.
- One clear code path over special-case UI behavior.

Do not add a feature unless it is needed to satisfy the requirements above or it materially reduces duplication.
