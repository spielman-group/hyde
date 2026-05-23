# Figure Window Specification

## Feature Checklist
- [x] Open first-class `@hyde.figure` figures as native MDI figure windows.
- [x] Treat the live kernel `Figure` as the runtime authority for draw, resize, close,
  and export.
- [x] Treat a kernel-owned IR attached to the live figure as the recreation and
  editability authority for first-class figures.
- [x] Keep first-class editable and recreatable figures on the `@hyde.figure` path.
- [x] Route routine figure edits through Hyde's command-driven hidden Python path.
- [x] Support save-on-close figure macro prompts through the generic save-window
  pattern.
- [x] Support explicit refresh/regenerate through Hyde's ordinary hidden command path.
- [ ] Support GridSpec multi-subplot figure editing.
- [ ] Define any future explicit promotion/import workflow for non-decorated figures.

## Purpose

The Figure window is Hyde's native MDI viewport for first-class `@hyde.figure`
figures owned by the kernel.

The runtime truth of an open Hyde figure window is the live kernel-side matplotlib
`Figure` registered in matplotlib's global figure registry. Hyde maintains a strict
1:1 relationship between:

- the matplotlib global registry key
- the live kernel `Figure`
- the GUI Figure window

Only first-class `@hyde.figure` figures participate in that relationship in the
initial deployment. Non-decorated figures remain ordinary kernel-side matplotlib
figures and do not open Hyde figure windows.

For generic MDI behavior, saved macros, and `session.py` restore source, the stable
figure window identity is the `QMdiSubWindow.objectName()` string, for example
`Figure0`.

Hyde generates table and figure subwindow names through one shared naming path.
Figures use the `Figure` prefix and tables use the `Table` prefix.

For first-class figures, this stable `objectName()` is also the base user-facing
figure name used in recreation source, for example `plt.figure("Figure0")`.
When figure creation requests a preferred figure name, Hyde accepts it if it is free;
otherwise Hyde falls forward to the next available figure name and rewrites the live
kernel figure label plus saved recreation source to that resolved stable name.
The GUI window title is derived presentation text. It begins with the stable
`objectName()` and may append `": ..."` detail text without changing the figure's MDI
identity. Any caller-provided title text is suffix-only additional detail, not a
replacement title.

The GUI does not own canonical plot structure, artist state, or recreation source.
For first-class figures, the recreation and editability truth is a kernel-owned IR
attached directly to the live figure, for example `fig._hyde_ir`.

In this figure feature, `IR` means the same kind of canonical internal state that the
table feature uses in its state-to-Python path, but moved to the correct side of the
architecture. The table GUI owns transient internal state long enough to generate
Python. The figure feature instead keeps its authoritative internal state in the
kernel on the figure itself because figure editing and recreation must remain attached
to the live kernel figure.

## Initial Deployment Scope

The initial deployment provides a live Hyde figure window only for first-class
`@hyde.figure` figures.

It includes:

- live rendering of first-class `@hyde.figure` figures inside native MDI windows
- resize redraw using the same live kernel `Figure`
- close coordination between the MDI window and the kernel-side figure registry entry
- export from the live kernel `Figure`
- save-on-close recreation macro prompts for first-class figures
- `Windows -> Graph Macros` integration for saved recreation macros
- explicit refresh/regenerate debug support
- first-class recreation and command-driven GUI editing for figures created through
  `@hyde.figure`
- a first-class figure-edit surface shaped as `FigureIR -> LayoutIR -> SubplotIR[] ->
  TraceIR[]`, with v1 constrained to exactly one subplot
- v1 supported edit/import surface for:
  - one subplot
  - zero or more line traces
  - subplot title
  - x label
  - y label
  - x limits
  - y limits
  - legend enabled/disabled
  - at least the trace properties needed by the initial trace edit dialog

It does not include:

- GUI-owned figure state as the source of redraw or recreation
- GUI-side source rewriting for figure edits
- Hyde MDI figure windows for non-`@hyde.figure` figures
- multi-subplot GUI editing in the initial deployment
- arbitrary artist editing beyond the supported v1 figure-edit surface

## Window Layout

The Figure window is an MDI child containing:

- the rendered matplotlib figure canvas
- figure-window controls or menus that operate on the active figure
- a title bar whose base text is the stable figure `objectName()` and which may append
  descriptive suffix text supplied as additional detail rather than replacement title
  text
- close behavior integrated with the generic saveable-window flow for first-class
  figures
