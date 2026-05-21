# Hyde Status

## Current State

Hyde now has a working GUI + kernel architecture with these implemented surfaces:
- managed `GUI -> spyder_kernels` runtime
- shared frontend `QtKernelClient`
- embedded Python Terminal
- Procedure Browser with GUI-owned file watching
- Python Variables via Spyder namespace comms
- kernel-backed editable tables
- first-class `@hyde.figure` figure windows
- Curve Fit with built-in and project-defined `@hyde.fit_function` discovery
- project save/load with `manifest.toml`, `session.toml`, `session.py`, and
  `terminal/history.py`

## Implemented Contracts

### Runtime
- GUI owns presentation, menus, watchers, and plugin state.
- Kernel owns scientific state and live figures.
- The kernel-runtime plugin owns the kernel subprocess, shared frontend client, Lane 1
  watcher, and the exported `kernel_runtime_service` plus
  `python_execution_service`.
- The Python Terminal plugin owns the visible console UI and exports
  `visible_terminal_service`.
- Runtime helper handles Lane 1 control messages and kernel-lifecycle watching.

### Tables
- `hyde.create_table(...)` opens or reopens a table by requested stable name.
- `hyde.append_table(...)` appends objects to an existing open table.
- `@hyde.table` is the recreation decorator.
- Open tables restore from `session.py`.
- Session restore preserves stable table names and `window_state='minimized'`.

### Figures
- Only first-class `@hyde.figure` figures open Hyde figure windows.
- Non-decorated figures stay out of the Hyde window system.
- Live matplotlib `Figure` is runtime truth.
- `fig._hyde_ir` is recreation/editability truth.
- Figure windows restore from `session.py` and preserve `window_pos` plus
  minimized/maximized window state.
- Figures that cannot yet lower complete recreation source are marked
  `[Macro Incomplete]`.

### Curve Fit
- `@hyde.fit_function` is the public project-facing registration path for Curve Fit
  discovery.
- Hyde ships built-in fit functions and merges them with project-defined procedures
  discovered after `procedures/__init__.py` reload.
- `New Fit Function...` appends a minimal valid scaffold to `procedures/__init__.py`,
  reloads procedures, refreshes the catalog, and keeps the dialog open on success.
- Curve Fit preview and commit commands lower from one GUI-side coefficient model, while
  authoritative fit results and attached figure traces remain kernel/runtime-owned.

### Project persistence
- Kernel objects save to `manifest.toml` + `data/`.
- Declarative GUI state saves to `session.toml`.
- Open saveable windows save to `session.py`.
- Visible command history saves to `terminal/history.py`.
- Mixed MDI restore preserves named `objectName()` order across tool windows, tables,
  and figures after successful `session.py` completion.

## Remaining Near-Term Gaps
- define the final Python Terminal output policy for silent kernel-runtime execution
- expand broader table interaction coverage
- continue figure-edit surface growth from the existing first-class figure model
- broaden Curve Fit beyond the implemented first pass

## Notes For Agents
- Specs and architecture docs describe the intended present-tense system.
- Keep history concise here; do not move implementation detail back into the default-open
  docs unless it changes current constraints.
