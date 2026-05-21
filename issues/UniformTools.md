# Uniform Tool Dialogs PRD

## Problem Statement

Hyde's tool dialogs do not currently present one consistent product language.

Some dialogs already resemble the intended Igor-style tool surface, with a lower
read-only text pane and a footer row built around `Do It`, `To Cmd Line`, `To Clip`,
`Help`, and `Cancel`. Other dialogs use partial versions of that pattern, and others
still use plain `QDialogButtonBox` layouts or bespoke footer arrangements.

This inconsistency has two concrete costs:

- users do not get one predictable dialog workflow across Hyde tools
- developers duplicate layout, preview, clipboard, help, and button wiring in each
  dialog implementation

Hyde needs one default tool-dialog shell for all dialogs that belong to the Igor-style
tool family, while preserving a separate path for prompt-like dialogs that do not fit
that contract.

## Solution

Hyde adopts one strict default shell for tool dialogs.

`HydeDialogWidget` becomes the standard Igor-style tool-dialog base. Every dialog in
that family uses the same shell:

- dialog-specific content in the upper region
- a built-in lower read-only text pane
- a fixed footer row with `Do It`, `To Cmd Line`, `To Clip` on the left and `Help`,
  `Cancel` on the right

Dialogs no longer build their own bottom sections. Instead, each dialog provides one
canonical derived text payload to the shared shell and ports its existing button
behavior into standard base-class hooks.

Prompt-like dialogs that do not belong to this tool family move to a separate
`HydePromptDialog` base that keeps Hyde convenience behavior without inheriting the
tool-dialog shell contract.

In the first implementation:

- all existing tool dialogs that currently inherit `HydeDialogWidget` migrate to the
  shared shell
- all dialog-specific `.ui` forms are reduced to upper-content-only layouts and stop
  defining their own lower preview/footer material
- `SaveWindowDialog` becomes a `HydePromptDialog`
- dialogs that do not currently produce executable visible-terminal commands still show
  canonical derived text, but keep `To Cmd Line` disabled

## User Stories

1. As a Hyde user, I want every tool dialog to share the same overall layout, so that
   I do not have to relearn the bottom controls for each feature.
2. As a Hyde user, I want the bottom text pane to always appear in the same place, so
   that I know where to inspect the dialog's generated output.
3. As a Hyde user, I want the bottom text pane to be read-only, so that the dialog's
   real controls remain the authoritative way to change behavior.
4. As a Hyde user, I want `Do It`, `To Cmd Line`, `To Clip`, `Help`, and `Cancel` to
   always appear in the same order, so that the footer feels like one coherent tool
   family.
5. As a Hyde user, I want buttons that are not active for a particular dialog to stay
   visible but disabled, so that the dialog family remains visually consistent.
6. As a Hyde user, I want `To Clip` to always copy the same text I see in the lower
   pane, so that the dialog never exposes competing output paths.
7. As a Hyde user, I want `To Cmd Line` to insert or dispatch the same canonical text
   shown in the lower pane when that action is supported, so that the visible terminal
   path matches the preview.
8. As a Hyde user, I want dialogs that cannot yet produce executable command-line
   output to disable `To Cmd Line`, so that Hyde does not imply a broken capability.
9. As a Hyde user, I want new table creation to use the same standard shell as other
   Hyde tools, so that simple creation dialogs still feel like part of the same
   product.
10. As a Hyde user, I want new figure creation to use the same standard shell, so that
    creating and editing figures share one visual language.
11. As a Hyde user, I want Curve Fit to use the same standard shell, so that its
    preview and footer controls align with the rest of Hyde.
12. As a Hyde user, I want Modify Axis to use the standard shell without bespoke
    footer code, so that it behaves like the rest of the tool family.
13. As a Hyde user, I want Modify Data Appearance to move from a simple `Apply/Cancel`
    dialog to the standard shell, so that trace editing no longer feels like a
    different application.
14. As a Hyde user, I want Help to always live in the same footer position, so that I
    can discover it consistently.
15. As a Hyde user, I want prompt-style confirmation dialogs to remain simple when they
    are not true tool dialogs, so that Hyde does not force an inappropriate shell onto
    save prompts.
16. As a Hyde developer, I want one base dialog shell instead of repeated footer and
    preview layouts, so that new tool dialogs stop copying boilerplate.
17. As a Hyde developer, I want one base dialog hook contract for the five footer
    buttons, so that behavior is standardized as well as layout.
18. As a Hyde developer, I want dialog-specific `.ui` files to contain only their
    upper content region, so that they can be edited in Qt Designer without duplicating
    the common footer.
19. As a Hyde developer, I want each tool dialog to publish one canonical derived text
    payload, so that preview, clipboard, and command-line export all reference the
    same source.
20. As a Hyde developer, I want first-class figure dialogs to keep their semantic
    `comm` execution path for real edits, so that this UI unification does not force a
    premature architecture rewrite.
