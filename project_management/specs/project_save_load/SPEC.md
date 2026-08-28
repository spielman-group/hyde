# Hyde Project Save/Load Specification

## Summary
Hyde saves and loads `.hy` project packages through explicit public Hyde commands.

The GUI owns package/session files and path selection. The kernel owns authoritative
scientific object serialization and restoration. File-menu actions therefore generate
Hyde command strings such as:

```python
hyde.save_project("/abs/path/to/project.hy", mode="save_as")
```

and

```python
hyde.load_project("/abs/path/to/project.hy")
```

The GUI dispatches these file-menu commands through Hyde's hidden kernel-runtime
execution path rather than through the visible Python Terminal session.

The GUI does not serialize live kernel objects directly.

Target-selecting project dialogs such as `New Project`, `Load Project`,
`Heal Project`, `Save As`, and `Save Copy` are preview-backed
`HydeDialogWidget` surfaces built on the shared `HydeFileDialog` /
`HydeFileWidget` family in `hyde.user_interface.base_hyde_widgets`. They show the
actual generated Hyde Python in the lower preview pane and use that same backing
command string for `Do It`, `To Cmd Line`, and `To Clip`.
`File -> Save` remains a direct hidden `hyde.save_project(mode='save')` dispatch
with no chooser dialog.

Hyde has an explicit no-project state. When no project is active:
- `hyde.HYDE_PROJECT_DIR is None`
- the GUI's `current_project_dir is None`
- only `File -> New Project...`, `File -> Load Project...`, `Windows -> Logging`, and `File -> Quit` are active
- the command, procedures, and data-browser windows remain inaccessible until a project is activated

`File -> Save As...` skips overwrite confirmation when the selected target is the
current project and otherwise prompts before overwriting an existing non-empty target
project.
`File -> Save` rewrites the package's current saved state in place rather than
preserving an older synchronized copy.

## Visible Controls

### Active
- `File -> Save`
- `File -> Save As...`
- `File -> Save Copy...`
- `File -> Load...`
- `File -> New Project...`

### Excluded
- hidden save/load implementation paths that bypass `hyde.save_project(...)` or
  `hyde.load_project(...)` command generation
- persistence of transient GUI editing state such as current table cell, in-progress text edits, or temporary selections

## Package Structure

Saved `.hy` packages use this structure:

```text
example.hy/
├── manifest.toml
├── session.toml
├── session.py
├── terminal/
│   └── history.py
├── procedures/
│   ├── __init__.py
│   └── helpers.py
└── data/
```

### `manifest.toml`
Records saved kernel objects:
- `format_version`
- `project_name`
- `saved_at`
- `[[objects]]`
  - `name`
  - `serializer`
  - `path`
  - `python_type`

### `session.toml`
Records GUI/session state:
- main-window geometry/state
- plugin-contributed declarative session payloads collected from each plugin's
  `get_session_toml_data()`

The shell owns writing one `session.toml` file, but feature-owned GUI state is supplied
and restored by plugins. Implemented plugin payloads currently include persistent tool
window state and Python Variables filter state.

### `session.py`
Records executable restore source for open saveable windows.

The shell owns writing one `session.py` file by concatenating plugin-owned restore
source gathered from each plugin's `get_session_restore_source()` hook.

Implemented restore blocks currently include:

- first-class `@hyde.figure(..., register=False)` recreation functions plus invocations
- `@hyde.table(..., register=False)` recreation functions plus invocations that call
  `hyde.create_table(..., name=<table_name>)`

`session.py` runs silently after a successful project load once `main_window` state is
restored, plugins have received `project_loaded`, and the kernel has already completed
its normal `procedures/__init__.py` bootstrap and saved-object restore.

### `terminal/history.py`
Stores visible command history only.

Muted GUI micro-mutations and kernel-runtime-owned silent execution are excluded.

## Editable Operations

### Save
- `File -> Save` dispatches hidden `hyde.save_project(mode="save")`.
- `File -> Save` does not open a chooser dialog and does not use the shared
  target-selecting file-dialog surface.
- After a successful kernel save result, the GUI rewrites `session.toml`,
  `session.py`, and `terminal/history.py` in the active project.
- The `session.toml` write collects plugin-owned GUI state through
  `get_session_toml_data()` before serializing the merged session file.
