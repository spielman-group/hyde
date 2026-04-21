# Stateful Control Pattern For Hyde Features

## Purpose

This document defines the planning direction for a state-centered control pattern in
`hyde/features/*_features.py` and the matching `HydeGuiState` ownership pattern in
`hyde/user_interface/...`.

The immediate goal is to establish a simple, reusable pattern for GUI-driven command
generation before figure and fitting editors arrive. Those future editors will have
many controls, order-sensitive content, and nontrivial validation rules. Hyde needs a
consistent way for the GUI to hold transient edit state, apply user actions, and lower
that state into visible Python commands.  The majority of hyde windows will have their
state information stored as metadata.

This is a planning document only. No runtime code is introduced here.


## Hyde Constraints That Bind This Design

The design is constrained by Hyde's existing architecture:

- The GUI may hold transient, serializable UI-edit state, but not authoritative
  scientific state.
- The kernel remains authoritative for live arrays, figures, tables, and analytical
  objects.
- GUI actions must still lower to ordinary Python strings that can run outside Hyde.
- `features/...` remains a translation layer between GUI-facing representations and
  Python code or semantic payloads. It is not the runtime API surface.

This means the proposed "state language" is not Hyde's scientific source of truth. It
is a GUI-owned, serializable edit representation whose purpose is to generate valid
Python and support deterministic GUI behavior.


## Current Problem

`hyde/features/hyde_features.py` currently mixes several different kinds of behavior:

- visible user-facing command builders to generate strings such as `hyde.table(...)`,
  `hyde.save_project(...)`, and `hyde.quit()`
- table-specific micro-mutation helpers such as cell edit, append, and delete commands
- runtime-helper / plumbing string builders such as procedure bootstrap and remote
  execution commands
- eligibility logic such as `is_eligible_for_table(...)`

This flat function bag works for the current small surface, but it does not scale well
to figure editors, fitting editors, or any feature with many widgets and order-aware
state.


## Decision Summary

### 1. Use a class-based codec pattern for stateful GUI features

Each recreated semantic feature should own its own `FeatureCodec` subclass in
`hyde/features/...`.

That codec owns:

- default edit state
- normalization
- validation
- deterministic state mutation
- Python generation

### 2. All Python generation belongs to Hyde GUI state and codec pairs

If the GUI generates Python for a user-visible feature or a GUI-owned background
request, that generation belongs to a `HydeGuiState` / `FeatureCodec` pair.

This includes:

- visible `hyde.table(...)` construction
- table recreation macro source
- table-data fetch requests
- table-macro publication requests
- table mutation commands

Pure transport such as message envelopes or queueing remains outside the codec layer,
but Python string generation does not.

The macro hook stays in the shared base interface as well:

- `FeatureCodec.state_to_macro_source(...)`
- `HydeGuiState.macro_source(...)`

This is intentional. Recreation-capable feature states should expose one shared
state-to-source interface rather than reintroducing ad hoc widget-local macro helpers.

### 3. Use feature-specific codecs for recreated features

Every recreated source should have its own codec class, for example:

- `TableCodec`
- `FigureFeatureCodec`
- `FitFeatureCodec`

This keeps each GUI/editor surface coupled to one semantic owner rather than to a
shared omnibus codec.

### 4. Use Hyde-specific GUI state objects as the universal GUI-side pattern

Every command-emitting Hyde GUI class must:

- be a Hyde-owned subclass under `hyde/user_interface/...`
- own one or more Hyde-specific `HydeGuiState` subclasses as needed to cover its
  command domains
- use composition rather than inheritance for that state ownership

There is no GUI-state multiple inheritance pattern. The GUI class owns those state
objects explicitly.

### 5. Share one state class across GUI surfaces when they express the same feature

If multiple GUI classes express the same semantic feature, they should share the same
Hyde-specific `...State` class whenever one state schema naturally covers them.

For example:

- `NewTableDialog` and `TableWidget` should both own `TableState`
- the simpler dialog edits a subset of `TableState`
- the richer table widget edits a larger subset of `TableState`

The split should happen only if the semantic state truly diverges.

State placement should still follow ownership:

- feature-specific GUI state such as `TableState` should live with that feature
- reusable GUI state such as `MutationState` should live in a shared UI-state module,
  not inside one feature package

