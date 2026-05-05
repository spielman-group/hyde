## Problem Statement

Hyde needs a figure system that satisfies four constraints at the same time:

- figures must be ordinary `matplotlib` figures created with standard user code such as
  `plt.figure()`, `fig.add_subplot(...)`, and `ax.plot(...)`
- the GUI must remain a viewport and command surface rather than becoming the owner of
  scientific or plotting state
- figures must support saved recreation macros and prompt GUI editing soon after v1,
  especially trace-level editing like the planned trace editor
- the base architecture must stay simple enough that GridSpec subplots, richer figure
  editing, and later figure persistence on shutdown can be layered on without a redesign

The key architectural fact is that `matplotlib` already has a kernel-side global figure
registry. Hyde should use that registry and the live kernel-side `Figure` instance as
the runtime source of truth for drawing, resize, close, and export behavior.

The second key fact is that runtime truth and recreation/editability truth are not the
same thing. A live `Figure` is the right runtime object, but GUI editing and saved
recreation macros need a canonical representation that can:

- replace semantic effects rather than append more source lines
- preserve ordering relative to unsupported operations
- lower back to standard matplotlib Python source
- remain attached to the figure rather than to the GUI

Across Hyde, "IR" means internal representation or internal state in the same sense as
the existing `features/...` state-to-Python path used today. It is not globally
synonymous with kernel-owned state. Depending on the feature, that internal
representation may live in the GUI or the kernel. For the figure feature specifically,
this PRD chooses a kernel-owned figure-local IR attached directly to the live figure.

The figure feature therefore needs a kernel-owned canonical figure IR attached directly
to the live figure object, with the GUI editing that IR over `comm` channels through
high-level semantic actions.

## Solution

Implement a dedicated Hyde matplotlib backend that creates transparent Hyde-instrumented
matplotlib subclasses while preserving standard user-facing matplotlib syntax.

The runtime and authoring model should be:

- all Hyde-backend figures open as native MDI figure windows in the GUI
- first-class Hyde figures are created through `@hyde.figure`
- each first-class Hyde figure is backed by exactly one live kernel `Figure`
- the live kernel `Figure` is the runtime truth
- a kernel-owned canonical figure IR attached to that `Figure` is the
  recreation/editability truth
- a backend-owned command log attached to that `Figure` records canonical observed
  plotting operations in parallel
- preserved source and AST artifacts may be kept for diagnostics and future tooling,
  but they are not authoritative

GUI figure editing is not performed by rewriting Python source in the GUI. Instead:

- the GUI sends semantic figure-edit actions over Jupyter `comm`
- the kernel mutates the authoritative IR attached to the figure
- the kernel applies the corresponding live matplotlib mutation when practical
- the kernel may regenerate the figure from the IR for operations that are semantically
  simple but operationally awkward to patch live
- the GUI remains a viewport and command source, not a semantic mirror

Saved recreation macros are generated from the authoritative IR only. Preserved raw
source is allowed only as IR node content, never as an external fallback outside the IR.

## Core Architecture

### Runtime Truth

The runtime truth of an open figure is the live kernel-side matplotlib `Figure`
instance. Hyde should maintain a strict 1:1 relationship between:

- the matplotlib global registry key
- the live kernel-side `Figure`
- the GUI `FigureWindow`

Hyde should not introduce a second GUI-owned semantic figure model for redraw, resize,
export, close, or ordinary interaction behavior.

### Recreation And Editability Truth

The recreation and GUI-editability truth of a first-class Hyde figure is a
kernel-owned canonical IR attached directly to the live figure object, for example:

- `fig._hyde_ir`

The IR must be fully self-sufficient for macro generation.

Preserved raw source is allowed only as data inside IR nodes. Hyde must not depend on
an external raw-source fallback to recreate a figure once the IR exists.

### Auxiliary Artifacts

The backend may also attach:

- `fig._hyde_command_log`
- `fig._hyde_source_artifact`
- `fig._hyde_ast_artifact`

These are artifacts, not authoritative state.

