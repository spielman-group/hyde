- [x] Slice 1: Adopt Shared Hidden And Visible Command Dispatch For Export Graphics
- [x] Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level
- [x] Slice 3: Trim Redundant Local State Shims Around Figure Export Paths
- [x] Slice 4: Lock Export Graphics With Behavior Tests And Present-Tense Docs

## Slice 1: Adopt Shared Hidden And Visible Command Dispatch For Export Graphics

### Type

`AFK`

### What to build

Make `Save Graphics...` use the same shared hidden/visible command-dispatch
path as the rest of Hyde while leaving current feature behavior intact. This
slice is the baseline plumbing step before export-specific source-generation
cleanup.

### Acceptance criteria

- [x] `Save Graphics...` uses Hyde’s shared hidden command-dispatch path.
- [x] Visible dispatch follows the same shared dispatch contract.
- [x] Export-specific source-generation cleanup can proceed without inventing a
      separate submission path.
- [x] Existing local state handling is not yet required to be removed at this
      stage.

### Blocked by

None - can start immediately.

### User stories covered

- `issues/nonuniform_python_strings.md`: User stories 2, 3, 4, 8

## Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level

### Type

`AFK`

### What to build

Refit `Save Graphics...` so it stops inventing a dialog-local export lowering
path and instead works through the existing shared figure/matplotlib feature
plumbing at the same architectural level as `Remove from Graph...`. This slice
does not ask for a broader package-wide `python_source()` cleanup. It only asks
that export command construction stop living in dialog-local widget-to-string
code and instead live in the same figure-family command model as other
first-class figure operations.

### Acceptance criteria

- [x] `Save Graphics...` no longer generates its final export command directly
      from dialog-local widget state in the dialog class.
- [x] Shared figure/matplotlib feature plumbing owns the export-command
      lowering.
- [x] Figure-scoped export command generation is expressed through the existing
      figure-family command path rather than a one-off dialog-local lowering
      function.
- [x] `Save Graphics...` reaches parity with the current `Remove from Graph...`
      family level of reuse and feature-layer ownership.

### Blocked by

- Slice 1: Adopt Shared Hidden And Visible Command Dispatch For Export Graphics

### User stories covered

- `issues/export_graphics.md`: User stories 3, 4, 5, 23, 24
- `issues/nonuniform_python_strings.md`: User stories 6, 7, 8

## Slice 3: Trim Redundant Local State Shims Around Figure Export Paths

### Type

`AFK`

### What to build

Clean up redundant feature-local state shims in the export-adjacent figure
command paths now that `Save Graphics...` uses the shared figure-family command
path. This slice should focus on the nearby figure export and figure patch
surfaces, not the whole package, and should leave the code closer to one clear
command-generation rule rather than overlapping local variations.

### Acceptance criteria

- [x] Nearby export-adjacent figure command paths no longer rely on redundant
      local state shims.
- [x] `Save Graphics...` and the current figure patch family follow one clear
      command-generation rule.
- [x] Removing redundant local state shims does not change the dispatched
      export behavior.
- [x] This cleanup remains local to export-adjacent figure command paths and
      does not broaden into a package-wide rewrite.

### Blocked by

- Slice 1: Adopt Shared Hidden And Visible Command Dispatch For Export Graphics
- Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level

### User stories covered

- `issues/nonuniform_python_strings.md`: User stories 2, 4, 7, 8

## Slice 4: Lock Export Graphics With Behavior Tests And Present-Tense Docs

### Type

`AFK`

### What to build

Add the behavior-focused tests and present-tense documentation needed to lock
the new export contract. The tests should verify the final dispatched command
rather than helper wiring. The docs should make clear that `Save Graphics...`
now follows the current figure-family command path rather than dialog-local
lowering.

### Acceptance criteria

- [x] Tests cover `Save Graphics...` preview/dispatch behavior through the new
      figure-family export command path.
- [x] Tests verify the export behavior through the shared command path rather
      than dialog-local or feature-local shims.
- [x] Present-tense docs describe the new export command path without implying
      that `Do It` must rerun `python_source()` when it is already dispatching
      the authoritative generated preview string.

### Blocked by

- Slice 1: Adopt Shared Hidden And Visible Command Dispatch For Export Graphics
- Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level
- Slice 3: Trim Redundant Local State Shims Around Figure Export Paths

### User stories covered

- `issues/export_graphics.md`: User story 25
- `issues/nonuniform_python_strings.md`: User stories 4, 7, 8, 9, 10
