## Problem Statement

Hyde's project-targeting file dialogs currently sit outside the standard
`HydeDialogWidget` pattern even though they already generate explicit Hyde Python
commands. They inherit `QFileDialog` directly, which leaves them as an outlier in the
dialog family, hides the generated command from the shared lower preview pane, and
provides no reusable file-selection widget or file-dialog base for upcoming dialogs
such as data import and figure export. Hyde needs one standard file-dialog family that
preserves the current hidden-command behavior for project operations while making the
chooser UI, preview contract, and common validation reusable.

## Solution

Introduce a shared file-dialog family inside Hyde's base widget layer. A reusable
`HydeFileWidget` will host the non-native Qt file chooser behavior and expose a
normalized selected target plus configurable selection policy such as file vs
directory mode, existence rules, and allowed suffix or name-filter rules. A shared
`HydeFileDialog` will sit on top of `HydeDialogWidget`, mount `HydeFileWidget` into
its upper content area, refresh the preview from the real backing command string, and
offer common validation plus optional overwrite confirmation. The existing project
dialogs for New, Load, Heal, Save As, and Save Copy will then be refactored onto that
family while keeping `SimpleCommandState` and the existing hidden Hyde command
generation path. Plain `Save` remains a direct hidden dispatch with no dialog.

## User Stories

1. As a Hyde user, I want project file dialogs to show the actual Hyde Python they
   will run, so that the dialog matches Hyde's command-emitting model.
2. As a Hyde user, I want `Do It`, `To Cmd Line`, and `To Clip` on project dialogs to
   operate on the same generated command string, so that the dialog footer behaves
   consistently with other Hyde dialogs.
3. As a Hyde user, I want `New Project`, `Load Project`, `Heal Project`, `Save As`,
   and `Save Copy` to keep their current behavior, so that the refactor does not
   regress the working project workflow.
4. As a Hyde developer, I want the file-dialog family to inherit from
   `HydeDialogWidget`, so that file dialogs use Hyde's standard preview-backed dialog
   contract instead of an isolated `QFileDialog` path.
5. As a Hyde developer, I want a reusable `HydeFileWidget`, so that future dialogs
   can share file and directory selection UI instead of rebuilding it.
6. As a Hyde developer, I want `HydeFileWidget` to support both directory and file
   targets, so that future consumers are not limited to `.hy` project directories.
7. As a Hyde developer, I want `HydeFileWidget` to support allowed suffixes or file
   filters, so that future dialogs can constrain selectable image or data formats.
8. As a Hyde developer, I want the reusable chooser to keep the non-native Qt file
   browser behavior, so that the refactor reuses the existing working chooser engine
   instead of rebuilding a custom browser.
9. As a Hyde developer, I want generic file-target rules to be declarative, so that
   future dialogs can configure the chooser without passing arbitrary callback logic.
10. As a Hyde developer, I want common file-dialog behavior to live in the shared
    base widget module, so that future plugins do not import generic chooser
    infrastructure from the project-file plugin.
11. As a Hyde developer, I want `HydeFileDialog` to offer optional overwrite
    confirmation, so that dialogs with save-like behavior can opt into shared
    confirmation logic without duplicating it.
12. As a Hyde developer, I want operation-specific rules such as copy-target
    restrictions to stay in concrete dialogs, so that the shared file family remains
    neutral and reusable.
13. As a Hyde user, I want project dialogs to keep hidden execution as the default
    `Do It` behavior, so that GUI-owned runtime operations continue to use Hyde's
    standard hidden command path.
14. As a Hyde user, I want the visible-terminal route to remain optional, so that I
    can still inspect or reuse the generated command when I explicitly choose `To Cmd
    Line`.
15. As a Hyde developer, I want `Save` to remain a direct hidden dispatch with no
    chooser dialog, so that the refactor only touches target-selecting actions.
16. As a Hyde tester, I want behavior-focused tests around preview, validation,
    dispatch, and shared overwrite confirmation, so that the refactor is protected by
    user-visible contract tests rather than implementation-shape assertions.

## Implementation Decisions

- Introduce a shared `HydeFileWidget` in the base widget layer rather than keeping
  reusable file-dialog code inside the project-file plugin.
- Introduce a shared `HydeFileDialog` between `HydeDialogWidget` and concrete
  file-targeting dialogs.
- Keep the existing `SimpleCommandState` and `SimpleHydeCommandCodec` as the command
  generation owner for project save/load/new/heal behavior.
- Preserve the embedded non-native Qt chooser behavior as the selection engine.
- Treat the lower preview pane's backing string as the real command payload for
  `Do It`, `To Cmd Line`, and `To Clip`.
- Keep hidden execution as the default `Do It` dispatch mode for file dialogs.
- Keep generic chooser policy declarative: target mode, existence requirements,
  allowed suffixes, allowed name filters, button labels, and initial path policy
  should come from dialog-owned configuration rather than ad hoc validator callbacks.
- Keep generic validity checks in the shared file family and keep operation-specific
  rules in concrete dialogs.
- Offer overwrite confirmation from the shared file-dialog base as an optional policy,
  rather than requiring each concrete save-like dialog to reimplement it.
- Keep same-target semantic decisions such as `Save As` degenerating to plain `Save`
  and `Save Copy` rejecting the current project target in the concrete dialogs.
- Leave plain `Save` as a direct hidden command dispatch with no chooser UI.
- Preserve suggested-path behavior for project dialogs while letting future file
  dialogs provide different defaults and filters.

## Testing Decisions

- Good tests should verify external behavior: selected-target validation, preview
  generation, footer enablement, hidden dispatch, optional visible command emission,
  overwrite confirmation, and operation-specific exceptions.
- Tests should avoid asserting incidental helper composition, internal signal wiring,
  or duplicated knowledge of how the chooser widget is embedded.
- The shared file-dialog family should be tested through behavior that a user or
  caller can observe: accepted or rejected targets, preview text, and dispatched
  command strings.
- The refactored project dialogs should be tested against the existing project command
  contracts for New, Load, Heal, Save As, and Save Copy.
- Prior art should come from the existing file dialog plugin tests plus the current
  `HydeDialogWidget`-style dialog tests in the codebase, using the same bias toward
  payload and dispatch behavior over internal call ordering.

## Out of Scope

- Replacing Qt's chooser engine with a custom Hyde-built file browser.
- Changing the public Hyde command surface for project save/load/new/heal.
- Pulling plain `Save` into a dialog.
- Adding migration shims for the old file-dialog implementation shape.
- Designing the full data import or figure export dialogs in this pass.
- Broad changes to project persistence semantics, status-bar progress behavior, or
  kernel runtime ownership.

## Further Notes

- This work is intentionally a shared-family refactor, not a project-command redesign.
- The first reuse target after the project dialogs is expected to need file-type
  filtering for image outputs, so suffix and name-filter support should be treated as
  part of the initial shared contract rather than deferred.
- The base widget placement should keep the shared file-dialog family close to
  `HydeDialog` and `HydeDialogWidget`, matching Hyde's documented widget hierarchy.
