# Figure Backend Cleanup Work Items

## Checklist

- [x] Slice 1: Introduce canonical first-class figure lookup and identity rules
- [x] Slice 2: Add backend dirty tracking and universal post-block figure resync
- [x] Slice 3: Re-import full supported IR and unsupported-feature status from live figures
- [x] Slice 4: Batch figure snapshot refresh and surface unsupported/incomplete warnings
- [ ] Slice 5: Move axis and trace dialogs onto canonical matplotlib patch emission
- [ ] Slice 6: Move Curve Fit attached display onto canonical matplotlib patch emission
- [ ] Slice 7: Restore save/reopen behavior for partially supported figures and harden tests

## Legacy-path cleanup checkpoints

These checkpoints are not separate work items. They are completion conditions for the
remaining slices so the old dual-path backend does not survive under a new name.

- [ ] Remove the remaining non-first-class `_hyde_live_state` / `_infer_live_state` backend replay path as part of the final cleanup once the new command-driven figure path is fully in place.
- [ ] Remove first-class figure edit use of semantic figure `comm` actions for routine edits as part of Slices 5 and 6.
- [ ] Delete obsolete tests that still defend the old live-state replay or semantic figure-action edit path when the product contract changes.
- [ ] Update docs and agent guidance so they no longer describe the old figure-edit `comm` exception as the intended architecture once the migration is complete.

## Slice 1: Introduce canonical first-class figure lookup and identity rules

### Type

`AFK`

### What to build

Introduce the canonical first-class figure lookup primitive and settle figure identity
on one truth shared by matplotlib and Hyde. Creation names, lookup names, and later
rename behavior should converge on one canonical figure identity, with failure on
name collision and restoration of the previous valid name.

### Acceptance criteria

- [x] Hyde exposes a canonical first-class figure lookup primitive for Python command blocks.
- [x] The canonical figure identity matches the creation/label name rather than a separate Hyde-only field.
- [x] Renaming a first-class figure updates Hyde identity when the new name is valid.
- [x] Rename collision fails and restores the previous valid canonical name.
- [x] The canonical figure-edit Python path is compatible with Hyde's existing hidden-command logging interface.

### Blocked by

None - can start immediately

### User stories covered

- 4, 5, 6, 7, 8

## Slice 2: Add backend dirty tracking and universal post-block figure resync

### Type

`AFK`

### What to build

Add backend-side dirty tracking for first-class figures using matplotlib-native
change/stale propagation, and run figure resync after every completed top-level
Python execution block across Hyde execution paths. Resync should cover only dirty
first-class figures and should still run after exceptions.

### Acceptance criteria

- [x] Dirty tracking for first-class figures uses matplotlib-native change/stale signals rather than broad method wrappers.
- [x] Completed visible and hidden Python execution blocks trigger backend resync.
- [x] Only dirty first-class figures are resynced after a block.
- [x] Resync still runs after execution blocks that end with an exception.
- [x] Hidden figure-edit Python blocks continue to appear in Hyde's normal debug logging stream.
- [x] Hidden figure-edit Python blocks appear in the same `[Hyde state] ... / python:` debug channel used by existing hidden commands such as `hyde.save_project(...)`.

### Blocked by

- Slice 1: Introduce canonical first-class figure lookup and identity rules

### User stories covered

- 1, 2, 3, 9, 10, 11, 13, 22

## Slice 3: Re-import full supported IR and unsupported-feature status from live figures

### Type

`AFK`

### What to build

Make backend resync rebuild the full supported semantic IR for each dirty
first-class figure from the live matplotlib object graph. Unsupported structure
should keep the figure first-class while marking it unsupported/incomplete and
preserving only the supported subset for Hyde semantics.

### Acceptance criteria

- [x] Dirty-figure resync rebuilds the full supported semantic IR from the live figure.
- [x] Unsupported live structure marks the figure unsupported/incomplete instead of ejecting it from Hyde.
- [x] Supported semantic regions remain available for later Hyde editing.
- [x] Rename and other identity-sensitive imports remain consistent with the canonical name contract.

### Blocked by

- Slice 2: Add backend dirty tracking and universal post-block figure resync

### User stories covered

- 12, 14, 15, 16, 18, 23

## Slice 4: Batch figure snapshot refresh and surface unsupported/incomplete warnings

### Type

`AFK`

### What to build

Batch figure snapshot updates per completed Python block and surface the resulting
status clearly in the figure window. Unsupported figures should show explicit warning
text and remain usable as first-class windows with the imported supported subset.

### Acceptance criteria

- [x] Figure snapshot updates are delivered to the GUI in one batch per completed execution block.
- [x] Figure windows show clear unsupported/incomplete warning text when appropriate.
- [x] Supported figure-window behaviors continue to work after batched refresh.
- [x] Unsupported figures stay live in Hyde windows rather than disappearing.
- [x] Batched refresh works from backend-imported figure snapshots rather than reviving any first-class `refresh_from_live_state` bridge.

### Blocked by

