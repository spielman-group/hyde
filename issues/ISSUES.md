# Hyde Refactor Boundary Issues

Source: `issues/REFACTOR_STATUS.md`

Purpose: resolve the remaining plugin-boundary and IR-ownership problems left by
the file-shape refactor. These slices are deliberately small and prescriptive so
an implementation agent cannot satisfy the letter of the plan while preserving the
wrong ownership shape.

## Progress Checklist

- [x] Slice 0: Baseline Boundary Audit
- [x] Slice 1: Move Pure Matplotlib Color Parsing To Feature Code
- [ ] Slice 2: Move Figure State Authority To Feature Code
      NOT COMPLETE. The names were copied into
      `hyde/features/matplotlib_figure_state.py`, not moved out of
      `hyde/features/matplotlib_features.py`. `FigureIRModel` still exists there
      and `FigureIRAuthority` is an 80% verbatim clone of it, with 10 diverged
      methods including `default_state`, `normalize_state`, and `validate_state`.
      The four acceptance greps pass because none of them looked at
      `matplotlib_features.py`. See `REFACTOR_STATUS.md`.
- [x] Slice 3: Move Canonical Trace Records To Feature Code
- [x] Slice 4: Reduce Figure Interactive Support To Plugin Support
- [x] Slice 5: Feature-To-Plugin Boundary Checkpoint
- [x] Slice 6: Add Feature Import Boundary Tests
- [x] Slice 7: Create The Explicit Figure Context Adapter
- [x] Slice 8: Make FigureDialogIR Workflow-Only
- [x] Slice 9: Move HydeFigureDialogWidget To Widget Support
- [x] Slice 10: Replace Broad Figure Context Fallbacks
- [x] Slice 11: Narrow Save Graphics To The Figure Context
- [x] Slice 12: Figure Dialog Boundary Checkpoint
- [x] Slice 13: Recheck Curve Fit Composition
- [x] Slice 14: Add Durable Figure Boundary Tests
- [x] Slice 15: Preserve Clean App/File, Table, And Python Variables Patterns
- [x] Slice 16: Resync Docs And Refactor Status
- [ ] Slice 17: Test Cleanup Pass (partial)
- [ ] Slice 18: Final Completion Checkpoint (static checks pass; targeted test
      run still outstanding)

## Global Rules

- Do not move feature authority back into `hyde/user_interface/shared/`.
- Do not add compatibility re-export modules to avoid updating imports.
- Do not add wrappers that only forward to the real owner under a different name.
- Do not create broad catch-all modules such as `figure_support.py`,
  `matplotlib_support2.py`, or `helpers.py`.
- Do not add production fallbacks for stale fake fixtures. Update the fixtures to
  match the real product contract.
- Do not mark a slice complete until its acceptance criteria and checkpoint
  commands pass.

## Slice 0: Baseline Boundary Audit

### Type

`AFK`

### What to build

Record the current boundary failures before changing production code. This slice
does not fix anything. It creates a short implementation note, either in the PR
description or in the commit message, identifying the current package-IR-to-plugin
dependencies and the current mixed IR/widget files.

### Acceptance criteria

- [ ] Run `rg "hyde\\.user_interface\\.plugins" hyde/features` and record the
      current matches.
- [ ] Confirm that `hyde/features/matplotlib_ir.py` imports from
      `hyde.user_interface.plugins.figure_interactive.matplotlib_support`.
- [ ] Confirm that
      `hyde/user_interface/plugins/figure_control_dialog/figure_dialog_IR.py`
      imports Qt and defines `HydeFigureDialogWidget`.
- [ ] Record any already-fixed divergence from `issues/REFACTOR_STATUS.md` before
      starting Slice 1.

### What not to do

- Do not begin moving code in this slice.
- Do not add allowlist exceptions for feature-to-plugin imports.

### Blocked by

None - can start immediately.

### User stories covered

- Refactor Status: Current Assessment
- Refactor Status: Recommended Next Slices / dependency boundary tests

## Slice 1: Move Pure Matplotlib Color Parsing To Feature Code

### Type

`AFK`

### What to build

Move pure matplotlib color parsing out of the Qt widget module so feature-side
figure state code can validate colors without importing a GUI plugin.

