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

Each feature spec folder separates inputs from output:
`<feature>/SPEC.md` is Hyde-authored and tracked; `<feature>/_source/`
holds third-party input material (vendor screenshots, vendor
documentation) and is gitignored. Never commit anything under `_source/`,
and never copy vendor prose into `SPEC.md`.

## Core Rules
1. **GUI is not scientific state.** Do not store authoritative arrays, figures, or
   analysis state in Qt.
2. **GUI is a string factory.** GUI actions should normally emit explicit,
   human-readable Python.
3. **Kernel is authoritative.** Use existing Jupyter/Spyder-style metadata paths rather
   than inventing GUI-owned mirrors.

Feature-specific transport and ownership rules live in
`project_management/ARCHITECTURE.md`. GUI-side IR/state/codec rules live in
`project_management/IR-CONTROL.md`.

## Working Rules
- Use feature branches for feature work. Branch naming conventions live in
  `project_management/STYLE.md`.
- Prefer the simplest working change in the existing path.
- Do not overbuild, generalize early, or add speculative infrastructure.
- Follow `project_management/STYLE.md` for `.ui` ownership, plugin naming, and branch
  naming conventions.
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
