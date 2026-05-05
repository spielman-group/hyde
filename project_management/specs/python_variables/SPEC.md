# Python Variables Specification

## Feature Checklist
- [x] Add a `Python Variables` MDI subwindow to the Hyde workspace.
- [x] Populate the browser from the live execution namespace using Spyder-style namespace tracking.
- [x] Show a filterable list of named Python objects rather than Igor-style data folders.
- [x] Show a selection-driven info pane with type and value metadata.
- [x] Show a selection-driven preview area with placeholder text for future plotting support.
- [x] Support `Copy Python Expression` and `Delete Object`.
- [x] Support table creation from the selection via `Edit` and the New Table dialog.
- [x] Support appending selected arrays to an existing table via `Append to Table`.
- [x] Keep the browser synchronized with kernel namespace changes without storing scientific state in the GUI.
- [ ] Define a first-class figure-launch path for Python Variables that stays consistent with `@hyde.figure` figures and the figure IR model.
- [ ] Define cross-project browsing of another `.hy` project.
  Cross-project browsing is specified here but is not part of the initial deployment.

## Purpose

Python Variables is Hyde's visual browser for the authoritative Python execution namespace.
It allows the user to inspect named objects, view concise metadata, preview plottable data,
and invoke common actions from a context menu. It also serves as the entry point for
table creation and appending from selected kernel-owned arrays.

Future figure-oriented actions are intentionally narrower than generic ad hoc plotting.
When Hyde adds them, they must create or target first-class `@hyde.figure` figures
rather than make undecorated matplotlib windows the primary workflow.

Python Variables is not a filesystem browser and does not implement Igor Pro data folders.
Its object model is Python-native:

- top-level names come from the live kernel namespace
- objects are identified by valid Python expressions
- actions generate explicit Python strings that are sent to the kernel

## Initial Deployment Scope

The initial deployment focuses on the active `.hy` project's live kernel namespace.
It includes:

- a single browser pane for the current execution namespace
- filtering by object type through the left-hand display controls
- single-selection inspection
- metadata-driven list rows for name, type, and display value
- a placeholder preview area
- currently supported actions that map cleanly onto Python and Hyde behavior
- table launch actions for supported array selections (`Edit`, `Append to Table`)
- `Edit` and `Append to Table` only for selection types the table widget supports in the initial deployment
- `pandas.DataFrame` objects remain visible under `Arrays` but their table actions are future work

The initial deployment does not include:

- Igor-style data folders
- dragging objects between hierarchical containers
- browsing a second project side-by-side
- save-copy workflows
- arbitrary "execute command on selection" UI
- figure-oriented `Display` and `Append to Graph` actions
- usage/dependency lookup unless a Hyde-native definition is later specified

## Window Layout

Python Variables lives as an MDI child window.
Its layout follows the broad structure suggested by the screenshot while using Hyde-native semantics:

- a left-hand sidebar containing display controls and action buttons
- a main object list occupying most of the window
- an info pane showing metadata for the current selection
- a preview pane reserved for future visual preview support

The browser reflects the active project and active kernel session.
Changing the current `.hy` project replaces the browser contents with the namespace of the newly loaded project.

## Visible Controls

The visible controls are classified as follows:

- `Arrays` - `active`
- `Variables` - `active`
- `Strings` - `active`
- `Info` - `active`
- `Plot` - `inert-but-visible`
- `Delete` - `active`
- `New Data Folder` - `excluded`
- `Save Copy` - `excluded`
- `Browse Expt...` - `excluded`
- `Execute Cmd...` - `excluded`
- `Current Data Folder` / `root:` field - `excluded`
- current-folder arrow indicator - `excluded`
- context-menu `Copy Python Expression` - `active`
- context-menu `Delete Object` - `active`
- context-menu `Edit` - `active`
- context-menu `Append to Table` - `active`
- context-menu `Display` - `excluded`
- context-menu `Append to Graph` - `excluded`
- context-menu `Show Where Object Is Used...` - `excluded`

## Left Sidebar Controls

The left-hand sidebar follows the user-approved screenshot.

The `Display` group contains:

- `Arrays`
  Show array-like scientific data, specifically `numpy.ndarray` and `pandas.DataFrame`.
- `Variables`
  Show numeric scalar variables.
- `Strings`
  Show `str` values.
- `Info`
  Toggle the visibility of the info pane.
- `Plot`
  Visible for layout continuity with the reference screenshot, but inert in the initial deployment.

The sidebar also contains action buttons derived from the reference screenshot.
In the initial deployment:

- `Delete` is active.
- `New Data Folder`, `Save Copy`, `Browse Expt...`, and `Execute Cmd...` are excluded from the initial deployment.

The screenshot-derived current-folder controls are excluded because Hyde does not implement Igor-style data folders.

## Object List

The main list shows objects from the live execution namespace.
For initial deployment, the list is defined in terms of top-level Python names rather than data-folder hierarchy.

Each row should provide enough information to recognize the object quickly, including:

- object name
- object type
- concise value summary or shape summary where appropriate

The list supports:

- single selection
- multi-selection for compatible actions such as delete
- type-based filtering
- sorting by at least name and type

The list does not expose Igor data folders or a "current data folder" concept.

## Info Pane

When one object is selected, the info pane displays Hyde-relevant metadata for that object.
The exact fields depend on type, but the pane should prefer Python-native information such as:

- name
- type
- dtype
- shape
- scalar value or abbreviated textual representation
- module/class origin when useful

The info pane is read-only in its default state.
If the selected object supports an edit operation, editing is initiated by an explicit action such as the context-menu `Edit` item rather than inline mutation by default.

