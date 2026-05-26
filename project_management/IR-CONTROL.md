# Hyde IR Control

This document defines Hyde's GUI-side control pattern for command-emitting
features.

Across Hyde, `IR` means feature-specific internal representation/internal state
that can lower to standard Python. `HydeIR` is the GUI-side truth for a
recreatable feature family, and `HydeIRDiff` is a real `HydeIR` subclass used
for change-oriented lowering. IR is not automatically kernel-owned. Ownership
depends on the feature:

- table IR is GUI-owned long enough to generate commands and recreation source
- figure IR is kernel-owned and attached to the live matplotlib `Figure`

## When This Applies

Use this pattern whenever a Hyde GUI surface:
- emits user-visible Python
- emits GUI-owned silent Python requests
- owns recreated feature state or bounded reopen source

## Core Rule

A command-emitting GUI surface owns one or more Hyde-specific IR objects by
composition. Those IR objects are the GUI-side truth and call package-pure
feature lowerers as needed.

`HydeGuiState` is retired. Hyde is `HydeIR`-based. Every widget base family
owns one base-level IR slot named `widget_ir`.
`HydeInteractiveWidget.widget_ir` is the live current object IR.
`HydeDialogWidget.widget_ir` and `HydeToolWidget.widget_ir` are their own IRs
and may contain external IR snapshots when the surface needs imported feature
state to build previews or commands.

The GUI surface does not:
- directly mutate deep state dictionaries in many places
- generate command Python outside `HydeIR.python_source()`
- duplicate lowering logic in widget helpers
- keep a second GUI-owned truth beside `widget_ir`
- become the authoritative owner of scientific state

## Ownership Split

### GUI surface owns
- widgets and signal wiring
- transient selection/focus state
- creation of action dictionaries
- user-facing warnings, confirmations, and dispatch decisions
- direct ownership of its family-level `widget_ir`

### `HydeIR` owns
- the current local edit session state
- validation and deterministic mutation semantics
- family-specific orchestration across package-pure lowerers
- typed normalized state access
- command lowering through `python_source()`
- any separate reopen-source lowering such as `macro_source()`

### `HydeIRDiff` owns
- diff-oriented state in the same family as its base IR
- change-oriented lowering when the diff case differs from full recreation

### `xxx_features.py` lowerers own
- package-local string lowering only
- no top-level IR authority or cross-package orchestration

The boundary is package-pure: `hyde_features.py` emits only Hyde strings,
`matplotlib_features.py` emits only matplotlib strings, and analogous feature
modules follow the same rule. Concrete IR classes may coordinate multiple
package-pure lowerers when assembling final Python.

### Kernel/backend owns
- authoritative scientific objects and values
- backend notifications and metadata
- runtime identity of live kernel objects

## Placement Rules

- Public runtime API belongs in `hyde/__init__.py`.
- GUI IR classes belong near the owning GUI family under
  `hyde/user_interface/...`.
- Feature lowerers belong under `hyde/features/...`.
- Pure transport, queueing, and message envelopes stay outside IR classes.
- Shared UI-family behavior may live in a feature-family widget base class. For
  first-class figure dialogs, prefer a shared `HydeDialogWidget` subclass over free
  helper functions when multiple dialogs need the same figure-dialog behavior.
- Target-selecting project dialogs follow the same rule through a shared
  `HydeFileDialog` / `HydeFileWidget` family in
  `hyde.user_interface.base_hyde_widgets` rather than dialog-local chooser logic.
- `HydeFileDialog` subclasses should extend that shared generation/submission path
  through hook overrides and `super()` rather than alternate dialog-local paths.
- Shared user-facing display metadata may live in a composed feature support class
  when it is not scientific state and when multiple surfaces need one canonical
  representation. For first-class figures, canonical figure-element display names
  should be owned by shared figure helper tooling such as `FigureDisplayHelper`,
  used through composition, not by duplicated widget-local formatting logic.

## Shared Pattern

Use one IR family across GUI surfaces when they express the same semantic
feature.

Current examples:
- the table interactive family shares `TableIR` / `TableIRDiff`
- the figure interactive family shares `FigureIR` / `FigureIRDiff`
- file/project dialogs use Hyde-owned app/file IR classes inside the shared
  file-dialog family

Split IR families only when the semantic schema truly diverges.

## Mutation Rule

IR mutation must be action-based and deterministic, not ad hoc deep dict
editing.

Typical actions are:
- `set`
- `clear`
- `replace_items`
- `append_item`
- `remove_item`
- command-specific state changes such as `set_command`

The GUI constructs actions. The IR family interprets them and delegates
package-specific string lowering to package-pure lowerers.

## Base Interface

The shared IR contract is intentionally small:

- `python_source()`
- optional `macro_source()`
- family-specific constructors or diff builders on `HydeIR` /
  `HydeIRDiff`

For command-emitting GUI surfaces, `HydeIR.python_source()` is the one
authoritative command-generation method. Preview text shows that same generated
string; Hyde does not grow separate preview-only Python-generation APIs.

Do not grow this into a framework unless the code actually needs it.

In particular, do not add by default:
- widget-binding helpers
- observer systems
- undo/redo frameworks
- parser registries
- migration frameworks

## Reverse Reconstruction

Reverse reconstruction is feature-specific.

Hyde does not require one universal parser from Python back into GUI-editable state.
If a feature needs reconstruction, it may define its own import/metadata decode path.

## Current Concrete Guidance

- Tables follow the full GUI-side `TableIR` / `TableIRDiff` pattern.
- Trivial visible project commands may share a lightweight Hyde-owned IR family.
- Target-selecting project dialogs keep chooser policy and generic overwrite checks
  in the shared file-dialog family while leaving command-specific exceptions in the
  concrete dialog. Their preview and submission strings come from the shared
  IR-owned `python_source()` path rather than dialog-local string assembly.
- Figure creation and recreation surfaces use the `FigureIR` family.
- Curve Fit command generation uses its IR object's `python_source()` for preview,
  commit, live-update, and rollback/store behaviors while attached-display
  patching stays on the shared figure IR family.
- Figure axis, trace, and Curve Fit attached-display dialogs now emit matplotlib
  patch Python from imported figure IR rather than using a separate semantic
  figure-action transport.
- Emitted strings that could plausibly be reused outside Hyde should prefer standard
  matplotlib/Python. Hyde public helpers are acceptable in emitted update strings only
  when they are the necessary or clearer contract for a Hyde-owned operation, not as a
  substitute for normal matplotlib when normal matplotlib would express the same edit
  cleanly.
- Canonical user-facing trace identification is separate from raw plotted `label`
  metadata. Figure-working surfaces should consume the shared figure helper's
  canonical `display_name` rather than inferring their own fallback strings.
- Runtime transport and feature-specific figure behavior belong in
  `ARCHITECTURE.md`, not in this generic control-pattern document.

## Revision Rule

When later work sharpens this contract, earlier docs and tests must be revised
to match. Hyde does not preserve stale `HydeGuiState`-era guidance or
superseded IR syntax as parallel truths.

## Design Bias

Prefer the smallest clear shape:
- one authoritative state owner
- one base-level `widget_ir` slot per widget family
- one IR class plus one diff subclass per recreatable interactive widget family
- one lowering path per behavior
- package-pure `xxx_features.py` lowerers rather than feature modules that mix
  multiple Python package surfaces
- composition over GUI/state multiple inheritance
