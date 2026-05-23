- [x] Slice 1: Normalize the Figure Dialog Family on `HydeFigureDialogWidget`
- [ ] Slice 2: Canonicalize Shared Figure Trace Lists
- [ ] Slice 3: Ship the `Remove from Graph` Core Flow
- [ ] Slice 4: Complete Regex Filter Behavior for `Remove from Graph`

This breakdown is sized for delegated implementation work. Slices are listed in
dependency order so subagents can pick up unblocked work without rediscovering the
agreed dialog contract.

## Slice 1: Normalize the Figure Dialog Family on `HydeFigureDialogWidget`

### Type

`AFK`

### What to build

Introduce the shared figure-dialog base class and migrate the existing figure-working
dialogs onto it without changing their intended user-facing behavior. This slice
establishes the required object-oriented reuse path for the figure-dialog family and
moves the common figure-patch lifecycle into that shared base.

The shared base should own the figure-dialog contract that is already duplicated:
optional figure attachment, figure-context access, shared session opening,
opening/applied effective-state tracking, figure-patch preview generation, hidden
patch execution, patch logging, applied-state advancement, and rollback to the opening
state. The base must continue to respect the standard `HydeDialogWidget` footer
contract rather than introducing launcher-side dispatch or dialog-local footer shims.

### Acceptance criteria

- [x] A shared `HydeFigureDialogWidget` exists as the figure-dialog family base and
      supports optional `figure_context`.
- [x] Existing figure-working dialogs inherit the shared base instead of duplicating
      their own figure-patch lifecycle.
- [x] `Do It`, `To Cmd Line`, and `To Clip` continue to follow the normal
      preview-backed `HydeDialogWidget` contract with no second launcher-side dispatch
      path added.
- [x] Existing figure-dialog behavior remains covered by observable behavior tests
      rather than implementation-detail tests.

### Blocked by

None - can start immediately.

### User stories covered

- PRD user stories 16-21
- PRD user stories 23-30
- PRD user stories 31-32

## Slice 2: Canonicalize Shared Figure Trace Lists

### Type

`AFK`

### What to build

Move supported-trace list behavior into the shared figure-dialog base so figure
dialogs use one canonical trace-row contract. This slice should make the shared base
responsible for loading supported trace records, projecting deterministic row text,
tracking stable trace IDs, and supporting list refresh for single-select and
multi-select consumers.

This is the slice that replaces dialog-local trace-list shaping with one figure-dialog
family contract. It should preserve the agreed rule that there is no row-text override
hook: migrated figure dialogs share one canonical row representation.

### Acceptance criteria

- [ ] The shared figure-dialog base owns supported-trace loading and canonical row
      text generation for figure dialogs.
- [ ] Canonical trace rows are keyed by stable Hyde trace IDs and remain deterministic.
- [ ] Migrated figure dialogs that consume supported traces now use the shared trace
      list contract instead of dialog-local row shaping.
- [ ] Behavior tests prove the shared trace-list contract through real dialogs or
      concrete consumers, not through helper-only tests.

### Blocked by

- Slice 1: Normalize the Figure Dialog Family on `HydeFigureDialogWidget`

### User stories covered

- PRD user stories 6
- PRD user stories 10
- PRD user stories 24
- PRD user stories 29-32

## Slice 3: Ship the `Remove from Graph` Core Flow

### Type

`AFK`

### What to build

Build the first complete `Remove from Graph` path for supported line traces on the
active first-class figure. This slice should deliver the standalone modal dialog
plugin, first-in-menu launcher behavior, no-initial-selection behavior, arbitrary
multi-selection, empty-list behavior, canonical command preview, and real commit
through Hyde's existing hidden figure patch path.

This slice also includes the underlying first-class figure-session mutation required
to remove one or more supported traces by stable trace ID. The dialog must stay inside
the established figure edit boundary rather than mutating raw figure IR dictionaries
directly.

### Acceptance criteria

- [ ] `Remove from Graph...` launches as the first action in the active `Figure` menu.
- [ ] The dialog is modal, opens against the active first-class figure, and may open
      with an empty removable-trace list.
- [ ] The dialog opens with no initial trace selection and supports arbitrary
      multi-selection.
- [ ] When the selection is valid, the lower pane shows the canonical removal command
      string and `Do It`, `To Cmd Line`, and `To Clip` all use that same backing
      string.
- [ ] `Do It` removes the selected traces from the authoritative live kernel figure
      through the normal hidden figure patch path and closes the dialog on success.
- [ ] Behavior tests cover empty-list behavior, no-selection behavior, preview-backed
      footer behavior, committed removal, and the figure-session removal contract.

### Blocked by

- Slice 1: Normalize the Figure Dialog Family on `HydeFigureDialogWidget`
- Slice 2: Canonicalize Shared Figure Trace Lists

### User stories covered

- PRD user stories 1-10
- PRD user stories 16-25
- PRD user stories 31-32

## Slice 4: Complete Regex Filter Behavior for `Remove from Graph`

### Type

`AFK`

### What to build

Add the full agreed regex-filter UX to `Remove from Graph`. Valid regex input should
update the visible trace list live. Invalid regex input should surface an error state
without changing the current filtered list. Selections hidden by a valid filter change
must be dropped so the actionable selection always matches what the user can see.

This slice is intentionally narrow: it completes the filter contract after the core
remove-from-graph path already exists.

### Acceptance criteria

- [ ] The dialog exposes a fully implemented regex text filter using standard regex
      syntax with no Hyde-specific matching rules.
- [ ] Valid regex input updates the visible trace list live.
- [ ] Invalid regex input shows an error state and leaves the current filtered list
      unchanged.
- [ ] Selections hidden by a valid filter change are dropped.
- [ ] Behavior tests cover valid filtering, invalid-regex handling, preserved visible
      selections, and dropped hidden selections.

### Blocked by

- Slice 3: Ship the `Remove from Graph` Core Flow

### User stories covered

- PRD user stories 11-15
- PRD user stories 17
- PRD user stories 31-32
