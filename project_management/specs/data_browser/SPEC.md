# Data Browser Specification

## Feature Checklist
- [ ] Add a `Data Browser` MDI subwindow to the Hyde workspace.
- [ ] Populate the browser from the live execution namespace using Spyder-style namespace tracking.
- [ ] Show a filterable list of named Python objects rather than Igor-style data folders.
- [ ] Show a selection-driven info pane with type and value metadata.
- [ ] Show a selection-driven preview pane for plottable array-like objects.
- [ ] Support right-click actions for display, edit, append to graph, append to table, copy expression, and delete.
- [ ] Support multi-selection for actions that naturally operate on multiple objects.
- [ ] Keep the browser synchronized with kernel namespace changes without storing scientific state in the GUI.
- [ ] Define cross-project browsing of another `.hy` project.
  Cross-project browsing is specified here but is not part of the initial deployment.

## Purpose

The Data Browser is Hyde's visual browser for the authoritative Python execution namespace.
It allows the user to inspect named objects, view concise metadata, preview plottable data,
and invoke common actions from a context menu.

The Data Browser is not a filesystem browser and does not implement Igor Pro data folders.
Its object model is Python-native:

- top-level names come from the live kernel namespace
- objects are identified by valid Python expressions
- actions generate explicit Python strings that are sent to the kernel

## Initial Deployment Scope

The initial deployment focuses on the active `.hy` project's live kernel namespace.
It includes:

- a single browser pane for the current execution namespace
- filtering by object type and text search
- single-selection inspection
- multi-selection for graph/table-oriented actions where the selected objects are compatible
- context-menu actions that map cleanly onto Python and Hyde behavior

The initial deployment does not include:

- Igor-style data folders
- dragging objects between hierarchical containers
- browsing a second project side-by-side
- save-copy workflows
- arbitrary "execute command on selection" UI
- usage/dependency lookup unless a Hyde-native definition is later specified

## Window Layout

The Data Browser lives as an MDI child window.
Its layout follows the broad structure suggested by the screenshot while using Hyde-native semantics:

- a main object list occupying most of the window
- a compact filter area above or beside the list
- an info pane showing metadata for the current selection
- a preview pane showing a quick visual preview for plottable objects

The browser reflects the active project and active kernel session.
Changing the current `.hy` project replaces the browser contents with the namespace of the newly loaded project.

## Object List

The main list shows objects from the live execution namespace.
For initial deployment, the list is defined in terms of top-level Python names rather than data-folder hierarchy.

Each row should provide enough information to recognize the object quickly, including:

- object name
- object type
- concise value summary or shape summary where appropriate

The list supports:

- single selection
- multi-selection for compatible actions
- text filtering
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

The preview pane shows a quick visual preview for objects that Hyde can render meaningfully without opening a full figure or table.
Examples include:

- 1D numeric arrays as a simple line preview
- 2D numeric arrays as an image preview

If the selected object is not previewable, the preview pane shows an empty state rather than guessing at a rendering.

The preview pane is a viewport only.
Any durable or user-directed visualization action still generates explicit Python commands and opens the appropriate Hyde window.

## Context Menu Actions

The screenshot establishes the core interaction model: the browser supports a right-click menu of object actions.
In Hyde, those actions are defined as follows:

- `Display`
  Open the selected object or objects in the most natural Hyde viewer.
  Array-like data should open a figure or image view as appropriate.
- `Edit`
  Open an edit path only for object types that Hyde explicitly supports editing.
  Unsupported types keep this action disabled.
- `Append to Graph`
  Generate Python that appends the selected compatible object or objects to the active figure.
- `Append to Table`
  Generate Python that appends the selected compatible object or objects to the active table.
- `Copy Python Expression`
  Copy the Python expression that identifies the selected object.
  For initial deployment this is the top-level variable name.
- `Delete Object`
  Delete the selected object or objects from the live namespace after confirmation.
- `Show Where Object Is Used`
  This action is not part of the initial deployment and remains unspecified until Hyde defines a Python-native usage model.

The browser enables or disables each action based on selection compatibility.
For example, `Append to Graph` is enabled only when the selected objects can be plotted meaningfully.

## Command Generation

The Data Browser follows Hyde's string-factory rule.
Browser actions do not mutate scientific state directly in the GUI.
Instead, the GUI generates explicit Python strings and dispatches them to the kernel.

Examples of the intended pattern include:

- displaying selected arrays with explicit matplotlib code
- opening a table through the Hyde public API exposed by `import hyde`
- deleting objects with explicit Python statements such as `del name`

The browser therefore remains a viewport and command source for kernel-owned state.

## Synchronization

The browser stays synchronized with the kernel namespace through the suite's namespace-tracking pattern based on Spyder-style comms.
The GUI may cache only the serializable metadata needed to render the browser.
It does not hold canonical arrays or other scientific objects.

Namespace changes caused by:

- terminal input
- procedure reloads
- figure/table actions
- external Python code run in the kernel

must update the Data Browser view.

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

## 08_data_browser_context_menu.png
![Data Browser Context Menu](08_data_browser_context_menu.png)
- What it shows: a selection-driven browser with a right-click action menu, an info area, and a preview-oriented workspace next to figure and table windows.
- Hyde interpretation: a namespace browser for Python objects, with context actions translated into explicit Hyde/Python commands rather than Igor object operations.