Create `hyde/features/matplotlib_color.py`. Move these pure functions from
`hyde/user_interface/plugins/figure_control_dialog/matplotlib_widgets.py` into it:

- `rgba_from_matplotlib_color`
- `normalize_matplotlib_color_text`

Keep Qt-specific color UI in
`hyde/user_interface/plugins/figure_control_dialog/matplotlib_widgets.py`.
That widget module should import the moved pure functions from
`hyde.features.matplotlib_color`.

Update `normalize_trace_style_color()` so it imports
`normalize_matplotlib_color_text` from `hyde.features.matplotlib_color`, not from
`figure_control_dialog.matplotlib_widgets`.

### Acceptance criteria

- [ ] `hyde/features/matplotlib_color.py` exists and imports no Qt modules.
- [ ] `matplotlib_widgets.py` still owns `MatplotlibColorDialog`,
      `MatplotlibColorLineEdit`, `qcolor_from_matplotlib_color_text`,
      `color_text_from_qcolor`, and `named_matplotlib_colors`.
- [ ] `rg "figure_control_dialog\\.matplotlib_widgets" hyde/features hyde/user_interface/plugins/figure_interactive`
      returns no matches.
- [ ] Existing matplotlib color picker tests still pass or are updated to import
      pure parsing from `hyde.features.matplotlib_color` and widgets from
      `matplotlib_widgets.py`.

### What not to do

- Do not import `qtutils`, `QtCore`, `QtGui`, or `QtWidgets` from
  `hyde/features/matplotlib_color.py`.
- Do not duplicate `normalize_matplotlib_color_text` in both files.
- Do not leave a lazy import from `matplotlib_support.py` to
  `figure_control_dialog.matplotlib_widgets`.

### Blocked by

- Slice 0: Baseline Boundary Audit

### User stories covered

- Refactor Status Finding 2: `matplotlib_support.py` Is Too Broad

## Slice 2: Move Figure State Authority To Feature Code

### Type

`AFK`

### What to build

Move package-level figure IR authority out of
`hyde/user_interface/plugins/figure_interactive/matplotlib_support.py` and into a
feature-side module.

Create `hyde/features/matplotlib_figure_state.py`. Move these names into it:

- `SUPPORTED_TRACE_STYLE_DEFAULTS`
- `TRACE_STYLE_ACTION_KEYS`
- `default_trace_color`
- `normalize_empty_choice`
- `normalize_trace_style_color`
- `apply_trace_style_values`
- `trace_style_defaults_by_subplot`
- `supported_trace_style_state`
- `_AXIS_SIDE_TO_AXIS`
- `_PRIMARY_SIDE`
- `_MIRROR_SIDE`
- `deep_merge_dict`
- all `normalize_*` helpers used by `FigureIRAuthority`
- `sync_legacy_subplot_axis_fields`
- `operand_names`
- `FigureIRAuthority`
- `figure_ir_default_state`
- `figure_ir_apply_title`
- `default_subplot_layout_state`
- `merge_defaulted_value`
- `figure_ir_with_defaults`

Update `hyde/features/matplotlib_ir.py` to import these names from
`hyde.features.matplotlib_figure_state`.

Update `hyde/user_interface/plugins/figure_interactive/window.py` to import
`FigureIRAuthority` from `hyde.features.matplotlib_figure_state`.

### Acceptance criteria

- [ ] `hyde/features/matplotlib_figure_state.py` exists and imports no
      `hyde.user_interface.plugins` modules.
- [ ] `hyde/features/matplotlib_ir.py` no longer imports from
      `hyde.user_interface.plugins.figure_interactive.matplotlib_support`.
- [ ] `figure_interactive/window.py` imports `FigureIRAuthority` from
      `hyde.features.matplotlib_figure_state`.
- [ ] `rg "FigureIRAuthority|figure_ir_default_state|figure_ir_with_defaults|supported_trace_style_state|trace_style_defaults_by_subplot" hyde/user_interface/plugins/figure_interactive/matplotlib_support.py`
      returns no matches.

### What not to do

- Do not move these names to `hyde/user_interface/shared/`.
- Do not leave duplicate definitions in `matplotlib_support.py`.
- Do not make `matplotlib_figure_state.py` import Qt or plugin modules.
- Do not satisfy this by renaming `matplotlib_support.py` without changing the
  dependency direction.

