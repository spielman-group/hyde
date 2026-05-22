# Hyde IR Control

This document defines Hyde's GUI-side control pattern for command-emitting features.

Across Hyde, `IR` means feature-specific internal representation/internal state that can
lower to standard Python or, for the remaining first-class figure edit path, support
semantic `comm` actions.
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
- lowering requests such as `python_source()` and `macro_source()`

### `FeatureCodec` owns
- canonical state schema
- defaults
- normalization
- validation
- deterministic mutation semantics
- lowering to Python or recreation source

### Kernel/backend owns
- authoritative scientific objects and values
- backend notifications and metadata
- runtime identity of live kernel objects

## Placement Rules

- Public runtime API belongs in `hyde/__init__.py`.
- GUI state classes belong under `hyde/user_interface/...`.
- Feature codecs belong under `hyde/features/...`.
- Pure transport, queueing, and message envelopes stay outside codec classes.

## Shared Pattern

Use one state class across GUI surfaces when they express the same semantic feature.

Current examples:
- `NewTableDialog` and `TableWidget` both use `TableState`
- table live data edits use shared `MutationState`
- file/project dialogs use Hyde-owned simple command state classes
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
- Figure creation surfaces use `FigureState` for GUI-side creation state.
- Figure axis and trace dialogs now emit matplotlib patch Python rather than using the
  semantic figure-action transport.
- Runtime transport and feature-specific figure behavior belong in
  `ARCHITECTURE.md`, not in this generic control-pattern document.

## Design Bias

Prefer the smallest clear shape:
- one authoritative state owner
- one lowering path per behavior
- one codec per semantic feature when practical
- composition over GUI/state multiple inheritance