## Preview Pane

The preview pane is present in the initial deployment but does not yet render data.
It displays static placeholder text indicating that preview support will arrive later.

The preview pane remains a viewport-only area.
Any durable or user-directed visualization action will still need to generate explicit Python commands and open the appropriate Hyde window once figure support exists.
For first-class figures, that future command path must create or target a decorated
figure workflow; once such a figure exists, later figure edits happen through semantic
figure `comm` actions against the figure feature's IR rather than through Python
Variables holding any plot state in the GUI. In this figure workflow, the PRD chooses
that IR to live in the kernel on the live figure.

## Editable Operations

The only live mutable operation in the initial deployment is `Delete Object`.

- Target objects: one or more selected top-level Python names in the active kernel namespace.
- Python-level effect: remove the selected binding(s) from the kernel namespace with explicit `del` statements.
- Timing: confirmed before dispatch.
- Invalid or unsupported selections: no deletion occurs if nothing valid is selected.

The following operations are visible in the screenshot but are not part of the initial deployment:

- `Display`
- `Append to Graph`
- `Show Where Object Is Used...`

Future figure actions do not imply a generic `plt.plot(...)` shortcut for arbitrary
selections. They must remain compatible with Hyde's first-class figure model:

- the created or targeted figure is a first-class `@hyde.figure` figure
- the figure's authoritative internal state is the figure feature's IR, which this PRD
  places in the kernel on the live figure
- later GUI edits on that figure use semantic `comm` actions, not Python Variables-side
  state mutation

## Context Menu Actions

The browser supports a right-click menu of object actions.
In the initial deployment, the active actions are:

- `Copy Python Expression`
  Copy the Python expression that identifies the selected object.
  For the initial deployment this is the top-level variable name.
  This is the Hyde-native replacement for Igor's `Copy Full Path` action.
- `Delete Object`
  Delete the selected object or objects from the live namespace after confirmation.
- `Edit`
  Open the New Table dialog with the selected array-like objects so the dialog can
  generate `hyde.table(...)`.
- `Append to Table`
  Append the selected array-like objects to the currently active table using
  `hyde.table(..., target=<table_name>)`.

The remaining Igor actions are intentionally not part of the initial deployment.

`Edit` and `Append to Table` are only enabled for selections that the initial table
widget supports. In the initial table deployment that means 1D numeric arrays.
`pandas.DataFrame` objects remain visible in the browser but their table actions are
deferred until the table widget defines DataFrame semantics.

## Table Integration

Python Variables launches the table widget through the New Table dialog and the
kernel-facing `hyde.table(...)` API.

- `Edit` opens the New Table dialog with the selected array-like objects
- `Append to Table` appends the selected array-like objects to the active table

If no table is active, `Append to Table` is unavailable.
If the selection is not compatible with the initial table widget, both table actions
are unavailable.

## Command Generation

Python Variables follows Hyde's string-factory rule.
Browser actions do not mutate scientific state directly in the GUI.
Instead, the GUI generates explicit Python strings and dispatches them to the kernel.

Examples of the intended pattern include:

- deleting objects with explicit Python statements such as `del name`
- copying a valid Python expression for the selected object
- creating a new table with `hyde.table(arr1, arr2)`
- appending to an existing table with `hyde.table(arr1, target="Table0")`

GUI state that is only needed to generate the command string may be transient, but it is never authoritative scientific state.

The browser therefore remains a viewport and command source for kernel-owned state.

## Synchronization

The browser stays synchronized with the kernel namespace through the suite's namespace-tracking pattern based on Spyder-style comms.
The GUI may cache only the serializable metadata needed to render the browser.
It does not hold canonical arrays or other scientific objects.

Namespace changes caused by:

- terminal input
- procedure reloads
- external Python code run in the kernel

must update the Python Variables view.

The browser establishes its own namespace-view comm path and requests an initial snapshot after that path is ready, so startup and project reopen begin with a populated list rather than waiting for a future user command.

## Cross-Project Browsing

Igor's "Browse Expt" concept maps in Hyde to opening another `.hy` project.
This is a project-level operation, not a data-folder import feature.

The long-term direction is:

- the user can open another `.hy` project for browsing
- Hyde presents that project's data in a clearly separate browsing context
- importing or copying data from that project into the active kernel is an explicit later feature

This cross-project capability is not part of the initial deployment.
The initial deployment only browses the active project's live kernel namespace.

## Explicit Exclusions

The following Igor concepts do not carry into Hyde as part of this specification:

- data folders
- current data folder indicators
- moving objects between data folders
- packed-experiment file browsing as an Igor file format feature
- unpacked save-copy workflows
- free-form execute-command dialogs
- root/current-folder navigation UI
- figure action support in the initial deployment
- `Show Where Object Is Used...` in the initial deployment

## Future Work

- display actions once Hyde defines a visible Python command path that opens or targets
  first-class `@hyde.figure` figures from a selection
- edit actions once the target widget semantics are defined
- append-to-graph actions once Hyde defines how a selection targets an existing
  first-class figure without bypassing the figure IR and semantic edit model
- broader append-to-table actions once the table widget supports more object types
- cross-project browsing of another `.hy` project

## 08_python_variables_context_menu.png
![Python Variables Context Menu](08_python_variables_context_menu.png)
- What it shows: a selection-driven browser with a right-click action menu, an info area, and a preview-oriented workspace next to figure and table windows.
- Hyde interpretation: a namespace browser for Python objects, with context actions translated into explicit Hyde/Python commands rather than Igor object operations.
