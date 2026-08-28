# Hyde Refactor Status

## Purpose

This file is the canonical local status note for the in-progress Hyde plugin and
IR boundary refactor.

It tracks the ownership cleanup that followed the earlier file-shape pass. The
file-shape pass established the intended module names and rough locations; the
slices in `issues/ISSUES.md` tightened the figure-family ownership boundaries
that remained ambiguous.

## Current Assessment

The figure-family boundary work has landed, including the duplicate figure IR
authority that Slice 2 originally copied instead of moved.

Landed and verified:

- package IR modules live under `hyde/features`
- feature-side matplotlib color parsing lives in `hyde/features/matplotlib_color.py`
- feature-side trace record helpers live in
  `hyde/features/matplotlib_figure_records.py`
- `figure_interactive/matplotlib_support.py` is plugin support only
- `EditableFigureContext` lives in
  `hyde/user_interface/plugins/figure_interactive/context.py`
- `FigureDialogIR` is workflow-only in
  `hyde/user_interface/plugins/figure_control_dialog/figure_dialog_IR.py`
- `HydeFigureDialogWidget` lives in
  `hyde/user_interface/plugins/figure_control_dialog/figure_dialog_widget.py`
- `SaveGraphicsDialog` uses `EditableFigureContext.current_size_inches()`
- `CurveFitIR` no longer imports `FigureDisplayHelper`
- the actual widget class hierarchy matches `STYLE.md`
- `FigureIRAuthority` is the single figure IR authority for both processes

## Resolved: Duplicate Figure IR Authority

Slice 2 created `hyde/features/matplotlib_figure_state.py` by copying out of
`hyde/features/matplotlib_features.py` without removing anything from the
source, so Hyde carried two figure IR authorities across the process boundary:
the kernel normalized `fig._hyde_ir` through `MatplotlibCodec` / `FigureIRModel`
and the GUI through `FigureIRAuthority`.

The duplication was not only a divergence risk. `FigureIRModel._range_lines`
carried a doubled `@classmethod` decorator, which Python 3.13 and later reject
as non-callable, so every kernel-side figure IR lowering that reached axis state
raised `TypeError`. The GUI copy of the same method was correct. One authority
worked and one did not, and only the tests exercising the kernel copy failed.

`FigureIRAuthority` is now the only figure IR authority. `FigureIRModel`,
`MatplotlibCodecView`, `FigureIRCodec`, `FigureGraphicsExportCodec`,
`FigureCodec`, and `FigurePatchCodec` are gone. `MatplotlibCodec` keeps its
multi-feature dispatch role and routes `figure_ir` to `FigureIRAuthority`, so
both processes reach the same code.

`matplotlib_features.py` went from 2,613 to 1,223 lines while
`matplotlib_figure_state.py` grew by 43. The source lost roughly what the audit
measured as duplicated, which is the check the original Slice 2 acceptance
criteria could not perform.

### Decisions Recorded

The three checks `FigureIRAuthority` had silently dropped were settled
deliberately rather than by accident:

- **`feature` key: restored.** `FigureIRAuthority.feature_name` is
  `"figure_ir"`, `default_state()` emits the key, and `normalize_state()`
  preserves an incoming one. The kernel and the GUI now produce byte-identical
  state dictionaries.
- **Feature-kind check in `validate_state()`: restored.** A state of another
  feature kind raises `ValueError`. Recorded as a current decision rather than a
  permanent one.
- **`state_version`: dropped.** Nothing in the repository ever read it, figure
  IR is not persisted to a versioned on-disk artifact, and `IR-CONTROL.md` rules
  out migration frameworks by default. It has since been removed from the
  sibling models too, so the state envelope stays uniform: `FeatureCodec` in
  `hyde/features/base.py` and the `hyde_features`, `lmfit_features`, and
  remaining `matplotlib_features` models no longer declare or emit it.
  `feature` / `feature_name` is a different key and is kept everywhere, because
  `MatplotlibCodec` dispatches on it.

### Dependency Direction

`matplotlib_features.py` now imports from `matplotlib_figure_state.py`, not the
reverse. The figure operand node helpers `operand_to_python` and
`operand_from_runtime_value` moved to `matplotlib_figure_state.py` alongside the
operand schema they serve, which is what makes that direction acyclic.

## Completed Ownership Work

### Feature-To-Plugin Direction

Feature-side modules are the source of package IR authority. They must not
import GUI plugin modules.

### Kernel-To-GUI Direction