- Slice 3: Re-import full supported IR and unsupported-feature status from live figures

### User stories covered

- 14, 15, 16, 21

## Slice 5: Move axis and trace dialogs onto canonical matplotlib patch emission

### Type

`AFK`

### What to build

Keep the existing axis and trace dialogs, but change their mutation path so they emit
the canonical minimal standard-matplotlib patch block for `Do It`, live update,
`Cancel`, and `To Cmd Line`. Dialogs continue reading imported IR snapshots rather
than live matplotlib objects directly.

### Acceptance criteria

- [ ] Axis and trace dialogs emit the same canonical matplotlib patch block for hidden execution and `To Cmd Line`.
- [ ] Live update uses the same command path as final commit.
- [ ] Cancel under live update restores the opening state of the dialog-owned region through the same Python ingress path.
- [ ] Dialog command emission changes only actually changed features.
- [ ] Hidden axis/trace edit commands are logged through Hyde's ordinary hidden-command logging path.
- [ ] Hidden axis/trace edit commands are logged through the same `[Hyde state] ... / python:` channel used for existing hidden commands.
- [ ] Axis and trace edits no longer depend on `FigureEditSession.commit()`, `send_figure_action(...)`, or backend semantic edit actions for routine mutation.
- [ ] Old axis/trace tests are updated to verify canonical emitted matplotlib patches and backend resync rather than the former figure-action transport.

### Blocked by

- Slice 1: Introduce canonical first-class figure lookup and identity rules
- Slice 4: Batch figure snapshot refresh and surface unsupported/incomplete warnings

### User stories covered

- 1, 2, 3, 4, 9, 16, 19, 20

## Slice 6: Move Curve Fit attached display onto canonical matplotlib patch emission

### Type

`AFK`

### What to build

Keep the current Curve Fit dialog surface, but move attached display figure mutation
onto the same canonical matplotlib patch emission model used by the other figure
dialogs. Hidden execution, visible command emission, live update, and rollback should
all converge on one Python ingress path.

### Acceptance criteria

- [ ] Curve Fit attached display uses canonical matplotlib patch emission instead of a separate figure action transport.
- [ ] Hidden execution and visible command-line emission use the same emitted patch block.
- [ ] Live update and rollback/cancel use the same canonical Python ingress path.
- [ ] Attached-display figure results converge with backend resync and imported IR.
- [ ] Hidden Curve Fit figure-edit commands are logged through Hyde's ordinary hidden-command logging path.
- [ ] Hidden Curve Fit figure-edit commands are logged through the same `[Hyde state] ... / python:` channel used for existing hidden commands.
- [ ] Curve Fit attached display no longer commits figure changes through `FigureEditSession.commit()`, `send_figure_action(...)`, or backend semantic edit actions.
- [ ] Routine first-class figure mutation no longer relies on semantic figure `comm` edit traffic after axis/trace/attached-display migration is complete.

### Blocked by

- Slice 1: Introduce canonical first-class figure lookup and identity rules
- Slice 4: Batch figure snapshot refresh and surface unsupported/incomplete warnings

### User stories covered

- 1, 2, 3, 4, 9, 16, 19, 20

## Slice 7: Restore save/reopen behavior for partially supported figures and harden tests

### Type

`AFK`

### What to build

Finalize the cleanup by defining save/reopen behavior for partially supported figures
and by hardening the behavioral test suite around the new one-path figure mutation
model. Saving unsupported figures should warn and recreate the supported subset only,
without silently losing windows when Hyde can still recover part of the figure.

### Acceptance criteria

- [ ] Saving unsupported first-class figures surfaces a clear warning.
- [ ] Save/reopen preserves the supported subset of unsupported figures rather than dropping the window entirely.
- [ ] Tests verify one canonical Python ingress path across figure dialogs and command-line execution.
- [ ] Tests cover dirty tracking, post-block resync, exception resync, rename collision, unsupported-feature warnings, and partial save/reopen behavior.
- [ ] Tests cover hidden figure-edit command logging through Hyde's existing debug log behavior.
- [ ] Tests cover hidden figure-edit command logging through the same `[Hyde state] ... / python:` debug channel used by existing hidden commands.
- [ ] The remaining non-first-class `_hyde_live_state` / `_infer_live_state` replay path, including stale public helpers/tests that only support it, is either removed or explicitly justified by a still-current product contract.
- [ ] Obsolete figure-edit transport code is deleted rather than left dormant once Slices 5 and 6 finish.
- [ ] `AGENTS.md`, `ARCHITECTURE.md`, `IR-CONTROL.md`, and `STATUS.md` describe the final one-path figure mutation model rather than the superseded semantic-edit exception.

### Blocked by

- Slice 3: Re-import full supported IR and unsupported-feature status from live figures
- Slice 5: Move axis and trace dialogs onto canonical matplotlib patch emission
- Slice 6: Move Curve Fit attached display onto canonical matplotlib patch emission

### User stories covered

- 2, 9, 13, 15, 17, 18, 21, 23
