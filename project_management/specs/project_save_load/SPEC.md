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
- tool-window visibility and geometry
- Data Browser filter state
- open table windows
  - handle
  - visible title
  - tracked kernel names
  - hidden/visible state
  - geometry
- active table handle
- table counter

### `terminal/history.py`
Stores visible command history only.

Muted GUI micro-mutations and runtime-helper-owned silent execution are excluded.

## Editable Operations

### Save
- `File -> Save` writes `session.toml` and `terminal/history.py` in the active project.
- It then executes visible `hyde.save_project()`.
- The kernel rewrites `manifest.toml` and `data/*` in place for the current project.
- Hyde does not preserve an older synchronized kernel-state snapshot alongside the new one.

### Save As
- `File -> Save As...` prompts for a target `.hy` directory.
- If the target exists and is non-empty, Hyde asks for confirmation before overwriting
  the existing project contents.
- The GUI writes `session.toml` and `terminal/history.py` into that target.
- It then executes visible `hyde.save_project(target, mode="save_as", overwrite=True)`.
- After a successful save, Hyde switches to the new project and restores that saved session.

### Save Copy
- `File -> Save Copy...` prompts for a target `.hy` directory.
- If the target exists and is non-empty, Hyde asks for confirmation before overwriting
  the existing project contents.
- The GUI writes `session.toml` and `terminal/history.py` into that target.
- It then executes visible `hyde.save_project(target, mode="copy", overwrite=True)`.
- After a successful copy, Hyde keeps the current project active.

### Load
- Opening a project blocks the whole GUI with an application-modal busy state until the operation completes.
- The visible command is `hyde.load_project(target)`.
- `hyde.load_project(...)` always begins by setting `hyde.HYDE_PROJECT_DIR = None` and signaling the GUI into its no-project state.
- The kernel then resets to Hyde's clean baseline, runs `procedures/__init__.py`, restores saved objects from `manifest.toml`, sets `HYDE_PROJECT_DIR` to the active project, and signals the GUI to activate that project.
- After kernel objects are restored, the GUI restores `session.toml`.
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
1. GUI writes `session.toml`
2. GUI writes `terminal/history.py`
3. GUI executes visible `hyde.save_project(...)`
4. kernel writes `manifest.toml` and `data/*`

### Load order
1. GUI executes visible `hyde.load_project(...)`
2. kernel sets `HYDE_PROJECT_DIR = None`
3. kernel signals the GUI into no-project state
4. kernel resets to Hyde's clean baseline for that session
5. runtime helper silently bootstraps `procedures/__init__.py`
6. kernel restores saved objects into `__main__`
7. kernel sets `HYDE_PROJECT_DIR` to the loaded project and signals GUI activation
8. GUI restores `session.toml`

Saved kernel objects override same-name objects produced by `procedures/__init__.py`.
Objects from the previously loaded project do not survive a project switch unless they are recreated by procedures or restored from the new project's saved state.

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
- figure package persistence
- package persistence for table contents beyond reopening saved table windows from kernel names recorded in `session.toml`
- restoration of transient table editor state
- hidden, non-reproducible GUI-to-kernel save/load shortcuts
