# Hyde Architecture

## Central Dogma
1. The GUI may hold UI state, never authoritative scientific state.
2. The kernel is authoritative for namespace objects, live figures, and any Hyde-owned
   state that must stay scientifically correct.
3. GUI actions normally emit explicit Python strings. First-class figure dialogs now
   emit explicit matplotlib patch Python for routine figure mutation and may emit
   explicit Hyde helper calls for Hyde-owned figure operations such as
   `hyde.remove_traces(...)`, converging through backend resync/import back into
   kernel-owned figure IR.
4. Use the narrowest existing transport that fits the feature. Prefer standard Jupyter
   execution/comms over Hyde-specific relays.

## Runtime Model

### Processes
- **GUI process**: owns the MDI shell, plugin system, file watcher, lyse-compatible
  listener, the kernel-runtime plugin, the shared frontend kernel client, and the
  runtime-helper thread.
- **Kernel process**: `spyder_kernels` IPython kernel. It owns the authoritative
  namespace and live scientific state.
- **Runtime helper thread**: GUI-owned Lane 1 control relay plus kernel-lifecycle
  watcher. It does not own silent execution.

### IPC lanes
- **Lane 1: control**. `zprocess.ProcessTree` carries orchestration plus the narrow
  implemented table relays (`OPEN_TABLE_REQUEST`, `APPEND_TABLE_REQUEST`,
  `TABLE_DATA_RESPONSE`, project-state notifications).
- **Lane 2: execution and metadata**. Standard Jupyter execution plus Jupyter `comm`
  channels carry visible commands, silent background execution through the
  kernel-runtime plugin's shared frontend client, Spyder namespace view, and
  figure-window metadata/window traffic.

### Runtime ownership seams
- The `kernel_runtime` plugin owns the kernel subprocess, shared
  `FrontendKernelService`, Lane 1 watcher startup/shutdown, and the exported
  `kernel_runtime_service` plus `python_execution_service`.
- `python_execution_service` is the authoritative GUI-side hidden/visible
  command-dispatch surface and owns logging of the final dispatched command
  string. Feature-local debug logging may exist for local state inspection, but
  it is not the authoritative command-visibility path.
- The `python_terminal` plugin owns the visible terminal UI and exports
  `visible_terminal_service` for visible user-facing execution and history behavior.
- The shell exports lifecycle adapters used by the runtime layer:
  `on_kernel_ready`, `on_kernel_crashed`, `enter_no_project_state`,
  `activate_project`, `on_project_state_result`, `request_gui_quit`, and
  `finalize_quit`.

## Public Hyde Surface

Anything exported from `hyde/__init__.py` is public kernel-facing API.

The docstrings in `hyde/__init__.py` are the primary API documentation for that
surface.

`features/...` is not public API. It is the GUI state/codec translation layer that
turns GUI state into Python strings or GUI-facing metadata. For the generic GUI-side
state/codec pattern, see `IR-CONTROL.md`.

Across Hyde, each supported feature-library surface has one authoritative
`FeatureCodec`. Hyde does not keep parallel codecs inside one feature module as
competing truths for one feature surface. The current canonical examples are
`MatplotlibCodec` for Hyde's matplotlib-backed figure surface and `HydeCodec`
for Hyde-owned command generation. Legacy names such as `FigureIRCodec` or
`TableCodec` may remain as compatibility views, but they are not additional
`FeatureCodec` authorities.

Across Hyde, GUI-generated command Python comes from
`HydeGuiState.python_source()`. Preview surfaces display that same generated string,
and `Do It`, `To Cmd Line`, or `To Clip` may dispatch the cached preview payload
without regenerating it.

Across Hyde, `IR` means feature-specific internal representation/internal state that can
lower to standard Python. It is not always kernel-owned. Table state is GUI-owned long
enough to emit commands. Figure IR is kernel-owned and attached to the live
matplotlib `Figure`.

## Project Layout And Persistence

```text
example.hy/
├── manifest.toml
├── session.toml
├── session.py
├── exports/
├── terminal/history.py
├── procedures/__init__.py
├── procedures/helpers.py
└── data/
```

- `manifest.toml` + `data/` store saved kernel objects.
- `session.toml` stores declarative GUI session state.
- `session.py` stores executable reopen source for open saveable windows.
- `exports/` is the default project-local destination for figure graphics export.
- `terminal/history.py` stores visible command history only.
- `procedures/__init__.py` is the canonical project bootstrap and the bounded macro
  store for explicit saved window macros and project-defined fit functions.

### Project load order
1. GUI dispatches hidden `hyde.load_project(...)` through the kernel-runtime path.
2. Kernel enters no-project state, resets to Hyde baseline, runs
   `procedures/__init__.py`, restores saved objects, and signals project activation.
3. GUI restores `main_window` state from `session.toml`.
4. GUI emits `project_loaded` so plugins restore their declarative GUI state.
5. GUI executes `session.py` silently so first-class figures and tables reopen through
   their normal recreation paths.
