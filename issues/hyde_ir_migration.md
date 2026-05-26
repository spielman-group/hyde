## Problem Statement

Hyde's first IR migration pass delivered working behavior across the app/file,
table, Python Variables, figure, and several figure-dialog plugins, but it
initially left transitional compromises in the repository. Slice 6 resynced the
docs, specs, and related tests to the landed remediation so the repository now
describes one current architecture.

The remediated architecture now addresses the original problems:

- widget families are uniformly centered on one base-level `widget_ir`
- figure behavior belongs on `FigureIR` rather than on helper/session escape
  hatches
- dialogs and tools express their own IR ownership model directly
- package boundaries stay package-pure in `features/..._features.py`
- the docs and issue plan describe the landed architecture instead of the
  temporary remediation-gap framing

Curve Fit remains distinct from the remediation work because it was implemented
fresh on top of the corrected architecture rather than being a rewrite of an
earlier provisional plugin family.

## Solution

Redo the previously completed plugin families against the final IR contract, then
implement Curve Fit on top of that corrected base. The migration remains TDD and
vertical, but the already-landed plugins are now treated as behavior prototypes,
not compliant architecture.

The final architecture is:

- `HydeGuiState` is replaced by `HydeIR`
- `HydeIRDiff` is a real subclass of `HydeIR`
- every widget base family owns one base-level IR slot named `widget_ir`
- `HydeInteractiveWidget.widget_ir` is the live current object IR for that widget
- `HydeDialogWidget.widget_ir` and `HydeToolWidget.widget_ir` are the widgets'
  own IR objects, and may contain any external IR snapshots they need
- `python_source()` lives on IR objects
- `xxx_features.py` files only emit strings for package `xxx`
- concrete IR classes orchestrate cross-package lowering
- figure behavior belongs on `FigureIR`, not in figure-session escape hatches
- earlier prototype slices are rewritten as needed so the repository ends with one
  current contract

Slices 2-5 delivered the concrete repo-level fixes:

- figure lowerers are package-pure again
- Python Variables delete dispatch lowers through tool-owned IR
- live table mutation commands lower from the widget-owned `TableIR` /
  `TableIRDiff` path
- remote requests use the shared hidden execution lane with `silent=True`

## User Stories

1. As a Hyde developer, I want one IR abstraction to replace `HydeGuiState`, so
   that Hyde has one coherent GUI-side command-generation model.
2. As a Hyde developer, I want every widget family to own one `widget_ir`, so
   that widget-level IR ownership is uniform across the application.
3. As a Hyde developer, I want `HydeInteractiveWidget.widget_ir` to be the live
   current object IR, so that interactive widgets do not depend on extra base
   slots to express their state.
4. As a Hyde developer, I want `HydeDialogWidget.widget_ir` and
   `HydeToolWidget.widget_ir` to own their workflow state, so that dialogs and
   tools do not depend on hidden external state during lowering.
5. As a Hyde developer, I want app/file flows redone to the final IR contract, so
   that the simplest slices are compliant and no longer transitional.
6. As a Hyde developer, I want runtime/request flows redone to the final IR
   contract, so that app-adjacent command generation follows the same model.
7. As a Hyde developer, I want table behavior redone to the final IR contract, so
   that `TableIR` is owned and used correctly.
8. As a Hyde developer, I want Python Variables redone to the final IR contract,
   so that it stops depending on transitional assumptions from earlier slices.
9. As a Hyde developer, I want figure behavior redone to the final IR contract, so
   that `FigureIR` becomes the true owner of figure behavior.
10. As a Hyde developer, I want figure dialogs redone to the final IR contract, so
    that each dialog owns its own `widget_ir` and carries whatever figure IR
    snapshots it needs.
11. As a Hyde developer, I want figure-session escape hatches removed, so that
    figure behavior actually lives on `FigureIR`.
12. As a Hyde developer, I want `FigureDisplayHelper` to remain only if it is
    genuinely neutral, so that figure behavior is not hidden in helpers.
13. As a Hyde developer, I want `CurveFitIR` to be implemented fresh on the final
    architecture, so that Curve Fit does not inherit the earlier transitional
    mistakes.
14. As a Hyde developer, I want feature modules to remain package-pure lowerers,
    so that package boundaries are not blurred by convenience logic.
15. As a Hyde developer, I want every slice to be TDD and vertical, so that
    architectural claims are proved by observable behavior.
16. As a Hyde developer, I want later slices to revise earlier prototype slices,
    so that Hyde ends with one current syntax and contract.
17. As a Hyde developer, I want docs updated first, so that workers do not build
    on stale instructions.
18. As a Hyde developer, I want docs updated again at the end, so that the landed
    architecture is the only one described in the repository.

## Implementation Decisions

- Keep the migration centered on typed IR classes, not dict-backed transitional
  wrappers.
- `python_source()` is a method on IR objects.
- `HydeIRDiff` is a real subclass of `HydeIR`.
- Every widget base family owns one base-level IR slot named `widget_ir`.
- `HydeInteractiveWidget` owns only its live current object IR in `widget_ir`.
- Dialog/tool workflows that need baseline snapshots carry them inside their own
  `widget_ir`.
- Previously completed plugin families are considered noncompliant until rewritten
  to this contract.
- The redo work should proceed from simple to complex:
  - docs first
  - app/file/runtime redo
  - table/Python Variables redo
  - figure core redo
  - figure-dialog redo
  - Curve Fit fresh implementation
  - final resync
- Figure-session escape hatches are explicitly not the target architecture.
  Figure behavior should migrate to `FigureIR`.
- `FigureDisplayHelper` is allowed to survive only if it becomes a truly small
  neutral helper with no hidden figure ownership.
- Curve Fit is not a “cleanup” slice. It is new work that must be built on the
  corrected figure-family architecture.

## Testing Decisions

- Every slice must include end-to-end tests of real observable behavior.
- TDD is required for each slice.
- Good tests should assert:
  - the widget family owns the correct `widget_ir`
  - dialogs/tools populate from and mutate IR rather than parallel local state
  - `python_source()` comes from IR objects
  - package-pure lowerers are respected
  - the final user-visible command text and widget behavior are correct
- Earlier tests from the prototype slices should be rewritten where necessary to
  reflect the final contract rather than the transitional implementation.
- Tests should prefer behavior and architectural contract over helper call order or
  implementation wiring.

## Out of Scope

- Preserving prototype slice architecture just because it already landed.
- Keeping `HydeGuiState` as a co-equal long-term abstraction beside `HydeIR`.
- Allowing `xxx_features.py` files to emit strings for other packages.
- Treating Curve Fit as the place to work around unresolved figure-family design.
- Deferring contract corrections solely to avoid revisiting completed slices.

## Further Notes

- The next worker should treat the already-completed plugins as needing rewrite,
  not minor touch-up.
- The instructions for rewritten plugin families are different from Curve Fit:
  the former must be brought into compliance; the latter must be implemented fresh
  on the compliant base.
- The issue file should make that distinction explicit and unavoidable.
