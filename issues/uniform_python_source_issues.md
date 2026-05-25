- [ ] Slice 1: Document The No-Exceptions `python_source()` Rule
- [ ] Slice 2: Inventory Every GUI Python-Generation Path
- [ ] Slice 3: Harden Shared `HydeGuiState` And `HydeFileDialog` Contracts
- [ ] Slice 4: Normalize Non-Figure Shortcut Command Surfaces
- [ ] Slice 5: Normalize Figure Refresh And Figure-Window Command Paths
- [ ] Slice 6: Normalize The Shared Figure Dialog Patch Family
- [ ] Slice 7: Normalize Curve Fit And Remaining Inventory Tail Cases
- [ ] Slice 8: Resync Final Docs After Package-Wide Migration

## Slice 1: Document The No-Exceptions `python_source()` Rule

### Type

`AFK`

### What to build

Update Hyde’s present-tense architecture/control documentation so it explicitly
states the final package-wide rule: GUI-generated Python comes from a
`HydeGuiState` `python_source()` path, preview displays that same generated
string, and cached preview dispatch is still allowed. This slice should also
state the `HydeFileDialog` family constraint
that subclasses extend the shared generation/submission path through overrides
and `super()` rather than custom alternate paths.

### Acceptance criteria

- [ ] Hyde docs clearly state the no-exceptions `HydeGuiState` /
      `python_source()` rule.
- [ ] Hyde docs clearly state that preview uses the string produced by
      `python_source()` itself rather than a second preview-only generation
      method.
- [ ] Hyde docs clearly state that cached preview dispatch is acceptable and is
      not a violation by itself.
- [ ] Hyde docs clearly state the `HydeFileDialog` subclass rule about using the
      shared generation/submission path through overrides and `super()`.
- [ ] The documentation is present-tense and describes the intended target
      architecture for the package-wide cleanup.

### Blocked by

None - can start immediately.

## Slice 2: Inventory Every GUI Python-Generation Path

### Type

`AFK`

### What to build

Create a temporary Markdown reference file under `issues/` that inventories the
current Python-generation path for the whole Hyde package, ideally grouped by
plugin/family. The inventory should identify each relevant GUI surface, the
current generation mechanism, whether it is compliant or noncompliant against
the final rule, and the migration family it belongs to. This is the package-wide
evidence map that later slices should work from.

### Acceptance criteria

- [ ] A temporary reference Markdown file is created under `issues/` for the
      inventory.
- [ ] The inventory covers the package-wide GUI Python-generation paths rather
      than only one feature family.
- [ ] The inventory is organized clearly enough that later migration work can be
      scoped by plugin/family.
- [ ] The inventory labels each path against the final rule and identifies the
      likely migration target or shared family.

### Blocked by

- Slice 1: Document The No-Exceptions `python_source()` Rule

## Slice 3: Harden Shared `HydeGuiState` And `HydeFileDialog` Contracts

### Type

`AFK`

### What to build

Make the smallest shared-base changes needed so the remaining package can move
onto the uniform `HydeGuiState` path without inventing new bypasses. This slice
should keep the shared command-generation boundary in the features/state layer,
codify the `HydeFileDialog` subclass rule in real shared behavior, and prove
that shared bases can support the remaining use cases through overrides rather
than alternate paths.

### Acceptance criteria

- [ ] Shared `HydeGuiState` infrastructure supports the remaining real package
      use cases without requiring feature-local generation bypasses.
- [ ] `HydeFileDialog` clearly owns the shared generation/submission path for its
      subclass family.
- [ ] `HydeFileDialog` subclasses can add behavior through overrides and
      `super()` rather than custom alternate generation/submission paths.
- [ ] Behavior tests prove the shared-base contract rather than helper
      structure.

### Blocked by

- Slice 1: Document The No-Exceptions `python_source()` Rule
- Slice 2: Inventory Every GUI Python-Generation Path

## Slice 4: Normalize Non-Figure Shortcut Command Surfaces

### Type

`AFK`

### What to build

Convert the non-figure shortcut surfaces identified in the inventory so they
stop bypassing `HydeGuiState` through direct codec/helper lowering. This slice
should focus on command surfaces that are already close to compliance but still
expose direct helper or codec lowering to GUI callers. The result should be
that these surfaces generate commands through `python_source()` instead.

### Acceptance criteria

- [ ] The non-figure shortcut command surfaces covered by this slice no longer
      expose direct codec/helper generation paths to GUI callers.
- [ ] The affected GUI surfaces now generate their commands through
      `HydeGuiState` `python_source()`.
- [ ] The command surfaces covered by this slice follow the same state-owned
      generation rule.
- [ ] Tests prove the public preview/dispatch contract and no longer rely on the
      old shortcut helpers.

### Blocked by