6. If `session.py` reports `hyde.task_complete("session_restore", True)`, the GUI
   reapplies saved MDI stacking order and deferred tool-window presentation state.
   Because first-class figure windows arrive asynchronously over the figure `comm`
   path, Hyde may retry that ordering pass over a small number of event-loop turns
   until the named MDI subwindow set stabilizes. If session restore fails, that
   finalization step is skipped.

### Project save order
1. GUI dispatches hidden `hyde.save_project(...)` through the kernel-runtime path.
2. Kernel writes `manifest.toml` and `data/*`.
3. GUI writes `session.toml`, `session.py`, and `terminal/history.py`.

Saved kernel objects override same-name objects produced by `procedures/__init__.py`
when a project is loaded.

## Feature Boundaries

### Python Terminal
- Embedded `RichJupyterWidget`.
- Uses the shared frontend `QtKernelClient`.
- User-entered commands are visible.
- Kernel-runtime-owned hidden work executes with `silent=True` and must not consume
  visible prompt history.

### Python Variables
- Uses Spyder's namespace-view comm path.
- Browses kernel metadata only, not kernel objects themselves.
- Launches tables through `hyde.create_table(...)`.
- Future figure actions must target first-class `@hyde.figure` workflows.

### Tables
- Imperative entry points: `hyde.create_table(...)` for opening/reopening a table and
  `hyde.append_table(...)` for appending objects to an existing open table.
- Explicit saved-macro/session decorator: `@hyde.table`.
- GUI owns `TableState` and `MutationState` only long enough to generate commands and
  recreation source.
- Kernel remains authoritative for table data.
- Project session restore reuses the same recreation-source path as explicit macros, but
  preserves stable names via `name=<table_name>` in `session.py`.

### Project file dialogs
- Target-selecting project dialogs such as `New Project`, `Load Project`,
  `Heal Project`, `Save As`, and `Save Copy` are preview-backed
  `HydeDialogWidget` surfaces built on the shared `HydeFileDialog` /
  `HydeFileWidget` family in `hyde.user_interface.base_hyde_widgets`.
- That shared file-dialog family owns chooser UI, preview refresh from the backing
  command string, generic target validation, and optional overwrite confirmation.
- The backing command string for that family comes from the dialog state's
  `python_source()` path. `HydeFileDialog` subclasses extend the shared
  generation/submission path by overriding hooks and calling `super()` as needed
  rather than by creating alternate command-generation or submission paths.
- Concrete project dialogs own command-specific defaults and operation-specific
  exceptions such as same-target semantics or copy-target restrictions.
- Plain `Save` remains a direct hidden `hyde.save_project(mode="save")` dispatch
  with no chooser dialog.

### Figures
- Only first-class `@hyde.figure` figures enter Hyde MDI figure windows.
- Non-decorated figures stay ordinary kernel-side matplotlib figures and do not open
  Hyde figure windows in this deployment.
- Runtime truth is the live kernel `Figure`.
- Recreation/editability truth is kernel-owned `fig._hyde_ir`.
- Hyde treats user-facing figure-element identification as display metadata, not as
  scientific state. That metadata is owned by shared figure helper tooling such as
  `FigureDisplayHelper`, used through composition by figure-working tools and
  windows.
- For traces, Hyde distinguishes the raw plotted `label` from the synthesized
  canonical `display_name`. The canonical trace display contract is:
  - `{label}: {y} vs {x}` when `label` and `x` exist
  - `{label}: {y}` when `label` exists and `x` does not
  - `{y} vs {x}` when `label` does not exist and `x` exists
  - `{y}` when `y` exists and the earlier cases do not apply
  - `{label}` when `label` exists and no canonical `y` name exists
  - trace ID fallback only when neither `label` nor canonical source names exist
- After each completed Python execution block, the backend re-imports the supported
  semantic IR for dirty first-class figures from the live matplotlib object graph.
- GUI figure payloads from one completed execution block are applied in one queued
  batch on the frontend rather than being streamed into windows piecemeal.
- Unsupported live figure structure does not eject the figure from Hyde; Hyde keeps
  the supported subset in `fig._hyde_ir`, keeps the figure window live, and marks the
  window `[Unsupported Feature]`.
- Saving an unsupported first-class figure warns, but Hyde still writes
  supported-subset recreation source into `session.py` so the window reopens with the
  part Hyde can still represent.
- Axis, trace, and Curve Fit attached-display edits emit hidden matplotlib patch
  Python using `hyde.get_figure(...)`, and those hidden commands flow through Hyde's
  ordinary hidden-command logging path. When emitted strings would plausibly be used
  outside Hyde, Hyde prefers standard matplotlib/Python. Hyde figure helpers are
  allowed in emitted update strings only when no standard matplotlib equivalent exists
  or when the Hyde helper is the clearer contract for a Hyde-owned operation, such as
  `hyde.refresh_figure(...)` or `hyde.remove_traces(...)`. Curve Fit attached live
  update, preview, `Do It`, and `To Cmd Line` now share one attached-display
  command-generation model.
