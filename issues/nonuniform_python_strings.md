# Uniform GUI Python Generation

This package-wide cleanup is complete. Hyde now follows one uniform rule for
GUI-originated command Python:

- every GUI-generated Python string comes from `HydeGuiState.python_source()`
- preview displays that same generated string
- `Do It` may dispatch the exact cached preview string without rerunning
  `python_source()`
- widgets, dialogs, and windows do not assemble command Python directly

The intended API surface is one generation method: `python_source()`. Hyde does
not keep a separate preview-only Python-generation path.

## Shared Constraints

- Direct GUI calls to codec lowering such as `FeatureCodec.state_to_python(...)`
  are not public GUI behavior paths.
- If a real use case does not fit the current `HydeGuiState` surface, Hyde
  extends the shared state/base infrastructure narrowly rather than adding a
  feature-local bypass.
- `HydeFileDialog` subclasses use the shared preview/generation/dispatch path
  defined by `HydeFileDialog`, adding behavior by overriding hooks and calling
  `super()` rather than inventing alternate submission paths.

## Package Findings

- Runtime/core command surfaces use `RuntimeCommandState.python_source()`.
- File/project dialogs use the shared `HydeFileDialog` flow with state-owned
  `python_source()` generation.
- Table creation, live table refresh, and table macro publication use
  `TableState.python_source()`.
- Figure creation, figure refresh/regenerate, figure close, and figure macro
  publication use `FigureState.python_source()`.
- Shared figure-dialog patch surfaces, including `Remove From Graph...`, axis
  edit, and trace appearance dialogs, use `FigurePatchState.python_source()`.
- `Save Graphics...` uses a dedicated figure export state/codec path and the
  shared `HydeFileDialog` preview/dispatch flow.
- Curve Fit uses `CurveFitState.python_source()` for preview, commit, live,
  snapshot-store, and rollback/restore command generation, while attached figure
  patching stays on the shared `FigurePatchState` path.

## Testing Guidance

- Tests should verify the visible contract:
  - the string shown in preview
  - the string dispatched for execution
- Cached preview dispatch is acceptable. Tests should verify that the
  dispatched string matches the authoritative generated preview string.
- Tests should avoid helper-name, codec-call, or call-order assertions when the
  same defect can be caught through preview text or dispatched text.
