# Curve Fit PRD

## Problem Statement

Hyde needs a first-class curve-fitting workflow that fits live kernel data without
forcing users to leave Hyde's existing figure-editing and namespace-driven workflow.
Today, users can inspect variables, edit figures, and manage tables, but they do not
have a Hyde-native surface for selecting a fit function, binding live data, running an
`lmfit` fit, previewing the generated Python, and managing the resulting fit outputs in
the same product model as other Hyde figure-control dialogs.

The feature must fit Hyde's architecture. The GUI cannot become the scientific owner of
fit state, fit arrays, or plotted results. The kernel namespace must remain
authoritative, real targets must be updated directly when live updates are enabled, and
the dialog must be able to revert any dialog-owned changes on cancel.

## Solution

Hyde will provide a modal Curve Fit dialog launched from the `Analysis` menu. The
dialog follows the same family behavior as `Modify Data Appearance` and `Modify Axis`:
it owns transient GUI state and preview state, uses one dedicated GUI state/codec path
for normalization, validation, and command generation, performs hidden reruns when live
updates are enabled, and restores opening state on cancel for any real targets it
changed.

The dialog configures one authoritative output: an `lmfit` result object in the kernel
namespace. The result object is always created or recreated. Plotting is optional. Fit
curve and residual displays are derived renderings of that result object, not separate
top-level scientific outputs. When a supported figure is available, the dialog can
attach to it and manage dialog-owned plotted displays. When no figure is available, the
dialog still runs for result-object creation and update, while graph-display controls
remain visible but disabled.

Fit-function discovery is limited to user-defined `@hyde.fit_function` definitions in
the normal procedures environment. The decorator uses `independent_vars` to align with
`lmfit` terminology. Multivariate fits are first-class. Supported function signatures
are strict first-pass forms: declared independent variables first, followed by
explicitly named coefficient parameters, with no supported `*args` or `**kwargs`.

## User Stories

1. As a Hyde user, I want to open Curve Fit from the `Analysis` menu, so that fitting is exposed as a normal first-class analysis workflow.
2. As a Hyde user, I want Curve Fit to auto-attach to the active supported figure when one is available, so that data-target narrowing and graph output are immediately useful.
3. As a Hyde user, I want Curve Fit to still open when no supported figure is active, so that I can create or update fit results even outside figure context.
4. As a Hyde user, I want graph-display controls to remain present but disabled when no figure target is available, so that the dialog shape stays consistent while making the unavailable behavior explicit.
5. As a Hyde user, I want the dialog to be modal, so that fit editing behaves like Hyde's existing figure-control dialogs.
6. As a Hyde user, I want the fit-function chooser to show discovered `@hyde.fit_function` definitions only, so that function availability comes from the normal Hyde procedures environment.
7. As a Hyde user, I want a `New Fit Function...` action in the dialog, so that I can scaffold a valid function without leaving the fit workflow entirely.
8. As a Hyde user, I want the scaffolded fit function to be minimal and valid, so that Hyde creates only the required starting point and leaves real authoring to ordinary source editing.
9. As a Hyde user, I want multivariate fit functions to be supported in the first pass, so that Hyde does not artificially restrict fitting to one independent variable.
10. As a Hyde user, I want one X-data selector per declared independent variable, so that the dialog reflects the semantic contract of the selected fit function.
11. As a Hyde user, I want Y-data and X-data selectors backed by live namespace objects, so that the fit always refers to current kernel data.
12. As a Hyde user, I want `From Target` to narrow or default object choices from the current figure target when available, so that common figure-driven fitting starts with useful selections.
13. As a Hyde user, I want to turn `From Target` off and browse all compatible namespace objects, so that figure context does not trap me in one selection path.
14. As a Hyde user, I want one explicit weighting-object selector, so that weighting follows one clear `lmfit`-native path.
15. As a Hyde user, I want zero weights to exclude points, so that inclusion and weighting stay on the same explicit control path.
16. As a Hyde user, I want coefficient controls that match `lmfit.Parameter` concepts, so that I can set initial values, bounds, `vary`, and `expr` without Igor-specific abstractions.
17. As a Hyde user, I want expression-owned parameters to remain visible, so that I can understand the full coefficient set even when some values are constrained by expressions.
18. As a Hyde user, I want required free parameters to block `Do It` until they have usable values, so that invalid fits are caught before execution.
19. As a Hyde user, I want the fit-result target to default from the selected Y data name, so that Hyde creates predictable result-object names with minimal typing.
20. As a Hyde user, I want the fit-result object to always be created or recreated, so that there is always one authoritative scientific output for the fit session.
21. As a Hyde user, I want fit-curve display to be optional, so that I can keep the fit result without forcing a plotted overlay.
22. As a Hyde user, I want residual display to be optional, so that I can inspect residual behavior only when it helps.
23. As a Hyde user, I want first-pass residuals to appear on the existing figure axes, so that Hyde reuses the current figure-editing model instead of introducing a new residual layout system.
24. As a Hyde user, I want a command preview and equation preview, so that I can understand both the executable action and the selected model form.
25. As a Hyde user, I want `To Clip`, so that I can export the current generated command text without committing to visible terminal execution.
26. As a Hyde user, I want live updates to rerun immediately when screen updates are enabled, so that I can tune coefficient and output settings interactively.
27. As a Hyde user, I want `Suppress Screen Updates` to prevent intermediate reruns, so that I can make larger edits without repeated expensive fit execution.
28. As a Hyde user, I want `Do It` in live mode to simply accept the current successful state, so that acceptance does not trigger a redundant extra fit.
29. As a Hyde user, I want `Do It` in suppressed mode to execute the fit once, so that deferred editing still commits real outputs when I am ready.
30. As a Hyde user, I want Curve Fit to mutate real targets instead of GUI-owned copies, so that the dialog behaves like Hyde's existing real-edit figure controls.
31. As a Hyde user, I want target changes to restore prior opening state when I switch result targets mid-session, so that the dialog does not leave abandoned live edits behind.
32. As a Hyde user, I want cancel to remove dialog-owned plotted displays it introduced, so that temporary fit previews do not survive an abandoned edit session.
33. As a Hyde user, I want cancel to restore any existing plotted display the dialog modified, so that I can safely experiment without destructive side effects.
34. As a Hyde user, I want the last successful live outputs to remain in place when a rerun fails, so that a bad edit does not destroy a working fit display or result target.
35. As a Hyde user, I want errors shown in a status strip while the dialog remains open, so that I can correct invalid settings in context.
36. As a Hyde user, I want unsupported fit-function forms such as `*args` and `**kwargs` rejected in the first pass, so that the dialog works from a deterministic and inspectable model contract.