- The `session.py` write collects plugin-owned executable restore source through
  `get_session_restore_source()`.
- The kernel rewrites `manifest.toml` and `data/*` in place for the current project.
- Hyde does not preserve an older synchronized kernel-state snapshot alongside the new one.

### Save As
- `File -> Save As...` prompts for a target `.hy` directory.
- If the selected target is the current project directory, Hyde previews and
  dispatches plain `hyde.save_project(mode='save')` and skips overwrite
  confirmation.
- Otherwise, if the target exists and is non-empty, Hyde asks for confirmation
  before overwriting the existing project contents.
- It then dispatches hidden
  `hyde.save_project(target, mode="save_as", overwrite=True)`.
- After a successful save, the GUI writes `session.toml`, `session.py`, and
  `terminal/history.py` into that target, switches Hyde to the new project, and
  restores that saved session.

### Save Copy
- `File -> Save Copy...` prompts for a target `.hy` directory.
- If the selected target is the current project directory, Hyde shows an inline
  validation error and does not generate a payload until the user picks a different
  `.hy` directory.
- Otherwise, if the target exists and is non-empty, Hyde asks for confirmation
  before overwriting the existing project contents.
- It then dispatches hidden
  `hyde.save_project(target, mode="copy", overwrite=True)`.
- After a successful copy, the GUI writes `session.toml`, `session.py`, and
  `terminal/history.py` into that target and Hyde keeps the current project active.

### Load
- Opening a project reports progress in the main-window status bar while the hidden
  project command is in flight.
- The dispatched command is `hyde.load_project(target)`.
- `hyde.load_project(...)` always begins by setting `hyde.HYDE_PROJECT_DIR = None` and signaling the GUI into its no-project state.
- The kernel then resets to Hyde's clean baseline, runs `procedures/__init__.py`, restores saved objects from `manifest.toml`, sets `HYDE_PROJECT_DIR` to the active project, and signals the GUI to activate that project.
- After kernel objects are restored, the GUI restores `main_window` state, broadcasts
  the loaded `session.toml` payload to plugins so each plugin can restore its own GUI
  session state, and then executes `session.py` silently so saveable windows reopen
  through their normal recreation paths.
- `session.py` executes inside a wrapper that reports
  `hyde.task_complete("session_restore", success=...)`.
- If `session_restore` succeeds, the GUI reapplies saved MDI stacking order and any
  deferred tool-window minimized/maximized presentation state.
- First-class figure windows are created over the Jupyter figure `comm` path, so the
  GUI may need a small number of event-loop turns after `session_restore` succeeds
  before all named saveable windows exist. Hyde therefore finalizes saved MDI order
  with a short settling pass rather than assuming every restored subwindow is present
  immediately when `task_complete(...)` arrives.
- If `session_restore` fails, the existing error path remains intact and that final
  ordering/presentation pass is skipped.
- If load fails after entering no-project state, both the kernel and the GUI remain in no-project state.

## Command Generation

### GUI-generated project commands
- `hyde.save_project(mode='save')`
- `hyde.save_project("/abs/path/to/project.hy", mode="save_as", overwrite=True)`
- `hyde.save_project("/abs/path/to/project.hy", mode="copy", overwrite=True)`
- `hyde.load_project("/abs/path/to/project.hy")`

These commands are generated by the GUI and dispatched through Hyde's hidden
kernel-runtime execution path. They do not enter `terminal/history.py` unless the user
types them manually in the Python Terminal.

For target-selecting project dialogs, the shared file-dialog family owns chooser UI,
preview synchronization, generic target validation, and optional overwrite
confirmation. Concrete dialogs own command-specific defaults and operation-specific
exceptions such as same-target `Save As` degenerating to plain `save` and
same-target `Save Copy` remaining inline validation.

### Kernel-runtime-owned silent execution
- file-menu project-command dispatch
- canonical `procedures/__init__.py` bootstrap
- `session.py` restore after project activation

The kernel-runtime path dispatches the commands, but it does not replace the public
Hyde command contract for save/load.

## Synchronization

### Save order
1. GUI dispatches hidden `hyde.save_project(...)`
2. kernel writes `manifest.toml` and `data/*`
3. kernel publishes the save result
4. GUI collects plugin `get_session_toml_data()` payloads and writes `session.toml`
5. GUI collects plugin `get_session_restore_source()` blocks and writes `session.py`
6. GUI writes `terminal/history.py`