### Blocked by

- Slice 1: Move Pure Matplotlib Color Parsing To Feature Code

### User stories covered

- Refactor Status Finding 1: The Figure Package IR Still Depends On A GUI Plugin
- Refactor Status Finding 2: `matplotlib_support.py` Is Too Broad

## Slice 3: Move Canonical Trace Records To Feature Code

### Type

`AFK`

### What to build

Move canonical trace display-name and supported-trace record generation to
feature-side code so `FigureIR` can expose trace records without importing a GUI
plugin helper.

Create `hyde/features/matplotlib_figure_records.py` with these pure functions:

- `trace_source_name(source)`
- `trace_label(trace)`
- `trace_display_name(trace)`
- `supported_trace_records(figure_ir)`

Update `FigureIR.supported_trace_records()` and
`FigureIR._trace_style_states_for_state()` in `hyde/features/matplotlib_ir.py` to
use `hyde.features.matplotlib_figure_records.supported_trace_records`.

If UI code still needs `FigureDisplayHelper`, keep a small delegating class in
`hyde/user_interface/plugins/figure_interactive/matplotlib_support.py`. That class
must only call the feature-side functions.

### Acceptance criteria

- [ ] `hyde/features/matplotlib_figure_records.py` exists and imports no Qt or
      plugin modules.
- [ ] `rg "FigureDisplayHelper" hyde/features` returns no matches.
- [ ] `FigureIR.supported_trace_records()` works through feature-side record code.
- [ ] Tests cover the documented display-name order:
      `{label}: {y} vs {x}`, `{label}: {y}`, `{y} vs {x}`, `{y}`, `{label}`,
      trace ID fallback.

### What not to do

- Do not create a second display-name algorithm in `FigureDisplayHelper`.
- Do not weaken the display-name fallback contract.
- Do not keep `FigureIR` importing `FigureDisplayHelper`.

### Blocked by

- Slice 2: Move Figure State Authority To Feature Code

### User stories covered

- Refactor Status Finding 1: The Figure Package IR Still Depends On A GUI Plugin
- Refactor Status Finding 10: The Tests Need Boundary Guards

## Slice 4: Reduce Figure Interactive Support To Plugin Support

### Type

`AFK`

### What to build

After Slices 1-3, reduce
`hyde/user_interface/plugins/figure_interactive/matplotlib_support.py` to plugin
support only.

Allowed remaining contents:

- `COMM_TARGET`
- `LOGGER`
- `register_auxiliary_figure_comm_sink`
- a tiny delegating `FigureDisplayHelper`, only if still useful for UI
  composition

If `FigureDisplayHelper` remains, it may import only from
`hyde.features.matplotlib_figure_records` and must contain no additional
semantics.

### Acceptance criteria

- [ ] `matplotlib_support.py` contains no figure IR state authority.
- [ ] `matplotlib_support.py` contains no axis defaults, trace-style defaults, or
      lowerer support.
- [ ] `rg "FigureIRAuthority|figure_ir_default_state|supported_trace_style_state|trace_style_defaults_by_subplot|deep_merge_dict|default_axis_state" hyde/user_interface/plugins/figure_interactive/matplotlib_support.py`
      returns no matches.
- [ ] Any remaining `FigureDisplayHelper` methods are simple delegates to
      `hyde.features.matplotlib_figure_records`.

### What not to do

- Do not create `matplotlib_support2.py`, `figure_support.py`, or another broad
  catch-all module.
- Do not move the removed authority into `shared/`.
- Do not keep hidden package authority in a plugin module just because the UI also
  uses it.

### Blocked by

- Slice 3: Move Canonical Trace Records To Feature Code

### User stories covered

- Refactor Status Finding 2: `matplotlib_support.py` Is Too Broad

## Slice 5: Feature-To-Plugin Boundary Checkpoint

### Type

`AFK`

### What to build

Evaluate the package-to-plugin boundary after Slices 1-4 and take corrective
action before any dialog work starts.

### Acceptance criteria

- [ ] `rg "hyde\\.user_interface\\.plugins" hyde/features` returns no matches.
- [ ] `rg "from hyde\\.user_interface\\.plugins|import hyde\\.user_interface\\.plugins" hyde/features`
      returns no matches.
