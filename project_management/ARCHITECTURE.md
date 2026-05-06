# Hyde Architecture

## Central Dogma
1. The GUI may hold UI state, never authoritative scientific state.
2. The kernel is authoritative for namespace objects, live figures, and any Hyde-owned
   state that must stay scientifically correct.
3. GUI actions normally emit explicit Python strings. The main exception is routine
   first-class figure editing, which uses semantic Jupyter `comm` actions against
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
  implemented table relays (`OPEN_TABLE_REQUEST`, `TABLE_DATA_RESPONSE`, project-state
  notifications).
- **Lane 2: execution and metadata**. Standard Jupyter execution plus Jupyter `comm`
  channels carry visible commands, silent background execution through the
  kernel-runtime plugin's shared frontend client, Spyder namespace view, and
  figure-window metadata/edit traffic.

## Public Hyde Surface

Anything exported from `hyde/__init__.py` is public kernel-facing API.

Current deliberate public entry points:
- `hyde.create_table(...)`
- `@hyde.table`
- `@hyde.figure`
- `hyde.save_project(...)`
- `hyde.load_project(...)`

`features/...` is not public API. It is the GUI state/codec translation layer that
turns GUI state into Python strings or GUI-facing metadata.

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
├── terminal/history.py
├── procedures/__init__.py
├── procedures/helpers.py
└── data/
```

- `manifest.toml` + `data/` store saved kernel objects.
- `session.toml` stores declarative GUI session state.
- `session.py` stores executable reopen source for open saveable windows.
- `terminal/history.py` stores visible command history only.
- `procedures/__init__.py` is the canonical project bootstrap and the bounded macro
  store for explicit saved window macros.

### Project load order
1. GUI sends visible `hyde.load_project(...)`.
2. Kernel enters no-project state, resets to Hyde baseline, runs
   `procedures/__init__.py`, restores saved objects, and signals project activation.
3. GUI restores `main_window` state from `session.toml`.
4. GUI emits `project_loaded` so plugins restore their declarative GUI state.
5. GUI executes `session.py` silently so first-class figures and tables reopen through
   their normal recreation paths.

### Project save order
1. GUI sends visible `hyde.save_project(...)`.
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
- Imperative entry point: `hyde.create_table(...)`.
- Explicit saved-macro/session decorator: `@hyde.table`.
- GUI owns `TableState` and `MutationState` only long enough to generate commands and
  recreation source.
- Kernel remains authoritative for table data.
- Project session restore reuses the same recreation-source path as explicit macros, but
  preserves stable handles via `target=<handle>` in `session.py`.

### Figures
- Only first-class `@hyde.figure` figures enter Hyde MDI figure windows.
- Non-decorated figures stay ordinary kernel-side matplotlib figures and do not open
  Hyde figure windows in this deployment.
- Runtime truth is the live kernel `Figure`.
- Recreation/editability truth is kernel-owned `fig._hyde_ir`.
- Routine GUI edits are semantic `comm` actions, not GUI-generated matplotlib source.
- Saved graph macros and `session.py` restore source both lower from figure IR.

## Plugin Structure

- First-party plugins live in `hyde.user_interface.plugins`.
- Shell infrastructure lives under `hyde.user_interface.main`.
- Shared plugin helpers live in `hyde.user_interface.plugin_tools`.
- Only plugin packages are discovered by the plugin manager.
- **Strict Boundary Rule**: The core shell (`HydeApp`) must provide ZERO wrapper methods for plugin services (e.g. no `HydeApp.execute_command`). Plugins must consume registered services directly from the plugin manager. Providing shell wrappers over plugin logic is a boundary issue in disguise.

## Design Rule For New Work

Prefer the smallest change that keeps Hyde on one authoritative path:
- one kernel authority
- one public API surface per behavior
- one persistence path per product (`procedures/__init__.py` for explicit macros,
  `session.py` for automatic reopen)
- no GUI-owned scientific mirrors
