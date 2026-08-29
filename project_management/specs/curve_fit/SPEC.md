# Curve Fitting Specification

## Feature Checklist
- [x] Add a Hyde-native Curve Fitting dialog shaped by the screenshot family in
  `project_management/specs/curve_fit/`.
- [x] Implement the dialog as a modal figure-control-style surface following the
  interaction pattern used by `Modify Data Appearance` and `Modify Axis`.
- [x] Keep the GUI authoritative only for transient dialog state and preview state.
- [x] Reuse the existing namespace metadata path for object pickers.
- [x] Reuse the existing first-class figure target-discovery path used by
  `Modify Data Appearance`.
- [x] Give the dialog one first-class `CurveFitIR` workflow object in `widget_ir`
  under Hyde's normal IR-control pattern.
- [x] Support `@hyde.fit_function` discovery as the only fit-function catalog path.
- [x] Support multivariate fits as a first-class capability.
- [x] Make the `lmfit` result object the authoritative fit output.
- [x] Keep accepted fit and residual displays rooted to that authoritative result
  object while rendering in-dialog attached previews from the current coefficient
  guesses.
- [x] Support live reruns when screen updates are enabled.
- [x] Support one-shot execution on `OK` when screen updates are suppressed.

## Purpose

The Curve Fitting dialog is Hyde's modal GUI surface for configuring and running fits
against live kernel data while following the same dialog family behavior used by the
existing figure-control dialogs.

The dialog owns only transient configuration state long enough to:

- select a discovered `@hyde.fit_function`
- bind the selected function to live namespace objects
- preview the generated Python
- drive live hidden reruns when enabled
- commit or revert the real kernel-side outputs owned by the dialog session

The dialog does not become the authoritative owner of scientific results. The
authoritative fit output is an `lmfit` result object stored in the kernel namespace.
While the dialog is open, attached fit and residual previews render from the current
coefficient guesses. After successful `OK` / accept, any surviving attached display
is re-rooted to that authoritative result object rather than becoming a separate
top-level scientific output channel.

## Initial Deployment Scope

The first implementation includes:

- a modal dialog launched from `Analysis`, auto-attaching to the active supported
  figure when available, and patterned after the existing
  figure-control dialogs
- one fit-function chooser populated only by discovered `@hyde.fit_function`
  definitions, including Hyde-provided built-ins and project-defined procedures
- `New Fit Function...` support that writes a minimal valid scaffold into
  `procedures/__init__.py`, triggers the normal procedures reload path, and updates the
  chooser
- multivariate support from the start
- one explicit X-data chooser per independent variable declared by the selected
  `@hyde.fit_function`
- Y-data and X-data selection from live namespace objects
- a `From Target` checkbox that only narrows or defaults what is easily selectable
  using the same supported-trace discovery path used by `Modify Data Appearance`
- a weighting control that accepts one explicit weight object and passes it through in
  the `lmfit`-native way
- an `lmfit`-native coefficient table
- a fit-result target control whose default name is based on the selected Y object,
  typically `<y_name>_fit_result`
- graph-display controls for fit-curve and residual rendering, with guessed previews
  while the dialog is open and result-rooted displays after successful `OK` /
  accept
- explicit Python preview
- `Copy`
- `To IPython`
- live hidden reruns when screen updates are enabled
- one-shot hidden execution on `OK` when screen updates are suppressed
- revert-on-cancel behavior for any real kernel-side targets and graph displays the
  dialog session changed

The first implementation does not include:

- `Help`
- `Graph Now`
- `Edit Fit Function...`
- range controls
- cursor-driven range insertion
- a separate data-mask control
- auto-guess mode
- separate top-level fit arrays such as `fit_<y_name>`
- separate top-level residual arrays
- separate covariance-matrix output controls
- Igor-style coefficient waves, epsilon waves, or constraints waves

## Window Layout

The Curve Fitting dialog is a modal tabbed window that preserves the screenshot
family's overall structure while using Hyde-native behavior behind those surfaces.

