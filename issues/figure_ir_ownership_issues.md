# Figure IR Ownership Work Items

## Checklist

- [x] Slice 1: Introduce the figure-owned edit session boundary
- [x] Slice 2: Move axis editing onto the figure-owned session
- [x] Slice 3: Move trace appearance editing onto the figure-owned session
- [x] Slice 4: Move Curve Fit attached-display ownership onto the figure-owned session
- [x] Slice 5: Remove raw figure-semantic leakage from consumers and harden tests

## Slice 1: Introduce the figure-owned edit session boundary

### Type

`AFK`

### What to build

Add a single figure-owned `open_session()` boundary for first-class figures. The session should be ephemeral, non-Qt, consumer-agnostic, and own figure action construction, dispatch, draft lifecycle, preview generation, and revert behavior. It should expose fine-grained getters and matplotlib-aligned mutating methods, plus only the minimum structured bulk methods needed to represent real figure concepts cleanly.

### Acceptance criteria

- [x] Figure consumers can open one figure-owned session from the figure context.
- [x] The session owns opening/current/revert state and dirty tracking.
- [x] The session owns preview/source generation and live apply / commit / revert behavior.
- [x] The public boundary does not expose raw figure IR or raw action payload construction as the consumer contract.

### Blocked by

None - can start immediately

### User stories covered

- 1, 2, 3, 4, 5, 6, 7, 12, 13, 15

## Slice 2: Move axis editing onto the figure-owned session

### Type

`AFK`

### What to build

Refit the axis editing workflow so the dialog becomes a thin widget/controller over the figure-owned session. The dialog should populate itself through fine-grained session getters and express edits through session methods rather than mutating local figure drafts, validating raw IR, lowering preview source itself, or assembling raw figure action payloads.

### Acceptance criteria

- [x] Axis editing no longer owns a dialog-local figure-semantic draft state.
- [x] Axis preview/source comes from the figure-owned session boundary.
- [x] Live update, commit, and cancel/revert still behave correctly through the session.
- [x] Existing axis-edit behavior remains intact for first-class figures.

### Blocked by

- Slice 1: Introduce the figure-owned edit session boundary

### User stories covered

- 1, 2, 3, 6, 7, 8, 12, 13

## Slice 3: Move trace appearance editing onto the figure-owned session

### Type

`AFK`

### What to build

Refit the trace appearance workflow so the dialog consumes session getters and session methods instead of rebuilding trace-style state from figure IR/defaults/live snapshots and re-lowering a draft figure IR itself. Keep the current live-update and cancel/revert behavior while making the figure system the only owner of trace-style semantics and protocol details.

### Acceptance criteria

- [x] Trace appearance no longer rebuilds figure-semantic draft IR in the dialog.
- [x] Trace appearance preview/source comes from the figure-owned session.
- [x] Live trace style updates still work through the session boundary.
- [x] Cancel/revert restores the prior trace appearance state through the session.

### Blocked by

- Slice 1: Introduce the figure-owned edit session boundary

### User stories covered

- 1, 2, 3, 6, 7, 9, 12, 13

## Slice 4: Move Curve Fit attached-display ownership onto the figure-owned session

### Type

`AFK`

### What to build

Move attached-display trace lifecycle out of Curve Fit and into the figure-owned session boundary. Curve Fit should express intent such as showing fit or residual traces and the root object to use, while the figure system owns trace identity, collision handling, replacement/removal ordering, and rollback semantics.

### Acceptance criteria

- [x] Curve Fit no longer acts as a figure trace manager for attached display traces.
- [x] Attached-display trace creation, update, removal, and rollback are figure-owned behaviors.
- [x] Curve Fit can still preview and commit attached fit/residual display behavior through figure-owned APIs.
- [x] Collision and rollback behavior remain stable and behaviorally covered.

### Blocked by

- Slice 1: Introduce the figure-owned edit session boundary

### User stories covered

- 1, 2, 3, 6, 7, 10, 11, 12, 13

## Slice 5: Remove raw figure-semantic leakage from consumers and harden tests

### Type

`AFK`

### What to build

Finish the first-step cleanup by removing remaining consumer reliance on raw figure IR and raw action protocol details for the covered workflows. Tighten tests around the new ownership boundary so future edits fail fast if semantic figure logic starts leaking back into consumer plugins.

### Acceptance criteria

- [x] Covered consumer plugins no longer depend on raw figure IR as their working contract.
- [x] Covered consumer plugins no longer construct raw figure action payloads directly.
- [x] Tests verify the new ownership boundary and covered workflows behaviorally.
- [x] The resulting design remains centered on first-class `figure_ir` figures.

### Blocked by

- Slice 2: Move axis editing onto the figure-owned session
- Slice 3: Move trace appearance editing onto the figure-owned session
- Slice 4: Move Curve Fit attached-display ownership onto the figure-owned session

### User stories covered

- 1, 2, 3, 6, 7, 14, 15