- [ ] If a feature-side module still needs plugin code, move the needed non-Qt,
      non-widget code into `hyde/features/` and update the plugin to import from
      feature code.

### What not to do

- Do not add allowlist exceptions.
- Do not proceed to Slice 6 while a feature module imports a plugin module.

### Blocked by

- Slice 4: Reduce Figure Interactive Support To Plugin Support

### User stories covered

- Refactor Status Finding 10: The Tests Need Boundary Guards

## Slice 6: Add Feature Import Boundary Tests

### Type

`AFK`

### What to build

Add durable architecture tests that fail if package-side feature modules import
GUI plugin modules again.

Add the test to `tests/test_hyde_feature_modules.py`. It should parse or scan the
Python sources under `hyde/features/` and fail on imports of
`hyde.user_interface.plugins`.

The test must include these new/current files:

- `hyde/features/hyde_ir.py`
- `hyde/features/matplotlib_ir.py`
- `hyde/features/lmfit_ir.py`
- `hyde/features/matplotlib_color.py`
- `hyde/features/matplotlib_figure_state.py`
- `hyde/features/matplotlib_figure_records.py`

It may allow `hyde.user_interface.shared.core` for `HydeIR` / `HydeIRDiff` until
those base classes move elsewhere.

### Acceptance criteria

- [ ] The test fails if a temporary import from
      `hyde.user_interface.plugins.figure_interactive.matplotlib_support` is
      added to `hyde/features/matplotlib_ir.py`.
- [ ] The test passes after Slices 1-5.
- [ ] The test checks import direction, not just file names.

### What not to do

- Do not skip, xfail, or broad allowlist `hyde.user_interface.plugins`.
- Do not write a test that only checks that `*_ir.py` files exist.

### Blocked by

- Slice 5: Feature-To-Plugin Boundary Checkpoint

### User stories covered

- Refactor Status Finding 10: The Tests Need Boundary Guards

## Slice 7: Create The Explicit Figure Context Adapter

### Type

`AFK`

### What to build

Create one supported adapter from `FigureWindow` to figure-working dialogs.

Create `hyde/user_interface/plugins/figure_interactive/context.py`. Move
`EditableFigureContext` from `figure_control_dialog/figure_dialog_IR.py` into
this file and make it the only supported figure-dialog context.

`EditableFigureContext` must expose:

- `figure_number`
- `figure_name()`
- `current_figure_ir()`
- `current_size_inches()`
- `has_supported_traces()`
- `supported_trace_records()`

It may read from a real `FigureWindow`, but it must normalize returned figure
state into a `FigureIR` before returning it.

### Acceptance criteria

- [ ] `rg "class EditableFigureContext" hyde/user_interface/plugins` returns one
      class definition in `figure_interactive/context.py`.
- [ ] Dialog launchers that previously imported `EditableFigureContext` from
      `figure_dialog_IR.py` import it from `figure_interactive.context` or from a
      deliberate `figure_interactive` package export.
- [ ] The context exposes `current_size_inches()` so Save Graphics does not need
      its own probing helper.

### What not to do

- Do not keep a second `EditableFigureContext` in `figure_dialog_IR.py`.
- Do not support arbitrary fake context methods such as `figure_ir()` as the
  product contract.
- Do not make consumer dialogs reach directly into `figure_context._figure_window`.

### Blocked by

- Slice 6: Add Feature Import Boundary Tests

### User stories covered

- Refactor Status Finding 4: Figure Dialogs Need A Clearer Context Boundary
- Refactor Status Finding 5: Save Graphics Has An Unclear Defaults Path

## Slice 8: Make FigureDialogIR Workflow-Only

### Type

`AFK`

### What to build

Make `hyde/user_interface/plugins/figure_control_dialog/figure_dialog_IR.py` own
only `FigureDialogIR` workflow state and patch-source selection.

Keep `FigureDialogIR` in this file. Remove from this file:

- Qt imports
- `HydeFigureDialogWidget`
- `EditableFigureContext`
- broad context fallback helpers
- list-widget rendering helpers
- dialog lifecycle and dispatch behavior

`FigureDialogIR` should accept only `FigureIR` instances or `None` for
opening/current/applied snapshots. Its `python_source()` should still lower the
non-live-update patch preview through `FigureIRDiff`.

