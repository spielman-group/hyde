# Hyde Dialog Footer Consolidation Work Items

## Checklist

- [x] Slice 1: Establish the `HydeDialogWidget` footer contract
- [x] Slice 2: Add shared help-file behavior to `HydeDialogWidget`
- [x] Slice 3: Move creation dialogs onto base-owned `Do It` dispatch
- [x] Slice 4: Route figure-control dialogs through the shared `Do It` dispatch path
- [x] Slice 5: Normalize Curve Fit as an explicit `Do It` exception over the same footer contract

## Notes

- This work targets `HydeDialogWidget`, not `HydeToolWidget`. The five-button footer
  lives on the dialog shell, and direct `HydeToolWidget` subclasses do not use it.
- `To Cmd Line` and `To Clip` are already base-owned in shape. The remaining work is
  to remove broken service wiring and secret second dispatch paths around them.
- `Cancel` remains dialog-local. This consolidation does not try to force a shared
  cancel policy across unrelated dialogs.
- The intended end state is:
  - one shared footer contract on `HydeDialogWidget`
  - one canonical preview / `To Cmd Line` / `To Clip` payload contract
  - one base-owned dispatch primitive for `Do It`
  - subclasses allowed to add local validation or bookkeeping around that primitive
- Curve Fit is the only current dialog family whose preview text is not always the
  executable `Do It` payload. The plan keeps that as an explicit supported exception
  rather than forcing the wrong abstraction onto the base class.

## Slice 1: Establish The `HydeDialogWidget` Footer Contract

### Type

`AFK`

### What to build

Clarify and harden the ownership boundary for the five-footer-button shell on
`HydeDialogWidget`.

This slice should make the base contract explicit:

- `canonical_text_payload()` is the shared preview / `To Cmd Line` / `To Clip`
  contract
- the base class owns the footer wiring and refresh behavior
- `Do It` has a shared base dispatch primitive instead of ad hoc kernel dispatch
  scattered across dialogs
- `Cancel` remains local

The goal is to remove ambiguity about whether this behavior belongs on
`HydeToolWidget` or on dialog subclasses.

### Acceptance criteria

- [ ] `HydeDialogWidget` is documented and tested as the owner of the five-button footer contract.
- [ ] The base class exposes one small shared dispatch primitive for `Do It` rather than requiring every subclass to open-code the same kernel dispatch shape.
- [ ] Existing footer behavior tests describe the intended present-tense contract rather than the current accidental implementation split.
- [ ] No direct `HydeToolWidget` subclass is pulled into this footer abstraction.

### Blocked by

None - can start immediately

### User stories covered

- Footer ownership clarification from the dialog-button consolidation discussion
- Shared command-routing behavior for `Do It`, `To Cmd Line`, and `To Clip`

## Slice 2: Add Shared Help-File Behavior To `HydeDialogWidget`

### Type

`AFK`

### What to build

Make `Help` a real base-owned behavior by adding a `help_filename` contract on
`HydeDialogWidget`.

When `help_filename` is unset, the button remains disabled. When it is set, the base
class resolves the file relative to the owning module and opens it. Subclasses should
not need to reimplement this default file-opening behavior.

This slice should stay narrow: shared file-backed help only, not a broader help
system.

### Acceptance criteria

- [ ] `HydeDialogWidget` has a `help_filename` contract with a `None` default.
- [ ] Base `can_show_help()` enables the button only when a valid help file is declared.
- [ ] Base `handle_help()` opens the declared file without requiring subclass overrides.
- [ ] Tests verify both the default disabled state and one real file-backed help path.

### Blocked by

- Slice 1: Establish the `HydeDialogWidget` footer contract

### User stories covered

- Shared footer help behavior from the dialog-button consolidation discussion

## Slice 3: Move Creation Dialogs Onto Base-Owned `Do It` Dispatch

### Type

`AFK`

### What to build

Remove the current split where `NewTableDialog` and `NewFigureDialog` only accept on
`Do It`, while their launcher services secretly dispatch `get_command()` after
`exec_()`.