The command log is useful for debugging, diagnostics, replay tracing, validation, and
future conversion of second-class figures. The captured source and AST are useful for
debugging, unsupported-operation preservation, and future tooling. None of them outrank
the IR once the figure exists.

## Figure Classes

The Hyde backend should use transparent subclasses of relevant matplotlib classes such
as:

- `Figure`
- `Axes`
- selected artist classes or figure/axes methods involved in the supported figure IR

This instrumentation must be invisible to the user. User code must remain standard
matplotlib code:

```python
fig = plt.figure()
ax = fig.add_subplot(111)
ax.plot(x, y)
```

Standard matplotlib interoperability is mandatory. Hyde is allowed to introduce
transparent subclasses and internal instrumentation, but not user-facing plotting
dialects or Hyde-specific object-creation APIs for normal figure construction.

## First-Class And Second-Class Figures

All Hyde-backend figures should render in Hyde figure windows through the same runtime
backend path.

However, first-class recreatable and editable figures in this deployment are only those
created through `@hyde.figure`.

That means:

- a first-class Hyde figure is guaranteed to have a canonical IR suitable for saved
  recreation macros and semantic GUI editing
- a non-decorated Hyde-backend figure may still render live in the GUI, but it is a
  second-class figure for now
- second-class figures may later be converted into first-class figures, potentially
  with some loss of information, but that conversion path is not part of this PRD

This PRD should optimize the architecture for first-class decorated figures.

## `@hyde.figure` Contract

`@hyde.figure` is the first-class figure creation entry point for Hyde.

It decorates an ordinary Python function that builds a matplotlib figure using standard
matplotlib code.

The decorated function may:

- explicitly return the created figure
- omit the return value, in which case Hyde resolves the figure from the decorated build
  session through the instrumented backend and registry

The decorated function must create exactly one first-class Hyde figure.

These are errors:

- zero figures created
- more than one figure created
- no resolvable active figure at the end of the decorated build session

The decorator should:

- start a Hyde figure build session
- execute the user function
- resolve exactly one live figure from that session
- ensure the figure is Hyde-instrumented
- ensure the figure has an authoritative IR and command log
- preserve source and AST artifacts for diagnostics and future tooling

The decorator should not be the thing that creates the command log conditionally. The
backend and instrumented figure objects own logging. The decorator creates a first-class
build session and stronger first-class guarantees.

## Authoritative IR

### Required Shape

The canonical IR should already be shaped for future subplot growth even though v1 only
allows one subplot in practice.

The required high-level shape is:

- `FigureIR`
- `LayoutIR`
- `SubplotIR[]`
- `TraceIR[]`

In v1:

- validation should require exactly one subplot
- the single subplot should correspond to the current `111`-equivalent editing scope
- subplot machinery should already exist so later GridSpec deployment is additive rather
  than a schema rewrite

### Required Properties

The IR must:

- be attached directly to the live figure
- be fully self-sufficient for recreation macro generation
- support semantic replacement of properties such as axis limits
- support embedded opaque nodes as part of the IR
- support ordered lowering back to standard matplotlib Python source
- make prompt follow-on work such as the trace edit dialog straightforward

### Opaque Nodes

The IR may include opaque preserved-source nodes, but only as IR nodes.

These opaque nodes are:

- part of the authoritative IR
- preserved in ordering relative to semantic nodes
- non-editable by GUI tools
- emitted back into recreated macro source at their defined positions

The correct ordering model is therefore:

- semantic structured containers such as figure, subplot, and trace nodes
- plus ordered opaque leaf nodes embedded at specific insertion points inside those
  containers

The IR must not degrade into a raw ordered source list. Semantic nodes remain first
class.

## Command Log

The backend should maintain a parallel figure-local command log, for example:

- `fig._hyde_command_log`

The command log should be recorded for first-class figures by the instrumented backend
and instrumented matplotlib objects while the decorated function executes.

The command log should store both:

- structured canonical replay records suitable for machine use
- canonical source rendering suitable for debugging and readable replay

The command log is not the authority for recreation/editability once the IR exists, but
it should remain available for:

- diagnostics
- debugging
- validation
- replay tracing
- future conversion/import tooling