21. As a Hyde developer, I want figure dialogs to show the canonical lowered text even
    while `To Cmd Line` is disabled, so that the user-facing text path still becomes
    explicit and inspectable.
22. As a Hyde developer, I want prompt dialogs to keep a smaller Hyde-specific base, so
    that service access and UI loading remain convenient without inheriting the tool
    shell.
23. As a Hyde tester, I want the dialog family contract to be observable through widget
    presence, enablement, and button behavior, so that tests can verify the real user
    experience instead of incidental implementation details.
24. As a Hyde maintainer, I want future tool dialogs to inherit the standard shell by
    default, so that the codebase stops drifting back into bespoke dialog layouts.

## Implementation Decisions

- `HydeDialogWidget` becomes the strict default base for Hyde tool dialogs.
- `HydeDialogWidget` loads a dedicated shell `.ui` file rather than requiring each
  dialog to build the common shell in Python.
- The `HydeDialogWidget` shell always contains:
  - an upper content mount area
  - a lower read-only text pane
  - fixed footer buttons `Do It`, `To Cmd Line`, `To Clip`, `Help`, `Cancel`
- Footer widgets remain present for every `HydeDialogWidget`; dialogs may disable them
  but do not hide them.
- The lower text pane is always read-only and is never parsed back into dialog state.
- Every `HydeDialogWidget` subclass must provide one canonical derived text payload.
- The shared shell uses that same payload for:
  - lower-pane display
  - `To Clip`
  - `To Cmd Line` when enabled
- The shared base owns the default button wiring and exposes dialog hooks for:
  - validation and `Do It` behavior
  - canonical text generation / refresh
  - `To Cmd Line`
  - `Help`
- Dialog-specific `.ui` files for existing `HydeDialogWidget` subclasses are revised so
  they define only the upper content region and remove any existing bottom text pane,
  footer buttons, or `QDialogButtonBox`-owned equivalents.
- Existing dialog handlers are ported from local buttons and button boxes onto the new
  base hooks instead of preserving duplicate wiring in each dialog.
- `HydePromptDialog` is introduced as the smaller convenience base for prompt-style
  dialogs that still need Hyde services and UI-loading helpers without the tool shell.
- `SaveWindowDialog` moves from `HydeDialogWidget` to `HydePromptDialog`.
- The migration target for current dialogs is:
  - New Table: standard shell, `To Cmd Line` enabled
  - New Figure: standard shell, `To Cmd Line` enabled
  - Curve Fit: standard shell, `To Cmd Line` disabled for now
  - Modify Axis: standard shell, `To Cmd Line` disabled for now
  - Modify Data Appearance: standard shell, `To Cmd Line` disabled for now
- For first-class figure dialogs, semantic `comm` actions remain the actual edit path
  for now. The canonical text is user-facing output and preview, not the executed edit
  path.
- Longer-term product direction is to make the canonical lowered text for figure tools
  executable as the true update path, with `comm` reserved for live preview behavior,
  but that is explicitly deferred.

## Testing Decisions

- Good tests should verify externally visible dialog behavior and explicit shell
  contracts rather than internal layout-construction details.
- Tests should verify:
  - every `HydeDialogWidget` subclass exposes the standard shell widgets
  - footer button labels and positions remain fixed
  - buttons are disabled rather than hidden when a dialog does not support an action
  - the lower text pane is read-only
  - `To Clip` copies the same canonical text shown in the lower pane
  - `To Cmd Line` enablement matches each dialog's contract
  - `SaveWindowDialog` no longer participates in the `HydeDialogWidget` tool family
- Representative dialog tests should cover migrated dialogs from different product
  categories:
  - a simple creation dialog
  - a figure-edit dialog
  - a prompt dialog
- Tests should assert observable outcomes such as accepted/rejected dialog behavior,
  clipboard contents, text refresh, and enabled/disabled states instead of asserting
  incidental signal order or helper call structure.
- Prior art exists in Hyde's dialog-focused tests and figure-control tests that already
  validate visible behavior and runtime-facing contracts rather than pure widget
  plumbing.

## Out of Scope

- rewriting first-class figure dialogs so their canonical lowered text becomes the real
  execution path
- changing Hyde's semantic figure `comm` architecture in this patch
- redesigning prompt dialogs into the Igor-style tool family
- hiding absent actions instead of disabling them
- making the lower text pane editable
- introducing multiple canonical text outputs per dialog
- changing unrelated tool-window (`HydeToolWidget`) architecture

## Further Notes

- This work is intentionally a full replacement for all current plugins that use
  `HydeDialogWidget`, not a partial pilot.
- The main architectural seam is between tool dialogs and prompt dialogs, not between
  simple dialogs and advanced dialogs.
- The migration is expected to remove duplication in both Qt Designer layouts and
  Python-side button wiring.
