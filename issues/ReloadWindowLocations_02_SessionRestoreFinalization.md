## Parent

[ReloadWindowLocations.md](./ReloadWindowLocations.md)

## What to build

Add the delayed session-restore finalization path that lets Hyde restore tables and
figures through `session.py`, then apply saved MDI ordering and final presentation
states only after `session.py` succeeds.

This slice should add the narrow public `hyde.task_complete(name, success=True)` API,
carry it over the existing kernel-to-GUI ProcessTree path, wrap `session.py` execution
with `task_complete("session_restore", ...)`, and finalize restore only on success.

The end-to-end behavior is:

- `session.py` success triggers final MDI ordering/state application
- `session.py` failure skips final ordering/state application
- `main_window.mdi_window_order` stores all named subwindows by `objectName()`
- final ordering is applied without raising hidden tool windows

## Acceptance criteria

- [ ] Hyde exposes `hyde.task_complete(name, success=True)` and the runtime helper forwards `TASK_COMPLETE` messages to the GUI.
- [ ] Project load wraps silent `session.py` execution so `session_restore` reports success or failure through `hyde.task_complete(...)`.
- [ ] `session.toml` capture stores `main_window.mdi_window_order` using all named subwindows in Qt stacking order.
- [ ] On successful `session_restore`, Hyde applies saved stacking order and then applies final saved presentation states; on failed `session_restore`, Hyde skips finalization.
- [ ] Tests cover success, failure, and ordering behavior for mixed named subwindows.

## Blocked by

- [ReloadWindowLocations_01_ToolWindowStateModel.md](./ReloadWindowLocations_01_ToolWindowStateModel.md)

