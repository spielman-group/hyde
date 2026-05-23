- [x] Slice 1: Add Canonical Figure-Element Tooling to a Figure Helper Class
- [x] Slice 2: Adopt Canonical Trace Display Names in User Selection Surfaces
- [x] Slice 3: Use Canonical Trace Display Names in Figure Window Titles

This file now tracks the canonical figure-element display-name work. It replaces the
completed `Remove from Graph` implementation slices.

All slices below must include a simplification pass as part of implementation:
- look for duplicated display-name formatting logic before adding new code
- prefer deleting local string assembly over layering new wrappers on top of it
- if a slice reveals repeated OO responsibilities, move them into the shared figure
  helper class rather than copying logic across dialogs or windows
- if a simplification would change product behavior, stop and surface it explicitly
  instead of silently changing the contract

## Slice 1: Add Canonical Figure-Element Tooling to a Figure Helper Class

### Type

`AFK`

### What to build

Add canonical user-facing figure-element display tooling to a shared figure helper
class. This helper must be the shared display surface for figure-working tools
through composition, not a free helper function.

If a suitable shared figure helper class does not already exist, create one. If
existing figure helper responsibilities can be absorbed into that class while keeping
the patch smaller and clearer, do that as part of this slice.

The initial implementation covers traces only, but the helper class must be shaped so
later work can extend it to image plots, contours, and analogous figure elements
without replacing the ownership model.

For traces, the canonical display name contract is:
- `{label}: {y} vs {x}` when `label` and `x` exist
- `{label}: {y}` when `label` exists and `x` does not
- `{y} vs {x}` when `label` does not exist and `x` exists
- `{y}` otherwise

`label` means the explicit plotted label value, such as `label='a'` in
`ax.plot(a, label='a')`. The helper class must preserve the distinction between the
raw plotted label and the synthesized canonical display name.

### Acceptance criteria

- [ ] A shared figure helper class owns canonical display-name tooling and is
      consumed through a has-a relationship by figure-facing code rather than by
      adding more free formatting helpers.
- [ ] The trace display contract distinguishes raw `label`, raw source names, and the
      canonical synthesized `display_name`.
- [ ] The four agreed trace display-name cases are covered by behavior tests.
- [ ] The implementation removes or consolidates any duplicate trace display-name
      formatting logic discovered during the slice instead of preserving it beside the
      helper class.

### Blocked by

None - can start immediately.

### User stories covered

- Canonical package-wide user-facing identification of traces
- Future extension seam for analogous figure elements such as images and contours

## Slice 2: Adopt Canonical Trace Display Names in User Selection Surfaces

### Type

`AFK`

### What to build

Move current trace-identification surfaces onto the canonical tooling in the shared
figure helper class so Hyde
shows one package-wide trace name wherever a user needs to identify a trace in a UI.

This slice should cover the current trace selection and inspection surfaces that
already expose trace rows or trace labels. The end state is that those surfaces no
longer locally assemble display text from trace metadata; they ask the shared figure
helper class for the canonical user-facing name instead.

As part of the slice, the worker must actively look for simplifications and delete
duplicate local formatting code when it can be replaced by the shared figure helper
class.

### Acceptance criteria

- [ ] Current trace selection lists and analogous trace-identification surfaces use
      the canonical shared `display_name`.
- [ ] No migrated consumer keeps its own ad hoc trace display-name assembly logic.
- [ ] Behavior tests prove that at least two concrete UI surfaces show the same
      canonical trace names for the same figure state.
- [ ] The slice includes a simplification pass that removes duplicate display-name
      logic found in the affected consumers.

### Blocked by

- Slice 1: Add Canonical Figure-Element Tooling to a Figure Helper Class

### User stories covered

- Canonical user-facing trace naming in selection and identification UIs
- Consistent trace naming across figure-working dialogs

## Slice 3: Use Canonical Trace Display Names in Figure Window Titles

### Type

`AFK`

### What to build

Update visible figure window titles to include the current figure name plus the
current trace display names from the shared figure helper class.

The visible title format is:
- `{Figure_name}: {list of trace display names}`

For this first pass, rely on the native title bar behavior for truncation rather than
adding custom Hyde-side ellipsis handling. The stable window identity must remain
unchanged; this slice changes visible title text only, not the stable handle or saved
window identity contract.

As with the earlier slices, the worker must look for simplifications while doing this
work and remove duplicate title-assembly logic where possible.

### Acceptance criteria

- [ ] Visible figure window titles include the figure name plus the current trace
      display-name list from the shared figure helper class.
- [ ] Stable figure window identity remains unchanged; only the visible title text is
      updated.
- [ ] Existing warning text behavior in figure window titles continues to compose
      correctly with the new visible title format.
- [ ] Behavior tests cover visible title updates for at least one ordinary figure
      state and one warning-bearing figure state.
- [ ] The slice includes a simplification pass that removes duplicate title-assembly
      or display-name plumbing discovered during implementation.

### Blocked by

- Slice 1: Add Canonical Figure-Element Tooling to a Figure Helper Class
- Slice 2: Adopt Canonical Trace Display Names in User Selection Surfaces

### User stories covered

- Canonical user-facing identification of traces in figure window chrome
- Consistent visible naming between figure windows and trace-selection dialogs
