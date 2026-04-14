# Table Specification

## Feature Checklist
- [x] Add a table MDI subwindow to the Hyde workspace.
- [x] Display live kernel-backed data objects in a spreadsheet-like grid.
- [x] Allow direct editing of supported data cells.
- [x] Expose `hyde.table(...)` as the kernel-facing table creation entry point.
- [x] Provide a New Table dialog that generates the `hyde.table(...)` creation string.
- [x] Allow the Data Browser to create a new table from selected arrays via `Edit`.
- [x] Allow the Data Browser to append selected arrays to an existing table via `Append to Table`.
- [x] Show a selection summary and editable value field for the current cell.
- [x] Keep the table synchronized with the authoritative kernel namespace.
- [x] Offer to save a parameterized table recreation macro when the table is closed.
- [x] Populate `Windows -> Table Macros` from registered table recreation macros.
- [ ] Support pandas DataFrame tables and editing.
- [ ] Support row insertion and deletion.
- [ ] Support sorting, formatting, export, and presentation workflows.
- [ ] Support multidimensional waves and non-numeric display modes.

## Purpose

The Table window is Hyde's editable, kernel-backed view for live scientific data.
It presents selected objects from the execution namespace in a spreadsheet-like form
so the user can inspect and modify supported values without breaking Hyde's backend-
authoritative model.

The table is not a standalone data store. It mirrors kernel-owned objects and sends
explicit Python commands when the user edits supported cells.

## Initial Deployment Scope

The initial deployment focuses on 1D wave-like objects from the active Hyde project.
Existing table creation from the namespace remains centered on numeric arrays, while
in-table creation of a new column infers dtype from the entered value.

It includes:

- creating a table from selected live objects in the namespace
- creating that table through the New Table dialog
- appending selected live objects to an existing open table
- using `hyde.table(...)` as the kernel-facing table constructor
- one displayed column per selected object
- a point/index column at the left
- direct editing of supported cells in displayed columns
- appending to an existing displayed array by editing the first cell below its current end
- creating a new displayed array by editing the top cell of the first inactive column
- a current-cell summary and value field above the grid
- live refresh when the underlying kernel data changes
- table creation from the Data Browser `Edit` action
- table append from the Data Browser `Append to Table` action
- save-on-close table recreation macros
- parameterized `@hyde.table` recreation decorators
- reopening saved tables from `Windows -> Table Macros`

It does not include:

- Igor-style data folders or current-folder navigation
- a separate table-owned data model that can drift from the kernel
- row/column formatting dialogs
- sort/export/presentation tooling
- multidimensional wave editing
- pandas DataFrame tables and editing
- arbitrary command-entry dialogs

## Window Layout

The Table window is a single MDI subwindow containing:

- a title bar that identifies the table by source objects
- a compact selection/status strip above the grid
- a main spreadsheet-like grid
- scrollbars for navigating the displayed data
- a close prompt that offers to save a recreation macro unless the close button is shift-clicked

The top strip shows the current target cell and the currently selected value.
The grid uses a point column on the left and one or more data columns to the right.
The grid also exposes one append row below the longest active column and one inactive
column at the right for creating a new array directly from the table.

The table window is created and updated by explicit Hyde kernel commands rather than
by GUI-owned table state.

## Table Creation And Append

The initial table API is kernel-facing and deliberately small:

- `hyde.table(...)` creates a new table from selected supported objects
- `hyde.table(..., target=<table_name>)` appends supported objects to an existing table

The New Table dialog uses this API to generate the creation string.

The Data Browser uses this API in two ways:

- `Edit` opens the New Table dialog with the selected arrays
- `Append to Table` appends the selected arrays to the currently active table

Append is only valid when an existing table is active. If no target table is active,
the action is unavailable.

## Visible Controls

The following visible controls are part of the initial Hyde table:

- `Point` column: `active`
  - read-only row/index indicator
  - helps the user identify the current row
- Data columns: `active`
  - display live kernel values
  - accept edits for supported objects and cells
- Current-cell summary / value field: `active`
  - shows the current selection and the edited value
- Gear menu / pop-up control: `active`
  - exposes table actions that are valid for the current selection
- Grid selection and scrollbars: `active`
  - navigate the visible data
- Save-on-close recreation prompt: `active`
- `Windows -> Table Macros`: `active`

