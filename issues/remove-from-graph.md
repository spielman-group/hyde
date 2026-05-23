## Problem Statement

Hyde has first-class figure editing for trace appearance, axis editing, and attached
Curve Fit display updates, but it does not yet provide a Hyde-native `Remove from
Graph` workflow for removing existing supported traces from an active first-class
figure. Users can inspect and edit traces, but they cannot remove one or more traces
through the same bounded command-driven figure-edit path. The current figure-dialog
family also lacks a shared object-oriented base for figure-specific dialog behavior,
which creates duplication across figure dialogs and makes future figure-edit surfaces
harder to grow coherently.

## Solution

Add a dedicated Hyde-native modal `Remove from Graph` dialog for the active
first-class figure. The dialog will list supported removable traces, support arbitrary
multi-selection, support a fully implemented regex text filter, and show the canonical
matplotlib patch command block in the lower read-only pane. `Do It` will execute that
same command block immediately through Hyde's existing hidden figure-edit command path,
`To Cmd Line` will emit the same visible command, and `To Clip` will copy the same
text. The dialog will be introduced as a standalone figure dialog plugin and will also
establish a shared `HydeFigureDialogWidget` base so existing figure-working dialogs
can migrate to one object-oriented family for figure session access, shared supported
trace list behavior, and shared figure-patch execution behavior.

## User Stories

1. As a Hyde user, I want a `Remove from Graph...` action in the active `Figure` menu,
   so that I can remove plotted traces through the same figure workflow as other
   first-class figure edits.
2. As a Hyde user, I want `Remove from Graph...` to appear as the first entry in the
   `Figure` menu, so that the action is easy to find.
3. As a Hyde user, I want the dialog to operate on the active first-class figure only,
   so that removal always targets the figure I am currently editing.
4. As a Hyde user, I want the dialog to be modal, so that the removal workflow is
   explicit and bounded.
5. As a Hyde user, I want the dialog to open even when there are no removable traces,
   so that the behavior stays consistent with existing figure-edit dialogs.
6. As a Hyde user, I want the dialog to show supported removable traces from the
   active figure, so that I can choose exactly what to remove.
7. As a Hyde user, I want the initial implementation to focus on supported line
   traces, so that the feature lands on Hyde's current supported figure IR.
8. As a Hyde user, I want arbitrary multi-selection in the trace list, so that I can
   remove several traces in one operation.
9. As a Hyde user, I want the dialog to open with no initial selection, so that I must
   choose the traces I intend to remove.
10. As a Hyde user, I want trace rows to be text-only, so that the interface stays
    simple and readable.
11. As a Hyde user, I want a fully implemented text filter, so that I can narrow a
    long trace list quickly.
12. As a Hyde user, I want the text filter to use standard regex syntax directly, so
    that I can use normal regex patterns without Hyde-specific matching rules.
13. As a Hyde user, I want the filter to update live as I type when the regex is
    valid, so that narrowing the list feels immediate.
14. As a Hyde user, I want an invalid regex to show an error without changing the
    current filtered list, so that a typo does not unexpectedly change my working
    selection context.
15. As a Hyde user, I want hidden selections to be dropped when the filter removes
    them from view, so that the actionable selection always matches the visible list.
16. As a Hyde user, I want the lower pane to show the exact command Hyde will use when
    the selection is valid, so that I can review the true removal command before
    committing it.
17. As a Hyde user, I want the lower pane to switch to validation or error text when
    the state is invalid, so that I understand why the dialog cannot currently act.
18. As a Hyde user, I want `Do It` to execute immediately without an extra confirmation
    prompt, so that the modal dialog itself remains the confirmation surface.
19. As a Hyde user, I want successful `Do It` to close the dialog, so that the dialog
    follows Hyde's standard dialog-widget contract.
20. As a Hyde user, I want `To Cmd Line` to send the exact same command block shown in
    the lower pane, so that visible execution matches what I reviewed.
21. As a Hyde user, I want `To Clip` to copy the exact same text shown in the lower
    pane, so that copying and pasting preserve the reviewed command.
22. As a Hyde user, I want removal to update the authoritative live kernel figure, so
    that the GUI never becomes the owner of scientific figure state.
23. As a Hyde user, I want removal to flow through the same bounded figure patch
    command model used by other figure dialogs, so that figure editing stays on one
    authoritative path.
24. As a Hyde user, I want the emitted removal patch to be deterministic, so that
    multi-trace removal produces stable command output.
25. As a Hyde developer, I want trace removal to be represented as a first-class
    figure-session mutation rather than dialog-local IR dict editing, so that figure
    dialogs stay inside the existing figure edit boundary.
26. As a Hyde developer, I want the figure-dialog family to share one dedicated base
    widget for figure behavior, so that figure dialogs reuse behavior through
    inheritance instead of free helper functions.
27. As a Hyde developer, I want the shared figure-dialog base to support optional
    figure attachment, so that both attached and unattached figure-capable dialogs can
    inherit the same base.
28. As a Hyde developer, I want the shared figure-dialog base to own the common
    figure-patch lifecycle, so that trace, axis, curve-fit, and remove-from-graph
    dialogs stop duplicating command-generation and patch-dispatch behavior.
