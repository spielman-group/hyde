# Curve Fit Follow-Up Issues

## Checklist

- [X] Issue 1: Unify Curve Fit command preview, clipboard export, and `Do It` execution
- [X] Issue 2: Collapse Curve Fit dialog execution and attached-display ownership
- [X] Issue 3: Split fit-function catalog flow from macro-registry flow
- [X] Issue 4: Simplify `New Fit Function...` scaffolding and Curve Fit catalog ownership
- [X] Issue 5: Merge duplicated coefficient lowering and trim repeated test structure
- [X] Issue 6: Align top-level Hyde docs and shared helper boundaries with the implemented system

## Issue 1: Unify Curve Fit command preview, clipboard export, and `Do It` execution

- **Title**: Make one authoritative Curve Fit command path
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: 24, 25, 28, 29

### What to build

Collapse the current split between the command shown in the dialog and the command
actually executed on `Do It`. The command preview, `To Clip`, and explicit `Do It`
execution should describe one authoritative commit action rather than two different
paths. Fit-report emission should be part of that one contract rather than being bolted
on through a second visible command path.

This slice is about command truthfulness and execution clarity, not broader dialog
orchestration.

### Acceptance criteria

- [ ] The command shown in `Commands` preview matches the authoritative explicit commit action.
- [ ] `To Clip` exports that same authoritative explicit commit action.
- [ ] `Do It` uses the same command contract rather than a different hidden command plus a second visible follow-up.
- [ ] Fit-report emission is handled through the same explicit commit contract.
- [ ] Behavior tests prove the preview/clipboard/`Do It` agreement through observable outputs rather than helper call order.

### TDD focus

- First failing behavior: the preview text and the explicit `Do It` behavior describe the same command contract.
- Follow-up behavior: `To Clip` exports the same explicit command the dialog will commit.
- Final behavior in this slice: successful explicit execution and fit-report emission still work without a second ad hoc command path.

## Issue 2: Collapse Curve Fit dialog execution and attached-display ownership

- **Title**: Reduce Curve Fit to one preview path and one commit path
- **Type**: AFK
- **Blocked by**: Issue 1
- **User stories covered**: 21, 22, 23, 26, 27, 28, 29, 31, 32, 33, 34, 35

### What to build

Simplify the Curve Fit dialog so it has one clear preview-only path and one clear
commit path. Today, hidden execution, preview-object sync, attached-display sync,
rollback, live rerun, and suppressed `Do It` behavior are spread across too many
partially-overlapping methods. Collapse that to the smallest clear orchestration that
still preserves guessed preview behavior while the dialog is open, authoritative result
ownership after `Do It`, and revert-on-cancel behavior.

This slice should not change the settled user-facing behavior. It should only make the
ownership model smaller and clearer.

### Acceptance criteria

- [ ] The dialog has one clear preview-only path for guessed-function preview updates.
- [ ] The dialog has one clear commit path for real fit execution and accepted display re-rooting.
- [ ] Live rerun, suppressed `Do It`, failure retention, and cancel/revert behavior still match the current settled contract.
- [ ] Attached fit/residual preview and accepted result-rooted displays still behave the same from the user's perspective.
- [ ] Behavior tests cover the user-visible contract without mirroring internal helper choreography.

### TDD focus

- First failing behavior: attached guessed preview still updates while editing, but explicit commit still produces the real fit result and accepted display.
- Follow-up behavior: live failure and cancel/revert still preserve the last successful outputs and opening display state.
- Final behavior in this slice: the same public behavior survives after collapsing the internal execution/display split.

## Issue 3: Split fit-function catalog flow from macro-registry flow

- **Title**: Give fit functions a dedicated catalog path
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: 6, 9, 36

### What to build

Stop treating fit functions as just another macro-registry kind. Keep a small shared
registry path for table and figure recreation macros, and give fit functions their own
explicit catalog path in the same module. The fit-function path should directly own the
behavior that is unique to it: callable references, source text, rejected entries, and
registration-order preservation.

This slice is about clarifying the architecture, not changing chooser contents or
signature rules.

### Acceptance criteria

- [ ] Table/figure recreation macros continue to use one small macro-registry path.
- [ ] Fit functions use a dedicated catalog path rather than protocol flags that emulate a special registry kind.
- [ ] Fit-function discovery, rejection, ordering, callable references, and source-text behavior remain unchanged.
- [ ] Publishing and clearing still work for all three public surfaces without broad regression.
- [ ] Behavior tests verify the preserved catalog behavior through the public API.

### TDD focus

