# Hyde Refactor Status

## Purpose

This file is the canonical local status note for the in-progress Hyde plugin and
IR boundary refactor.

It tracks the ownership cleanup that followed the earlier file-shape pass. The
file-shape pass established the intended module names and rough locations; the
slices in `issues/ISSUES.md` tightened the figure-family ownership boundaries
that remained ambiguous.

## Current Assessment

Most of the figure-family boundary work landed. One slice did not, and the
acceptance criteria did not detect it.

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

Not landed:

- Slice 2 copied figure IR authority instead of moving it. See
  **Open Defect: Duplicate Figure IR Authority** below.

## Open Defect: Duplicate Figure IR Authority

`hyde/features/matplotlib_figure_state.py` was created by copying out of
`hyde/features/matplotlib_features.py`. Nothing was removed from the source
file, so Hyde now carries two figure IR authorities.

Evidence:

- `matplotlib_features.py` changed by +11/-4 lines while a 1,175-line "moved"
  module appeared beside it
- `FigureIRAuthority` (685 lines) is an 80% verbatim copy of `FigureIRModel`
  (898 lines), which still exists in `matplotlib_features.py`
- 26 shared method names: 16 byte-identical, 10 diverged
- 18 module-level names are defined in both files: 13 byte-identical, 5 diverged
- ~1,224 of the 2,613 lines in `matplotlib_features.py` are duplicated

The two authorities are split across the process boundary, so the kernel and the
GUI disagree:

- `hyde/matplotlib_backend.py` (kernel) builds `fig._hyde_ir` through
  `MatplotlibCodec` / `FigureIRModel`, which include `feature` and
  `state_version`
- `hyde/features/matplotlib_ir.py` (`FigureIR`, GUI) normalizes through
  `FigureIRAuthority`, whose `default_state()` omits both keys and whose
  `normalize_state()` strips them from kernel-produced state
- `FigureIRAuthority.validate_state()` dropped the feature-kind check, so the
  GUI path accepts a state of the wrong feature kind that the kernel path
  rejects
- the two copies of `operand_names` disagree on return type, whitespace
  handling, and empty values, and `operand_names` feeds `tracked_names`

The four Slice 2 acceptance greps all pass because none of them inspected
`matplotlib_features.py`.

### Resolving it

`IR-CONTROL.md` already decides the ownership: `xxx_features.py` lowerers own
"package-local string lowering only - no top-level IR authority". So
`FigureIRAuthority` is the surviving authority and `FigureIRModel` goes. This is
a split rather than a delete, because `FigureIRAuthority` currently also carries
`state_to_python` and the `_*_lines` lowering helpers.

The three checks that `FigureIRAuthority` dropped - `feature`, `state_version`,
and the feature-kind validation - need a deliberate keep-or-drop decision rather
than being lost by accident.

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

## Remaining Work

### Collapse The Duplicate Figure IR Authority

See **Open Defect** above. Blocks any honest completion claim for Slice 2.

The dialog tests no longer reference `FigureIRCodec`, so `FigureIRModel` and its
`FigureIRCodec` view can now be removed without rewriting those fixtures.
`FigureCodec` and `FigurePatchCodec` in `matplotlib_features.py` are currently
unreferenced and should be settled as part of that same pass rather than removed
piecemeal beforehand.

### Slice 17: Test Cleanup Pass

Partially done. Completed so far:

- the numeric-series helper test now compares classification results across
  callers instead of asserting helper identity
- figure dialog tests build fixtures with `FigureIRAuthority`, the authority the
  dialogs actually run on, instead of `FigureIRCodec`

Still to do: review the remaining tests changed during the refactor and keep
only durable public behavior or explicit architecture-boundary checks.

### Slice 18: Final Completion Checkpoint

All static checks pass. The targeted test run has not happened because the
`labscript` conda environment is being rebuilt.

## Current Bottom Line

The figure-family boundary shape is correct except for the duplicate figure IR
authority, which is a real kernel/GUI divergence and not a tidiness issue. The
refactor is not complete until that duplication is collapsed, Slice 17 finishes,
and the Slice 18 targeted tests run.
