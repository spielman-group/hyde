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

Those user-facing surfaces are implemented. The current IR refactor phase is the
file-shape pass: feature-side package IR files, plugin-local widget workflow IR
files, and removal of non-neutral feature authority from `shared/`.
Behavior-level IR ownership cleanup remains later work.

## Implemented Contracts

### Runtime
- GUI presentation and plugin state are working against a kernel-authoritative runtime.
- The kernel-runtime and Python Terminal services are in place and exported through the
  current plugin architecture.

### IR Contract
- Hyde's intended app-wide contract is the `HydeIR` / `HydeIRDiff` model, not the
  earlier prototype codec/state architecture.
- `HydeIRDiff` is a `HydeIR` subclass.
- Every widget base family owns one base-level IR slot named `widget_ir`.
- `HydeInteractiveWidget.widget_ir` is the live current object IR.
- `HydeDialogWidget.widget_ir` and `HydeToolWidget.widget_ir` are their own IRs
  and may contain external IR snapshots used for preview or command generation.
- `python_source()` lives on IR objects, and `features/..._features.py` files are
  package-pure lowerers only.
- The repository now uses explicit IR module placement:
  package-owned IR families live in `hyde/features/<package>_ir.py`,
  widget-local workflow IRs live in plugin-local `<widget>_IR.py`, and
  non-neutral feature support code no longer lives under
  `hyde.user_interface.shared`.
- The repository now has the intended module shape for package IR and widget
  workflow IR. Later work will tighten behavior ownership inside those modules.

### Tables
- `hyde.create_table(...)` opens or reopens a table by requested stable name.
- `hyde.append_table(...)` appends objects to an existing open table.
- `@hyde.table` is the recreation decorator.
- `TableWidget.widget_ir` owns the live `TableIR` for table-window creation,
  recreation, layout capture, and in-table edit/create/delete mutation flows.
- Open tables restore from `session.py`.
- Session restore preserves stable table names and `window_state='minimized'`.

### Figures
- Only first-class `@hyde.figure` figures open Hyde figure windows.
- Figure windows restore from `session.py` and preserve saved window metadata.
- Figure windows now expose `Save Graphics...`, a figure-scoped `HydeFileDialog`
  export surface that defaults into the project-local `exports/` container and emits
  preview-backed live-kernel `savefig(...)` commands generated from figure IR
  through package-pure matplotlib lowerers.
- Figure-working surfaces now share canonical trace `display_name` generation
  through feature-side matplotlib trace-record helpers rather than widget-local
  fallback strings.
- Matplotlib figure state authority now lives under `hyde/features`, with
  figure-interactive support narrowed to plugin transport/window composition.
  That move is not finished: `hyde/features/matplotlib_features.py` still carries
  a second figure IR authority. See `issues/REFACTOR_STATUS.md`.
- Figure dialogs now use an explicit `EditableFigureContext` adapter, with
  `FigureDialogIR` kept workflow-only and `HydeFigureDialogWidget` owned by
  plugin-local widget support.
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
- Curve Fit preview/commit uses one GUI-side workflow IR over kernel-owned fit
  results and attached figure state. Preview, `Do It`, live update, and
  rollback/store command generation all flow through that IR object's
  `python_source()`, while attached-display patching stays on the shared
  figure-patch path.
- The next behavior pass will tighten Curve Fit semantics inside the new
  `lmfit_IR.py` / `curve_fit_IR.py` shape.

### Hidden Execution
- GUI-owned hidden work dispatches through the shared kernel-runtime execution path
  with `silent=True`, including file-menu project commands, table refresh helpers,
  file-watcher reload work, and remote requests from the lyse-compatible listener.

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
- do the behavior-level IR pass now that the file-shape refactor has landed
- define the final Python Terminal output policy for silent kernel-runtime execution
- expand broader table interaction coverage
- continue figure-edit surface growth from the existing first-class figure model
- broaden Curve Fit beyond the implemented first pass