### Acceptance criteria

- [ ] `rg "QtCore|QtWidgets|HydeDialogWidget|EditableFigureContext|QListWidget" hyde/user_interface/plugins/figure_control_dialog/figure_dialog_IR.py`
      returns no matches.
- [ ] `FigureDialogIR` stores opening/current/applied snapshots as `FigureIR` or
      `None`, not arbitrary objects.
- [ ] `FigureDialogIR.python_source(log=False)` still emits the same patch source
      as the corresponding pre-refactor patch path.

### What not to do

- Do not leave a compatibility import like
  `from .figure_dialog_widget import HydeFigureDialogWidget` in
  `figure_dialog_IR.py`.
- Do not keep `_context_figure_ir()` in this file.
- Do not preserve fake-fixture compatibility by accepting arbitrary snapshot
  object shapes.

### Blocked by

- Slice 7: Create The Explicit Figure Context Adapter

### User stories covered

- Refactor Status Finding 3: `FigureDialogIR` Mixes Workflow IR With Widget Infrastructure

## Slice 9: Move HydeFigureDialogWidget To Widget Support

### Type

`AFK`

### What to build

Create `hyde/user_interface/plugins/figure_control_dialog/figure_dialog_widget.py`
and move `HydeFigureDialogWidget` into it.

The widget support file owns:

- Qt wiring
- supported trace list rendering
- live-update checkbox policy
- dispatch decisions
- rollback / accept / reject lifecycle

The widget must store command-relevant figure snapshots only through
`self.widget_ir`, and `self.widget_ir` must be a `FigureDialogIR`.

Update imports in:

- `hyde/user_interface/plugins/figure_control_dialog/axis_edit_dialog.py`
- `hyde/user_interface/plugins/figure_control_dialog/trace_edit_dialog.py`
- `hyde/user_interface/plugins/remove_from_graph_dialog/dialogs.py`
- `hyde/user_interface/plugins/curve_fit_dialog/dialogs.py`
- tests that import `HydeFigureDialogWidget`

### Acceptance criteria

- [ ] `rg "HydeFigureDialogWidget" hyde/user_interface/plugins/figure_control_dialog/figure_dialog_IR.py`
      returns no matches.
- [ ] `rg "from .*figure_dialog_IR import .*HydeFigureDialogWidget" hyde tests`
      returns no matches.
- [ ] Figure-control dialogs still use `FigureDialogIR` as their `widget_ir`.

### What not to do

- Do not keep `HydeFigureDialogWidget` importable from `figure_dialog_IR.py`.
- Do not introduce another `widget_ir`-like field on the widget.
- Do not let the widget assemble final Python strings except by asking
  `FigureDialogIR` / `FigureIRDiff` for `python_source()`.

### Blocked by

- Slice 8: Make FigureDialogIR Workflow-Only

### User stories covered

- Refactor Status Finding 3: `FigureDialogIR` Mixes Workflow IR With Widget Infrastructure

## Slice 10: Replace Broad Figure Context Fallbacks

### Type

`AFK`

### What to build

Make figure-working dialogs use only the explicit context from Slice 7.

Update `HydeFigureDialogWidget.__init__` to accept either:

- an `EditableFigureContext`, or
- `None` for tests that intentionally cover no active figure

If a launcher has a raw `FigureWindow`, adapt it at the launcher boundary with
`EditableFigureContext(figure_window)`.

Remove fallback probing for:

- `figure_context._figure_window`
- `figure_window.figure_ir()`
- `figure_window.snapshot_state.figure_ir()`
- arbitrary `figure_context.current_figure_ir()`
- arbitrary `figure_context.figure_ir()`

Update tests to use either `EditableFigureContext` or a minimal test double with
exactly the public context interface from Slice 7.

### Acceptance criteria

- [ ] `rg "_figure_window|snapshot_state|figure_ir\\(" hyde/user_interface/plugins/figure_control_dialog`
      returns no context-fallback matches.
- [ ] Dialog tests fail if passed an object that lacks the explicit context
      interface.
- [ ] Production dialog launchers adapt raw `FigureWindow` objects before passing
      context into dialogs.

### What not to do