## IR Initialization

IR initialization during a decorated build session should be driven by observed
instrumented matplotlib calls only.

That means:

- the user writes ordinary matplotlib code
- the function executes
- Hyde-instrumented figure/axes methods fire during execution
- the backend updates the IR incrementally as those observed calls happen
- the backend records the command log in parallel

Source and AST are preserved as artifacts, but do not initialize the authoritative IR.

## GUI Boundary

The GUI figure window is a viewport and event source only.

It may own:

- window geometry
- focus
- visibility
- toolbar or debug-state concerns
- transient UI state needed to emit a semantic edit request

It must not own:

- canonical figure IR
- canonical plot structure
- scientific data
- arrays
- artist truth

The GUI must not maintain a mirrored semantic figure state as the source of recreation
or editing behavior.

## GUI Edit Transport

Figure editing should use a dedicated Jupyter `comm` action protocol, not Python
snippets and not `ProcessTree` relays.

The GUI should send semantic action payloads such as:

- set axis limits
- set axis labels
- set figure or subplot title
- mutate trace styling
- toggle legend
- request full regeneration from IR as a debug action

Python-source generation remains for:

- saved recreation macros
- debugging
- explicit regenerate-from-IR workflows

Routine GUI editing should operate through semantic `comm` actions only.

This figure edit protocol is a private Hyde service in v1, not a public user API.

## Kernel Edit Semantics

Each semantic GUI edit should be handled in the kernel as a transaction against the
live figure and the authoritative IR.

The normal flow is:

1. receive semantic action over `comm`
2. resolve target figure from registry identity
3. mutate the authoritative IR on that figure
4. apply the corresponding live matplotlib mutation when practical
5. redraw and publish the updated render and metadata

The kernel edit path should support two execution strategies:

- `apply_live_patch`
- `regenerate_from_ir`

Direct live mutation is preferred for edits such as:

- trace styling
- axis labels
- axis limits
- title changes
- legend toggles

Full regeneration from IR is allowed for edits that are semantically clear but
operationally awkward to patch live.

The figure windows should also expose a useful debug action to force regeneration from
the IR, since this costs little additional architecture and exercises the IR-to-source
and IR-to-figure path explicitly.

## Macro Generation

Saved figure recreation macros are generated from the authoritative IR only.

The output must be standard matplotlib and numpy Python code with no Hyde plotting
dialect.

Hyde should still prefer explicit object-oriented matplotlib style in the generated
source, such as:

- `fig = plt.figure(...)`
- `ax = fig.add_subplot(...)`
- `ax.plot(...)`
- `ax.set_xlim(...)`

When later GUI-authored figure layout exceeds the single-subplot case, recreated code
should prefer explicit `GridSpec`-style construction rather than compact implicit
subplot codes.

Saved figure macros should follow the existing table-macro persistence pattern:

- bounded source written into `procedures/__init__.py`
- procedures reload path triggered
- graph macro registry republished
- `Windows -> Graph Macros` menu updated

Graph macros are explicit reproducibility artifacts. They are not the authoritative live
state of an already-open figure.

## Figure Window Behavior

The figure window must be a native MDI child window in the GUI process.

It should:

- display the current rendered image from the live kernel figure
- resize smoothly, optionally with temporary local stretching during drag
- request a proper redraw of the same live kernel figure at the settled size
- coordinate kernel-side close with GUI-side close
- prompt to save a recreation macro on close through the generic save-window pattern
- support shift-click hide if the generic saveable-window behavior is enabled for
  figures

The settled redraw after resize must always come from the live figure object, not from a
GUI-owned semantic figure reconstruction.

## Initial Semantic Surface

The initial GUI editing surface should remain narrow but real.

The initial authoritative IR and semantic edit contract must support, at minimum:

- one figure
- one subplot in v1
- zero or more line traces
- subplot title
- x label
- y label
- x limits
- y limits
- legend enable/disable
- trace properties needed to make the prompt follow-on trace editor straightforward,
  such as at least one styling property like marker type or trace color