It contains:

- a `Function and Data` tab
- a `Data Options` tab
- a `Coefficients` tab
- an `Output Options` tab
- a preview mode switch for `Commands` and `Equation`
- a large preview pane
- a one-line status/error strip
- footer buttons for `OK`, `To IPython`, `Copy`, and `Cancel`

The first implementation follows the existing figure-control-dialog family behavior:

- live changes rerun immediately when screen updates are enabled
- `Cancel` restores the opening state for any target the dialog changed
- `OK` accepts the current state rather than triggering an extra rerun in live mode
- `To IPython` is enabled only in `Commands` preview mode because `Equation` preview
  is not the executable commit payload

## Fit Function Discovery

The fit-function chooser is populated only from discovered `@hyde.fit_function`
definitions.

For the first implementation:

- Hyde-provided built-in fit functions and project-defined procedures fit functions are
  both allowed, but they still enter the chooser only through
  `@hyde.fit_function` registration
- chooser order follows registration/definition order rather than alphabetical sorting;
  Hyde's built-ins register first, with `line` first
- Hyde does not maintain a second fit-function registry outside the normal procedures
  environment

`@hyde.fit_function` must support explicit independent-variable declaration, for
example:

```python
@hyde.fit_function(independent_vars=("x", "y"))
def plane(x, y, a, b, c):
    return a + b*x + c*y
```

The decorator metadata defines the independent-variable names and order. The remaining
named function parameters are the fit coefficients.

## New Fit Function

`New Fit Function...` is part of the first implementation.

Its job is narrow:

- generate a minimal valid `@hyde.fit_function` scaffold
- append that scaffold to `procedures/__init__.py`
- trigger the normal procedures reload path
- leave the Curve Fitting dialog open
- select the newly created function in the fit-function chooser after reload succeeds

The scaffold is intentionally minimal. It is not a full function editor or expression
builder. Users finish the function by editing ordinary source outside the Curve Fitting
dialog.

`Edit Fit Function...` is not part of the first implementation and should not appear as
an active control.

## Function And Data Tab

The `Function and Data` tab contains:

- the fit-function chooser
- `New Fit Function...`
- Y-data selection
- one X-data selector per declared independent variable
- the `From Target` checkbox

`From Target` is a selector-convenience control only.

When checked:

- the available selections are narrowed or defaulted using the same supported-trace
  discovery mechanism used by `Modify Data Appearance`

When unchecked:

- all compatible namespace objects become available through the selectors

`From Target` does not change the output model. Output defaults are driven by the
currently selected data objects, especially the selected Y object.

## Data Options Tab

The first implementation keeps the Data Options surface narrow and `lmfit`-native.

It contains:

- one weighting-object selector
- `Suppress Screen Updates`

It does not include:

- range controls
- cursor controls
- separate data-mask controls
- weighting interpretation radios

Weighting rules:

- Hyde accepts one explicit weight object
- Hyde passes those weights through in the `lmfit`-native way
- zero weights exclude points

`Suppress Screen Updates` is a performance control on actual fit execution, not merely
a visual toggle.

When enabled:

- no intermediate fit reruns occur while the user changes controls
- attached guessed-function previews may still update as the user edits the dialog
- the real outputs are updated only once, on `OK`

When disabled:

- relevant control changes rerun immediately and update the current real targets

## Coefficients Tab

The Coefficients tab is designed around `lmfit.Parameter` options rather than Igor
compatibility concepts.

The coefficient table shows one row per coefficient and supports at least:

- parameter name
- initial value
- `vary`
- lower bound
- upper bound
- `expr`

Parameter rules:

- required free parameters start blank unless explicit defaults are supplied by the fit
  function metadata
- `OK` is invalid until every required free parameter has a usable value
- a non-empty `expr` makes that parameter expression-owned
- expression-owned parameters remain visible, but ordinary manual controls become
  subordinate to the expression

There is no auto-guess mode in the first implementation.

## Output Options Tab

