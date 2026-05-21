# Uniform Tool Dialogs Issues

## Checklist

- [ ] Issue 1: Build the shared tool-dialog shell and prompt-dialog split
- [ ] Issue 2: Migrate `NewTableDialog` to the shared `HydeDialogWidget` shell
- [ ] Issue 3: Migrate `NewFigureDialog` to the shared `HydeDialogWidget` shell
- [ ] Issue 4: Migrate `CurveFitDialog` to the shared `HydeDialogWidget` shell
- [ ] Issue 5: Migrate `AxisEditDialog` to the shared `HydeDialogWidget` shell
- [ ] Issue 6: Migrate `TraceAppearanceDialog` to the shared `HydeDialogWidget` shell
- [ ] Issue 7: Move `SaveWindowDialog` to `HydePromptDialog`

## Issue 1

**Title**: Build the shared Hyde tool-dialog shell and prompt-dialog split  
**Type**: AFK  
**Blocked by**: None - can start immediately  
**User stories covered**: 1, 2, 3, 4, 5, 6, 7, 8, 14, 16, 17, 18, 19, 22, 23, 24

## Parent

[Uniform Tool Dialogs PRD](./UniformTools.md)

## What to build

Refactor Hyde's dialog foundations so that `HydeDialogWidget` becomes the strict
Igor-style tool-dialog shell and `HydePromptDialog` becomes the smaller convenience
base for prompt-style dialogs.

The shared `HydeDialogWidget` shell should own:

- an upper content mount area for dialog-specific UI
- a built-in lower read-only text pane
- a fixed footer with `Do It`, `To Cmd Line`, `To Clip` on the left and `Help`,
  `Cancel` on the right
- default button wiring via subclass hooks

The shell contract is strict:

- the footer buttons are always present
- dialogs may disable unsupported actions but do not hide them
- the lower text pane is always read-only
- each tool dialog provides one canonical derived text payload used for display,
  clipboard copy, and command-line export when enabled

Introduce `HydePromptDialog` as the separate small convenience base for non-tool prompt
dialogs that still need Hyde service access and UI loading without the tool-dialog
shell.

## Acceptance criteria

- [ ] `HydeDialogWidget` loads a dedicated shell UI and exposes an upper content mount
      area, lower read-only text pane, and fixed footer buttons.
- [ ] The base class owns default `Do It`, `To Cmd Line`, `To Clip`, `Help`, and
      `Cancel` wiring through overridable hooks rather than requiring each dialog to
      wire those buttons manually.
- [ ] `HydePromptDialog` exists as the small shared base for prompt-style dialogs and
      is separate from the strict tool-dialog shell contract.
- [ ] Tests verify the shared shell's visible contract, including button presence,
      stable placement contract, read-only lower text pane, and disabled-not-hidden
      behavior.

## Issue 2

**Title**: Migrate `NewTableDialog` to the shared `HydeDialogWidget` shell  
**Type**: AFK  
**Blocked by**: Issue 1  
**User stories covered**: 1, 2, 3, 4, 5, 6, 7, 9, 18, 19, 23

## Parent

[Uniform Tool Dialogs PRD](./UniformTools.md)

## What to build

Convert `NewTableDialog` to the shared `HydeDialogWidget` shell.

Its dialog-specific UI should become upper-content-only, with the old local bottom
material removed from the dialog form. The dialog should provide one canonical derived
command text for table creation, display that text in the shared lower pane, enable
`To Clip`, and enable `To Cmd Line` because the derived text is executable.

Port the existing `Do It` behavior and state synchronization onto the new shell hooks
instead of preserving `QDialogButtonBox`-specific wiring.

## Acceptance criteria

- [ ] The `NewTableDialog`-specific UI no longer defines its own bottom button or
      preview section and mounts only its upper content into the shared shell.
- [ ] The shared lower pane shows the canonical table-creation text derived from the
      current dialog state.
- [ ] `To Clip` copies that same canonical text and `To Cmd Line` is enabled for this
      dialog.
- [ ] Tests verify observable `NewTableDialog` behavior through the shared shell,
      including canonical text refresh and command-related button enablement.

## Issue 3

**Title**: Migrate `NewFigureDialog` to the shared `HydeDialogWidget` shell  
**Type**: AFK  
**Blocked by**: Issue 1  
**User stories covered**: 1, 2, 3, 4, 5, 6, 7, 10, 18, 19, 23

## Parent

[Uniform Tool Dialogs PRD](./UniformTools.md)

## What to build

Convert `NewFigureDialog` to the shared `HydeDialogWidget` shell.

Its dialog-specific UI should become upper-content-only, with its existing bottom
button-box material removed from the form. The dialog should produce one canonical
derived figure-creation text payload, surface that in the shared lower pane, enable
`To Clip`, and enable `To Cmd Line` because the derived text is executable.

Port the current accept/reject and state-refresh logic onto the shared shell hooks.

## Acceptance criteria

- [ ] The `NewFigureDialog` form no longer includes its own bottom button section and
      mounts only its upper content into the shared shell.
- [ ] The shared lower pane shows the canonical figure-creation text derived from the
      current dialog state.
- [ ] `To Clip` copies that same canonical text and `To Cmd Line` is enabled for this
      dialog.
