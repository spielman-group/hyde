## Parent

[ReloadWindowLocations.md](./ReloadWindowLocations.md)

## What to build

Implement the figure-side restore metadata required by the TRD on top of the current
`master` figure identity model.

This slice should preserve the existing `objectName()`-based figure identity and
kernel-owned figure naming logic while teaching machine-generated `session.py` restore
blocks to carry normal window position plus `window_state` for visible, minimized, and
maximized figure restore.

In the initial path, `geometry_minimized` belongs to machine-generated `session.py`
restore, not explicit saved figure macros.

## Acceptance criteria

- [ ] Figure `session.py` restore blocks preserve the stable figure `objectName()` and current kernel-owned figure naming behavior.
- [ ] Figure session restore metadata can represent `visible`, `minimized`, and `maximized` restore states.
- [ ] Minimized figure restore uses saved normal geometry as the restored figure window geometry and uses separate minimized geometry for the minimized title-bar representation.
- [ ] Explicit saved figure macros do not emit `geometry_minimized` in this initial path.
- [ ] Tests cover minimized/maximized figure restore and verify that minimized title-bar geometry is not reused as normal figure geometry.

## Blocked by

- [ReloadWindowLocations_01_ToolWindowStateModel.md](./ReloadWindowLocations_01_ToolWindowStateModel.md)
- [ReloadWindowLocations_02_SessionRestoreFinalization.md](./ReloadWindowLocations_02_SessionRestoreFinalization.md)