- `Save Graphics...` is a preview-backed figure export surface. The dialog owns
  only transient file/output UI state; figure export command generation belongs
  to a dedicated figure export state/codec path in the matplotlib feature
  layer, and execution still targets the live kernel figure resolved by stable
  Hyde figure name.
- Explicit first-class figure refresh/regenerate also emits hidden Python through
  Hyde's normal command path using `hyde.refresh_figure(...)`. `resize_redraw`
  remains the narrow accepted backend control-traffic exception for viewport-driven
  redraw only.
- Non-first-class figures do not use Hyde replay helpers or inferred GUI-owned live
  state. They remain ordinary matplotlib figures outside Hyde's first-class save/edit
  path.
- Consumer plugins edit first-class figures through the figure-owned
  `EditableFigureContext.open_session()` boundary exported by
  `figure_interactive`.
- That figure edit session now serves primarily as the figure-owned local draft/read
  boundary used to build emitted matplotlib patch Python against imported figure IR.
- Figure-working dialogs share UI-family behavior through a dedicated
  `HydeDialogWidget` subclass for figure work rather than through free shared helper
  functions. The intended shared surface for that family is a figure-dialog base class
  such as `HydeFigureDialogWidget`.
- Figure-working dialogs and windows should not each assemble their own user-facing
  trace names. They should consume shared figure helper tooling such as
  `FigureDisplayHelper` through a has-a relationship and use its canonical
  `display_name` surface.
- Consumer dialogs do not use raw `figure_ir` dictionaries or raw figure-action
  payloads as their working contract.
- Saved graph macros and `session.py` restore source both lower from figure IR.
- Figure window identity remains the stable figure/window handle. Visible figure
  window titles may include the current figure name plus canonical trace display
  names, but that does not change the stable save/restore identity. Hyde relies on
  the native title-bar truncation behavior for this first pass.

### Curve Fit
- Curve Fit is a GUI-owned command surface over kernel-owned namespace arrays,
  project-defined `@hyde.fit_function` procedures, and live first-class figure state
  when attached.
- Hyde ships built-in fit functions from `hyde.__init__`, and project-defined fit
  functions are discovered by running `procedures/__init__.py` and publishing the
  fit-function catalog through `hyde.recreation_registry`.
- `New Fit Function...` is intentionally narrow: it appends one minimal valid
  `@hyde.fit_function` scaffold to `procedures/__init__.py`, triggers the normal
  procedures reload path, refreshes the catalog, and reselects the new function.
- Curve Fit command generation flows through `CurveFitState.python_source()`
  over the GUI-side codec work in `hyde.features.lmfit_features`; authoritative
  fit results and any attached figure display objects live in the kernel/runtime
  figure path, not in Qt state.
- When Curve Fit is attached to a first-class figure, attached display traces are
  managed through the figure edit session boundary rather than by a dialog-local
  figure trace manager.

## Plugin Structure

- First-party plugins live in `hyde.user_interface.plugins`.
- Shell infrastructure lives under `hyde.user_interface.main`.
- Shared plugin helpers live in `hyde.user_interface.plugin_tools`.
- Only plugin packages are discovered by the plugin manager.
- Plugin/package naming, branch naming, and `.ui` ownership conventions live in
  `STYLE.md`.
- UI plugins that need Jupyter execution or metadata consume the runtime-owned shared
  services directly rather than reaching through shell wrappers or other widgets.
- Shared UI helpers should stay transport- or shell-level. Feature-specific support
  policy belongs in the consuming plugin or dialog. For example,
  `active_interactive_window()` only resolves the active typed Hyde interactive widget;
  Curve Fit and figure-control plugins decide separately whether an active figure window
  is sufficiently ready for their own dialogs.
- For figure-working dialogs, structural reuse should prefer inheritance from a shared
  figure-dialog base widget over free helper functions. Use helpers only for neutral
  transport- or shell-level utilities, not as the primary reuse mechanism for figure
  dialog behavior.
- Cross-plugin code reuse through neutral mixins or shared helpers is allowed when it
  is purely structural code sharing. Importing a mixin across plugin boundaries is not
  itself a boundary violation if the mixin does not carry runtime authority, does not
  reach through another plugin's widget internals, and does not substitute for a
  declared service boundary.
- **Strict Boundary Rule**: The core shell (`HydeApp`) must provide ZERO wrapper methods for plugin services (e.g. no `HydeApp.execute_command`). Plugins must consume registered services directly from the plugin manager. Providing shell wrappers over plugin logic is a boundary issue in disguise.

## Design Rule For New Work

Prefer the smallest change that keeps Hyde on one authoritative path:
- one kernel authority
- one public API surface per behavior
- one persistence path per product (`procedures/__init__.py` for explicit macros,
  `session.py` for automatic reopen)
- no GUI-owned scientific mirrors
