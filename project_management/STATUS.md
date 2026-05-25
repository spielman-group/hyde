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
- GUI presentation and plugin state are working against a kernel-authoritative runtime.
- The kernel-runtime and Python Terminal services are in place and exported through the
  current plugin architecture.

### Feature codecs
- Each supported feature-library surface now has one authoritative
  `FeatureCodec`.
- `MatplotlibCodec` is the one GUI-side codec truth for figure command
  generation, figure IR normalization, figure patch lowering, and graphics
  export lowering.
- `HydeCodec` is the one GUI-side codec truth for Hyde-owned project-command,
  runtime-command, table, and mutation generation.
- Legacy names such as `FigureCodec`, `FigureIRCodec`, `RuntimeCommandCodec`,
  and `TableCodec` now exist only as compatibility views over those canonical
  codecs.

### Tables
- `hyde.create_table(...)` opens or reopens a table by requested stable name.
- `hyde.append_table(...)` appends objects to an existing open table.
- `@hyde.table` is the recreation decorator.
- Open tables restore from `session.py`.
- Session restore preserves stable table names and `window_state='minimized'`.

### Figures
- Only first-class `@hyde.figure` figures open Hyde figure windows.
- Figure windows restore from `session.py` and preserve saved window metadata.
- Figure windows now expose `Save Graphics...`, a figure-scoped `HydeFileDialog`
  export surface that defaults into the project-local `exports/` container and emits
  preview-backed live-kernel `savefig(...)` commands generated through a dedicated
  figure export state/codec path in the matplotlib feature layer.
- Figure-working surfaces now share canonical trace `display_name` generation through
  the composed `FigureDisplayHelper` path rather than widget-local fallback strings.
- Figure-window chrome now shows the current figure name plus canonical trace display
  names while preserving stable window identity separately for save/restore and
  subwindow binding.
- Dirty first-class figures resync from the live matplotlib object graph and stay live
  when unsupported structure is imported.
- Unsupported imported live structure is surfaced in figure-window chrome.
- Saving an unsupported first-class figure warns and still preserves the supported
  subset in `session.py`, so the window reopens instead of disappearing entirely.
- Axis, trace, and Curve Fit attached-display dialogs now mutate first-class figures
  through hidden matplotlib patch Python routed over Hyde's standard hidden-command
  execution/logging path, and Curve Fit attached live/preview uses the same
  command-generation model as `Do It` / `To Cmd Line`.
- Hidden and visible GUI command dispatch now log the final dispatched command at the
  transport layer, so command visibility no longer depends on feature-local logging
  shims.
- Explicit first-class figure refresh/regenerate now uses the same hidden
  command-driven path; only viewport `resize_redraw` stays on the narrow backend
  control lane.
- For detailed figure ownership and transport rules, see `ARCHITECTURE.md`.

### Curve Fit
- `@hyde.fit_function` is the public project-facing registration path for Curve Fit
  discovery.
- Hyde ships built-in fit functions and merges them with project-defined procedures
  discovered after `procedures/__init__.py` reload.
- `New Fit Function...` appends a minimal valid scaffold to `procedures/__init__.py`,
  reloads procedures, refreshes the catalog, and keeps the dialog open on success.
- Curve Fit preview/commit uses one GUI-side coefficient model over kernel-owned fit
  results and attached figure state. Preview, `Do It`, live update, and
  rollback/store command generation all flow through
  `CurveFitState.python_source()`, while attached-display patching stays on the
  shared figure-patch path.

### Project persistence
- Kernel objects save to `manifest.toml` + `data/`.
- Declarative GUI state saves to `session.toml`.
- Open saveable windows save to `session.py`.
- Visible command history saves to `terminal/history.py`.
- Target-selecting project dialogs now use the shared `HydeFileDialog` /
  `HydeFileWidget` family, preview the real generated Hyde command, and route
  `Do It`, `To Cmd Line`, and `To Clip` through that same preview payload.
- `File -> Save` remains a direct hidden `hyde.save_project(mode='save')` dispatch
  with no chooser dialog.
- Same-target `Save As...` degenerates to plain `hyde.save_project(mode='save')`
  without overwrite confirmation.
- Same-target `Save Copy...` stays inline validation that requires a different `.hy`
  target before Hyde enables payload actions.
- Mixed MDI restore preserves named `objectName()` order across tool windows, tables,
  and figures after successful `session.py` completion.

## Remaining Near-Term Gaps
- define the final Python Terminal output policy for silent kernel-runtime execution
- expand broader table interaction coverage
- continue figure-edit surface growth from the existing first-class figure model
- broaden Curve Fit beyond the implemented first pass
