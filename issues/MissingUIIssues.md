# Missing UI Issues

## Checklist

- [x] Issue 1: Convert `CurveFitDialog` to a `.ui`-driven dialog body
- [x] Issue 2: Convert `AxisEditDialog` to a `.ui`-driven dialog body
- [x] Issue 3: Convert `TraceAppearanceDialog` to a `.ui`-driven dialog body
- [x] Issue 4: Convert `ProcedureBrowser` to a `.ui`-driven tool window body

## Scope

This file breaks down the current plugin UI audit into independently grabbable issues.

The main offenders are:

- `CurveFitDialog`
- `AxisEditDialog`
- `TraceAppearanceDialog`
- `ProcedureBrowser`

The following are not currently treated as issues in this breakdown:

- `FigureWindow`, because `hyde_window_widget.ui` is already the intended static shell
  for `HydeInteractiveWidget` surfaces and the figure plugin is only mounting its
  runtime display content into that shell
- `LoggingWindow`, which mounts a dynamic `OutputBox`
- `PythonTerminal`, which mounts a `RichJupyterWidget`
- stock/customized file dialogs, which are a different category from Hyde-authored
  form/dialog layouts

## Issue 1: Convert `CurveFitDialog` To A `.ui`-Driven Dialog Body

- **Type**: AFK
- **Blocked by**: None

### What to build

Replace the Python-built `CurveFitDialog` layout with one or more `.ui` files that
define the dialog-specific upper content. The shared `HydeDialogWidget` shell should
remain responsible for the lower text pane and footer buttons.

The `.ui` surface should cover:

- the main tab widget
- each tab body
- the preview-mode row
- the status strip

Python should be reduced to wiring, dynamic row/table population, and state
synchronization.

### Acceptance criteria

- [x] `CurveFitDialog` no longer constructs its main widget tree in `_build_*` layout
      helpers
- [x] Dialog structure is defined by `.ui` files except for genuinely dynamic controls
      such as per-fit-function rows
- [x] The current shared-shell behavior remains intact: lower read-only text pane,
      fixed footer buttons, and hook-based button behavior
- [x] Existing Curve Fit behavior and tests still pass after the layout migration

## Issue 2: Convert `AxisEditDialog` To A `.ui`-Driven Dialog Body

- **Type**: AFK
- **Blocked by**: None

### What to build

Replace the Python-built `AxisEditDialog` body with a `.ui`-driven layout. The header
row, tab widget, and tab contents should live in `.ui` artifacts rather than being
assembled in Python.

Python should remain responsible for:

- loading and syncing axis state
- dynamic enable/disable behavior
- applying live edits and building preview text

### Acceptance criteria

- [x] The main dialog body for `AxisEditDialog` is loaded from `.ui` rather than
      assembled by `_build_ui` and tab-specific widget factories
- [x] Tab structure and static controls are defined in `.ui`
- [x] Dialog startup sizing still correctly shows all tabs
- [x] Existing axis-edit behavior and tests remain green

## Issue 3: Convert `TraceAppearanceDialog` To A `.ui`-Driven Dialog Body

- **Type**: AFK
- **Blocked by**: None

### What to build

Replace the Python-built `TraceAppearanceDialog` body with a `.ui`-driven layout. The
trace list, form area, and static controls should be declared in `.ui`, with Python
limited to populating values, reacting to edits, and emitting figure-style actions.

### Acceptance criteria

- [x] `TraceAppearanceDialog` no longer builds its static form layout in Python
- [x] The dialog body is defined by a `.ui` file mounted into the shared shell
- [x] The lower preview text and footer continue to come from `HydeDialogWidget`
- [x] Existing trace-style editing behavior and tests still pass

## Issue 4: Convert `ProcedureBrowser` To A `.ui`-Driven Tool Window Body

- **Type**: AFK
- **Blocked by**: None

### What to build

Move the `ProcedureBrowser` tool-window content out of Python layout construction and
into a `.ui` file. The tree view should be declared in `.ui`, while Python continues
to own the file-system model setup, root-path changes, and double-click behavior.

### Acceptance criteria

- [x] `ProcedureBrowser` loads a `.ui` body instead of constructing the tree view
      layout directly in Python
- [x] The file-system model and behavior remain unchanged
- [x] The mounted tool-window content still fits the shared `HydeToolWidget` pattern
- [x] Existing procedure-browser behavior is preserved