## Implementation Decisions

- Curve Fit is a modal figure-control-style dialog, not a persistent MDI tool window.
- The feature launches from the `Analysis` menu.
- The dialog may run attached to a supported figure or unattached.
- On `Analysis` launch, Hyde auto-attaches to the active supported figure when one is available; otherwise the dialog opens unattached.
- In unattached mode, result-object creation and update remain available, while fit-curve and residual display controls remain visible but disabled.
- The dialog reuses the existing figure-control interaction model for live preview, explicit accept, explicit revert, and clipboard export.
- The dialog owns one dedicated GUI state object and one dedicated codec for curve-fit state. That path owns normalization, validation, command preview generation, and equation preview generation.
- The GUI owns only transient configuration state, preview text, transient enabled/disabled UI state, and opening-state snapshots needed for revert.
- The kernel namespace remains authoritative for scientific objects, fit results, and any live plotted outputs.
- The authoritative fit output is one `lmfit` result object stored in the kernel namespace.
- The fit-result target control has no explicit `nothing` choice. A fit-result object is always created or recreated.
- Fit-curve and residual displays are derived renderings of the fit result object, not separate top-level scientific output channels.
- First-pass residual display stays on the existing figure axes as a dialog-owned derived trace. The feature does not introduce a dedicated residual subplot, second axis layout, or broader multi-panel figure layout support.
- Fit-function discovery is limited to user-defined `@hyde.fit_function` definitions in the normal procedures environment.
- The decorator uses the `independent_vars` name to align with `lmfit.Model`.
- No extra Hyde-specific decorator metadata is added in the first pass beyond `independent_vars`.
- Supported fit-function signatures are strict first-pass forms: declared independent variables first, then explicitly named coefficient parameters. `*args` and `**kwargs` are not supported.
- Coefficient names are inferred from the function signature after the declared independent variables.
- Initial coefficient guesses do not come from Python parameter defaults. The dialog owns initial-value entry directly.
- `New Fit Function...` generates a minimal valid scaffold, appends it to the procedures source, triggers the normal reload path, keeps the dialog open, and selects the new function after reload succeeds.
- `Edit Fit Function...` is not part of the first pass.
- `From Target` is a narrowing/defaulting convenience only. It uses the existing supported-trace discovery path when a figure target is available and does not change the output model.
- Namespace-backed object pickers use existing namespace metadata service paths rather than GUI-owned scientific mirrors.
- The data-options surface is intentionally narrow: one weighting-object selector plus `Suppress Screen Updates`.
- Zero weights exclude points.
- Range controls, cursor-driven range insertion, separate data-mask controls, and weighting interpretation radios are not included in the first pass.
- The coefficient surface is organized around `lmfit.Parameter` semantics and supports name, initial value, `vary`, lower bound, upper bound, and `expr`.
- A non-empty `expr` makes a parameter expression-owned while keeping that row visible.
- Required free parameters must have usable values before `Do It` is valid.
- The output-options surface centers on the fit-result target plus fit-curve and residual display toggles.
- The result-object target defaults from the selected Y object name and falls forward to a unique indexed name when needed.
- The dialog provides `Commands` and `Equation` preview modes plus a single status/error strip.
- `To Clip` copies the current command preview.
- `To Cmd Line`, `Graph Now`, and `Help` are not part of the first pass.
- Live execution uses the hidden kernel execution path.
- When screen updates are enabled, relevant control changes rerun immediately and update current real targets.
- When screen updates are suppressed, intermediate reruns do not occur and real outputs update only on `Do It`.
- In live mode, `Do It` accepts the current valid state and does not trigger an extra rerun.
- In suppressed mode, `Do It` performs the one actual hidden fit/update execution.
- The dialog owns real live targets during the session. It does not create hidden duplicate scientific state.
- If the user changes the active result target during a live session, Hyde restores the previous target's opening state before updating the new target.
- If the dialog introduces a fit or residual display, cancel removes it.
- If the dialog updates an existing fit or residual display, cancel restores its opening state.
- When a live rerun fails, the last successful live outputs remain in place, the dialog stays open, the error is shown, and `Do It` remains disabled until the configuration becomes valid again.
- The feature should be implemented as a small set of deep modules with simple interfaces: fit-function discovery and validation, curve-fit GUI state/codec, hidden fit execution and target-ownership orchestration, figure display adaptation for fit/residual traces, and fit-function scaffold generation.

