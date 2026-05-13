I don’t have a `to-trd` skill installed in this session, so I’m using the same synthesis approach and outputting the TRD here.

**TRD: Restore MDI Window State, Geometry, and Order Correctly**

## Problem Statement

When Hyde saves a project with minimized MDI windows, those windows reload as normal visible windows whose title bars have the size and position of the minimized MDI representation. Hyde is persisting the minimized geometry as if it were the normal geometry and does not preserve enough presentation state to restore minimized/maximized/hidden windows correctly.

This affects all Hyde MDI windows: tool windows, tables, figures, and the Python window.

## Goals

- Persist normal geometry separately from minimized presentation geometry.
- Replace boolean `visible` tool-window persistence with explicit `window_state`.
- Restore MDI windows in the same stacking order they had when saved.
- Support minimized and maximized restore states.
- Use Qt’s existing MDI container and `QMdiSubWindow.objectName()` for identity.
- Keep the patch focused; rely on the existing `objectName()`-based identity model
  without redefining generic MDI identity again in this work.

## Persistence Model

`window_state` values:

- Tool windows in `session.toml`: `hidden`, `visible`, `minimized`, `maximized`
- Tables/figures in `session.py`: `visible`, `minimized`, `maximized`
- `visible` is valid public syntax but omitted from generated table/figure restore code because it is the default.
- `hidden` is invalid for tables/figures; closed tables/figures are omitted from `session.py`.

Geometry fields:

- `geometry`: normal restored window geometry, always required for restored windows.
- `geometry_minimized`: minimized title-bar/icon geometry, required only when `window_state == "minimized"`.
- No `geometry_maximized`; maximized windows have a single MDI-area-determined geometry.

Window order:

- Store `main_window.mdi_window_order` in `session.toml`.
- Capture from `QMdiArea.subWindowList(QtWidgets.QMdiArea.StackingOrder)`.
- Store each subwindow’s `objectName()`.

## Restore Flow

1. Restore/create all windows in normal state using `geometry`.
2. Execute `session.py` for tables and figures.
3. On successful session restore completion, apply saved stacking order.
4. Apply final presentation states:
   - `visible`: leave normal
   - `hidden`: hide tool window
   - `minimized`: call `showMinimized()`, then apply `geometry_minimized`
   - `maximized`: call `showMaximized()`

If session restore fails, skip final ordering/state finalization and let the existing raised error appear through the current log/output path.

## Completion Signal

Add public Hyde API:

```python
hyde.task_complete(name, success=True)
```

Initial use:

```python
try:
    <session.py contents>
except Exception:
    hyde.task_complete("session_restore", False)
    raise
else:
    hyde.task_complete("session_restore", True)
```

Implementation uses the existing kernel-to-GUI ProcessTree message path, not figure comms.

## Identity

Use `QMdiSubWindow.objectName()` as the single MDI-level stable identity.

- Tool windows: existing MDI keys, e.g. `python_terminal`
- Tables: table identity strings, e.g. `Table0`
- Figures: add generated figure object names, e.g. `Figure0`
- Title-bar text remains presentation only. It begins with `objectName()` and any
  caller-provided text is suffix-only additional detail, not replacement identity text.

Do not add a new MDI registry or `QMdiSubWindow` subclass.

## Validation

For tool-window `session.toml` restore:

- Missing/invalid `window_state`: warn and restore hidden.
- Missing/invalid `geometry`: warn and restore hidden.
- Missing/invalid `geometry_minimized` when minimized: warn and restore hidden.
- Geometry must be four numeric values with positive width and height. Negative x/y are allowed.

For table/figure `session.py` restore:

- Public Hyde API validates decorator/create-table `window_state`.
- Invalid session Python follows the existing execution/error path.

## Implementation Areas

- Session capture/write/read helpers for `window_state`, `geometry`, `geometry_minimized`, and `mdi_window_order`.
- Shared MDI helper logic for capturing normal geometry by temporarily restoring minimized/maximized windows, reading `geometry()`, then returning to the prior state.
- Tool-window restore helpers.
- Table and figure restore-source generation.
- Figure session identity/object-name generation.
- Public `hyde.task_complete(...)` API and IPC message handling.
- Main restore finalization path after successful `session_restore`.

## Testing Decisions

Tests should verify user-visible contracts:

- A minimized tool window reloads minimized and retains normal geometry.
- A minimized table/figure reloads minimized and does not use title-bar geometry as normal geometry.
- A maximized window reloads maximized.
- Hidden tool windows reload hidden but retain geometry.
- Invalid tool-window TOML state/geometry warns and hides the window.
- Mixed MDI window order is captured from `StackingOrder` and restored after successful `session.py`.
- Failed `session.py` sends `task_complete(..., False)` and skips finalization.

## Out of Scope

- Broad removal of all “handle” terminology.
- Public API rename of table `target=...`.
- New MDI registry.
- `QMdiSubWindow` subclassing.
- Robust hidden-execution lifecycle tracking beyond `task_complete`.
- Compatibility shims for old `visible`-based session files unless explicitly requested.