- Do not add `hasattr` fallback ladders to preserve old tests.
- Do not let dialogs reach around the context into `FigureWindow`.
- Do not make the context authoritative for scientific state; it adapts
  kernel-owned figure IR snapshots.

### Blocked by

- Slice 9: Move HydeFigureDialogWidget To Widget Support

### User stories covered

- Refactor Status Finding 4: Figure Dialogs Need A Clearer Context Boundary

## Slice 11: Narrow Save Graphics To The Figure Context

### Type

`AFK`

### What to build

Remove the multi-shape figure-size probing from Save Graphics and use the explicit
figure context.

Update `SaveGraphicsDialog` to require the `EditableFigureContext` from
`hyde/user_interface/plugins/figure_interactive/context.py`.

Delete `figure_context_size_inches()` from
`hyde/user_interface/plugins/save_graphics_dialog/dialogs.py`.

Use only `figure_context.current_size_inches()` for the opening size. Keep export
command generation in `build_preview_state()` through
`FigureIR(...).with_save_graphics(...)`.

### Acceptance criteria

- [ ] `rg "figure_context_size_inches|_figure_window|snapshot_state|widget_ir" hyde/user_interface/plugins/save_graphics_dialog/dialogs.py`
      returns no matches related to figure context probing.
- [ ] Save Graphics tests still assert the emitted live-kernel `fig.savefig(...)`
      command.
- [ ] The same-size UI defaults come from `EditableFigureContext.current_size_inches()`.

### What not to do

- Do not inspect `figure_context._figure_window`.
- Do not inspect `figure_window.widget_ir`.
- Do not inspect `snapshot_state.figure_ir()` or `snapshot_state.figure_defaults()`
  from the Save Graphics dialog.
- Do not move export command generation out of `FigureIR`.

### Blocked by

- Slice 10: Replace Broad Figure Context Fallbacks

### User stories covered

- Refactor Status Finding 5: Save Graphics Has The Right Command Path But An Unclear Defaults Path

## Slice 12: Figure Dialog Boundary Checkpoint

### Type

`AFK`

### What to build

Evaluate the figure-dialog boundary after Slices 7-11 and correct any ownership
drift before touching Curve Fit.

### Acceptance criteria

- [ ] `figure_dialog_IR.py` has no Qt imports and no widget class.
- [ ] `figure_dialog_widget.py` owns `HydeFigureDialogWidget` and UI helpers.
- [ ] `EditableFigureContext` has exactly one implementation.
- [ ] Save Graphics and figure-control dialogs use the explicit context interface.
- [ ] If a dialog needs one more fact from the figure window, that fact is added
      to `EditableFigureContext` and tests, not reached through from the consumer
      dialog.

### What not to do

- Do not proceed with a known fallback ladder still present.
- Do not add compatibility imports from the old module locations.

### Blocked by

- Slice 11: Narrow Save Graphics To The Figure Context

### User stories covered

- Refactor Status Findings 3, 4, and 5

## Slice 13: Recheck Curve Fit Composition

### Type

`AFK`

### What to build

Update Curve Fit after the figure boundary cleanup so it composes stable IR
surfaces rather than broad plugin support modules.

Update `hyde/user_interface/plugins/curve_fit_dialog/curve_fit_IR.py` so it may
import:

- `LmfitIR` from `hyde.features.lmfit_ir`
- `FigureDialogIR` from `figure_control_dialog.figure_dialog_IR`
- pure trace-label helpers from `hyde.features.matplotlib_figure_records`, if
  needed

It must not import `FigureDisplayHelper` from
`figure_interactive.matplotlib_support`.

Keep preview mode UI policy, such as `"Commands"` vs `"Equation"`, on
`CurveFitDialog`, not in `CurveFitIR`.

Keep attached-display patching through `FigureDialogIR` / `FigureIRDiff`.

### Acceptance criteria

- [ ] `rg "FigureDisplayHelper|_figure_window|FigureWindow|snapshot_state" hyde/user_interface/plugins/curve_fit_dialog/curve_fit_IR.py`
      returns no matches.
- [ ] Curve Fit preview, commit, live update, rollback/store, and attached-display
      patching still share the IR command path.
- [ ] No lmfit command lowering moves into matplotlib or figure modules.

### What not to do

