# Figure Backend Cleanup Work Items

## Checklist

- [x] Slice 1: Move explicit figure regenerate and refresh onto the command path
- [x] Slice 2: Unify Curve Fit live and preview attached-display command emission
- [x] Slice 3: Retire stale figure-action test scaffolding and assertions
- [x] Slice 4: Rewrite stale figure specs around the final one-path model

## Notes

- `resize_redraw` is a bounded exception. It is preferred, but not required, to move it onto the command-driven model.
- Leaving `resize_redraw` on backend control traffic is acceptable as long as docs, specs, and tests describe it as a narrow non-command exception rather than evidence of a general figure-edit action lane.

## Slice 1: Move Explicit Figure Regenerate And Refresh Onto The Command Path

### Type

`AFK`

### What to build

Remove the remaining active production split where explicit first-class figure refresh
and regenerate operations use the private figure-action transport instead of Hyde's
normal command-driven Python path.

This slice should cover explicit refresh/regenerate control only. It does not need to
move `resize_redraw` if that would broaden the patch beyond the narrow exception you
already approved.

### Acceptance criteria

- [x] `hyde.refresh_figure(...)` no longer mutates first-class figures through direct backend action dispatch.
- [x] Figure-window explicit regenerate/refresh requests no longer depend on the private figure-action transport.
- [x] Hidden refresh/regenerate commands route through Hyde's existing hidden Python execution path.
- [x] Hidden refresh/regenerate commands appear in the standard `[Hyde state] ... / python:` debug log channel.
- [x] If `resize_redraw` stays on backend control traffic, the remaining control lane is documented as a narrow exception rather than a general second figure-edit path.

### Blocked by

None - can start immediately

### User stories covered

- 1, 5, 10, 13, 22, 24

## Slice 2: Unify Curve Fit Live And Preview Attached-Display Command Emission

### Type

`AFK`

### What to build

Remove the remaining split inside Curve Fit attached display so that live update,
preview-style figure control, `Do It`, and `To Cmd Line` all converge on one
canonical command-generation model with one standard hidden-command logging path.

### Acceptance criteria

- [x] Curve Fit attached-display live behavior no longer uses a distinct command path from `Do It` / `To Cmd Line`.
- [x] Preview-style attached-display figure commands use the same command-generation model as the committed attached-display path.
- [x] Preview-related hidden Curve Fit figure commands appear in Hyde's standard `[Hyde state] ... / python:` debug log channel.
- [x] Focused Curve Fit tests verify one canonical attached-display command path across live update, preview, `Do It`, and `To Cmd Line`.

### Blocked by

None - can start immediately

### User stories covered

- 1, 2, 3, 5, 19, 20, 24

## Slice 3: Retire Stale Figure-Action Test Scaffolding And Assertions

### Type

`AFK`

### What to build

Harden the figure tests around the final control model by deleting stale test seams
that still scaffold or defend the superseded figure-action transport for routine
figure control.

This includes backend/public tests, dialog tests, and Curve Fit harnesses where the
remaining assertions no longer match the production contract.

### Acceptance criteria

- [x] Tests no longer defend routine semantic figure-edit actions for axis, trace, or Curve Fit attached display.
- [x] Stale `_hyde_live_state` terminology or fixtures are removed from figure tests unless they still prove a current product contract.
- [x] Figure-control test scaffolding reflects the remaining real transport split, if any, instead of the removed general semantic-edit path.
- [x] The focused figure test suite verifies the current one-path command model plus any explicitly accepted narrow exceptions.

### Blocked by

- Slice 1: Move explicit figure regenerate and refresh onto the command path
- Slice 2: Unify Curve Fit live and preview attached-display command emission

### User stories covered

- 5, 10, 13, 19, 20, 24

## Slice 4: Rewrite Stale Figure Specs Around The Final One-Path Model

### Type

`AFK`

### What to build

Update the remaining figure-related specs so they stop describing the superseded
semantic `comm` figure-edit architecture as current behavior.

The updated specs should clearly distinguish:
- the canonical command-driven figure-edit path
- any accepted narrow exception such as `resize_redraw`
- unsupported or not-yet-implemented surfaces that should not be described as already complete

### Acceptance criteria

- [x] `IPC_PROTOCOL.md` no longer describes routine figure editing as a semantic `comm` lane.
- [x] `figure_window/SPEC.md` no longer describes routine dialog editing through session `live apply / commit / revert` transport or semantic figure actions.
- [x] `axis_edit_dialog/SPEC.md` and `trace_edit_dialog/SPEC.md` describe emitted command-driven figure control rather than semantic figure actions.
- [x] `remove_from_graph/SPEC.md` is either updated to the command-driven model or clearly marked as stale/not implemented instead of documenting the superseded action path as complete.
- [x] Specs describe `resize_redraw` accurately if it remains a bounded non-command exception.

### Blocked by

- Slice 1: Move explicit figure regenerate and refresh onto the command path
- Slice 2: Unify Curve Fit live and preview attached-display command emission

### User stories covered

- PRD Implementation Decisions
- PRD Testing Decisions
- PRD Further Notes