The fit result object is the authoritative output.

The first implementation does not offer separate top-level fit-array or residual-array
output channels. Instead, the Output Options tab centers on:

- the fit-result object target
- whether to display or update the fit curve on the graph
- whether to display or update residuals on the graph

In attached mode, `Show Fit` defaults on unless the figure already opens with an
existing attached fit-display state that should be preserved.

The fit-result object target:

- defaults to a name derived from the selected Y object, typically
  `<y_name>_fit_result`
- may be changed by choosing an existing name or typing a new one

Graph-display behaviors:

- while the dialog is open, attached `Show Fit` and `Show Residuals` previews render
  from the current coefficient guesses rather than from an already-computed fit result
- on successful `OK` / accept, any surviving attached fit or residual display is
  re-rooted to the authoritative fit result object
- neither is treated as a separate top-level scientific output

Covariance information is part of the `lmfit` result path and does not require a
separate first-pass output control.

## Preview And Execution

The dialog has two preview modes:

- `Commands`
- `Equation`

The dialog owns one GUI-side `CurveFitIR` workflow object in `widget_ir`.
`CurveFitIR`:

- normalizes and validates dialog state
- carries any opening/current/applied `FigureIR` snapshots needed for attached-
  display preview and rollback
- orchestrates package-pure lowering for command preview source
- builds equation preview content from the selected function definition body when
  source is available

Execution rules:

- when screen updates are enabled, relevant changes rerun immediately through a hidden
  execution path
- `OK` in live mode accepts the current state and does not trigger an extra rerun
- when screen updates are suppressed, intermediate fit reruns do not occur, but
  guessed attached previews may still update
- `OK` in suppressed mode performs the one hidden fit/update execution

`Copy` copies the backing command preview string. In `Equation` mode the lower
preview pane may show equation text instead, but `Copy` still copies the command
block the dialog would execute.

`To IPython` emits the same canonical command block the dialog would execute through
Hyde's hidden-command path.

## Real Targets, Live Ownership, And Revert Behavior

The dialog mutates real kernel-side targets. It does not mutate hidden duplicates.

When live updates are enabled:

- the currently selected real targets are updated immediately
- if the user changes the result-object target, the dialog restores the previous
  target's opening state before it starts updating the new one
- graph displays introduced or updated by the dialog are part of that owned live state

When `Cancel` is pressed:

- any result-object target changed by the dialog is restored to its opening state
- any dialog-owned graph display introduced by the dialog is removed
- any dialog-owned graph display updated by the dialog is restored to its opening state

When a live rerun fails:

- the last successful live outputs remain in place
- the dialog stays open
- the status area shows the error
- `OK` remains disabled until the configuration becomes valid again

## Synchronization

The synchronization contract is:

- the kernel namespace remains authoritative
- the fit result object is the authoritative fit output
- graph displays are renderings derived from that fit result object
- object pickers reuse the existing Python Variables metadata path
- figure target discovery reuses the existing first-class figure dialog context path,
  with attached figure state entering Curve Fit as `FigureIR` snapshots carried by
  `CurveFitIR`

`CurveFitIR` and the surrounding dialog may cache only:

- transient normalized fit configuration
- preview text
- opening-state snapshots needed for revert

The dialog must not become the authoritative owner of:

- fit results
- plotted fit displays
- coefficient values
- live namespace data

## Explicit Exclusions

The first implementation explicitly excludes:

- `Help`
- `Graph Now`
- `Edit Fit Function...`
- range controls
- cursor controls
- separate data masks
- auto guess
- separate top-level fit arrays
- separate top-level residual arrays
- separate covariance-matrix output controls
- Igor-style coefficient waves
- Igor-style epsilon waves
- Igor-style constraints waves

## Future Work

- richer fit-function metadata beyond the initial decorator contract
- bundled imported fit-function collections that still enter through
  `@hyde.fit_function`
- broader launch paths beyond the figure-context workflow
- finalized residual-display layout and presentation rules
