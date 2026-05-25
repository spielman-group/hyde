# GUI Python-Generation Inventory

Superseded temporary planning artifact. The package-wide
`HydeGuiState.python_source()` migration is complete, so this file remains only
as a compact historical inventory of the final normalized command-generation
surfaces. It is not an active work tracker.

Scope note:
- This inventory is about GUI-generated command/preview Python.
- Saved macro/session restore source remains a separate `macro_source()` family
  and is not the target of this migration unless a surface also mixes that
  macro path into command generation.

## Shared Base Families

| Family | Current mechanism | Status |
| --- | --- | --- |
| `HydeGuiState` command owner | `python_source()` validates, lowers through the codec, and logs the generated command string. | Compliant baseline. |
| `HydeFileDialog` shared flow | Shared preview/dispatch shell builds preview strings from dialog-owned `HydeGuiState` objects via `python_source()`, then may dispatch that cached string. | Compliant. |

## Runtime / Core Shell

| Surface | Current mechanism | Status |
| --- | --- | --- |
| Procedure reload from `main` | `RuntimeCommandState.python_source()` | Compliant |
| Remote request server | `RuntimeCommandState.python_source()` | Compliant |
| Window macro execution menu | `RuntimeCommandState.python_source()` | Compliant |

## File / Project Family

| Surface | Current mechanism | Status |
| --- | --- | --- |
| Direct `Save`, `Quit`, and request-driven `Load` actions | `SimpleCommandState` / `LoadProjectState` `python_source()` | Compliant |
| `New Project`, `Load Project`, `Heal Project`, `Save As`, `Save Copy` dialogs | `HydeFileDialog` builds preview/dispatch strings from the dialog state object's `python_source()`. | Compliant |

## Python Variables / Mutation Family

| Surface | Current mechanism | Status |
| --- | --- | --- |
| Delete object from Python Variables | `MutationState.python_source()` | Compliant |
| Table cell edit / append / create-array paths | `MutationState.python_source()` | Compliant |

## Table Family

| Surface | Current mechanism | Status |
| --- | --- | --- |
| `New Table...` dialog preview | `TableState.python_source()` | Compliant |
| Append to active table | `TableState.python_source()` | Compliant |
| Publish table macros on project activation | `TableState.set_publish_table_macros()` then `python_source()` | Compliant |
| Push table data refresh requests | `TableState.set_push_table_data(...)` then `python_source()` | Compliant |

## Figure Creation / Figure Window Family

| Surface | Current mechanism | Status |
| --- | --- | --- |
| `New Figure...` dialog preview | `FigureState.python_source()` | Compliant |
| Publish figure macros on project activation | `FigureState.set_publish_figure_macros()` then `python_source()` | Compliant |
| Figure window close command | `FigureState.set_close_figure(...)` then `python_source()` | Compliant |
| Figure refresh / regenerate | `FigureState.set_refresh_figure(...)` then `python_source()` | Compliant |

## Shared Figure Dialog Patch Family

| Surface | Current mechanism | Status |
| --- | --- | --- |
| `HydeFigureDialogWidget` preview / commit path | Builds a `FigurePatchState` from source/target effective states and lowers it through `python_source()`. | Compliant |
| `Remove From Graph...` | Uses the shared `HydeFigureDialogWidget` `FigurePatchState` preview/commit path. | Compliant |
| Axis edit and trace appearance dialogs | Use the shared `HydeFigureDialogWidget` `FigurePatchState` preview/commit path. | Compliant |

## Figure Export Family

| Surface | Current mechanism | Status |
| --- | --- | --- |
| `Save Graphics...` dialog preview | `HydeFileDialog` builds preview/dispatch strings from `FigureGraphicsExportState.python_source()`. | Compliant |

## Curve Fit Family

| Surface | Current mechanism | Status |
| --- | --- | --- |
| Curve Fit preview/commit/live command generation | `CurveFitState` selects the active command mode and lowers it through `python_source()` with dialog-supplied context. | Compliant |
| Curve Fit attached-display updates | Attached display patching still uses the shared `FigurePatchState` path, while the lmfit preview/live/store/restore command pieces come from `CurveFitState.python_source()`. | Compliant |

## Status

All inventoried GUI command-generation families are compliant with the uniform
`HydeGuiState.python_source()` rule.