- title-bar warning text when Hyde cannot yet lower complete recreation source for the
  active first-class figure

The window may cache transient viewport concerns such as:

- geometry
- focus
- visibility
- `window_pos`
- `window_state='minimized'` or `window_state='maximized'`
- temporary resize/stretch presentation during drag

The window does not cache authoritative scientific state or canonical plot structure.

## Visible Controls

- Figure canvas: `active`
  - shows the current rendered output of the live kernel `Figure`
- Window close button: `active`
  - closes the figure through Hyde's saveable-window policy
- `Save Figure Macro...` action: `active`
  - available for first-class figures
- `Save Graphics...` action: `active`
  - available for the active first-class figure window
- `Regenerate From IR` debug action: `active`
  - forces kernel-side full regeneration from the authoritative IR
- figure-edit entry points such as trace editing: `active`
  - active only when the selected figure and target node are first-class and supported

No GUI-side editable source box, IR inspector, or raw matplotlib command editor is
part of the initial deployment.

## Editable Operations

The Figure window itself is primarily a viewport. Supported live edits in the initial
deployment are launched from figure-related dialogs and target the kernel-owned IR for
first-class figures.

Those dialogs do not own raw figure draft dictionaries. They open one
consumer-agnostic figure edit session from the active figure context and use that
session's getters, mutators, and preview/source helpers to build canonical
matplotlib patch Python.

Those edits target:

- `FigureIR`
- the single supported `SubplotIR`
- supported `TraceIR` nodes within that subplot

The Python-level effect of a successful edit is a kernel-side mutation of the live
matplotlib objects associated with the edited IR node, plus a redraw of the affected
figure.

The Figure window never becomes the authority for those edits. It only identifies the
active figure and launches the correct figure-edit surface.

## Context Menu And Window Actions

The active figure window exposes figure-scoped actions that operate against the active
window selected in the MDI workspace and resolve to the live figure through Hyde's
existing runtime figure-routing path.

Initial actions are:

- `Save Figure Macro...`
- `Save Graphics...`
- `Edit Trace...` when a supported trace target exists
- `Regenerate From IR`

These actions are scoped to the active figure window only. They do not operate on
other figures implicitly. User-facing recreation source keeps the stable
`objectName()`-derived figure name, while live GUI routing continues to resolve the
active runtime figure through the current matplotlib registry identity.

## Command Generation

The Figure window does not own figure mutation logic, but Hyde does regenerate Python
in the GUI for routine figure editing.

Its command responsibilities are:

- figure creation and saved macro publication lower bounded internal state into
  explicit matplotlib Python source
- routine figure-edit dialogs lower imported figure state plus current dialog draft
  into minimal matplotlib patch Python
- `Do It`, live update, `Cancel` rollback, and `To Cmd Line` all use that same
  command-generation model for the dialog-owned region
- explicit refresh/regenerate lowers to Hyde's ordinary hidden command path instead of
  using a private routine figure-action transport

The figure-specific meaning of `IR` should stay aligned with Hyde's existing
state-control language:

- for tables, "internal state" is the canonical state representation used by the GUI
  state/codec pair to generate Python
- for figures, "IR" is the same kind of canonical internal state representation, but
  it is authoritative in the kernel on the live figure because figures must remain
  synchronized with live matplotlib objects and future figure editors

Saved figure macros are generated from `fig._hyde_ir` only. They lower to ordinary
object-oriented matplotlib Python source and are written into the project's bounded
macro block in `procedures/__init__.py`.

The figure-edit session boundary is intentionally consumer-agnostic. Axis editing,
trace appearance editing, and attached Curve Fit display all use the same session
entry point and generic figure operations rather than consumer-specific figure
services.

Project session restore uses the same lower-level recreation-source builder in
`session.py`, wrapped as `@hyde.figure(..., register=False)` and invoked after project
activation so first-class figures reopen through the same figure-building path.

## Default-Diff Lowering

First-class figures carry two distinct kernel-owned figure-edit artifacts:

- `fig._hyde_ir`: the canonical figure state used for editing and regeneration
- `fig._hyde_defaults`: a snapshot of the effective matplotlib defaults that were
  current in the kernel for this figure family when the figure was built or refreshed

`fig._hyde_defaults` is not a GUI-owned guess and not a hardcoded Hyde table of
matplotlib defaults. It is a kernel-side snapshot of the current effective defaults in
the running matplotlib environment, including active rcParams, style sheets, and the
current property cycler semantics that affect ordinary first-class figure lowering.

