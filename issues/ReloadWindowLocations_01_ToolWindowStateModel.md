## Parent

[ReloadWindowLocations.md](./ReloadWindowLocations.md)

## What to build

Implement the tool-window persistence model described by the TRD using
`QMdiSubWindow.objectName()` as the stable identity.

This slice should replace boolean tool-window visibility persistence with explicit
`window_state` plus separate normal `geometry` and minimized `geometry_minimized`
capture/restore in `session.toml`.

The end-to-end behavior is:

- tool windows save as `hidden`, `visible`, `minimized`, or `maximized`
- minimized tool windows save both normal geometry and minimized title-bar geometry
- restore validates persisted data and hides invalid tool windows with warnings
- tool-window persistence keys track the subwindow `objectName()`, not a parallel
  Hyde-owned handle concept

## Acceptance criteria

- [ ] Tool-window `session.toml` state stores `window_state` and `geometry`, and stores `geometry_minimized` only for minimized windows.
- [ ] Tool-window restore accepts `hidden`, `visible`, `minimized`, and `maximized`, and restores hidden windows without showing them.
- [ ] Invalid or missing tool-window `window_state`, `geometry`, or required `geometry_minimized` causes the tool window to restore hidden and records a warning.
- [ ] Tests cover capture and restore for visible, hidden, minimized, and maximized tool windows using `objectName()` identity.

## Blocked by

None - can start immediately.
