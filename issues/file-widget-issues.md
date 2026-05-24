- [ ] Slice 1: Correct File Dialog Architecture Documentation
- [ ] Slice 2: Establish Shared Hyde File Dialog Family
- [ ] Slice 3: Refactor Project Target Dialogs Onto Preview-Backed File Dialogs
- [ ] Slice 4: Lock The Shared Contract With Behavior Tests
- [ ] Slice 5: Establish Final File Dialog Documentation Coherence

## Slice 1: Correct File Dialog Architecture Documentation

### Type

`AFK`

### What to build

Correct the Hyde documentation that governs architecture and dialog-family behavior so
the intended file-dialog design is explicit before implementation starts. The docs
should describe file-working dialogs as `HydeDialogWidget`-style surfaces, establish
the shared `HydeFileWidget` plus `HydeFileDialog` family in the base widget layer,
state that project-targeting dialogs are preview-backed command emitters, and clarify
which responsibilities belong to the shared file family versus concrete dialogs.

### Acceptance criteria

- [ ] Hyde's architecture and style guidance describe the shared file-dialog family
      in the base widget layer rather than leaving project file dialogs as a
      `QFileDialog` outlier.
- [ ] The relevant command/state documentation describes file-working dialogs as
      preview-backed command emitters that follow the `HydeDialogWidget` contract.
- [ ] The project save/load documentation reflects that target-selecting project
      dialogs will use the shared file-dialog family while plain Save remains a direct
      hidden dispatch.
- [ ] The docs clearly separate shared file-family policy from concrete
      project-operation exceptions so implementation agents have one coherent target.

### Blocked by

None - can start immediately.

### User stories covered

- User stories 4, 5, 7, 9, 10, 11, 13, 15

## Slice 2: Establish Shared Hyde File Dialog Family

### Type

`AFK`

### What to build

Build the shared file-dialog infrastructure in Hyde's base widget layer so file and
directory targeting dialogs can use the standard `HydeDialogWidget` shape. This slice
should introduce a reusable chooser widget that preserves the current non-native Qt
file-browser behavior while exposing a normalized selected target and declarative
selection policy for file vs directory targets, existence requirements, allowed
suffixes or name filters, and initial path behavior. It should also introduce a
shared file-dialog base that mounts that chooser, refreshes the preview-backed
command string through the standard Hyde footer contract, defaults `Do It` to hidden
execution, and offers optional shared overwrite confirmation for save-like dialogs.

### Acceptance criteria

- [ ] A shared file chooser widget exists in Hyde's base widget layer and supports
      both file and directory target modes.
- [ ] The shared chooser supports declarative target policy, including existence
      requirements and allowed suffix or name-filter constraints suitable for future
      image-export dialogs.
- [ ] A shared file-dialog base exists on top of `HydeDialogWidget` and uses the
      preview backing string as the execution, copy, and send-to-terminal payload.
- [ ] The shared file-dialog base defaults `Do It` to hidden execution and offers
      optional overwrite confirmation without forcing that policy on every dialog.

### Blocked by

- Slice 1: Correct File Dialog Architecture Documentation

### User stories covered

- User stories 4, 5, 6, 7, 8, 9, 10, 11, 13, 14

## Slice 3: Refactor Project Target Dialogs Onto Preview-Backed File Dialogs

### Type

`AFK`

### What to build

Refactor Hyde's project-targeting dialogs for New, Load, Heal, Save As, and Save Copy
onto the shared file-dialog family while preserving the existing project command
contracts and operation semantics. Each dialog should use the shared chooser and the
standard preview pane to show the actual generated Hyde Python, and should dispatch
the same backing command string through the existing hidden runtime path when the user
chooses `Do It`. Generic confirmation behavior should flow through the shared base,
while operation-specific rules such as same-target save behavior and copy-target
restrictions remain local to the concrete dialogs. Plain `Save` remains the existing
direct hidden dispatch with no dialog.

### Acceptance criteria

- [ ] New, Load, Heal, Save As, and Save Copy are implemented as preview-backed Hyde
      dialogs rather than direct `QFileDialog` subclasses.
- [ ] Each refactored project dialog shows the generated Hyde command in the lower
      preview pane and uses that same command as the backing payload for `Do It`,
      `To Cmd Line`, and `To Clip`.
- [ ] Existing project-operation semantics are preserved, including hidden default
      execution, generic overwrite confirmation where applicable, Save As same-target
      handling, and Save Copy rejecting the current project target.
- [ ] Plain Save remains a direct hidden dispatch and is not pulled into the new
      dialog family.

### Blocked by

- Slice 2: Establish Shared Hyde File Dialog Family

### User stories covered

- User stories 1, 2, 3, 12, 13, 14, 15

## Slice 4: Lock The Shared Contract With Behavior Tests

### Type

`AFK`

### What to build

Add or revise behavior-focused tests that protect the shared file-dialog family and
the refactored project dialogs against regressions. The tests should verify what the
user can observe or what callers depend on: target validation, preview generation,
footer enablement, hidden dispatch, optional visible command emission, shared
overwrite confirmation, and operation-specific exceptions. The test suite should not
assert incidental embedding details or internal signal wiring.

### Acceptance criteria

- [ ] Shared file-dialog tests verify observable chooser and preview-backed dialog
      behavior rather than internal implementation shape.
- [ ] Project-dialog tests verify the generated command strings and dispatch behavior
      for New, Load, Heal, Save As, and Save Copy against the established Hyde
      command contracts.
- [ ] Tests cover shared overwrite-confirmation behavior and the concrete exceptional
      cases that stay dialog-local.
- [ ] The resulting tests would catch a user-visible regression in target validation,
      preview payload, or dispatch behavior rather than merely detecting refactoring
      of helper structure.

### Blocked by

- Slice 2: Establish Shared Hyde File Dialog Family
- Slice 3: Refactor Project Target Dialogs Onto Preview-Backed File Dialogs

### User stories covered

- User story 16
- Regression coverage for user stories 1, 2, 3, 7, 11, 12, 13, 14, 15

## Slice 5: Establish Final File Dialog Documentation Coherence

### Type

`AFK`

### What to build

After the implementation and tests settle, take a final documentation pass so Hyde's
current-state docs describe the implemented file-dialog family coherently. This slice
should update present-tense project docs to reflect the final shared file-dialog
shape, note the new reusable chooser path as an implemented capability, and remove
any ambiguity left over from the pre-implementation guidance pass.

### Acceptance criteria

- [ ] The final implemented file-dialog family is reflected coherently across the
      present-tense Hyde docs that describe architecture, style, and current product
      status.
- [ ] Project save/load and related UI docs match the implemented preview-backed
      file-dialog behavior and default hidden execution path.
- [ ] Documentation no longer mixes old `QFileDialog`-centric descriptions with the
      new shared `HydeFileWidget` plus `HydeFileDialog` family.
- [ ] The final documentation set would guide a new implementation agent toward the
      shipped design rather than the pre-refactor shape.

### Blocked by

- Slice 3: Refactor Project Target Dialogs Onto Preview-Backed File Dialogs
- Slice 4: Lock The Shared Contract With Behavior Tests

### User stories covered

- User stories 3, 4, 5, 7, 10, 13, 15, 16
