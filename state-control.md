# Stateful Control Pattern For Hyde Features

## Purpose

This document defines the planning direction for a state-centered control pattern in
`hyde/features/*_features.py`.

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

Each recreated semantic feature should own its own `FeatureCodec` subclass. Multiple
GUI classes may participate in editing that feature, but they should all talk to the
same codec for that feature.

That codec owns:

- default edit state
- normalization
- validation
- deterministic state mutation
- Python generation

### 2. Do not force every string builder into the codec abstraction

The codec pattern should apply to GUI features, not to every trivial
one-shot helper.

In particular, runtime-helper transport strings such as:

- procedure bootstrap code
- table-data fetch requests
- remote request forwarding
- menu-registry publication

should not be forced through `update_state(...)`. They are transport/plumbing helpers,
not GUI-edit languages.

### 3. Use feature-specific codecs for recreated features

Every recreated source should have its own codec class, for example:

- `TableFeatureCodec`
- `FigureFeatureCodec`
- `FitFeatureCodec`

This keeps each GUI/editor surface coupled to one semantic owner rather than to a
shared omnibus codec.

### 4. Use a shared lightweight codec only for trivial visible commands

Fairly trivial visible command generation such as:

- `new_project`
- `load_project`
- `heal_project`
- `save_project`
- `quit`

may share a small command-oriented codec because these commands do not define the same
kind of recreated feature state as tables, figures, or fits.

### 5. Do not require a universal reverse parser

The common interface should be forward-oriented:

- GUI edit state -> Python

Reverse reconstruction remains feature-specific. Some features may reconstruct state
from metadata, some from explicit backend notifications, some from command semantics,
and some from parser-produced structures. Hyde should not impose one reverse mechanism
before the real features demand it.


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
```

### Why this is enough

- `default_state()` gives each editor a fresh starting point.
- `normalize_state()` lets the codec fill defaults and canonicalize shape before later
  steps.
- `validate_state()` makes failures explicit and testable.
- `update_state()` supports rich GUI mutation without ad hoc dict manipulation spread
  across widgets.
- `state_to_python()` keeps Hyde's string-factory rule intact.

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

Single-feature codecs such as `TableFeatureCodec` or `FigureFeatureCodec` generally do
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
- local editor/controller state
- construction of action dictionaries
- display of validation failures
- transient selection and focus bookkeeping

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

The pilot should establish the pattern in the simplest credible Hyde setting without
forcing unrelated helpers into it.

### Recommended pilot scope

The pilot should use two layers rather than one omnibus codec:

- a `TableFeatureCodec` for recreated table state and `hyde.table(...)` generation
- a shared lightweight command codec for trivial visible commands such as
  `new_project`, `load_project`, `heal_project`, `save_project`, and `quit`

This better matches the intended long-term structure for figures and fits.

### Recommended exclusions from the pilot

Do not force these into the first codec:

- procedure bootstrap helper generation
- remote request helper generation
- table-data fetch relay generation
- table macro publication helper generation
- table cell edit / append / delete micro-mutations
- name-suggestion helpers
- data-browser eligibility predicates

Reasons:

- runtime-helper transport strings are not GUI edit languages
- table cell mutations are a separate table-editor feature surface
- eligibility predicates are validation/support logic, not command-family state

The pilot remains meaningful if it narrows `hyde_features.py` to the visible public
Hyde command path and leaves other helpers outside that boundary or moves them later.


## Proposed `TableFeatureCodec` State Shape

For the recreated table feature, a dedicated codec is the preferred pilot:

```python
{
    "feature": "table",
    "state_version": 1,
    "settings": {
        "target": None,
        "title": None,
    },
    "items": ["x", "y"],
    "ui": {},
}
```

Notes:

- `items` is primarily for argument order where it matters, especially `hyde.table(...)`
- `settings` is feature-specific rather than command-family-specific
- `ui` remains optional and non-semantic

Expected table semantics:

- `items`: ordered object names
- `settings.target`: optional existing table handle
- `settings.title`: optional visible title


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

Some features may later need more than one Python rendering target, such as:

- visible command string
- decorated macro source
- muted mutation command

The base interface can still stay small if `context` selects the rendering purpose.
The default purpose should remain the visible command path.


## How GUI Code Should Bind To The Codec

Do not build a generic widget-binding framework yet.

The smallest workable pattern is a local controller/presenter per editor or dialog:

- it holds the current state
- it converts widget events into action dictionaries
- it calls `codec.update_state(...)`
- it repopulates widgets from normalized state when needed
- it calls `codec.state_to_python(...)` when dispatch is requested

For example, the current New Table dialog should evolve from:

- direct calls to `format_table_command(...)`
- direct use of `is_eligible_for_table(...)`

toward:

- a local state object
- one explicit dependency on `TableFeatureCodec`
- action-based updates from selection/title widgets
- a final `state_to_python(...)` call

No PyQt classes should be imported into the codec layer.


## Important Practical Rule About Ordering

The user already identified a real issue: order matters.

For Hyde, that means the state language must preserve:

- user-chosen item order
- stable generated argument order
- deterministic reordering behavior

This should be solved in the state shape itself, not by relying on dict insertion order
or the incidental ordering returned by PyQt selection APIs.

If a widget does not naturally preserve user order, the GUI controller must define an
explicit policy such as:

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

### `TableFeatureCodec` pilot tests

- table state lowers to the expected `hyde.table(...)` string
- table GUI/editor entry points can share the same codec contract
- ordered item updates preserve exact argument order

### `SimpleHydeCommandCodec` pilot tests

- project command states lower to the expected visible commands
- invalid command/state combinations fail clearly
- `set_command` resets or normalizes command-specific defaults correctly
- repeated normalization is idempotent
- generated Python is deterministic for a fixed canonical state


## Recommendation

The best next implementation shape is:

1. Add a very small shared codec base class.
2. Add one codec subclass per recreated feature source such as table, figure, or fit.
3. Add one shared lightweight codec for trivial visible Hyde commands.
4. Keep runtime-helper transport helpers outside the codec boundary.
5. Leave reverse reconstruction feature-specific.
6. Introduce local GUI controllers where needed rather than a global binding framework.

This gives Hyde a real state-language pilot without overcommitting to a large framework
before figures and fitting reveal the true pressure points.
