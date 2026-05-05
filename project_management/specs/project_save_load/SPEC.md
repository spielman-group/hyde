# Hyde Project Save/Load Specification

## Summary
Hyde saves and loads `.hy` project packages through explicit public Hyde commands.

The GUI owns package/session files and path selection. The kernel owns authoritative
scientific object serialization and restoration. File-menu actions therefore generate
visible command strings such as:

```python
hyde.save_project("/abs/path/to/project.hy", mode="save_as")
```

and

```python
hyde.load_project("/abs/path/to/project.hy")
```

The GUI does not serialize live kernel objects directly.

Hyde has an explicit no-project state. When no project is active:
- `hyde.HYDE_PROJECT_DIR is None`
- the GUI's `current_project_dir is None`
- only `File -> New Project...`, `File -> Load Project...`, `Windows -> Logging`, and `File -> Quit` are active
- the command, procedures, and data-browser windows remain inaccessible until a project is activated

`File -> Save As...` prompts for confirmation before overwriting an existing non-empty
target project.
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
- automatic hidden kernel save/load calls that bypass visible command generation
- persistence of transient GUI editing state such as current table cell, in-progress text edits, or temporary selections

## Package Structure

Saved `.hy` packages use this structure:

```text
example.hy/
├── manifest.toml
├── session.toml
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
- plugin-contributed session payloads collected from each plugin's `get_save_data()`

The shell owns writing one `session.toml` file, but feature-owned GUI state is supplied
and restored by plugins. Implemented plugin payloads currently include persistent tool
window state, Python Variables filter state, and open table descriptors.

Live figure windows are not yet part of the implemented session payload set. When
figure persistence is introduced, Hyde restores first-class figure windows from
IR-backed recreation data or equivalent IR-derived descriptors rather than by pickling
live matplotlib `Figure` objects or trusting GUI-owned figure mirrors.

### `terminal/history.py`
Stores visible command history only.

Muted GUI micro-mutations and runtime-helper-owned silent execution are excluded.

## Editable Operations

### Save
- `File -> Save` executes visible `hyde.save_project(mode="save")`.
- After a successful kernel save result, the GUI rewrites `session.toml` and `terminal/history.py` in the active project.
- The `session.toml` write collects plugin-owned GUI state through `get_save_data()` before serializing the merged session file.
- The kernel rewrites `manifest.toml` and `data/*` in place for the current project.
- Hyde does not preserve an older synchronized kernel-state snapshot alongside the new one.

### Save As
- `File -> Save As...` prompts for a target `.hy` directory.
- If the target exists and is non-empty, Hyde asks for confirmation before overwriting
  the existing project contents.
- It then executes visible `hyde.save_project(target, mode="save_as", overwrite=True)`.
- After a successful save, the GUI writes `session.toml` and `terminal/history.py` into that target, switches Hyde to the new project, and restores that saved session.

### Save Copy
- `File -> Save Copy...` prompts for a target `.hy` directory.
- If the target exists and is non-empty, Hyde asks for confirmation before overwriting
  the existing project contents.
- It then executes visible `hyde.save_project(target, mode="copy", overwrite=True)`.
- After a successful copy, the GUI writes `session.toml` and `terminal/history.py` into that target and Hyde keeps the current project active.

### Load
- Opening a project reports progress in the main-window status bar while the visible command is in flight.
- The visible command is `hyde.load_project(target)`.
- `hyde.load_project(...)` always begins by setting `hyde.HYDE_PROJECT_DIR = None` and signaling the GUI into its no-project state.
- The kernel then resets to Hyde's clean baseline, runs `procedures/__init__.py`, restores saved objects from `manifest.toml`, sets `HYDE_PROJECT_DIR` to the active project, and signals the GUI to activate that project.
- After kernel objects are restored, the GUI restores `main_window` state and broadcasts the loaded `session.toml` payload to plugins so each plugin can restore its own GUI session state.
- If load fails after entering no-project state, both the kernel and the GUI remain in no-project state.

## Command Generation

### GUI-generated visible commands
- `hyde.save_project()`
- `hyde.save_project("/abs/path/to/project.hy", mode="save_as", overwrite=True)`
- `hyde.save_project("/abs/path/to/project.hy", mode="copy", overwrite=True)`
- `hyde.load_project("/abs/path/to/project.hy")`

### Runtime-helper-owned silent execution
- canonical `procedures/__init__.py` bootstrap

The runtime helper may coordinate completion/error reporting, but it does not replace the
visible-command contract for save/load.

## Synchronization

### Save order
1. GUI executes visible `hyde.save_project(...)`
2. kernel writes `manifest.toml` and `data/*`
3. kernel publishes the save result
4. GUI collects plugin `get_save_data()` payloads and writes `session.toml`
5. GUI writes `terminal/history.py`

### Load order
1. GUI executes visible `hyde.load_project(...)`
2. kernel sets `HYDE_PROJECT_DIR = None`
3. kernel signals the GUI into no-project state
4. kernel resets to Hyde's clean baseline for that session
5. `hyde.load_project(...)` bootstraps `procedures/__init__.py` inside the kernel command path
6. kernel restores saved objects into `__main__`
7. kernel sets `HYDE_PROJECT_DIR` to the loaded project and signals GUI activation
8. GUI restores `main_window` state and emits `project_loaded` with the parsed `session.toml` payload so plugins restore their own GUI session state

Saved kernel objects override same-name objects produced by `procedures/__init__.py`.
Objects from the previously loaded project do not survive a project switch unless they are recreated by procedures or restored from the new project's saved state.

Table layout restore is currently implemented by the table plugin. Table recreation
macros and `hyde.table(...)` may also carry saved table layout through `geometry` and
`column_widths`, but that recreation state is intentionally separate from project
session restore.

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
- Corrupt or missing `session.toml` is reported during GUI session restore without
  blocking kernel-state restore.
- Missing data files referenced by `manifest.toml` are reported and skipped.
- A failed load leaves Hyde in explicit no-project state rather than partially restoring the previous project.

## Explicit Exclusions
- current project save does not persist live figure windows, figure IR, or matplotlib
  `Figure` objects
- package persistence for table contents beyond reopening saved table windows from kernel names recorded in `session.toml`
- restoration of transient table editor state
- hidden, non-reproducible GUI-to-kernel save/load shortcuts

## Table Layout Persistence Boundary

The table plugin currently persists:

- table geometry
- table visibility
- saved data-column widths
- active table handle
- table counter

Table recreation source generated from `TableState` may also include:

- `geometry=(x, y, width, height)`
- `column_widths={"array_name": width, ...}`

`session.toml` remains the plugin-restored GUI session source, while recreation macros
remain the explicit table-reopen source stored in `procedures/__init__.py`. Hyde keeps
both because project session restore and explicit macro recreation solve different
workflow needs.

## Future Figure Persistence Boundary

Figure persistence is future work, but its architectural boundary is already defined.

When Hyde persists first-class figures, it uses the same authoritative figure IR that
powers saved figure recreation macros. In this context, figure IR means the figure
feature's internal representation or internal state in the same sense that
`TableState` is the table feature's internal state for the state-to-Python codec path.
The figure PRD makes a figure-specific architectural choice that this IR is
kernel-owned and attached to the live figure.

Future figure persistence therefore follows these rules:

- only first-class `@hyde.figure` figures participate
- the live kernel `Figure` remains the runtime object during a session
- the figure IR remains the recreation and editability truth
- project/session restore reopens figures from IR-backed recreation source or an
  equivalent serialized IR descriptor
- Hyde does not pickle live matplotlib `Figure` objects as the persistence format
- Hyde does not rely on GUI-owned semantic figure state during save or restore
