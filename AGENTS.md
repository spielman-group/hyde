# Hyde Agent Instructions

Read this file before changing the Hyde codebase.

## Scope
- Hyde is a greenfield labscript-suite application, not a narrow legacy patch target.
- Do not use the `labscript-narrow-patch` skill here.
- Hyde does not own hardware control, runmanager queue logic, or broader suite HDF5
  lifecycle changes.

## Required Docs
Review these before coding:
- `project_management/ARCHITECTURE.md`
- `project_management/STYLE.md`
- `project_management/PLAN.md`
- `project_management/STATUS.md`

Use `project_management/specs/` only for the feature you are touching.

## Core Rules
1. **GUI is not scientific state.** Do not store authoritative arrays, figures, or
   analysis state in Qt.
2. **GUI is a string factory.** GUI actions should normally emit explicit,
   human-readable Python.
3. **Kernel is authoritative.** Use existing Jupyter/Spyder-style metadata paths rather
   than inventing GUI-owned mirrors.

For first-class figures, routine editing is the deliberate exception: use the existing
semantic figure `comm` path rather than GUI-generated matplotlib source.

## Working Rules
- Use feature branches for feature work.
- Prefer the simplest working change in the existing path.
- Do not overbuild, generalize early, or add speculative infrastructure.
- Do not add compatibility shims or migration code unless explicitly requested.
- Check `PLAN.md` for active remaining work.
- Use the local `$add-hyde-ui-feature` skill when creating or revising frontend specs.

## Tests
Run Hyde tests in the `labscript` conda environment.

## Documentation Rules
- Specs and architecture docs should describe the intended present-tense system.
- Put historical notes only in history/progress docs, not in specs.