- Slice 2: Inventory Every GUI Python-Generation Path
- Slice 3: Harden Shared `HydeGuiState` And `HydeFileDialog` Contracts

## Slice 5: Normalize Figure Refresh And Figure-Window Command Paths

### Type

`AFK`

### What to build

Move figure-window command generation such as refresh/regenerate onto explicit
`HydeGuiState` `python_source()` paths instead of helper-generated strings. This
slice should preserve existing user-visible behavior while
making figure-window command surfaces obey the same state/codec rule as the rest
of Hyde.

### Acceptance criteria

- [ ] Figure refresh/regenerate command generation uses a `HydeGuiState`
      `python_source()` path.
- [ ] Figure-window command surfaces covered by this slice no longer build or
      expose raw helper-generated Python strings directly.
- [ ] Existing refresh/regenerate behavior is preserved.
- [ ] Tests prove the preview/dispatched-string contract without relying on old
      helper-specific labels.

### Blocked by

- Slice 2: Inventory Every GUI Python-Generation Path
- Slice 3: Harden Shared `HydeGuiState` And `HydeFileDialog` Contracts

## Slice 6: Normalize The Shared Figure Dialog Patch Family

### Type

`AFK`

### What to build

Bring the shared figure-dialog patch family onto the strict `HydeGuiState`
path. This includes the shared figure-dialog patch command shape used by figure
edit dialogs and related family members. The goal is to replace helper-owned
patch generation as the GUI contract with a state-owned `python_source()` path
while keeping the shared figure/matplotlib lowering seam.

### Acceptance criteria

- [ ] Shared figure-dialog patch generation now has an authoritative
      `HydeGuiState` `python_source()` owner.
- [ ] Figure-dialog family members covered by this slice no longer rely on
      helper-only patch generation as their GUI command contract.
- [ ] Shared figure/matplotlib lowering remains the lowering seam beneath that
      state-owned path.
- [ ] Tests prove the preview/dispatched-string behavior for the figure dialog
      family rather than helper-specific metadata.

### Blocked by

- Slice 2: Inventory Every GUI Python-Generation Path
- Slice 3: Harden Shared `HydeGuiState` And `HydeFileDialog` Contracts
- Slice 5: Normalize Figure Refresh And Figure-Window Command Paths

## Slice 7: Normalize Curve Fit And Remaining Inventory Tail Cases

### Type

`AFK`

### What to build

Finish the package-wide migration by converting Curve Fit’s remaining mixed
helper/state command paths and any leftover tail cases from the inventory to the
uniform `HydeGuiState` `python_source()` solution. This slice is explicitly the
closure slice for remaining exceptions, not a new broad refactor: whatever the
inventory still shows as noncompliant after prior slices must be brought onto
the standard solution here.

### Acceptance criteria

- [ ] Curve Fit no longer mixes state-backed command generation with helper-only
      GUI command paths for the behaviors covered by the inventory.
- [ ] The remaining tail cases from the inventory no longer bypass
      `HydeGuiState` command generation.
- [ ] The package has no known remaining GUI command-generation exceptions after
      this slice.
- [ ] Tests cover the converted tail cases through the uniform
      preview/dispatched-string contract.

### Blocked by

- Slice 2: Inventory Every GUI Python-Generation Path
- Slice 3: Harden Shared `HydeGuiState` And `HydeFileDialog` Contracts
- Slice 4: Normalize Non-Figure Shortcut Command Surfaces
- Slice 5: Normalize Figure Refresh And Figure-Window Command Paths
- Slice 6: Normalize The Shared Figure Dialog Patch Family

## Slice 8: Resync Final Docs After Package-Wide Migration

### Type

`AFK`

### What to build

Resync Hyde’s present-tense docs after the package-wide migration is complete.
This final slice should update architecture/control/status/spec docs so they
describe the real final system, and it should also clean up the temporary
inventory artifact appropriately for a completed migration pass.

### Acceptance criteria

- [ ] Present-tense docs describe the final package-wide `HydeGuiState` /
      `python_source()` design accurately.
- [ ] Docs describe the final cached-preview-dispatch rule accurately.
- [ ] Docs describe the final shared `HydeFileDialog` subclass contract
      accurately.
- [ ] The temporary inventory artifact is either removed or clearly marked as a
      temporary reference/superseded planning artifact.

### Blocked by

- Slice 1: Document The No-Exceptions `python_source()` Rule
- Slice 2: Inventory Every GUI Python-Generation Path
- Slice 3: Harden Shared `HydeGuiState` And `HydeFileDialog` Contracts
- Slice 4: Normalize Non-Figure Shortcut Command Surfaces
- Slice 5: Normalize Figure Refresh And Figure-Window Command Paths
- Slice 6: Normalize The Shared Figure Dialog Patch Family
- Slice 7: Normalize Curve Fit And Remaining Inventory Tail Cases