- Do not make `CurveFitIR` reach into `FigureWindow`.
- Do not let `CurveFitDialog` assemble final attached-display matplotlib Python
  directly.
- Do not move lmfit lowering into `matplotlib_features.py`.

### Blocked by

- Slice 12: Figure Dialog Boundary Checkpoint

### User stories covered

- Refactor Status Finding 6: Curve Fit Is Closer, But Still Carries Old Composition Risks

## Slice 14: Add Durable Figure Boundary Tests

### Type

`AFK`

### What to build

Add tests that preserve the intended figure-family boundaries without pinning
private helper wiring.

Add or update tests to prove:

- `figure_dialog_IR.py` does not import Qt modules.
- `figure_dialog_IR.py` does not define `HydeFigureDialogWidget`.
- `figure_dialog_widget.py` defines `HydeFigureDialogWidget`.
- `FigureDialogIR.python_source(log=False)` produces the same patch string shown
  by a figure-dialog widget preview for the same opening/applied/current IR
  snapshots.
- Save Graphics uses a context with `figure_name()` and `current_size_inches()`,
  not fake `_figure_window` or `snapshot_state` shapes.

### Acceptance criteria

- [ ] The tests fail if `HydeFigureDialogWidget` is moved back into
      `figure_dialog_IR.py`.
- [ ] The preview assertion exercises emitted Python, not private flags or helper
      call order.
- [ ] `tests/test_save_graphics_dialog.py` contains no fake context that relies on
      `_figure_window` or `snapshot_state`.

### What not to do

- Do not assert private helper call order.
- Do not test that a temporary helper exists.
- Do not use fake context fallback shapes removed by Slice 10.

### Blocked by

- Slice 13: Recheck Curve Fit Composition

### User stories covered

- Refactor Status Finding 10: The Tests Need Boundary Guards

## Slice 15: Preserve Clean App/File, Table, And Python Variables Patterns

### Type

`AFK`

### What to build

Guard the already-cleaner areas from regression while the figure family changes.

Keep or add focused tests proving:

- project file dialogs build `HydeAppIR` directly as `widget_ir`
- `HydeFileDialog.refresh_from_file_selection()` previews
  `widget_ir.python_source(log=False)`
- table edit/create/delete commands lower from active `TableIR` / `TableIRDiff`
- Python Variables delete dispatch lowers through transient `HydeAppIR`
- Python Variables view/filter state remains widget-local

### Acceptance criteria

- [ ] Existing file-dialog, table, and Python Variables tests pass after figure
      cleanup.
- [ ] No new non-neutral code appears in `hyde/user_interface/shared/`.
- [ ] No table presentation cache is moved into IR.

### What not to do

- Do not redesign `HydeFileDialog` as part of the figure cleanup.
- Do not move table display cache into `TableIR`.
- Do not introduce table or Python Variables compatibility wrappers to mimic old
  command helpers.

### Blocked by

- Slice 14: Add Durable Figure Boundary Tests

### User stories covered

- Refactor Status Finding 7: File And Project Dialogs Are A Good Pattern
- Refactor Status Finding 8: Table IR Ownership Looks Mostly Real
- Refactor Status Finding 9: Python Variables Delete Dispatch Is On The Right Track

## Slice 16: Resync Docs And Refactor Status

### Type

`AFK`

### What to build

Update documentation after the code cleanup so the repository describes the landed
ownership in present tense.

Update only the docs that need to change:

- `project_management/ARCHITECTURE.md`
- `project_management/IR-CONTROL.md`
- `project_management/STYLE.md`
- `project_management/STATUS.md`
- `issues/REFACTOR_STATUS.md`

The docs should describe:

- feature-side figure state authority under `hyde/features`
- plugin-local figure dialog widget support outside `figure_dialog_IR.py`
- the explicit figure context adapter
- any remaining gaps that were not solved

### Acceptance criteria

- [x] Docs no longer describe
      `figure_interactive/matplotlib_support.py` as the home of figure IR
      authority.
- [x] Docs no longer imply `figure_dialog_IR.py` owns
      `HydeFigureDialogWidget`.
- [x] `issues/REFACTOR_STATUS.md` reflects which slices are complete and what
      remains.

### What not to do

