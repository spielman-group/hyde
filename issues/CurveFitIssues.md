# Curve Fit Issues

## Checklist

- [X] Issue 1: Launch Curve Fit from `Analysis` with attach/unattach behavior
- [X] Issue 2: Discover `@hyde.fit_function` definitions and scaffold new functions
- [X] Issue 3: Configure function/data binding and generate preview text
- [X] Issue 4: Edit coefficient and data-option state with validation-gated `Do It`
- [X] Issue 5: Execute suppressed one-shot fits to create or recreate the result object
- [X] Issue 6: Add live rerun, failure retention, and result-target handoff behavior
- [X] Issue 7: Render and revert dialog-owned fit and residual traces on attached figures

## Issue 1: Launch Curve Fit from `Analysis` with attach/unattach behavior

- **Title**: Launch Curve Fit from `Analysis`
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: 1, 2, 3, 4, 5

### What to build

Add the first thin end-to-end Curve Fit path: a modal Curve Fit dialog reachable from
the `Analysis` menu that auto-attaches to the active supported figure when one exists
and otherwise opens unattached. In unattached mode, the dialog still opens with the
same overall layout, but graph-display controls are visibly disabled.

This slice should prove the launch contract, modal behavior, active-figure resolution,
and no-figure fallback without yet requiring fit-function discovery or fit execution.

### Acceptance criteria

- [ ] The `Analysis` menu exposes `Curve Fit...` as a first-pass launch surface.
- [ ] Launching from `Analysis` opens one modal Curve Fit dialog.
- [ ] If a supported figure is active, the dialog starts attached to that figure context.
- [ ] If no supported figure is active, the dialog still opens and remains usable as an unattached dialog shell.
- [ ] In unattached mode, fit-curve and residual display controls remain visible but disabled.
- [ ] Behavior tests cover attached and unattached launch behavior through public UI/service entry points.

### TDD focus

- First failing behavior: launching `Curve Fit...` from `Analysis` with no active figure opens the modal dialog and disables plotting controls.
- Follow-up behavior: launching with an active supported figure opens the same dialog in attached mode.
- Tests should assert observable dialog state and launch results, not menu wiring internals or helper call order.

## Issue 2: Discover `@hyde.fit_function` definitions and scaffold new functions

- **Title**: Discover and scaffold fit functions
- **Type**: AFK
- **Blocked by**: Issue 1
- **User stories covered**: 6, 7, 8, 9, 36

### What to build

Add the first complete fit-function workflow through the dialog: populate the chooser
from discovered `@hyde.fit_function` definitions, including Hyde-provided built-ins and
project-defined procedures functions, enforce the strict first-pass signature contract,
and support `New Fit Function...` by appending a minimal valid scaffold to the
procedures environment, reloading procedures, keeping the dialog open, and selecting
the newly created function.

This slice should cover discovery, validation, user feedback for unsupported signatures,
and scaffold/reload behavior without yet requiring full data binding or fit execution.

### Acceptance criteria

- [ ] The fit-function chooser shows discovered `@hyde.fit_function` definitions only, including Hyde-provided built-ins and project-defined procedures functions.
- [ ] The fit-function chooser preserves registration/definition order rather than alphabetical sorting, with Hyde's built-in `line` appearing first.
- [ ] Discovery accepts multivariate functions using `independent_vars` and explicitly named coefficient parameters.
- [ ] Discovery rejects unsupported first-pass forms such as `*args` and `**kwargs`.
- [ ] `New Fit Function...` creates a minimal valid scaffold in the procedures environment.
- [ ] After reload succeeds, the dialog remains open and the new function is selected in the chooser.
- [ ] Behavior tests cover accepted discovery cases, rejected signature forms, and scaffold/reload selection behavior.

### TDD focus

- First failing behavior: a valid `@hyde.fit_function` appears in the chooser after discovery.
- Follow-up behavior: an unsupported signature is excluded or rejected with clear surfaced behavior.
- Final behavior in this slice: `New Fit Function...` creates a new selectable fit function without closing the dialog.

## Issue 3: Configure function/data binding and generate preview text

- **Title**: Bind function and data into previewable fit state
- **Type**: AFK
- **Blocked by**: Issue 2
- **User stories covered**: 10, 11, 12, 13, 19, 20, 24, 25

### What to build

Implement the first complete `CurveFitState` / `CurveFitCodec` path for selecting a fit
function, choosing Y data, choosing one X data object per declared independent variable,
using `From Target` as a narrowing/defaulting convenience when a figure target exists,
and generating both command preview and equation preview. `Equation` should show the
selected function definition body when source is available. The fit-result target must
be part of this slice and must always resolve to a real object name rather than
`nothing`.