This is the minimum useful semantic layer that keeps the current PRD compatible with the
planned trace editor while leaving subplot growth additive.

## Future-Proofing Requirements

This PRD should explicitly preserve the following future paths:

- GridSpec-based multi-subplot support soon after v1
- trace editing dialogs operating on first-class trace nodes inside the IR
- richer axis and trace editing surfaces
- possible later persistence of live figures on shutdown using the same IR that already
  powers recreation macros

The base deployment should not require a schema rewrite to support `figure -> layout ->
subplots -> traces`.

## User Stories

1. As a user, I want to write standard matplotlib code inside a decorated Python
   function so that Hyde figures remain fully compatible with the normal matplotlib
   ecosystem.
2. As a user, I want my Hyde figures to appear as native MDI child windows in the GUI
   so that they integrate with the rest of Hyde.
3. As an architect, I want the GUI figure window to remain a viewport and event source
   so that canonical figure structure stays in the kernel.
4. As a developer, I want the live kernel `Figure` to be the runtime truth so that
   resize, redraw, export, and close stay simple and local to the figure object.
5. As a developer, I want a canonical kernel-owned IR attached directly to the figure
   so that recreation macros and GUI edits are authoritative without depending on the
   GUI or on brittle raw-source rewriting.
6. As a user, I want GUI edits like setting x limits to replace the current semantic
   effect rather than append yet another command, so that GUI editing feels first class.
7. As a developer, I want the IR to be self-sufficient for macro generation so that
   future persistence does not depend on external source history.
8. As a user, I want to save a figure recreation macro on close and reopen it from
   `Windows -> Graph Macros`.
9. As a developer, I want the first deployed IR shape to already support future
   GridSpec subplot growth and prompt trace-edit work, so that later features are
   additive rather than architectural rewrites.

## Testing Decisions

- **What makes a good test:** Tests should verify backend behavior, registry identity,
  IR authority, command-log capture, GUI-to-kernel edit protocol, and saved-macro
  generation without over-coupling to exact pixels.
- **Core behaviors to test:**
  - `@hyde.figure` decorated functions resolve exactly one figure
  - zero-figure and multi-figure decorated build sessions fail clearly
  - the backend creates transparent Hyde-instrumented figure objects
  - the live figure, registry identity, and GUI window stay in strict 1:1 relation
  - the IR is attached directly to the live figure
  - the command log is attached directly to the live figure
  - IR initialization is driven by observed instrumented plotting calls
  - saved macro generation uses the IR only
  - opaque IR nodes survive macro generation in-order
  - semantic GUI edit actions mutate both the IR and the live figure
  - direct live patch is used where expected
  - full regenerate-from-IR works as a supported fallback
  - the debug regenerate-from-IR action works
  - close-time save prompt, macro persistence, and `Windows -> Graph Macros` refresh
    match the existing table pattern
- **Prior art:** Existing tests for table macros, recreation registry behavior,
  save-window prompting, and project save/load should be reused as structure where
  possible.

## Out Of Scope

- making second-class non-decorated figures fully recreatable in this deployment
- inferring complete semantic dependency graphs for arbitrary undecorated matplotlib
  figures
- exposing the private figure edit protocol as a public Hyde API
- a full matplotlib scene-graph decompiler
- advanced multi-subplot editing UI in this deployment
- advanced axis editing dialogs in this deployment
- interactive graph cursors in this deployment, though the backend must not block them
- monkey-patching existing matplotlib backends at runtime
- migration shims from older designs

## Further Notes

- The main simplification is to separate runtime truth from recreation truth cleanly:
  runtime truth is the live figure; recreation/editability truth is the IR on that
  figure.
- The GUI is still a string factory in the broader Hyde sense, but routine figure
  editing should use semantic `comm` actions rather than ad hoc Python code emission.
- This is one of the few places where Hyde should lean into a richer kernel-side model,
  because saved figure macros and prompt figure-edit tooling need semantic replacement
  behavior that raw source and raw command logging do not provide by themselves.
- The implementation must strictly follow `project_management/ARCHITECTURE.md` and
  `project_management/STYLE.md`.