### Load order
1. GUI dispatches hidden `hyde.load_project(...)`
2. kernel sets `HYDE_PROJECT_DIR = None`
3. kernel signals the GUI into no-project state
4. kernel resets to Hyde's clean baseline for that session
5. `hyde.load_project(...)` bootstraps `procedures/__init__.py` inside the kernel command path
6. kernel restores saved objects into `__main__`
7. kernel sets `HYDE_PROJECT_DIR` to the loaded project and signals GUI activation
8. GUI restores `main_window` state and emits `project_loaded` with the parsed `session.toml` payload so plugins restore their own GUI session state
9. GUI dispatches wrapped `session.py` through the kernel-runtime hidden execution path so saveable windows reopen after normal project activation
10. On successful `hyde.task_complete("session_restore", True)`, GUI reapplies saved `main_window.mdi_window_order` plus deferred tool-window presentation state
11. If late-arriving first-class figure windows are still entering through the figure `comm` path, GUI repeats the ordering pass over a small number of event-loop turns until the named restored subwindow set stabilizes

Saved kernel objects override same-name objects produced by `procedures/__init__.py`.
Objects from the previously loaded project do not survive a project switch unless they are recreated by procedures or restored from the new project's saved state.

Project session restore and explicit window macros share the same recreation-source
lowering paths, but they remain separate persistence products:

- `procedures/__init__.py` stores explicit user-facing saved macros
- `session.py` stores machine-generated reopen source for currently open saveable windows

## Kernel Save/Load Rules

### Inclusion model
Kernel objects are saved by exclusion, not whitelist.

### Exclusions
- names starting with `_`
- modules
- packages
- functions / methods / builtins
- classes / types
- interactive namespace artifacts such as `In` and `Out`
- interactive helpers such as `exit` and `quit`

### Serializers
- `numpy.ndarray` -> `.npy`
- all other saveable objects -> pickle `.pkl`

## Failure Behavior
- If one object fails to save, Hyde continues saving the rest and reports warnings.
- In-place save rewrites the current persisted state; Hyde does not keep an additional backup copy of the older saved state in this pass.
- If one object fails to load, Hyde continues loading the rest and reports warnings.
- Corrupt or missing `session.toml` or `session.py` is reported during GUI session restore without
  blocking kernel-state restore.
- Missing data files referenced by `manifest.toml` are reported and skipped.
- A failed load leaves Hyde in explicit no-project state rather than partially restoring the previous project.

## Explicit Exclusions
- current project save does not persist live figure windows, figure IR, or matplotlib
  `Figure` objects as kernel saved objects
- package persistence for table contents beyond reopening saved table windows from
  `session.py`
- restoration of transient table editor state
- hidden GUI-to-kernel save/load paths that bypass public Hyde command generation

## Table Layout Persistence Boundary

The table plugin currently persists:

- table geometry
- `window_state='minimized'` or `window_state='maximized'`
- saved data-column widths
- active table `objectName()`
- stable table `objectName()` values through `name=<table_name>` in `session.py`
  restore blocks

Table recreation source generated from `TableIR` may also include:

- `geometry=(x, y, width, height)`
- `column_widths={"array_name": width, ...}`

`session.py` remains the machine-generated plugin-restored reopen source, while
recreation macros remain the explicit table-reopen source stored in
`procedures/__init__.py`. Hyde keeps both because project session restore and explicit
macro recreation solve different workflow needs.

## Figure Persistence Boundary

First-class figure persistence uses the same authoritative figure IR that
powers saved figure recreation macros. In this context, figure IR means the figure
feature's internal representation or internal state in the same sense that
`TableIR` is the table feature's internal state for the state-to-Python path. The
figure feature makes the figure-specific architectural choice that this IR is
kernel-owned and attached to the live figure.

Figure project/session restore therefore follows these rules:

- only first-class `@hyde.figure` figures participate
- the live kernel `Figure` remains the runtime object during a session
- the figure IR remains the recreation and editability truth
- project/session restore reopens figures from IR-backed recreation source in
  `session.py`
- figure restore metadata may request `window_pos`, `window_state='minimized'`, or
  `window_state='maximized'`
- Hyde does not pickle live matplotlib `Figure` objects as the persistence format
- Hyde does not rely on GUI-owned semantic figure state during save or restore