This slice should make the dialog semantically meaningful end-to-end even before actual
fit execution exists.

### Acceptance criteria

- [ ] Selecting a fit function updates the required X-data selectors to match declared independent variables.
- [ ] Y and X selectors are populated from live namespace metadata.
- [ ] In attached mode, `From Target` narrows or defaults selections using the supported-trace discovery path.
- [ ] In unattached mode or when `From Target` is off, selectors expose all compatible namespace objects.
- [ ] The fit-result target always resolves to a real object name and defaults from the selected Y object with unique-name fall-forward.
- [ ] The dialog shows generated `Commands` and `Equation` preview modes derived from one state/codec path.
- [ ] `To Clip` copies the current command preview.
- [ ] Behavior tests cover selector shaping, target-name defaults, `From Target` behavior, and preview generation through public state or dialog interfaces.

### TDD focus

- First failing behavior: choosing a multivariate fit function reshapes the X-data controls and preview deterministically.
- Follow-up behavior: selecting Y data produces a default result-object target name with unique fall-forward.
- Final behavior in this slice: `To Clip` exports the same command preview the dialog shows.

## Issue 4: Edit coefficient and data-option state with validation-gated `Do It`

- **Title**: Validate coefficients and data options
- **Type**: AFK
- **Blocked by**: Issue 3
- **User stories covered**: 14, 15, 16, 17, 18, 27, 35

### What to build

Add the coefficient table and narrow data-options behavior to the same state/codec path.
The dialog must support `lmfit.Parameter`-style controls for initial value, `vary`,
lower bound, upper bound, and `expr`, plus one weighting-object selector and `Suppress
Screen Updates`. Required free parameters must keep `Do It` disabled until the current
configuration is valid, and the status area must surface validation failures in-context.

This slice should complete the first pass of dialog configuration behavior without yet
requiring hidden fit execution.

### Acceptance criteria

- [ ] The coefficient surface exposes one row per coefficient with first-pass `lmfit.Parameter` controls.
- [ ] A non-empty `expr` makes the parameter expression-owned while keeping the row visible.
- [ ] Required free parameters with unusable values keep `Do It` disabled.
- [ ] The data-options tab supports one weighting-object selector and `Suppress Screen Updates`.
- [ ] Zero weights are treated as point exclusion on the intended fit path.
- [ ] Validation failures appear in the dialog status area without closing the dialog.
- [ ] Behavior tests cover validation-gated `Do It`, expression-owned parameters, and weighting/data-option state through public dialog behavior.

### TDD focus

- First failing behavior: leaving a required free parameter unusable disables `Do It` and shows a validation message.
- Follow-up behavior: entering an `expr` changes the parameter's effective editing behavior while keeping it visible.
- Final behavior in this slice: toggling `Suppress Screen Updates` changes the dialog's actual-fit execution policy without executing yet.

## Issue 5: Execute suppressed one-shot fits to create or recreate the result object

- **Title**: Commit suppressed one-shot fit execution
- **Type**: AFK
- **Blocked by**: Issue 4
- **User stories covered**: 20, 27, 29, 30

### What to build

Add the first real hidden execution path for Curve Fit in suppressed mode. When screen
updates are suppressed, editing the dialog must not mutate real fit outputs until `Do It`.
Pressing `Do It` must execute one hidden fit/update path that creates or recreates the
authoritative `lmfit` result object in the kernel namespace using the current valid
dialog state.

This slice is the first end-to-end scientific commit path and should remain result-only
even in attached mode.

Implementation note: if this slice needs more preview/status/footer shell code, prefer a
tiny shared helper with `Modify Axis` for the modal preview pane plus status strip plus
`Do It` / `To Clip` / `Cancel` footer rather than adding a new base class or duplicating
the shell further.

### Acceptance criteria

- [ ] When `Suppress Screen Updates` is enabled, ordinary control changes do not update real fit outputs before `Do It`.
- [ ] Pressing `Do It` in suppressed mode runs one hidden fit/update execution.
- [ ] The hidden execution creates or recreates the authoritative result object target in the kernel namespace.
- [ ] `Do It` in suppressed mode leaves the dialog in an accepted state after a successful run.
- [ ] Behavior tests verify the no-intermediate-update contract and the one-shot result-object commit path through public execution interfaces.

### TDD focus

- First failing behavior: editing a valid suppressed dialog does not mutate the result target before `Do It`, even though guessed previews may still update.
- Follow-up behavior: pressing `Do It` once creates or recreates the chosen fit-result object.
- Tests should verify resulting namespace behavior rather than internal execution helper choreography.

## Issue 6: Add live rerun, failure retention, and result-target handoff behavior

