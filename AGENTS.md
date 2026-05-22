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
- `project_management/IR-CONTROL.md`
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

For command-emitting GUI surfaces or GUI-side lowering/state work, follow
`project_management/IR-CONTROL.md`.

## Working Rules
- Use feature branches for feature work.
- Prefer the simplest working change in the existing path.
- Do not overbuild, generalize early, or add speculative infrastructure.
- For plugin dialogs and tool-window bodies, keep static layout structure in `.ui`
  files by default. Use Python to wire signals, populate dynamic rows/items, and host
  genuinely runtime-only widgets, not to hand-build large static form/layout trees.
- Do not add compatibility shims or migration code unless explicitly requested.
- Do not add optional production fallbacks solely to accommodate outdated tests,
  fake UI hosts, or stale local fixtures. When the real product contract changes,
  update the tests and fixtures to match the real contract.
- Do not add trivial pass-through helpers or wrapper methods that only rename or
  forward to a shared helper without adding real local policy. Prefer making the
  shared helper the actual interface.
- Neutral shared mixins are allowed across plugin boundaries when they only share code
  shape. Do not flag a mixin import as a boundary violation unless it carries runtime
  authority or causes plugin interaction to bypass declared services.
- Check `PLAN.md` for active remaining work.
- Use the local `$add-hyde-ui-feature` skill when creating or revising frontend specs.

## Tests
Run Hyde tests in the `labscript` conda environment.
- Tests must verify behavior or an explicit architectural contract whenever possible.
  Do not accept tests that only assert incidental call order, helper wiring, import
  shape, or mock interactions when a real behavior can be exercised instead.
- Before adding or keeping a test, ask what defect it would catch in the running
  application. If the answer is only "this implementation changed," rewrite the test
  around the observable contract.

## Documentation Rules
- Specs and architecture docs should describe the intended present-tense system.
- Put historical notes only in history/progress docs, not in specs.
