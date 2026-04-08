# Hyde Agent Start Here

Read these files first:

1. `AGENTS.md` in the workspace root.
2. `HYDE.md` in this directory.
3. This file.
4. `STATUS.md` in this directory for current implementation state, test status, and remaining gaps.

Hyde is a new labscript-suite application. The spec in `HYDE.md` is the source of truth.
`STATUS.md` is the current handoff/state document and should be checked before resuming work.

Immediate goals:

- Set up the package scaffolding for the Hyde application.
- Build the application shell.
- Implement the separated execution process with IPython.
- Implement package open/save/load for `.hy` projects.
- Implement the data browser, procedure browser, figure windows, and curve fitting workflow.
- Wire message handling compatible with the current `lyse` message path.

Working rules:

- Use existing labscript-suite abstractions where possible.
- Do not import raw Qt bindings directly.
- Do not build an in-app code editor.
- Keep scripts as ordinary `.py` files.
- Use the annotation convention described in `HYDE.md`.
- Prefer narrow, testable changes over broad refactors.

Suggested order of implementation:

1. Scaffold the package and application entry points.
2. Build the main window and shell UI.
3. Add the execution process and IPC bridge.
4. Add package persistence and browser views.
5. Add figures, tables, and live refresh.
6. Add curve fitting and annotation discovery.
7. Add message compatibility and tests.