- **Title**: Run live fits with safe target ownership
- **Type**: AFK
- **Blocked by**: Issue 5
- **User stories covered**: 26, 28, 30, 31, 34, 35

### What to build

Extend the hidden execution path for live mode. When screen updates are enabled,
relevant control changes should rerun immediately and update the current real result
target. `Do It` in live mode must accept the current state without triggering a second
rerun. If the user changes the active result target during the session, Hyde must
restore the previous target's opening state before updating the new target. If a live
rerun fails, the last successful live outputs must remain in place and the dialog must
stay open with an error shown.

Implementation note: if this slice needs more preview/status/footer shell code, prefer a
tiny shared helper with `Modify Axis` for the modal preview pane plus status strip plus
`Do It` / `To Clip` / `Cancel` footer rather than adding a new base class or duplicating
the shell further.

### Acceptance criteria

- [ ] In live mode, relevant dialog changes rerun immediately and update the current real result target.
- [ ] `Do It` in live mode accepts the current successful state without triggering an extra rerun.
- [ ] Changing the active result target restores the previous target's opening state before updating the new target.
- [ ] On live rerun failure, the last successful live outputs remain in place.
- [ ] On live rerun failure, the dialog stays open, shows the error, and keeps `Do It` disabled until the configuration is valid again.
- [ ] Behavior tests cover live rerun, target handoff, and failure retention through observable namespace and dialog behavior.

### TDD focus

- First failing behavior: changing a live-fit control mutates the current real result target immediately.
- Follow-up behavior: changing the chosen result target restores the old target before updating the new one.
- Final behavior in this slice: a failing rerun preserves the last successful live result and leaves the dialog open with an error.

## Issue 7: Render and revert dialog-owned fit and residual traces on attached figures

- **Title**: Plot and revert fit-derived traces on figures
- **Type**: AFK
- **Blocked by**: Issue 6
- **User stories covered**: 21, 22, 23, 30, 32, 33

### What to build

Complete the attached-figure path by rendering fit-curve and residual displays as
dialog-owned traces on attached figures. While the dialog is open, attached previews
render from the current coefficient guesses. On successful `Do It` / accept, any
surviving display is re-rooted to the authoritative fit result object. In the first
pass, residuals stay on the existing figure axes rather than creating a second layout.
The dialog must track ownership so that cancel removes traces it introduced and
restores any existing displays it modified.

Implementation note: if this slice needs more preview/status/footer shell code, prefer a
tiny shared helper with `Modify Axis` for the modal preview pane plus status strip plus
`Do It` / `To Clip` / `Cancel` footer rather than adding a new base class or duplicating
the shell further.
Implementation note: `Show Fit` and `Show Residuals` already exist in the dialog as live
controls. This slice should wire those existing controls to real attached-figure
behavior instead of introducing replacement toggles.
Implementation note: in attached mode, `Show Fit` defaults on unless Hyde is preserving
an existing attached fit-display state from the opening figure.

This slice completes the first pass end-to-end attached figure workflow.

### Acceptance criteria

- [ ] In attached mode, enabling fit-curve display renders a dialog-owned preview trace from the current coefficient guesses.
- [ ] In attached mode, enabling residual display renders a dialog-owned preview residual trace on the existing figure axes.
- [ ] In attached mode, `Show Fit` defaults on unless Hyde is preserving an opening attached-display state that should survive the dialog session.
- [ ] On successful `Do It` / accept, any surviving attached fit or residual display is re-rooted to the authoritative fit result object.
- [ ] Plotting remains optional; the result-object workflow still succeeds when fit and residual displays are off.
- [ ] Cancel removes dialog-owned fit or residual traces the dialog introduced.
- [ ] Cancel restores the opening state of any fit or residual display the dialog modified.
- [ ] Behavior tests cover attached plotting, residual-on-existing-axes behavior, and cancel-driven revert through public figure state behavior.

### TDD focus

- First failing behavior: enabling fit display in attached mode adds a preview trace from the current coefficient guesses.
- Follow-up behavior: enabling residual display adds a preview residual trace on the same axes rather than on a new subplot.
- Final behavior in this slice: successful `Do It` / accept re-roots surviving displays to the authoritative fit result, while cancel removes introduced traces and restores modified ones.

## Notes

- These slices are intentionally tracer bullets, not horizontal layer splits. Each issue
  should land as a narrow end-to-end behavior path through menu/service entry,
  dialog/state/codec behavior, hidden execution or figure integration where needed, and
  behavior-focused tests.
- All slices are marked `AFK` on the current shared understanding. No remaining design
  questions require a HITL issue before implementation.
- Each issue should be implemented with red-green-refactor discipline: one behavior
  test, minimal implementation to green, then the next behavior in the same slice.
