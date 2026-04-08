You are building a new labscript-suite application called Hyde.

Start here:
- Read `AGENTS.md` in the workspace root.
- Read `HYDE.md` in this directory.
- Read `START_HERE.md` in this directory.
- Read `STATUS.md` in this directory for the current implementation and handoff state.

The agent starts in `/Users/ispielma/Python/Labscript`. The Hyde project lives in the `hyde/` subdirectory. Change into `/Users/ispielma/Python/Labscript/hyde` and work there.
`HYDE.md` remains the spec source of truth. `STATUS.md` is the current progress and pickup document.

Use the existing labscript-suite conventions already present in the workspace.

Goal:
- Implement a working v1 of Hyde as a standalone PyQt application integrated with the labscript suite.
- Hyde is a Pythonic, Igor-Pro-like analysis and plotting application.
- Hyde is analysis/plotting only. It does not own experiment scripting or instrument control.

Non-negotiable constraints:
- Use the existing labscript Qt compatibility layer; do not import raw Qt bindings directly.
- Use a separate Python execution process for the terminal/session namespace, with IPython in that process.
- The GUI process and execution process must communicate through a clear IPC boundary.
- Hyde must accept the same inbound messages currently sent to lyse from runmanager or blacs.
- Hyde must not own the queue or the shot lifecycle.
- The project package is a portable `.hy` directory tree.
- Scripts are ordinary `.py` files on disk.
- Do not build an in-app text editor; selecting a script must open it in an external editor.
- The browser is a file browser over `.py` files in the `.hy` tree, not a custom IDE.
- Support the annotation/decorator convention from a Hyde import such as `from hyde import *`, including at least `@figure`, `@table`, `@fit_function`, and `@procedure`.
- The source remains plain Python; the annotations are metadata only.
- Figures must refresh when underlying data changes, but not when only the script text changes.
- GUI-generated actions must be represented as Python commands runnable in the terminal.
- Closing a figure must prompt to save a rerunnable figure script.
- Curve fitting must be built on lmfit and exposed through a GUI dialog with the four functional tab groups from the spec.
- Use matplotlib for plotting, gridspec-based figure composition, numpy for array-backed data, and existing suite conventions for persistence/locking where relevant.

Implementation priorities:
1. Read `HYDE.md` and inspect existing suite code paths for Qt, IPC, saving/loading, and message handling.
2. Build the application shell: main window, MDI area, terminal panel, data browser, procedure browser.
3. Implement the separated execution process with IPython and a minimal, reliable IPC bridge.
4. Implement package open/save/load for `.hy` projects and full session persistence.
5. Implement data-object browsing, inspection, table creation, and figure creation from browser actions.
6. Implement figure windows, trace/axis editing, save-on-close script prompting, and menu surfacing.
7. Implement live data-driven figure refresh via Hyde-managed data objects and change notifications.
8. Implement the curve-fitting workflow and command generation.
9. Wire message handling so incoming lyse-style messages are received and routed into Hyde actions.
10. Add tests for the core flows you implement.

Design rules:
- Prefer the simplest architecture that satisfies the spec.
- Reuse existing labscript-suite abstractions before writing new ones.
- Keep the codebase explicit and readable.
- If the spec leaves an ambiguity, make the smallest reasonable assumption, implement it, and document it.
- If you are truly blocked, ask at most one concise clarifying question.
- Do not do broad unrelated cleanup.

Deliverables:
- Working code in the workspace.
- Tests for the main behaviors.
- A short implementation summary with any assumptions and any remaining gaps.
- If you introduce any internal API changes, document them clearly.

Acceptance target:
- A user can create/open a `.hy` package.
- A user can browse data, create figures/tables, and run commands in the terminal.
- A user can save and reopen figures and scripts.
- A user can edit underlying data and see dependent figures refresh.
- A user can run curve fits from the GUI and generate replayable Python commands.
- Incoming lyse-style messages are received and handled by Hyde.