### 6. Use a generic mutation codec for data edits across GUI features

Hyde should use a generic `MutationCodec` plus `MutationState(HydeGuiState)` for
data-mutating GUI paths that are not specific to one semantic feature object.

The initial table implementation uses this for:

- cell edit
- append value
- create array
- delete indices

Future figure-control surfaces may reuse the same mutation pattern where the GUI
describes a data mutation and lowers it into explicit Python.

This generic mutation path is an intentional exception to any "collapse table logic
into one state object" simplification advice. `MutationState` is preserved as a
cross-feature abstraction because future mutation-capable editors are expected to
reuse it.

### 7. Use a shared lightweight codec only for trivial visible commands

Fairly trivial visible command generation such as:

- `new_project`
- `load_project`
- `heal_project`
- `save_project`
- `quit`

may share a small command-oriented codec because these commands do not define the same
kind of recreated feature state as tables, figures, or fits.

### 8. Do not require a universal reverse parser

The common interface should be forward-oriented:

- GUI edit state -> Python

Reverse reconstruction remains feature-specific. Some features may reconstruct state
from metadata, some from explicit backend notifications, some from command semantics,
and some from parser-produced structures. Hyde should not impose one reverse mechanism
before the real features demand it.

For tables, recreation source is also allowed to include GUI-restorable layout such as
window geometry and column widths. This intentionally duplicates layout information
that also appears in `session.toml`: session restore owns workspace restore, while
recreation macros own explicit user-invoked reopen behavior.


## Recommended Base Interface

The smallest useful shared contract is:

```python
class FeatureCodec:
    feature_name = None
    state_version = 1

    @classmethod
    def default_state(cls):
        ...

    @classmethod
    def normalize_state(cls, state):
        ...

    @classmethod
    def validate_state(cls, state):
        ...

    @classmethod
    def update_state(cls, state, action):
        ...

    @classmethod
    def state_to_python(cls, state, context=None):
        ...

    @classmethod
    def state_to_macro_source(cls, state, macro_name, context=None):
        raise NotImplementedError
```

### Why this is enough

- `default_state()` gives each editor a fresh starting point.
- `normalize_state()` lets the codec fill defaults and canonicalize shape before later
  steps.
- `validate_state()` makes failures explicit and testable.
- `update_state()` supports rich GUI mutation without ad hoc dict manipulation spread
  across widgets.
- `state_to_python()` keeps Hyde's string-factory rule intact.
- `state_to_macro_source()` gives recreation-capable states a shared way to emit
  explicit reopen source when needed.

### Why this should stay small

The base class should not start with:

- widget binding helpers
- undo/redo infrastructure
- observer/event systems
- schema registries
- parser APIs
- migration frameworks

Those may become necessary later, but they are not part of the smallest clear pilot.


## Recommended Canonical State Shape

Use a plain nested Python structure composed only of TOML/JSON-friendly values.

Recommended top-level shape for a recreated feature codec:

```python
{
    "feature": "table",
    "state_version": 1,
    "settings": {},
    "items": [],
    "ui": {},
}
```

### Optional `command` discriminator

Single-feature codecs such as `TableCodec` or `FigureFeatureCodec` generally do
not need a top-level `command` discriminator. The feature identity already tells the
codec what semantic object it is editing.

A top-level `command` field is still reasonable for a shared lightweight command codec
that groups several trivial visible Hyde commands.

Reasons:

- validation may need to branch on command family immediately
- normalization may need to know command family before filling defaults
- the resulting structure is clearer than burying the discriminator inside `settings`

### Field roles

- `feature`: stable feature identifier
- `state_version`: schema version for the edit-state contract
- `command`: optional command-family or mode discriminator for shared command codecs
- `settings`: named scalar or structured settings
- `items`: ordered semantic records or names
- `ui`: transient GUI-only edit state

### Order semantics

Order is semantic only where represented explicitly by list order.

That means:

- `items` order matters
- dict insertion order must not carry semantic meaning
- if a widget presents ordered content, the controller must emit that order explicitly


## Mutation Model

`update_state(...)` should be action-based, not a generic dict merge.

Recommended action shape:

```python
{"type": "set", "path": ["settings", "title"], "value": "My Table"}
{"type": "clear", "path": ["settings", "title"]}
{"type": "append_item", "item": "wave0"}
{"type": "remove_item", "index": 1}
{"type": "move_item", "old_index": 2, "new_index": 0}
{"type": "patch_item", "index": 0, "patch": {"label": "signal"}}
```

For a shared trivial-command codec, an additional action such as
`{"type": "set_command", "command": "save_project"}` is reasonable.

Recommended rules:

- `update_state(...)` returns normalized state
- mutation is deterministic
- invalid actions fail clearly
- common action names are reused across features where practical

The GUI should construct these action dictionaries and pass them to the codec. The GUI
should not directly mutate deep state structure in many separate places.


## GUI Ownership Model

The right ownership split is:

### GUI layer owns

- widgets
- signal wiring
- one or more Hyde-specific `HydeGuiState` objects per command-emitting GUI class
- widget-to-state synchronization
- construction of action dictionaries
- display of validation failures
- transient selection and focus bookkeeping

### Hyde-specific `HydeGuiState` object owns

- the current local edit session state for that GUI surface
- the shared canonical state structure for that semantic feature
- calls into the associated `FeatureCodec`
- normalization / validation / code-generation requests through that codec
- `macro_source(...)` delegation where the codec supports recreation-source generation

`...State` objects do not own command dispatch, GUI warnings/confirmations, or
filesystem existence/overwrite checks. Those decisions remain in the owning GUI
surface, which may inspect the state and then decide whether to dispatch the
generated Python.

### Codec owns

- canonical edit-state schema
- default filling
- normalization
- validation
- mutation semantics
- lowering to Python

### Kernel or other backend signals own

- authoritative scientific state
- object identity and values
- any future reconstruction signals emitted from public Hyde APIs or metadata relays

This preserves Hyde's architecture: the GUI has edit memory, but not scientific
memory.


## Universal GUI-Side Rule

Hyde should adopt one explicit project-wide pattern.

### Command-emitting GUI classes

A command-emitting GUI class is a Hyde-owned window, dialog, or comparable interactive
surface that can generate Hyde-visible or Hyde-owned Python from user interaction.

These classes:

- live under `hyde/user_interface/...`
- are Hyde-specific subclasses of the appropriate Qt base classes
- must own the `HydeGuiState` instances required for the command domains they express

The corresponding `...State` classes should also live with Hyde's GUI-side code under
`hyde/user_interface/...`, typically alongside the GUI surfaces that use them.

When several GUI-side state classes share the same local state mechanics, they may
inherit from a Hyde-owned GUI-side base state class. That inheritance is distinct from
GUI/widget inheritance; the composition rule still applies to GUI surfaces.

This rule applies to complex feature windows and to simple dialogs such as file
selection dialogs that ultimately generate Hyde commands.

It does not imply that every child widget, `QAction`, or helper control owns its own
state object. Child widgets forward their events to the owning surface and its
state objects.

### File-dialog pattern

Very simple command-emitting dialogs may share a package such as
`hyde/user_interface/file_dialogs/`.

In that case the recommended structure is:

- one Hyde base file-dialog class
- a small set of narrow Hyde subclasses for cases such as new/load/save/heal

This is preferred over one large dialog class full of command-specific branching.

### No GUI-state inheritance

The GUI ownership rule is composition only:

- a command-emitting GUI class owns the Hyde-specific `HydeGuiState` instances
  required for its command domains

The GUI class does not also inherit from the state class. This keeps ownership clear
and avoids Qt multiple-inheritance coupling.


## Reverse Reconstruction

Different features are likely to reconstruct GUI-editable state from different sources:

- explicit public Hyde command semantics
- backend metadata notifications
- structured kernel responses
- feature-specific import routines
- parser-produced semantic payloads

If a specific feature needs reverse reconstruction, it may add a feature-specific hook
such as:

- `metadata_to_state(...)`
- `import_to_state(...)`
- `decode_to_state(...)`

But that should remain outside the required shared base interface.


## Scope For The `hyde_features.py` Pilot

The pilot should establish the pattern in the first credible Hyde setting where one
GUI surface both recreates a semantic object and issues live mutations.

### Recommended pilot scope

The pilot should use three layers rather than one omnibus codec:

- a `TableCodec` for recreated table state and `hyde.table(...)` generation
- a generic `MutationCodec` for live data-mutation Python generation
- a shared lightweight command codec for trivial visible commands such as
  `new_project`, `load_project`, `heal_project`, `save_project`, and `quit`

This better matches the intended long-term structure for figures and fits.

### Recommended exclusions from the pilot

Do not force these into the first pilot pass:

- procedure bootstrap helper generation
- remote request helper generation
- reverse parsers for reconstruction from arbitrary user Python
- generic persistence unification between recreation state and `session.toml`
- table eligibility predicates unless they are directly needed by state validation


## Proposed `TableCodec` State Shape

For the recreated table feature, a dedicated codec is the preferred pilot:

```python
{
    "feature": "table",
    "state_version": 1,
    "settings": {
        "command": "open",
        "target": None,
        "title": None,
        "geometry": None,
        "column_widths": {},
        "request_id": None,
    },
    "items": ["x", "y"],
    "ui": {},
}
```

Notes:

- `items` is primarily for argument order where it matters, especially `hyde.table(...)`
- `settings.command` selects the table command family
- `ui` remains optional and non-semantic

Expected table semantics:

- `items`: ordered object names
- `settings.command`: one of `open`, `append`, `push_table_data`, or
  `publish_table_macros`
- `settings.target`: optional existing table handle
- `settings.title`: optional visible title
- `settings.geometry`: optional `(x, y, width, height)` tuple for saved layout
- `settings.column_widths`: optional `{name: width}` mapping for saved layout
- `settings.request_id`: request token for background table-data or macro-publication
  requests

The same table state schema covers both semantic table definition and saved layout
needed to recreate a table window. That layout state is also stored in `session.toml`
for session restore in the current architecture.


## Proposed `TableState` Pattern

`TableState` is a `HydeGuiState` subclass for the table feature.

It is shared by every command-emitting GUI surface that expresses the table feature
when one table-state schema naturally covers those surfaces.

For the current planning direction:

- `NewTableDialog` should own `TableState`
- `TableWidget` should own `TableState`
- both should use `TableCodec`

This is desirable because both surfaces express the same `hyde.table(...)` language,
with the table widget acting as a semantic superset of the creation dialog.

`TableState` should therefore be able to represent:

- the selected ordered table items
- target table handle
- visible title
- saved table geometry
- saved data-column widths
- background table fetch / publication requests

At the same time, `TableState` should not become a bucket for transient widget-only
details that are not part of table semantics. Widget-local details such as current
selection focus, current edit text, and temporary menus should stay outside the
canonical semantic portion of `TableState` unless they are explicitly needed for
Hyde's recreation language.

## Proposed `MutationCodec` And `MutationState`

`MutationCodec` is the generic `FeatureCodec` subclass for GUI-driven data mutations.
`MutationState` is the matching `HydeGuiState` subclass.

The initial table implementation uses:

- `feature == "mutation"`
- `settings.command` as one of `edit_value`, `append_value`, `create_array`, or
  `delete_indices`
- `settings.var_name`, `settings.value_text`, `settings.index`, `settings.indices`,
  and `settings.existing_names` as the minimum mutation fields

`MutationCodec` owns literal parsing, generated-name selection, validation, and
lowering to explicit Python mutation strings. `TableWidget` owns `MutationState`
alongside `TableState`.


## Proposed `SimpleHydeCommandCodec` State Shape

For trivial visible command generation, a shared codec is reasonable:

```python
{
    "feature": "hyde_command",
    "state_version": 1,
    "command": "save_project",
    "settings": {
        "project_dir": None,
        "mode": "save",
        "overwrite": False,
        "load": True,
    },
    "items": [],
    "ui": {},
}
```

Expected command-family semantics:

#### `command == "new_project"`

- `settings.project_dir`
- `settings.load`
- `settings.overwrite`

#### `command == "load_project"`

- `settings.project_dir`

#### `command == "heal_project"`

- `settings.project_dir`

#### `command == "save_project"`

- `settings.project_dir`
- `settings.mode`
- `settings.overwrite`

#### `command == "quit"`

- no required items
- no required settings


## `state_to_python(...)` Contract

`state_to_python(...)` should emit standard Python source, not Hyde-internal wrapper
syntax.