This defaults snapshot exists for three reasons:

1. user-facing source should look like code a human would write against the current
   matplotlib defaults rather than a full serialization of every effective property
2. figure-edit dialogs must seed their controls from "defaults plus current
   non-default overrides" rather than from Hyde's own hardcoded schema defaults
3. regeneration and saved-macro lowering need one stable comparison baseline for the
   lifetime of the dialog or snapshot that produced them

The contract is:

- the kernel snapshots the current effective defaults for first-class figures
- the GUI receives that snapshot as ordinary figure-window metadata
- axis and trace dialogs seed their initial controls from the defaults snapshot plus
  the current figure state
- preview source, saveable macro source, and session restore source all lower as a diff
  against that defaults snapshot
- properties that match the current kernel defaults are omitted from lowered source
  even if the user explicitly set them back to the default value

Examples of intended omission behavior:

- do not emit `ax.set_title(...)` when the subplot title is still the default blank
  title
- do not emit trace color, linewidth, or marker properties when they match the current
  effective matplotlib defaults for that trace index
- do not emit axis label position, tick direction, spine visibility, or other axis
  presentation calls when they still match the current defaults snapshot

This is a figure-wide rule, not an axis-dialog-specific rule. Any Hyde figure feature
that produces user-facing matplotlib source must compare against the kernel-owned
defaults snapshot rather than lowering a full effective state dump.

## Edit Session Boundary

The active editable figure context exports one `open_session()` entry point.

That session:

- is ephemeral per dialog opening
- is plain Python, not a Qt object
- owns current/opening/revert figure edit state
- exposes fine-grained getters over first-class figure state
- exposes generic figure mutators, including trace and attribute-path line
  operations needed by current figure consumers
- owns preview/source generation
- does not own a second transport lifecycle; dialogs execute the emitted hidden or
  visible Python through Hyde's ordinary command interfaces

Consumer dialogs may wrap those fine-grained getters into higher-level local helpers,
but they do not treat raw `figure_ir` dictionaries as their edit contract.

## Synchronization

The figure window synchronizes against the kernel over Jupyter `comm` channels.

The synchronization contract is:

- the kernel owns the live matplotlib `Figure`
- the kernel owns the authoritative `fig._hyde_ir`
- the kernel owns the effective-defaults snapshot `fig._hyde_defaults`
- the kernel may also retain `fig._hyde_command_log` plus preserved source and AST
  artifacts for diagnostics
- the GUI receives only the metadata and rendered output needed to display the figure
  and launch valid edits
- only first-class `@hyde.figure` figures publish figure-window metadata over this lane

Resize behavior follows this sequence:

1. the GUI window resizes locally
2. the GUI notifies the kernel of the settled target size
3. the kernel redraws the same live `Figure`
4. the GUI displays the updated render

Edit behavior follows this sequence:

1. the dialog reads imported figure state through the active edit session
2. the dialog lowers its current draft into a minimal matplotlib patch block
3. Hyde executes that block through the ordinary hidden or visible command path
4. the backend resyncs dirty first-class figures from the live matplotlib object graph
5. the kernel publishes updated render metadata and imported figure snapshot state

Close behavior follows this sequence:

1. GUI-side close targets the active registry-backed figure window
2. first-class figures prompt through the save-window path unless bypassed by the
   supported close gesture
3. kernel-side close removes the corresponding live figure and attached IR

During project load, first-class figures reopen from `session.py` before the shell
reapplies saved mixed-workspace MDI ordering. That final ordering step uses the
stable subwindow `objectName()` across tool windows, tables, and figures.

## Explicit Exclusions

- GUI-owned canonical figure state
- GUI-side parsing or rewriting of figure source for live edits
- a routine semantic figure-edit `comm` protocol
- `ProcessTree` as the normal transport for figure edits
- automatic Hyde figure-window creation for arbitrary non-decorated matplotlib figures
- a general matplotlib decompiler in the initial deployment

## Future Work

- GridSpec-based multi-subplot figure editing on the existing `LayoutIR` /
  `SubplotIR[]` shape
- richer trace editing beyond the initial styling surface
- additional axis and legend editing surfaces
- any explicit import/promotion path that turns a non-decorated figure into a
  first-class Hyde figure before it enters the window system
- using the same IR-driven recreation path for live figure persistence at shutdown