## Testing Decisions

- Good tests must verify user-visible behavior or explicit architectural contracts, not helper wiring, incidental call order, or private implementation structure.
- The core contract tests should cover state validation and lowering behavior for the curve-fit GUI state/codec, because that is the deterministic boundary between the dialog and kernel execution.
- Fit-function discovery tests should verify accepted and rejected first-pass function signatures, `independent_vars` handling, coefficient-name inference, and unsupported signature forms.
- Execution-flow tests should verify live-update behavior, suppressed-update behavior, `Do It` semantics in each mode, and failure handling that preserves the last successful live outputs.
- Ownership and revert tests should verify that result targets and dialog-owned plotted displays are restored or removed correctly on target changes and cancel.
- Figure-integration tests should verify attached and unattached dialog behavior, including disabled plotting controls when no figure target is available and derived trace behavior when a figure target is attached.
- Scaffold tests should verify that `New Fit Function...` produces a minimal valid function declaration, triggers the normal reload flow, and reselects the created function on success.
- UI tests should prefer observable dialog behavior, validation messaging, button enabled state, and resulting namespace or figure state over mock-heavy tests.
- Prior art for these tests should come from Hyde's existing contract-focused tests around figure editing, window restore behavior, table state/codec behavior, and runtime execution paths rather than from brittle signal-wiring tests.

## Out of Scope

- `To Cmd Line`
- `Help`
- `Graph Now`
- `Edit Fit Function...`
- Range controls
- Cursor-driven range insertion
- Separate data-mask controls
- Weighting interpretation radios
- Auto-guess mode
- Separate top-level fit-array outputs
- Separate top-level residual-array outputs
- Separate covariance-matrix output controls
- Igor-style coefficient waves
- Igor-style epsilon waves
- Igor-style constraints waves
- Residual subplot layouts, second-axis residual layouts, or broader figure-layout expansion specifically for Curve Fit
- Additional `@hyde.fit_function` metadata beyond `independent_vars`
- Support for fit-function signatures that rely on `*args` or `**kwargs`
- Any broader fit-function library/import catalog outside the normal discovered procedures environment

## Further Notes

- This feature must stay on Hyde's existing architectural rails: the GUI is not scientific state, the GUI is a string factory except where figure editing uses semantic figure actions, and the kernel remains authoritative.
- The implementation should prefer the smallest clear change in the existing figure-control and namespace-service paths.
- The feature should reuse existing figure target discovery, figure draft/revert behavior, namespace metadata access, and hidden execution services instead of inventing parallel plumbing.
- The current first pass is explicitly an `lmfit`-native Hyde workflow, not an Igor-compatibility surface.
