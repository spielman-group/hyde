## Parent

[ReloadWindowLocations.md](./ReloadWindowLocations.md)

## What to build

Implement the figure-side restore metadata required by the TRD on top of the current
`master` figure identity model.  The vast majority of the code should overlap with the just-
implemented table code.  Refactor as needed to not duplicate.

This slice should preserve the existing `objectName()`-based figure identity and
kernel-owned figure naming logic while teaching machine-generated `session.py` restore
blocks to carry normal window position plus `window_state` for visible, minimized, and
maximized figure restore.

## Acceptance criteria

- [ ] Figure `session.py` restore blocks preserve the stable figure `objectName()` and current kernel-owned figure naming behavior.
- [ ] Figure session restore metadata can represent `visible`, `minimized`, and `maximized` restore states.
- [ ] Minimized figure restore uses saved normal geometry as the restored figure window geometry when it returns to normal state.
- [ ] Table code is reused, and refactored if needed.
- [ ] Explicit saved figure macros do not emit minimized-layout-only metadata in this initial path.
- [ ] Tests cover minimized/maximized figure restore and verify that minimized restore remains state-only.

## Blocked by

- [ReloadWindowLocations_01_ToolWindowStateModel.md](./ReloadWindowLocations_01_ToolWindowStateModel.md)
- [ReloadWindowLocations_02_SessionRestoreFinalization.md](./ReloadWindowLocations_02_SessionRestoreFinalization.md)