No module under `hyde/` outside `hyde/user_interface/` may reach
`hyde.user_interface.plugins` or Qt. `hyde/__main__.py` is the one exception,
because it is the GUI process entry point.

Lane 2 `comm` target names live in `hyde/execution/comms.py`, so kernel-side
code never imports a GUI plugin module to learn a target name.

`tests/test_hyde_feature_modules.py` guards this with a transitive import
closure that models parent-package execution. Following only explicit
`from X import Y` edges is what let `hyde/matplotlib_backend.py` reach `qtutils`
through the `__init__.py` of a Qt-free-looking plugin submodule.

### One Definition Per Name

`tests/test_hyde_feature_modules.py` also asserts that no two modules under
`hyde/features/` define the same top-level name. A "move A to B" slice whose
acceptance criteria only grep B cannot tell a move from a copy; this guard can.
It found `normalize_optional_text` defined in both `base.py` and
`matplotlib_ir.py` with divergent whitespace handling, plus a third identical
copy as a private method on a class in `matplotlib_ir.py`. All three collapsed
onto `base.normalize_optional_text`.

### Canonical Trace Records

Canonical supported trace records and display-name generation live in
`hyde/features/matplotlib_figure_records.py`. Figure surfaces consume that
contract directly; there is no delegating wrapper class in between.

### Figure Dialog Boundary

`FigureDialogIR` owns workflow snapshots and patch-source selection only.

`HydeFigureDialogWidget` lives in
`hyde/user_interface/plugins/figure_control_dialog/figure_dialog_widget.py` and
owns Qt wiring, supported-trace list rendering, live-update policy, dispatch
decisions, and dialog lifecycle.

`EditableFigureContext` is the explicit adapter from a figure window to
figure-working dialogs.

### Save Graphics

`SaveGraphicsDialog` keeps export command generation on `FigureIR` and takes
opening size defaults from `EditableFigureContext.current_size_inches()`.

### Curve Fit

`CurveFitIR` no longer imports `FigureDisplayHelper`; attached-display patching
remains on the figure IR / figure-dialog IR path.

### Clean Reference Patterns

The app/file dialog path, table path, and Python Variables delete dispatch
remain reference patterns:

- project file dialogs build `HydeAppIR` directly as `widget_ir`
- `HydeFileDialog` previews the `widget_ir.python_source()` payload it submits
- table mutation commands lower from active `TableIR` / `TableIRDiff`
- Python Variables delete dispatch lowers through transient `HydeAppIR`
- Python Variables view/filter state remains widget-local

### Test Cleanup

The tests changed during the refactor were reviewed against the Slice 17
criteria. The suite keeps behavior and explicit-architecture-contract tests and
lost one refactor-history sentinel:

- deleted `test_figure_ir_runtime_path_no_longer_uses_matplotlib_codec_authority`,
  which patched four `MatplotlibCodec` methods to raise so it could assert
  `FigureIR` did not call them. It asserted a call path rather than an outcome,
  and now that both routes reach `FigureIRAuthority` the path it forbade would
  produce identical results. `TestFigureIRAuthorityIsShared` covers the real
  intent positively, by asserting the two entry points agree.
- rewrote the graphics-export macro-source test to go through
  `MatplotlibCodec.state_to_macro_source`, the surviving public surface, instead
  of a deleted codec view.
- repointed the figure dialog fixtures onto `FigureIRAuthority`, the authority
  the dialogs actually run on.

Two stale test fixtures were corrected rather than accommodated in production,
per `AGENTS.md`:

- `FakeShell` gained `enable_gui`, which matplotlib's
  `install_repl_displayhook` calls on the IPython shell it is standing in for.
- the new-figure-dialog launcher test patched
  `figure_interactive.NewFigureDialog`, a module-level name that never existed;
  the launcher imports it from `.dialogs` inside the method.

Kept deliberately:

- the AST check that `figure_dialog_IR.py` is Qt-free and does not define
  `HydeFigureDialogWidget`. It lives inside `hyde/user_interface/`, so the
  kernel-side import closure guard does not cover it, and the separation is an
  explicit `IR-CONTROL.md` contract.
- the trace-dialog check that patches `exec_` to raise. That asserts a
  user-visible outcome, that no dialog opens when there are no supported traces.
- `test_hyde_feature_module_owns_hyde_figure_lowerers`, which asserts emitted
  Python strings rather than import shape.

## Test Status

