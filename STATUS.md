# Hyde Status

## Current State

Hyde has a working first-pass implementation in this repo. The core paths are:

- `hyde/app.py`
- `hyde/main_window.py`
- `hyde/execution_controller.py`
- `hyde/execution_subprocess.py`
- `hyde/runtime.py`
- `hyde/project.py`
- `hyde/message_server.py`
- `hyde/message_handling.py`
- `hyde/annotations.py`
- `hyde/data.py`

The repo also has focused tests in:

- `tests/test_annotations.py`
- `tests/test_message_handling.py`
- `tests/test_project.py`
- `tests/test_runtime.py`

## What Is Implemented

- Standalone Hyde package scaffold and entry points.
- Main Qt window with:
  - MDI area
  - terminal dock
  - data browser dock
  - procedure browser dock
- Separate execution process using `labscript_utils.ls_zprocess.ProcessTree`.
- IPython-backed execution runtime in the child process.
- GUI-generated actions expressed as Python commands sent to the child runtime.
- Portable `.hy` project layout creation/open/save.
- Session persistence for:
  - objects
  - figures
  - tables
  - terminal history
  - incoming shot list
  - message handler settings
  - main-window geometry/state
- Hyde-managed array objects with revision tracking.
- Live figure/table refresh when Hyde-managed data changes through Hyde-aware operations.
- Procedure discovery from decorators:
  - `@figure`
  - `@table`
  - `@fit_function`
  - `@procedure`
- External-editor launching based on labconfig `programs.text_editor` and `text_editor_arguments`.
- Figure close prompt with save-to-script path.
- Basic lmfit workflow and replayable fit-command generation.
- Lyse-compatible inbound message handling for:
  - `'hello'`
  - `{'filepath': ...}`
  - raw filepath strings
  - `'get dataframe'`
  - `('get dataframe', n_sequences, filter_kwargs)`

## Architecture Notes

### Reused Suite Paths

- Reused `labscript_utils.labconfig` for appconfig conventions.
- Reused `labscript_utils.ls_zprocess.ProcessTree` for the GUI/child-process boundary.
- Reused lyse’s message contract rather than inventing a new inbound protocol.
- Mirrored the suite convention for launching an external editor from labconfig.

### Hyde-Specific Code

There was no existing suite app with Hyde’s `.hy` package model or its IPython-owned runtime, so those pieces are local to this repo and were not moved into `labscript-utils`.

## Important Behavior Assumptions

- Data-driven refresh is implemented for Hyde-managed runtime objects, not for arbitrary external mutations outside Hyde-aware code paths.
- Script text changes alone do not trigger figure refresh. Rerunning the script or running new commands does.
- Figure recreation scripts are plain `.py` files written into the project `figures/` directory.
- Tables are currently array-backed views over Hyde array data.
- The fit dialog and command generation are implemented, but the GUI is still a minimal v1 shell rather than a polished Igor-style workflow.

## Known Gaps / Next Work

- The GUI exists, but it has not been exercised end-to-end in this environment because the current shell does not have the full Qt/labscript runtime import path configured.
- `hyde/app.py` currently assumes suite dependencies are available at runtime; packaging/install validation still needs a real labscript environment.
- The fit dialog is functional but still basic:
  - no coefficient presets from parsed default values
  - no richer weighting/masking UI beyond the current command surface
  - no dedicated text output window yet
- Figure editing is basic:
  - title/xlabel/ylabel
  - trace label/style
  - no richer axis/legend/style UI yet
- Table editing currently routes cell edits back through generated Python commands, but only for simple array-style assignments.
- Message handling currently records inbound shots and exposes a dataframe-compatible listing, but does not yet parse shot-file contents into Hyde data objects.
- No zip import/export test yet beyond the project helper implementation.
- No GUI integration tests yet.
- No branch-memory update has been made outside this file.

## Test Status

These tests pass:

```bash
cd /Users/ispielma/Python/Labscript/hyde
MPLCONFIGDIR=/tmp/mpl-hyde PYTHONPATH=/Users/ispielma/Python/Labscript/hyde \
  /Users/ispielma/miniconda3/bin/python -m pytest -q \
  tests/test_annotations.py \
  tests/test_message_handling.py \
  tests/test_project.py \
  tests/test_runtime.py
```

Notes:

- `python -m compileall hyde tests` also passed.
- IPython emitted a warning in tests because `~/.ipython` was not writable in the current shell; tests still passed.

## Recommended Next Step

The next agent should start by validating the actual GUI in a real suite environment with working `qtutils`, `desktop_app`, and `labscript_utils` imports, then tighten the roughest v1 edges:

1. launch Hyde for real
2. verify project open/save and child-process round trips
3. verify figure save-on-close path from the GUI
4. verify lyse-style message receipt from runmanager/blacs-side tooling
5. refine fit/table/figure UX where the real runtime exposes gaps
