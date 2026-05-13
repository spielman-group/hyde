## Parent

[ReloadWindowLocations.md](./ReloadWindowLocations.md)

## What to build

Implement the table-side restore metadata required by the TRD on top of the current
`master` table identity model.

This slice should keep the current public table API shape
(`hyde.create_table(..., name=...)`, `hyde.append_table(..., name=...)`,
`@hyde.table`) and teach machine-generated `session.py` restore blocks to carry the
table window's normal geometry and `window_state` while preserving the stable table
`objectName()`.

## Acceptance criteria

- [ ] Table `session.py` restore blocks preserve the stable table `objectName()` through the current `name=<table_name>` path.
- [ ] Table session restore metadata can represent `visible`, `minimized`, and `maximized` restore states.
- [ ] Minimized table restore uses saved normal geometry as the table's restored geometry when it returns to normal state.
- [ ] Explicit saved table macros do not emit minimized-layout-only metadata in this initial path.
- [ ] Tests cover minimized/maximized table restore and verify that minimized restore remains state-only.

## Blocked by

- [ReloadWindowLocations_01_ToolWindowStateModel.md](./ReloadWindowLocations_01_ToolWindowStateModel.md)
- [ReloadWindowLocations_02_SessionRestoreFinalization.md](./ReloadWindowLocations_02_SessionRestoreFinalization.md)
