# New Table Dialog Specification

## Feature Checklist
- [x] Present a Hyde-native dialog for creating a new table from selected live objects.
- [x] Generate the kernel-facing `hyde.table(...)` command string from the dialog state.
- [x] Support table creation from selected 1D numeric arrays / wave-like objects.
- [ ] Support pandas DataFrame table creation.
- [ ] Support style macros, recreation macros, and table reopen-on-close workflows.
- [ ] Support `@hyde.table` recreation decorators.
- [ ] Support multidimensional waves, text waves, and presentation workflows.

## Purpose

The New Table dialog is the user-facing entry point for creating a Hyde table.
It collects the selected live objects, table naming details, and the initial column
mode, then generates the explicit Python command that asks the kernel to create the
table.

The dialog does not own table state. It is a string factory that prepares the
`hyde.table(...)` call and sends it to the backend-authoritative execution kernel.

## Initial Deployment Scope

The initial deployment focuses on creating tables from 1D numeric wave-like objects.
It includes:

- selecting one or more eligible live objects from the current Hyde namespace
- choosing the initial display mode for supported objects
- entering an optional table title
- generating the `hyde.table(...)` command string
- sending that command to the kernel so the kernel triggers table creation
- opening the resulting table in the GUI after the kernel-side helper runs

It does not include:

- pandas DataFrame creation support
- multidimensional wave creation or editing
- style macros
- recreation macros
- automatic reopen-on-close behavior
- Igor-style data folders or root selection
- arbitrary command-entry boxes beyond the command string Hyde generates

## Window Layout

The dialog is a single modal-style window with:

- a left-side object list for eligible namespace items
- display mode controls on the right
- a title field
- command-generation / action buttons along the bottom

The visible controls are intentionally Hyde-native, even when they echo the layout
of the Igor dialog used as inspiration.

## Visible Controls

The visible controls are classified as follows:

- object list of selectable live arrays: `active`
- search/filter field for the list: `active`
- `Edit data columns only`: `active`
- `Edit index and data columns`: `inert-but-visible`
- `Edit dimension label and data columns`: `inert-but-visible`
- `From Top Graph`: `inert-but-visible`
- `Title` field: `active`
- `Style` selector: `inert-but-visible`
- `Do It`: `active`
- `To Cmd Line`: `inert-but-visible`
- `To Clip`: `inert-but-visible`
- `Help`: `active`
- `Cancel`: `active`

The dialog does not include a current-folder/root control because Hyde does not use
Igor-style data folders.

## Editable Operations

The only live operation in the initial deployment is table creation.

- Target objects: selected 1D numeric wave-like objects from the current namespace
- Python-level effect: generate and dispatch a `hyde.table(...)` call
- Timing: confirmed before dispatch
- Invalid or unsupported selections: the dialog refuses to generate a table command

The initial deployment does not allow in-dialog editing of source objects. It only
selects the inputs and generates the table-creation command.

## Command Generation

The dialog follows Hyde's string-factory rule.
When the user clicks `Do It`, the GUI generates an explicit `hyde.table(...)` string
and sends it to the kernel.

The kernel receives that command, creates the table through the kernel-facing Hyde
helper, and then triggers the GUI to present the new table window.

The dialog may also expose the generated string for debugging or copy-to-clipboard
purposes only if that does not change the backend-authoritative flow.

## Synchronization

The dialog must reflect the current live namespace when it opens.
It should be populated from the same namespace-tracking path used by the Data Browser
so that table-creation choices are based on authoritative kernel state.

The dialog may cache only transient metadata needed to populate the object list and
build the `hyde.table(...)` call.

## Explicit Exclusions

The following Igor concepts are not part of the initial Hyde dialog even if the
controls remain visible for layout continuity:

- data folders
- `root:` selection controls
- table recreation macros
- style macro selection workflows
- export/presentation workflows
- multidimensional wave editing
- text-wave editing
- copy-to-clipboard as a primary workflow
- top-graph import selection

## Future Work

Future table-dialog work may include:

- `pandas.DataFrame` support
- `@hyde.table` recreation decorators
- table reopen/recreation menus
- style macros
- additional initial-display modes
- wider object-type support

These features are deferred until the kernel-facing behavior is defined.
