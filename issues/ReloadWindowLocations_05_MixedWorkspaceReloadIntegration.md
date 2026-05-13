## Parent

[ReloadWindowLocations.md](./ReloadWindowLocations.md)

## What to build

Finish the TRD by proving that a mixed Hyde workspace restores correctly end-to-end.

This slice should verify the full save/load path across tool windows, tables, and
figures using the current `objectName()` identity model, with `session.toml`
contributing declarative tool-window state and MDI order, and `session.py` reopening
saveable windows before final ordering/state application.

This is the integration slice that demonstrates the restore model is coherent across
all named MDI subwindows.

## Acceptance criteria

- [ ] Saving a mixed workspace captures all named subwindows in `main_window.mdi_window_order`, including hidden tool windows.
- [ ] Loading that workspace restores tool windows, tables, and figures with the correct final visible/minimized/maximized presentation states.
- [ ] Final MDI stacking order after successful restore matches the saved order across mixed named subwindows.
- [ ] A failed `session.py` restore leaves the project load error path intact and skips final ordering/state application.
- [ ] Specs and architecture docs that describe project restore, IPC, table restore, and figure restore are updated to match the implemented behavior.

## Blocked by

- [ReloadWindowLocations_02_SessionRestoreFinalization.md](./ReloadWindowLocations_02_SessionRestoreFinalization.md)
- [ReloadWindowLocations_03_TableSessionRestoreState.md](./ReloadWindowLocations_03_TableSessionRestoreState.md)
- [ReloadWindowLocations_04_FigureSessionRestoreState.md](./ReloadWindowLocations_04_FigureSessionRestoreState.md)