29. As a Hyde developer, I want the shared figure-dialog base to own the canonical
    supported-trace list behavior, so that figure dialogs stop inventing separate
    trace row loading and filtering rules.
30. As a Hyde developer, I want migrated figure dialogs to use one canonical trace-row
    representation, so that the figure-dialog family stays consistent.
31. As a Hyde tester, I want tests to verify observable dialog behavior rather than
    internal helper wiring, so that implementation cleanup does not force test churn.
32. As a Hyde tester, I want tests around command preview, filtering, and committed
    removal behavior, so that regressions in the actual user contract are caught.

## Implementation Decisions

- Add a standalone `Remove from Graph` figure dialog plugin rather than folding the
  feature into the existing figure-control dialog plugin.
- Place `Remove from Graph...` as the first contributed action in the active `Figure`
  menu.
- Keep the initial deployment trace-only. The PRD does not include an object-type
  selector, image-plot removal, or contour-plot removal.
- Use the existing `HydeDialogWidget` footer behavior directly: the lower pane is the
  read-only source of truth for the current command string or validation text, `Do It`
  executes the current command string, `To Cmd Line` emits that same string visibly,
  and `To Clip` copies that same string.
- Treat `Do It` as immediate commit with no secondary confirmation prompt.
- Close the dialog on successful `Do It` using the standard dialog-widget success path.
- Add a shared `HydeFigureDialogWidget` base for figure-working dialogs. This base is
  the required object-oriented reuse mechanism for the figure-dialog family.
- Migrate the existing figure-working dialogs into the new shared base as part of this
  work, not as deferred cleanup.
- Allow `HydeFigureDialogWidget` to be constructed with or without a figure context so
  attached and unattached figure-capable dialogs can share the same base.
- Move all reasonable shared figure-dialog behavior into `HydeFigureDialogWidget`,
  including figure-context access, optional figure-session setup, shared supported
  trace-list behavior, canonical trace-row rendering, regex filter application, figure
  patch generation, hidden patch execution, figure-patch logging, applied-state
  advancement, and rollback to the opening effective state.
- Do not provide a row-text override hook. The shared figure-dialog base owns one
  canonical trace-row representation for migrated figure dialogs.
- Add a first-class figure-session removal mutation for removing one or more traces by
  stable trace ID. The dialog must mutate figure state through the figure session
  boundary rather than editing figure IR dictionaries directly.
- Generate the removal preview and commit command through Hyde's canonical figure patch
  mechanism against the active first-class figure. Do not introduce a second
  figure-edit transport.
- Use stable Hyde trace IDs as the dialog's authoritative local identifiers.
- Support arbitrary multi-selection in the removal list.
- Open the dialog with no trace selected.
- Use a text-only list presentation.
- Implement full regex filtering using standard regex syntax with no Hyde-specific
  matching behavior.
- Apply filtering live on text change only when the regex is valid.
- When the regex is invalid, show an error state and leave the current filtered list
  unchanged.
- Drop selections that become hidden by filtering.
- Keep the menu action and dialog available even when the active figure currently has
  no supported removable traces.
- Prefer the simplest working removal order and maintain deterministic command output.
- Treat the PRD's product decisions as replacing the older remove-from-graph spec draft
  anywhere they differ, especially around the removed object-type selector shell.

## Testing Decisions

- Tests should verify externally visible behavior and architectural contracts, not
  incidental call order, helper extraction, or mock interaction shape.
- A good test for this work proves what the running product does: what appears in the
  list, how filtering behaves, what the lower pane shows, when actions are enabled,
  what command is emitted, and what removal does to the active first-class figure.
- Test the standalone remove-from-graph dialog behavior, including empty-list behavior,
  no-initial-selection behavior, multi-selection, valid regex filtering, invalid regex
  handling, hidden-selection dropping, preview generation, `To Cmd Line`, `To Clip`,
  and successful `Do It` close behavior.
- Test the new figure-session removal mutation as a behavioral contract over supported
  figure state rather than as a dict-manipulation implementation detail.
- Test `HydeFigureDialogWidget` through the concrete figure dialogs that use it rather
  than through isolated implementation-only unit tests where possible.
- Add migration coverage for existing figure dialogs only where the shared base changes
  their observable behavior or guarantees.
- Reuse existing Hyde figure-dialog and first-class figure testing patterns as prior
  art, especially tests that already exercise figure patch preview, command dispatch,
  and figure-session-backed dialog behavior.

## Out of Scope

- Removing image plots in this implementation.
- Removing contour plots or contour subtraces in this implementation.
- Any object-type selector UI for the first pass.
- Automatic axis removal or automatic empty-figure cleanup after the last trace is
  removed.
- Support for non-first-class figures.
- Direct canvas hit-testing or click-to-remove workflows.
- Any second figure-edit transport outside Hyde's existing figure patch command path.
- Speculative abstraction beyond the shared figure-dialog base and the first-class
  figure-session removal mutation required for this work.

## Further Notes

- This work has two intentional outcomes: user-facing remove-from-graph behavior and
  a stronger object-oriented foundation for the figure-dialog family.
- The figure-dialog family standard is inheritance-based reuse through
  `HydeFigureDialogWidget`, not free helper functions.
- When this work is later decomposed into implementation issues, follow-up issues can
  be added from this PRD rather than reopening the design questions already settled
  here.