No meaningful visible control is retained purely for layout continuity in the initial
deployment. Igor-only folder/root controls are excluded rather than shown inertly.

## Editable Operations

The initial deployment supports direct editing of existing data cells in displayed
1D wave-like objects.

Supported edits:

- changing a selected data cell to a new value
- committing the edited value from the value field or equivalent table entry path
- appending to an existing column by editing the first inactive cell directly below
  that column's current data
- creating a new array by editing the top cell of the first inactive column

For each live edit:

- the target object is the selected kernel-owned wave-like object
- the Python-level effect is an indexed assignment into that object
- the edit is committed immediately after confirmation

For append edits:

- the target object is the selected kernel-owned array
- the Python-level effect is appending one value to that array
- the entered value is converted to an explicit Python literal before the command is sent

For new-column creation:

- the table creates a new kernel array from the entered value
- the new array is equivalent to `np.array([value])`, so numpy infers the dtype from
  the typed value
- the created array is automatically appended to the current table
- default names follow Hyde's current auto-generated wave naming pattern such as
  `wave0` or `textWave0`

Invalid or unsupported edits:

- editing the point/index column is rejected
- editing an unsupported object type is rejected
- editing with no valid selection is rejected
- empty values are rejected without mutating the kernel

Future table behavior may expand this section to include row insertion, row deletion,
clipboard paste, and additional object types, but those are not part of the initial
deployment.

## Command Generation

The GUI follows Hyde's string-factory rule.
When the user edits a supported cell, the table generates an explicit Python mutation
string for the kernel rather than mutating scientific state in the GUI.

Examples of the intended pattern:

- `wave[row] = value` for a 1D wave-like object
- `wave = np.append(wave, value)` for appending one value below an existing column
- `hyde.table(arr1, arr2)` for creating a new table from selected arrays
- `hyde.table(arr1, target="Table0")` for appending to an existing table
- `wave0 = np.array([value])` for creating a new array from the first inactive column

The table does not own the authoritative value being edited. The GUI may hold only
transient edit text long enough to generate the kernel command.

The kernel-facing `hyde.table(...)` API is the first deliberate helper exposed through
`import hyde` for this feature. The same public symbol also supports
decorator use:

- `@hyde.table`

Saved recreation macros are written into `procedures/__init__.py`, reloaded through the
existing procedures path, and then surfaced in `Windows -> Table Macros`. Saved table
macros declare parameters naming the live kernel variables required to recreate the
table, and the menu invokes them with those visible names.

## Synchronization

The Table window stays synchronized with the kernel's authoritative namespace and
object values.

The table should:

- request an initial snapshot when it opens
- refresh after kernel execution that changes the displayed objects
- refresh after supported table edits are accepted by the kernel
- preserve the current selection when possible
- trigger a procedures reload after saving a recreation macro so the menu registry refreshes

The GUI may cache only the metadata needed to render the grid and the current cell.
It must not cache canonical scientific data as its own source of truth.

The implementation should reuse the suite's existing live kernel communication paths
instead of inventing a Hyde-specific tracking protocol.

## Explicit Exclusions

The following Igor concepts are not part of the initial Hyde table:

- data folders
- current data folder selectors
- packed-experiment table workflows
- row/column formatting dialogs
- sort controls
- add-row / delete-row toolbars
- export-as-picture workflows
- presentation-only table styling
- arbitrary command insertion boxes

## Future Work

The long-term table direction may include:

- multidimensional wave display
- pandas DataFrame table display and editing
- row insertion and deletion
- column sorting and formatting
- clipboard copy/paste workflows
- additional table-aware kernel metadata contracts

These capabilities are deferred until their underlying backend behavior is defined.

## Screenshot Notes

### 03_data_tables.png
![Data Tables](03_data_tables.png)
- What it shows: a Hyde data browser beside a live table window.
- Hyde interpretation: the table is a live, editable view into kernel-owned objects.

### 13_table_with_features.png
![Table Features](13_table_with_features.png)
- What it shows: a table titled `Table0:delay2,fit_delay2` with a point column, two
  data columns, a current-cell value strip, a gear menu, and scrollbars.
- Hyde interpretation: the table supports direct cell editing and kernel-synchronized
  display of selected wave-like objects.
