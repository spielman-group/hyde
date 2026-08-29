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

## IR File Shape

For every Python package with a Hyde lowerer in `hyde/features`, Hyde uses a
matching package-IR module beside that lowerer:

- `hyde/features/hyde_features.py` pairs with `hyde/features/hyde_ir.py`
- `hyde/features/matplotlib_features.py` pairs with
  `hyde/features/matplotlib_ir.py`
- `hyde/features/lmfit_features.py` pairs with `hyde/features/lmfit_ir.py`

Those package IR modules are feature-side runtime surfaces, not `shared/`
surfaces.
Together, a package-level `*_IR.py` file and its `features/..._features.py`
lowerer constitute Hyde's complete IR + lowering toolset for that package.

At the widget level, every widget owns one `widget_ir`. That `widget_ir` may be:

- a package-level IR imported from `hyde/features/<package>_ir.py`, when the
  widget belongs to one package-owned feature family
- a class-level workflow IR in plugin-local `<widget>_IR.py`, when the widget
  composes multiple package IR families

`CurveFitIR` is the canonical example of a class-level workflow IR: it owns the
Curve Fit dialog workflow and composes package-level IR families rather than
pretending to be the package-level matplotlib or lmfit IR itself.

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

Concrete IR authority belongs on the IR class or on small plugin-local support
modules that serve that IR family. Do not hide feature authority in `shared/`
modules.

This file-shape rule is first-class. Hyde does not treat it as optional cleanup
or a naming preference.

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
- Package-level IR belongs in `hyde/features/<package>_ir.py`.
- Widget-level workflow IR belongs in plugin-local `<widget>_IR.py` near the
  owning GUI family under `hyde/user_interface/plugins/...`.
- Feature lowerers belong under `hyde/features/...`.
- Pure transport, queueing, and message envelopes stay outside IR classes.
- Widget-local workflow IRs that compose package IRs belong in plugin-local
  `<widget>_IR.py` files, not in `shared/`.
- Supporting material that carries runtime authority for one IR family belongs in
  that plugin directory, not in `hyde/user_interface/shared/`.
- `hyde/user_interface/shared/` is reserved for neutral scaffolding, base widget
  families, and genuinely neutral helpers that do not own feature authority.
- Shared UI-family behavior may live in a feature-family widget base class. For
  first-class figure dialogs, prefer a shared `HydeDialogWidget` subclass over free
  helper functions when multiple dialogs need the same figure-dialog behavior.
- Target-selecting project dialogs follow the same rule through a shared
  `HydeFileDialog` / `HydeFileWidget` family in
  `hyde.user_interface.base_hyde_widgets` rather than dialog-local chooser logic.
- `HydeFileDialog` subclasses should extend that shared generation/submission path
  through hook overrides and `super()` rather than alternate dialog-local paths.
- Shared user-facing display metadata may live in feature-side support code when it
  is not scientific state and multiple surfaces need one canonical representation.
  For first-class figures, canonical figure-element display names come from the
  feature-side matplotlib trace-record helpers. Plugin-local helpers may delegate to
  that contract for UI composition, but should not duplicate the formatting logic.

## Shared Pattern

Use one IR family across GUI surfaces when they express the same semantic
feature.

Current examples:
- the table interactive family shares `TableIR` / `TableIRDiff`
- the figure interactive family shares `FigureIR` / `FigureIRDiff`
- file/project dialogs use `HydeAppIR` directly as `widget_ir` inside the
  shared file-dialog family

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
- Figure clipboard copy is a distinct `FigureIR` copy command rather than a save
  with a null target, so both validations stay honest. It carries `dpi='figure'`,
  matplotlib's own sentinel, which lets the kernel resolve DPI against the live
  figure instead of the GUI mirroring kernel state.
- That copy command lowers to a `hyde.copy_figure(...)` call rather than plain
  matplotlib. The clipboard is GUI-owned and matplotlib cannot express it, which
  is precisely the case the Hyde-helper allowance above is for.
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