After this slice, creation dialogs should:

- receive the services they need for inherited footer behavior
- use the shared base `Do It` dispatch path
- keep `To Cmd Line` and `To Clip` working through the same canonical payload contract
- stop depending on post-`exec_()` launcher execution

This slice is the main removal of duplicated command dispatch for simple dialogs.

### Acceptance criteria

- [ ] `NewTableDialog` and `NewFigureDialog` no longer rely on caller-owned post-accept command dispatch.
- [ ] Their launchers no longer execute `get_command()` after `exec_()`.
- [ ] `To Cmd Line` works in real launcher paths because the dialogs now receive the required services.
- [ ] `Do It`, `To Cmd Line`, and `To Clip` all operate on the same canonical payload for these creation dialogs.
- [ ] Focused tests cover the removal of the old double-dispatch pattern.

### Blocked by

- Slice 1: Establish the `HydeDialogWidget` footer contract

### User stories covered

- Shared `Do It` / `To Cmd Line` / `To Clip` behavior for simple command dialogs
- Removal of launcher-owned secret second dispatch

## Slice 4: Route Figure-Control Dialogs Through The Shared `Do It` Dispatch Path

### Type

`AFK`

### What to build

Refactor the figure-control dialogs so their local validation and bookkeeping stay in
the dialog, but the actual kernel dispatch path for `Do It` goes through the shared
`HydeDialogWidget` primitive.

This applies to:

- `Modify Axis`
- `Modify Data Appearance`

These dialogs should still own:

- widget-to-state synchronization
- validation
- applied/opening snapshot bookkeeping

But they should stop owning an entirely separate dispatch implementation when the base
can provide that shared behavior.

### Acceptance criteria

- [ ] `AxisEditDialog` and `TraceAppearanceDialog` keep local validation/bookkeeping but delegate the actual `Do It` dispatch through the shared base path.
- [ ] `Do It`, `To Cmd Line`, and `To Clip` remain aligned on the next pending patch contract.
- [ ] No second dispatch helper or protocol path is introduced just for figure-control dialogs.
- [ ] Focused tests still prove the live-update canonical-patch contract after the refactor.

### Blocked by

- Slice 1: Establish the `HydeDialogWidget` footer contract

### User stories covered

- Shared footer dispatch behavior with figure-dialog local policy preserved
- Command-driven figure control without duplicated dispatch code

## Slice 5: Normalize Curve Fit As An Explicit `Do It` Exception Over The Same Footer Contract

### Type

`AFK`

### What to build

Bring `CurveFitDialog` under the stronger shared footer contract without pretending
that its preview text is always the executable `Do It` payload.

This slice should make the exception explicit and clean:

- the footer shell remains shared
- `To Cmd Line` and `To Clip` still use the canonical preview payload when appropriate
- `Do It` remains local because Curve Fit has mode-dependent commit behavior
- if the base class needs a second small hook such as an executable `Do It` payload
  separate from the preview payload, define it here only if that actually simplifies
  the code

The goal is to avoid either extreme:
- forcing Curve Fit into the wrong generic `Do It == preview` model
- leaving Curve Fit as an undocumented special case

### Acceptance criteria

- [ ] `CurveFitDialog` is explicitly aligned with the shared footer contract while keeping its legitimate local commit policy.
- [ ] The code clearly distinguishes preview payload from executable `Do It` behavior where needed.
- [ ] No stale assumptions remain that every dialog's `canonical_text_payload()` is always the `Do It` payload.
- [ ] Tests cover the intended Curve Fit footer behavior in both command-preview and equation-preview modes.

### Blocked by

- Slice 1: Establish the `HydeDialogWidget` footer contract
- Slice 4: Route figure-control dialogs through the shared `Do It` dispatch path

### User stories covered

- Shared footer ownership with an explicit Curve Fit exception
- Clean present-tense documentation of when subclass-local `Do It` work is allowed