Default expectation:

- visible GUI actions render one readable Python command string

Example outputs:

- `hyde.table(x, y, title='My Table')`
- `hyde.new_project('/tmp/demo.hy', load=True, overwrite=False)`
- `hyde.save_project(mode='save')`
- `hyde.quit()`

### Multiple render targets

Some features need more than one Python rendering target, such as:

- visible command string
- decorated macro source
- muted mutation command

The base interface stays small by giving codecs `state_to_python(...)` plus optional
`state_to_macro_source(...)`. The default purpose remains the visible command path.


## How GUI Code Should Bind To The Codec

The required pattern is:

1. A Hyde GUI surface owns the `HydeGuiState` objects required for its command domains.
2. Each `HydeGuiState` object uses its associated `FeatureCodec`.
3. Widget events are translated into action dictionaries and applied to the relevant
   state object.
4. The GUI surface requests Python generation from those state objects.

For example, the current New Table dialog should evolve from:

- direct table command-string formatting

toward:

- a `TableState` instance owned by the dialog
- one explicit dependency from `TableState` to `TableCodec`
- action-based updates from selection/title widgets into `TableState`
- a final Python-generation request through `TableState`

The table widget should follow the same pattern and should own:

- one `TableState` for table construction, recreation, and saved layout
- one `MutationState` for live data edits

No table or mutation Python generation should live in free helper functions once this
pattern is adopted.

No PyQt classes should be imported into the codec layer.


## Important Practical Rule About Ordering

The user already identified a real issue: order matters.

For Hyde, that means the state language must preserve:

- user-chosen item order
- stable generated argument order
- deterministic reordering behavior

This should be solved in the state shape itself, not by relying on dict insertion order
or the incidental ordering returned by PyQt selection APIs.

If a widget does not naturally preserve user order, the owning GUI surface and its
state object must define an explicit policy such as:

- use current list display order
- use explicit move-up / move-down actions
- use append order when selections are added


## Validation And Errors

Initial validation can stay simple.

Recommended behavior:

- `normalize_state(...)` first
- `validate_state(...)` second
- `state_to_python(...)` assumes normalized valid input

Recommended failure style for the pilot:

- raise `ValueError` with concrete, GUI-displayable messages

Do not build a large structured error framework in the first pass unless the GUI
actually needs it.


## Recommended Test Contract

When implementation starts, tests should lock down the contract rather than the
internal class layout.

### Shared codec tests

- `default_state()` returns a fresh object each time
- normalization fills defaults predictably
- malformed states fail validation
- identical semantic inputs normalize to the same canonical state
- `update_state(...)` is deterministic
- ordered item operations preserve exact order

### `TableCodec` and `MutationCodec` pilot tests

- table state lowers to the expected `hyde.table(...)` string
- table macro source includes non-default layout only when present
- table GUI/editor entry points can share the same `TableState` schema
- ordered item updates preserve exact argument order
- the simpler table dialog can edit a subset of `TableState`
- the richer table widget can edit a superset of that same state
- mutation state lowers edit, append, create-array, and delete commands deterministically

### `SimpleHydeCommandCodec` pilot tests

- project command states lower to the expected visible commands
- invalid command/state combinations fail clearly
- `set_command` resets or normalizes command-specific defaults correctly
- repeated normalization is idempotent
- generated Python is deterministic for a fixed canonical state


## Recommendation

The best next implementation shape is:

1. Add a very small shared codec base class.
2. Add `state_to_macro_source(...)` as the optional recreation-source interface on that
   base class.
3. Add one codec subclass per recreated feature source such as table, figure, or fit.
4. Add one generic `MutationCodec` for reusable data-mutation command generation.
5. Add Hyde-specific `HydeGuiState` subclasses such as `TableState` and `MutationState`
   where GUI surfaces need shared local edit state.
6. Require every command-emitting Hyde GUI class to own the state objects required for
   its command domains.
7. Share those state classes across GUI surfaces when one semantic schema naturally
   covers them.
8. Add one shared lightweight codec for trivial visible Hyde commands.
9. Leave reverse reconstruction feature-specific.

This gives Hyde a real state-language pilot without overcommitting to a large framework
before figures and fitting reveal the true pressure points.
