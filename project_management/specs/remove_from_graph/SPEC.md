# Remove from Graph Dialog Specification

## Feature Checklist
- [ ] Present a Hyde-native modal `Remove from Graph` dialog for the active figure.
- [ ] Remove one or more supported plotted traces from the authoritative live kernel
  figure.
- [ ] Support list filtering and multi-selection before confirmation.
- [ ] Provide a type selector, candidate list, lower preview/status pane, and footer
  actions.
- [ ] Support image-plot removal.
- [ ] Support contour-plot removal.
- [ ] Support richer cleanup policies after the final plotted item is removed.

## Purpose

This document describes the intended command-driven `Remove from Graph` dialog for the
active first-class Hyde figure. Hyde does not currently ship this dialog.

In the intended initial deployment, "supported plotted objects" means supported line
traces from the current first-class figure IR. The dialog is a confirmed destructive
action surface, not a live-update editor.

The authoritative removal target is always the active live kernel `Figure` plus its
kernel-owned `fig._hyde_ir`. The GUI owns only transient list state, filtering state,
selection state, and read-only preview/status text.

## Initial Deployment Scope

The initial deployment includes:

- launching the dialog for the active first-class figure window
- listing supported removable trace targets from the active figure IR
- filtering the candidate list by displayed trace metadata
- selecting one or more supported traces
- previewing the pending removal as Hyde-generated read-only matplotlib patch source or
  validation text
- confirming removal through `OK`
- emitting the same removal patch through `To IPython`
- copying the current preview/status text through `Copy`

The initial deployment does not include:

- removing image plots
- removing contour plots or contour sub-traces
- automatic removal of axis structure when the final trace is removed
- arbitrary matplotlib artist removal outside Hyde's supported trace surface

## Window Layout

The dialog is a modal single-view window with a compact top selector, a large central
candidate list, a narrow filter row, a large lower preview/status pane, and a footer
button row.

ASCII layout sketch:

```text
+------------------------------------------------------------------------+
| Remove from Graph                                                      |
|                                                                        |
| Object type: [ Trace(s) v ]                                            |
|                                                                        |
| +--------------------------------------------------------------------+ |
| | [icon] trace label            y source vs x source                 | |
| | [icon] trace label            y source vs x source                 | |
| |                                                                    | |
| |                                                                    | |
| +--------------------------------------------------------------------+ |
| [Trace name filter..................................................] | |
|                                                                        |
| +--------------------------------------------------------------------+ |
| | Pending removal summary / validation status                        | |
| | Remove 1 trace: fracneg1_9                                         | |
| +--------------------------------------------------------------------+ |
|                                                                        |
| [OK] [To IPython] [Copy] [Help]                      [Cancel]   |
+------------------------------------------------------------------------+
```

The candidate list rows show:

- the canonical Hyde trace display name
- text only in the first pass

The footer keeps the shared dialog composition, but Hyde does not treat the lower
pane as an executable command editor.

## Visible Controls

- removable-object list: `active`
- text-only trace rows using Hyde's canonical display names: `active`
- trace-name filter field: `active`
- lower preview/status pane: `active`
  - read-only only
- `OK`: `active`
- `To IPython`: `active`
- `Copy`: `active`
- `Help`: `inert-but-visible`
- `Cancel`: `active`

## Context Menu Actions

The dialog is launched from the active figure workflow rather than from a generic
global menu.

Initial entry points are:

- `Figure -> Remove from Graph...` for the active first-class figure
- the figure right-click menu when Hyde exposes the same registered figure actions in a
  contextual popup

The first shipped path is the active `Figure` menu entry for the active first-class
figure. The dialog may open even when the current figure has no supported removable
traces.

## Editable Operations

The dialog performs confirmed figure mutations against kernel-owned figure state.

Initial live operations are:

- filtering the visible candidate list
  - immediate GUI-only filter update
  - targets displayed trace metadata only
- selecting one or more supported traces
  - immediate GUI-only selection update
  - updates the lower preview/status pane immediately
- confirming removal with `OK`
  - targets the selected supported `TraceIR` nodes in the active subplot
  - removes those traces from the live figure and kernel-owned figure IR
  - is confirmed, not live-on-selection

The Python-level effect of a successful removal is that the corresponding supported
trace entries disappear from the active first-class figure's trace list and
their live matplotlib line artists are removed from the rendered figure.

Invalid or unsupported states behave as follows:

- if no supported trace is selected, `OK` is disabled and the lower pane explains
  that no removable target is selected
- if the figure has no supported removable traces, the candidate list is empty and the
  lower pane states that no supported traces are available to remove
- if a trace disappears from the figure before confirmation, the stale selection is
  dropped during refresh and is not treated as an authoritative target

## Command Generation

If Hyde implements this dialog, routine figure removal should follow the same
command-driven model as the shipped axis, trace, and Curve Fit attached-display
surfaces.

On `OK`, the GUI should resolve the selected stable trace IDs from the active
figure context, build a `FigureIRDiff` between the opening and current `FigureIR`
states, and emit one bounded command block through that shared figure-family lowering
path. Because stable trace identity is Hyde-owned rather than ordinary matplotlib
state, the canonical emitted command for this dialog uses Hyde's public
`hyde.remove_traces(...)` helper instead of exposing `_hyde_trace_id` lookup code
directly. `To IPython` emits that same canonical block visibly.

The lower pane shows Hyde-native preview/status text only:

- when the selection is valid, it shows the current removal patch block
- when the state is invalid or unsupported, it shows validation/status text
- it is never authoritative state
- it is never a command log
- it is never executed directly

`Copy` copies the current preview/status text only. `To IPython` emits the same
canonical removal block shown in the lower pane.

## Synchronization

The dialog operates on the active first-class figure only.

Synchronization rules are:

- the authoritative removable-target list comes from the kernel-owned figure IR reached
  through the active editable figure context
- the GUI may cache transient row labels, filter results, and selected IDs only long
  enough to drive the current dialog session
- list rows are keyed by stable Hyde trace IDs rather than by row position
- when the live figure changes while the dialog is open, the dialog refreshes from the
  current figure state before applying removal and drops stale selections
- successful removal triggers the ordinary figure redraw plus backend resync path for
  the active figure window

The GUI never becomes the owner of plotted data arrays, live matplotlib artists, or the
canonical list of plotted objects.

## Explicit Exclusions

- removing image plots in the initial deployment
- removing contour plots or contour levels in the initial deployment
- automatic axis deletion when the final plotted item on an axis is removed
- GUI-side direct mutation of live matplotlib artists without the command-driven
  figure-edit path
- support for non-first-class figures outside Hyde's figure-window system
- direct hit-testing or canvas-click removal entry points in the initial deployment

## Future Work

- activate the `Image Plot(s)` mode when Hyde's first-class figure IR supports those
  targets
- activate the `Contour Plot(s)` mode with clear separation between whole-contour
  removal and contour-subtrace removal
- add richer cleanup rules for empty axes or empty figures if Hyde adopts that
  behavior explicitly
- add a real local help target for the dialog or remove the inert button shell if Hyde
  decides not to keep it