The `labscript` conda environment works
(`/Users/ispielma/miniforge3/envs/labscript`, Python 3.14.7, matplotlib 3.11.1).
It has no `pytest`; run suites with `unittest` and `QT_QPA_PLATFORM=offscreen`.

Slice 18 targeted suites, compared against a worktree at the last commit:

| Suite | At `HEAD` | Now |
| --- | --- | --- |
| `test_hyde_feature_modules` | 3 pass | 9 pass |
| `test_figure_display` | 1 error | 3 pass |
| `test_hyde_tool_widget` | 35 pass | 36 pass |
| `test_axis_edit_dialog` | 13 errors | 14 pass |
| `test_trace_edit_dialog` | 14 errors | 15 pass |
| `test_remove_from_graph_dialog` | 11 errors | 12 pass |
| `test_save_graphics_dialog` | 1 error | 15 pass |
| `test_curve_fit` | 7 failures, 20 errors | 60 pass |
| `test_file_dialog_plugin` | 13 pass | 14 pass |
| `test_table_features` | 62 pass | 62 pass |
| `test_python_variables_final` | 14 pass | 15 pass |
| `test_matplotlib_features` | 6 failures, 24 errors | 86 pass |

No test fails now that was not already failing at `HEAD`, and the whole suite
now passes: **500 tests across all 21 modules, 0 failures, 0 errors** in a
single process, in 58 seconds.

The rest of the suite (`test_figure_comm_actions`, `test_kernel_launcher`,
`test_kernel_runtime`, `test_kernel_signals`, `test_matplotlib_color_picker`,
`test_plugin_tools`, `test_project_save_load`, `test_window_macros`,
`test_figure_window_session_save`) passes.

### matplotlib 3.11 Compatibility

`hyde/matplotlib_backend.py` read axis label line spacing as
`float(getattr(label_artist, "_linespacing", default))`. In matplotlib 3.11
`Text` linespacing defaults to the string `'normal'`, meaning "use the font's
natural spacing", so that `float()` raised `ValueError` and took out the whole
live figure IR reimport path. Hyde IR stores a numeric multiplier, so a
non-numeric live value now maps back to the IR default. This was the single root
cause behind most of the errors in the `HEAD` column above.

### Test Harness CWD And sys.path Pollution

The 14 `tests/test_curve_fit.py` failures that this document previously listed
as an unexplained pre-existing attached-display regression had nothing to do
with the attached display. They were caused by the test harness.

`ProcedureExecutionHarness` runs the product's real
`execute_procedures_bootstrap`, which deliberately `chdir`s into the project
directory and puts it on `sys.path` and deliberately never undoes that: a
running Hyde GUI resolves `procedures/` imports from there. The harness pointed
that behaviour at a `TemporaryDirectory` it then deleted, without restoring
either. Two consequences:

- the process was left standing in a deleted directory, so `os.getcwd()` raised
  `FileNotFoundError`
- `sys.path` grew from 8 entries to 115, 107 of them dangling into deleted
  temporary directories, two per test

Within `test_curve_fit` itself that broke the tests running after the first
offending one, which is where the trace-count mismatches came from. Across a
single-process whole-suite run it was worse: `tests.test_curve_fit` is second of
twenty-one alphabetically, so the other nineteen modules all failed to load, and
any subprocess spawned afterwards inherited the dangling CWD and died during
import. `zprocess` calls `os.getcwd()` at import time, which made the failure
look like a `zprocess` or kernel-launcher problem rather than a test-harness one.

The fix is in the harness, not the product, per `AGENTS.md`: capture the CWD and
`sys.path` in `__init__`, and restore both in `close()` *before*
`tempdir.cleanup()`. Restoring after the delete still leaves a window.
`TestProcedureExecutionHarnessLeavesTheProcessUsable` pins this, and asserting
it required no production change.

Confirmed by removing only the restore, in memory, and re-running the module: 54
errors without it, 0 with it.

Note that `python -m unittest discover -s tests -t .` does not work in this
repository, because `tests/` has no `__init__.py`, so it is a namespace package.
That is what steered everyone toward per-module runs, which gave every module a
fresh process and hid this bug completely.

## Remaining Work

### Behaviour-Level IR Pass

The file-shape and ownership refactor has landed. The behaviour-level IR pass
described in `project_management/STATUS.md` is the next substantive step.

## Current Bottom Line

The duplicate figure IR authority is collapsed, Slice 17 is complete, and the
Slice 18 targeted suites have actually run. All twelve pass, and so does the
rest of the suite: 500 tests across 21 modules, 0 failures, 0 errors, in one
process.
