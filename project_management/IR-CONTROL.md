# Hyde IR Control

This document defines Hyde's GUI-side control pattern for command-emitting features.

Across Hyde, `IR` means feature-specific internal representation/internal state that can
lower to standard Python.
It is not automatically kernel-owned. Ownership depends on the feature:

- table IR/state is GUI-owned long enough to generate commands and recreation source
- figure IR is kernel-owned and attached to the live matplotlib `Figure`

## When This Applies

Use this pattern whenever a Hyde GUI surface:
- emits user-visible Python
- emits GUI-owned silent Python requests
- owns recreated feature state or bounded reopen source

## Core Rule

A command-emitting GUI surface owns one or more Hyde-specific state objects by
composition. Those state objects delegate normalization, validation, mutation, and
lowering to a codec.

The GUI surface does not:
- directly mutate deep state dictionaries in many places
- generate command Python outside `HydeGuiState.python_source()`
- duplicate lowering logic in widget helpers
- become the authoritative owner of scientific state

## Ownership Split

### GUI surface owns
- widgets and signal wiring
- transient selection/focus state
- creation of action dictionaries
- user-facing warnings, confirmations, and dispatch decisions
- one or more `HydeGuiState` instances

### `HydeGuiState` owns
- the current local edit session state
- calls into its codec
- normalized/validated state access
- command lowering through `python_source()`
- any separate reopen-source lowering such as `macro_source()`

### `FeatureCodec` owns
- canonical state schema
- defaults
- normalization
- validation
- deterministic mutation semantics
- lowering to Python or recreation source

Each supported feature-library surface has one authoritative `FeatureCodec`.
Hyde does not keep multiple parallel codecs inside one feature module as
competing truths for one feature surface. The canonical codec owns the surface,
and any retained legacy names are compatibility views rather than additional
`FeatureCodec` authorities.

### Kernel/backend owns
- authoritative scientific objects and values
- backend notifications and metadata
- runtime identity of live kernel objects

## Placement Rules

- Public runtime API belongs in `hyde/__init__.py`.
- GUI state classes belong under `hyde/user_interface/...`.
- Feature codecs belong under `hyde/features/...`.
- Pure transport, queueing, and message envelopes stay outside codec classes.
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

Use one state class across GUI surfaces when they express the same semantic feature.

Current examples:
- `NewTableDialog` and `TableWidget` both use `TableState`
- table live data edits use shared `MutationState`
- file/project dialogs use Hyde-owned simple command state classes inside the shared
  file-dialog family
- figure creation surfaces use `FigureState` for GUI-side creation state

Split state classes only when the semantic schema truly diverges.

## Mutation Rule

Codec mutation must be action-based and deterministic, not ad hoc deep dict editing.

Typical actions are:
- `set`
- `clear`
- `replace_items`
- `append_item`
- `remove_item`
- command-specific state changes such as `set_command`

The GUI constructs actions. The codec interprets them.

## Base Interface

The shared codec contract is intentionally small:

- `default_state()`
- `normalize_state(state)`
- `validate_state(state)`
- `update_state(state, action)`
- `state_to_python(state, context=None)`
- optional `state_to_macro_source(state, macro_name, context=None)`

For command-emitting GUI surfaces, `HydeGuiState.python_source()` is the one
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

- Tables follow the full GUI-side IR/state/codec pattern.
- Generic data mutation is intentionally shared through `MutationState` /
  `MutationCodec` rather than being table-local.
- Trivial visible project commands may share a lightweight command codec.
- Target-selecting project dialogs keep chooser policy and generic overwrite checks
  in the shared file-dialog family while leaving command-specific exceptions in the
  concrete dialog. Their preview and submission strings come from the shared
  state-owned `python_source()` path rather than dialog-local string assembly.
- Figure creation surfaces use `FigureState` for GUI-side creation state.
- Curve Fit command generation uses `CurveFitState.python_source()` for preview,
  commit, live-update, and rollback/store behaviors while attached-display
  patching stays on the shared `FigurePatchState` path.
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

## Design Bias

Prefer the smallest clear shape:
- one authoritative state owner
- one lowering path per behavior
- one `FeatureCodec` per supported feature-library surface
- compatibility views only when needed to preserve callers during migration,
  never as parallel codec truths
- composition over GUI/state multiple inheritance