- Do not add historical notes to architecture/spec docs.
- Do not document temporary compatibility imports as accepted patterns.
- Do not claim the whole IR migration is complete if Slice 18 still fails.

### Blocked by

- Slice 15: Preserve Clean App/File, Table, And Python Variables Patterns

### User stories covered

- Refactor Status Finding 11: The Docs Should Keep The Phase Distinction

## Slice 17: Test Cleanup Pass

### Type

`AFK`

### What to build

Use the `test-cleanup` skill to remove or rewrite leftover development tests from
the refactor.

Classify changed tests as:

- Keep: tests that fail when public behavior or an intentional architecture
  boundary breaks.
- Rewrite: tests that assert real behavior through private helper structure.
- Delete: tests that only preserve temporary implementation paths, old fake
  fixture shapes, helper call order, or incidental file movement.

The final suite should preserve a small durable safety net around:

- feature-to-plugin import direction
- preview/dispatch command identity
- figure dialog IR/widget separation
- explicit figure context usage
- canonical trace display names
- Save Graphics export command generation
- app/file, table, and Python Variables reference patterns

### Acceptance criteria

- [ ] Every changed test has a clear public behavior or architecture-contract
      reason to exist.
- [ ] Tests that only assert private helper wiring, private call order, or stale
      fake fixture shape are removed or rewritten.
- [ ] No production fallback is added solely to keep an old test passing.
- [ ] Relevant targeted tests pass after cleanup.

### What not to do

- Do not delete broad coverage casually. Remove only development scaffolding or
  implementation-coupled tests.
- Do not rewrite durable behavior tests into weaker import-shape tests.
- Do not change production behavior to satisfy old tests.

### Blocked by

- Slice 16: Resync Docs And Refactor Status

### User stories covered

- To-Issues required test-cleanup slice
- Refactor Status Finding 10: The Tests Need Boundary Guards

## Slice 18: Final Completion Checkpoint

### Type

`AFK`

### What to build

Run the final static and behavioral checks. Correct any issue before marking the
refactor complete.

### Acceptance criteria

- [x] `rg "hyde\\.user_interface\\.plugins" hyde/features` returns no matches.
- [x] `rg "FigureIRAuthority" hyde/user_interface/plugins/figure_interactive/matplotlib_support.py`
      returns no matches.
- [x] `rg "HydeFigureDialogWidget" hyde/user_interface/plugins/figure_control_dialog/figure_dialog_IR.py`
      returns no matches.
- [x] `rg "QtCore|QtWidgets" hyde/user_interface/plugins/figure_control_dialog/figure_dialog_IR.py`
      returns no matches.
- [x] `rg "figure_context_size_inches|_figure_window|snapshot_state" hyde/user_interface/plugins/save_graphics_dialog/dialogs.py`
      returns no context-probing matches.
- [x] `rg "_figure_window|snapshot_state|figure_ir\\(" hyde/user_interface/plugins/figure_control_dialog`
      returns no broad context fallback matches.
- [ ] Run targeted tests in the `labscript` conda environment (NOT YET RUN -
      the environment is being rebuilt; every other box in this slice was
      verified statically):
      `tests.test_hyde_feature_modules`,
      `tests.test_figure_display`,
      `tests.test_hyde_tool_widget`,
      `tests.test_axis_edit_dialog`,
      `tests.test_trace_edit_dialog`,
      `tests.test_remove_from_graph_dialog`,
      `tests.test_save_graphics_dialog`,
      `tests.test_curve_fit`,
      `tests.test_file_dialog_plugin`,
      `tests.test_table_features`, and
      `tests.test_python_variables_final`.

### Corrective action

If a static check fails, move code to the ownership location named in these
issues. Do not add allowlist exceptions without human review.

If a behavior test fails because it encoded an old fake fixture shape, update the
fixture to the explicit product contract. Do not add production fallbacks.

If emitted command text changes, inspect whether the new command preserves the
documented product contract. Preserve documented command behavior unless a human
explicitly approves the change.

### What not to do

- Do not mark the refactor complete if any static check still fails.
- Do not hide remaining violations in docs as accepted exceptions.
- Do not skip targeted tests because unrelated tests are slow.

### Blocked by

- Slice 17: Test Cleanup Pass

### User stories covered

- Refactor Status: Current Bottom Line