- First failing behavior: fit-function catalog behavior is preserved after the registry split.
- Follow-up behavior: table and figure macro behavior is unchanged.
- Final behavior in this slice: the module no longer needs generic flags just to make fit functions fit the macro framework.

## Issue 4: Simplify `New Fit Function...` scaffolding and Curve Fit catalog ownership

- **Title**: Decouple fit-function scaffolding from window-macro storage
- **Type**: AFK
- **Blocked by**: Issue 3
- **User stories covered**: 6, 7, 8

### What to build

Simplify the `New Fit Function...` path so it no longer depends on window-macro store
machinery that exists for table/figure persistence. The narrow behavior needed here is:
validate the name, reject real conflicts, append one minimal scaffold to
`procedures/__init__.py`, reload, refresh the fit-function catalog, and select the new
function. While doing that, collapse the extra state split between `Plugin` and
`CurveFitCatalogService` so catalog ownership is clearer.

This slice should leave the user-facing scaffold behavior intact while removing
unrelated storage machinery from the path.

### Acceptance criteria

- [ ] `New Fit Function...` still appends one minimal valid scaffold to `procedures/__init__.py`.
- [ ] Real name conflicts are still rejected with clear user-facing feedback.
- [ ] Reload still keeps the dialog open and selects the new fit function.
- [ ] The Curve Fit catalog state has one clearer owner rather than being copied between service and plugin.
- [ ] Behavior tests cover scaffold/reload/select behavior through the dialog and catalog service surfaces.

### TDD focus

- First failing behavior: creating a new fit function still yields one new selectable function after reload.
- Follow-up behavior: name conflicts still fail cleanly.
- Final behavior in this slice: the same scaffold workflow survives without window-macro storage machinery and plugin/service state copying.

## Issue 5: Merge duplicated coefficient lowering and trim repeated test structure

- **Title**: Keep coefficient lowering and tests on one authoritative path
- **Type**: AFK
- **Blocked by**: Issue 2
- **User stories covered**: 16, 17, 18, 24, 26, 27

### What to build

Reduce duplication between guessed-preview coefficient lowering and real-fit lowering.
Today those paths parse and lower parameter state separately, which risks drift on
expression-owned rows and validation semantics. Move to one coefficient-lowering model
that feeds both preview and real-fit generation. While doing that, trim repeated test
structure so registry-level facts stay in registry tests and dialog tests focus on
dialog-visible behavior.

This slice should preserve behavior while removing drift risk and reducing test noise.

### Acceptance criteria

- [ ] One coefficient-lowering representation feeds both guessed preview and real-fit command generation.
- [ ] Expression-owned parameters and missing/invalid-value rules behave the same in preview and real-fit paths.
- [ ] Repeated registry/content assertions are removed from dialog tests when those facts are already proven at the registry layer.
- [ ] Dialog tests still prove user-visible behavior, especially preview generation and execution semantics.
- [ ] The targeted test suite becomes smaller or clearer overall rather than merely shifting assertions around.

### TDD focus

- First failing behavior: one coefficient edit changes preview and real-fit lowering consistently.
- Follow-up behavior: expression-owned rows behave identically across preview and commit paths.
- Final behavior in this slice: tests still prove the contract with less duplicated structure.

## Issue 6: Align top-level Hyde docs and shared helper boundaries with the implemented system

- **Title**: Reconcile architecture docs and shared helper ownership
- **Type**: AFK
- **Blocked by**: Issue 2, Issue 3
- **User stories covered**: None directly - architectural/documentation cleanup

### What to build

Update Hyde's top-level architecture/status docs so they describe the present-tense
system after the Curve Fit branch work. At the same time, revisit shared helper
boundaries that are now muddier because of the branch, especially
`active_interactive_window()`, and move those helpers back toward their smallest clear
responsibility.

This slice is intentionally late because it should document and clean up the final
architecture after the more substantive simplifications land.

### Acceptance criteria

- [ ] `ARCHITECTURE.md`, `PLAN.md`, and `STATUS.md` no longer lag the implemented Curve Fit and `@hyde.fit_function` behavior.
- [ ] Shared helper responsibilities are documented and simplified where they now carry feature-specific policy.
- [ ] Curve Fit docs, top-level Hyde docs, and code-level helper boundaries no longer point future agents in conflicting directions.
- [ ] Any resulting tests or doc checks remain narrow and behavior-focused.

### TDD focus

- First failing behavior: a fresh reader of the top-level docs reaches the same present-tense understanding as the implemented system.
- Follow-up behavior: shared helper boundaries are simpler and less policy-laden.
- Final behavior in this slice: top-level Hyde docs and helper ownership no longer conflict with the settled Curve Fit implementation.