- [ ] Tests verify the migrated dialog's observable shell behavior and canonical text
      contract.

## Issue 4

**Title**: Migrate `CurveFitDialog` to the shared `HydeDialogWidget` shell  
**Type**: AFK  
**Blocked by**: Issue 1  
**User stories covered**: 1, 2, 3, 4, 5, 6, 8, 11, 18, 19, 23

## Parent

[Uniform Tool Dialogs PRD](./UniformTools.md)

## What to build

Convert `CurveFitDialog` to the shared `HydeDialogWidget` shell.

The dialog currently carries some of the intended pattern already, but its preview,
status strip, and footer behavior need to be normalized onto the base shell. The
dialog-specific content should remain in the upper region only. The dialog must expose
one canonical derived text payload to the shared lower pane and `To Clip`.

`To Cmd Line` stays present but disabled for now because the displayed text is not yet
the truly executable update path for the running fit surface.

## Acceptance criteria

- [ ] `CurveFitDialog` stops building its own local preview/footer structure and uses
      the shared shell for the lower pane and footer.
- [ ] The dialog publishes one canonical derived text payload to the shared lower pane
      and `To Clip`.
- [ ] `To Cmd Line` remains visible but disabled for this dialog until the product
      contract changes.
- [ ] Tests verify the migrated dialog's shared-shell behavior, including disabled
      `To Cmd Line` and canonical text refresh.

## Issue 5

**Title**: Migrate `AxisEditDialog` to the shared `HydeDialogWidget` shell  
**Type**: AFK  
**Blocked by**: Issue 1  
**User stories covered**: 1, 2, 3, 4, 5, 6, 8, 12, 18, 19, 20, 21, 23

## Parent

[Uniform Tool Dialogs PRD](./UniformTools.md)

## What to build

Convert `AxisEditDialog` to the shared `HydeDialogWidget` shell.

The dialog already resembles the intended pattern, but its bespoke preview/footer
construction should be removed and replaced with the shared shell. The dialog-specific
UI should remain only in the upper content region. The dialog must continue to expose
canonical lowered text for display and clipboard copy.

`To Cmd Line` stays visible but disabled because first-class figure edits still run
through semantic `comm` actions for actual execution in this patch.

## Acceptance criteria

- [ ] `AxisEditDialog` no longer constructs its own lower preview/footer widgets and
      relies on the shared shell instead.
- [ ] The canonical lowered text for the current axis draft appears in the shared lower
      pane and is copied by `To Clip`.
- [ ] `To Cmd Line` remains present but disabled for this dialog.
- [ ] Tests verify the migrated dialog's shared-shell behavior and figure-edit
      constraints through observable outcomes.

## Issue 6

**Title**: Migrate `TraceAppearanceDialog` to the shared `HydeDialogWidget` shell  
**Type**: AFK  
**Blocked by**: Issue 1  
**User stories covered**: 1, 2, 3, 4, 5, 6, 8, 13, 18, 19, 20, 21, 23

## Parent

[Uniform Tool Dialogs PRD](./UniformTools.md)

## What to build

Promote `TraceAppearanceDialog` from its current simpler `Apply/Cancel` layout into
the full shared `HydeDialogWidget` shell.

The dialog-specific trace-selection and style-editing UI should become the upper
content region only. The dialog must provide one canonical derived text payload to the
shared lower pane and `To Clip`, while preserving its existing figure-edit semantics
for actual execution.

`To Cmd Line` stays visible but disabled for now because the canonical displayed text
is not yet the executable path for figure updates.

## Acceptance criteria

- [ ] `TraceAppearanceDialog` moves from its local `Apply/Cancel` footer to the full
      shared `HydeDialogWidget` shell.
- [ ] The dialog-specific UI defines only the upper content region and no longer owns a
      local bottom section.
- [ ] The shared lower pane displays one canonical derived text payload and `To Cmd Line`
      is visible but disabled.
- [ ] Tests verify the new shared-shell behavior and preserve observable figure-edit
      semantics.

## Issue 7

**Title**: Move `SaveWindowDialog` to `HydePromptDialog`  
**Type**: AFK  
**Blocked by**: Issue 1  
**User stories covered**: 15, 22, 23

## Parent

[Uniform Tool Dialogs PRD](./UniformTools.md)

## What to build

Detach `SaveWindowDialog` from `HydeDialogWidget` and move it to `HydePromptDialog`.

`SaveWindowDialog` is a prompt-style save/no-save/cancel workflow rather than an
Igor-style tool dialog, so it should not inherit the standard lower-pane and fixed
five-button footer contract. It should retain its prompt semantics while continuing to
benefit from Hyde's shared dialog conveniences through the new prompt base.

## Acceptance criteria

- [ ] `SaveWindowDialog` no longer inherits from `HydeDialogWidget` and instead uses
      `HydePromptDialog`.
- [ ] `SaveWindowDialog` keeps its prompt-specific save / no-save / help / cancel
      behavior without inheriting the tool-dialog shell.
- [ ] Tests verify that `SaveWindowDialog` remains a prompt workflow and no longer
      participates in the `HydeDialogWidget` shell contract.
- [ ] The separation between tool dialogs and prompt dialogs is explicit and stable in
      the dialog base-class hierarchy.
