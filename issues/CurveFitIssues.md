# Curve Fit Follow-Up Issues

## Checklist

- [X] Issue 1: Restore live-edited fit result targets on `Cancel`
- [X] Issue 2: Validate fit-result target names before lowering Python
- [X] Issue 3: Discover `@hyde.fit_function` definitions in project helper modules
- [X] Issue 4: Move Curve Fit catalog refresh onto Hyde's command-lowering path

## Issue 1: Restore live-edited fit result targets on `Cancel`

- **Title**: Make live Curve Fit `Cancel` restore the opening fit-result target state
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: Curve Fit live editing, Curve Fit cancel/revert behavior

### What to build

Fix the live Curve Fit revert path so `Cancel` restores any fit-result object the
dialog changed while live updates were enabled. Right now attached display traces are
rolled back, but the real kernel-side fit result target is left mutated after the
dialog closes.

This slice should preserve the current live-preview behavior while making `Cancel`
honor the existing Curve Fit contract for result-target ownership and revert.

### Acceptance criteria

- [X] When live updates are enabled, `Cancel` restores the opening state of any fit-result target the dialog changed.
- [X] If the dialog rotated across multiple result targets during one live session, each previously touched target is restored correctly.
- [X] Attached display rollback continues to work as it does now.
- [X] `Do It` / accept behavior is unchanged.
- [X] Behavior tests prove the live-cancel revert contract through observable kernel-side results, not just attached-display cleanup.

### TDD focus

- First failing behavior: live editing mutates a real fit-result target, then `Cancel` leaves it changed.
- Follow-up behavior: changing the target name during one live session still restores earlier targets on cancel.
- Final behavior in this slice: attached-display rollback and result-target rollback both happen on `Cancel`.

## Issue 2: Validate fit-result target names before lowering Python

- **Title**: Reject invalid fit-result target names in Curve Fit
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: Curve Fit command preview, `Do It`, `To Clip`

### What to build

Tighten Curve Fit validation so the fit-result target field only accepts names that
can be lowered safely into Python. The dialog should reject syntactically invalid
target names instead of reporting the configuration as valid and then emitting bad
Python source.

This slice should keep the editable target field while moving the validity check up
to the same stage as the rest of the Curve Fit configuration validation.

### Acceptance criteria

- [ ] Curve Fit rejects invalid Python identifiers in the fit-result target field.
- [ ] Invalid target names disable `Do It` and show a clear status message.
- [ ] `To Clip` and command preview never emit syntactically invalid assignment targets for a “valid” configuration.
- [ ] Valid target names continue to work exactly as before.
- [ ] Behavior tests cover at least one invalid identifier case and one valid editable target case.

### TDD focus

- First failing behavior: an invalid editable target name is treated as valid and lowers bad Python.
- Follow-up behavior: the dialog status and enabled/disabled state reflect that invalid target name immediately.
- Final behavior in this slice: only valid target names can reach preview/clipboard/execute paths.

## Issue 3: Discover `@hyde.fit_function` definitions in project helper modules

- **Title**: Treat helper-module `@hyde.fit_function` definitions as project fit functions
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: Curve Fit fit-function discovery, project procedures layout

### What to build

Extend fit-function discovery so project-defined `@hyde.fit_function` procedures are
accepted when they live in helper modules under the project `procedures/` package,
not just when they are defined in `procedures/__init__.py` itself.

This slice should align fit-function discovery with the documented project layout and
remove the current silent exclusion of helper-module functions.

### Acceptance criteria

- [X] `@hyde.fit_function` definitions loaded from `procedures` helper modules are registered in the fit-function catalog.
- [X] Built-in Hyde fit functions still register as before.
- [X] Non-project, non-Hyde functions are still excluded.
- [X] Tests cover a helper-module fit function without faking its `__module__` to `"procedures"`.
- [X] Existing fit-function registry behavior for rejection reporting and ordering still works.

### TDD focus

- First failing behavior: a fit function defined in a helper module under `procedures/` is ignored by discovery.
- Follow-up behavior: built-ins and top-level project procedures remain unchanged.
- Final behavior in this slice: project fit-function discovery matches the documented `procedures/` package layout.

## Issue 4: Move Curve Fit catalog refresh onto Hyde's command-lowering path

- **Title**: Stop hardcoding Curve Fit catalog refresh commands in plugin code
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: Curve Fit fit-function catalog refresh, architectural cleanup

### What to build

Replace the hardcoded hidden execution string used by `CurveFitCatalogService.refresh()`
with a normal Hyde command-lowering path. Curve Fit catalog refresh should use the same
kind of GUI-to-command translation boundary Hyde already uses for other runtime commands,
instead of embedding a raw Python string directly in plugin code.

This slice is primarily architectural. It should not change visible Curve Fit behavior.

### Acceptance criteria

- [X] Curve Fit catalog refresh no longer hardcodes a raw Python command string in plugin code.
- [X] Refresh still republishes the fit-function catalog successfully.
- [X] The implementation follows Hyde's normal command-lowering/runtime-command path rather than inventing a second one.
- [X] Existing user-visible catalog refresh behavior is unchanged.
- [X] Tests prove the refresh behavior without pinning incidental plugin internals.

### TDD focus

- First failing behavior: catalog refresh still works after moving off the hardcoded command string.
- Follow-up behavior: the refresh path uses Hyde's normal command-lowering/runtime-command mechanism.
- Final behavior in this slice: Curve Fit refresh stays behaviorally identical while the architectural split is removed.
