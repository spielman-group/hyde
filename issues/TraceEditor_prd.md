# Trace Edit Dialog PRD

## Problem Statement

Hyde has first-class figure windows and figure-scoped menu infrastructure, but it does
not yet provide a practical dialog for editing the appearance of an existing plotted
trace. Users currently lack a GUI workflow for common styling tasks such as changing
line style, marker shape, marker colors, opacity, or line width on a first-class Hyde
figure.

The missing workflow is not a tiny surface. The expected behavior is close to Igor's
`Modify Trace Appearance` dialog: the user works in a modal dialog, chooses a trace
from a list, edits a broad set of ordinary appearance properties, sees the figure
update while working, and can still back out safely with `Cancel`.

This feature therefore needs to be broader than a narrow "edit one style property"
surface. It should cover most ordinary matplotlib `Line2D` appearance attributes that
can be changed cleanly through Hyde's existing semantic figure-edit architecture, while
explicitly excluding advanced Igor behaviors that Hyde does not yet model.

## Solution

Hyde adds a `Modify Data Appearance` dialog for first-class figure windows. The dialog
is launched from the active `Figure` menu and operates on the active figure only. It
uses an Igor-inspired two-pane modal layout:

- a left pane that lists supported traces in the active figure
- a right pane that presents grouped appearance controls for the selected trace

The dialog supports one supported trace at a time and is broadly complete for ordinary
matplotlib `Line2D` appearance editing. Supported controls include:

- hide trace
- display mode for lines, markers, or lines plus markers
- line color
- line style
- line width
- line opacity
- draw style
- marker shape
- marker size
- marker face color
- marker edge color
- marker edge width

Edits apply live through Hyde's semantic figure `comm` path against the kernel-owned
live figure and figure IR. The GUI remains transient. It holds only the information
needed to seed the dialog, emit bounded semantic edit requests, and restore the opening
trace appearance if the user clicks `Cancel`.

This dialog belongs to a new `figure_control_dialogs` plugin. That plugin owns the
trace-edit dialog and the reusable dialog-family helpers that later figure control
dialogs will need, such as:

- validating that a figure window is currently the active MDI window
- collecting the active figure and trace snapshot needed to seed controls
- sending semantic figure-edit messages
- coordinating figure refresh after a kernel-side edit
- supporting live-update plus cancel-revert behavior

The existing `figure` plugin remains the owner of figure windows, figure identity, and
the figure runtime transport. The new plugin contributes actions through the normal
`Figure` menu registration path and does not become a second figure-runtime owner.

## User Stories

1. As a Hyde user, I want a `Modify Data Appearance` dialog for figures, so that I can
   edit plotted trace styling without writing matplotlib code manually.
2. As a Hyde user, I want the dialog to open from the active `Figure` menu, so that it
   fits naturally into the figure workflow Hyde already uses.
3. As a Hyde user, I want the dialog to operate only on the active figure, so that
   figure-edit actions always have one clear target.
4. As a Hyde user, I want to choose the trace from a list in the dialog, so that I can
   edit the correct trace even when several traces are present.
5. As a Hyde user, I want the dialog layout to resemble Igor's trace editor, so that
   the workflow feels familiar and efficient.
6. As a Hyde user, I want line color controls, so that I can quickly restyle traces
   for clarity or presentation.
7. As a Hyde user, I want line style controls, so that I can distinguish traces by
   dash pattern.
8. As a Hyde user, I want line width controls, so that I can emphasize or de-emphasize
   a trace visually.
9. As a Hyde user, I want opacity controls, so that I can make overlapping traces
   easier to read.
10. As a Hyde user, I want draw style controls, so that I can switch among ordinary
    supported matplotlib line drawing modes.
11. As a Hyde user, I want marker shape controls, so that I can change the visual
    identity of trace points.
12. As a Hyde user, I want marker size controls, so that I can tune readability for
    dense or sparse data.
13. As a Hyde user, I want marker face color controls, so that I can style filled
    markers directly from the dialog.
14. As a Hyde user, I want marker edge color controls, so that I can style marker
    outlines independently.
15. As a Hyde user, I want marker edge width controls, so that marker outline styling
    is complete enough for ordinary plotting work.
16. As a Hyde user, I want a hide-trace control, so that I can temporarily suppress a
    trace without deleting it.
17. As a Hyde user, I want a mode control for lines, markers, and lines-plus-markers,
    so that I can quickly switch among common trace display modes.
18. As a Hyde user, I want the figure to update while I work, so that I can evaluate
    styling changes immediately.
19. As a Hyde user, I want `Cancel` to restore the trace exactly to its opening state,
    so that I can experiment without risk.
20. As a Hyde user, I want `Apply` to keep the current edited state, so that I can
    confirm the live changes I have made.
21. As a Hyde user, I want unsupported advanced trace behaviors to stay out of the
    first version, so that the dialog remains coherent and reliable.
22. As a Hyde developer, I want the dialog to use semantic figure-edit actions rather
    than GUI-generated source strings, so that Hyde stays aligned with its first-class
    figure architecture.
23. As a Hyde developer, I want the kernel to remain authoritative for the live figure
    and figure IR, so that the GUI does not become a scientific state owner.
24. As a Hyde developer, I want this dialog in a dedicated `figure_control_dialogs`
    plugin, so that future figure dialogs can reuse common active-window and dispatch
    helpers without tangling the runtime figure plugin.
25. As a Hyde plugin author, I want the dialog action contributed through the normal
    `Figure` menu system, so that contextual figure tools share one shell contract.
26. As a Hyde developer, I want the first implementation to stay focused on ordinary
    `Line2D` traces, so that the initial semantic surface is broad but still
    well-bounded.

## Implementation Decisions

- The feature is implemented as a new `figure_control_dialogs` plugin.
- The runtime-owning `figure` plugin remains responsible for figure windows, figure
  identity, and the figure `comm` transport.
- The new plugin contributes a `Modify Data Appearance` action through the normal
  `Figure` menu registration path.
- The dialog is modal and uses a two-pane Igor-inspired layout with a trace list on
  the left and grouped property controls on the right.
- The first deployment supports one supported trace at a time.
- The first deployment targets ordinary first-class line traces represented as
  supported matplotlib `Line2D` semantics in Hyde's figure-edit model.
- The supported appearance surface is intentionally broad for ordinary line styling and
  includes line, marker, visibility, mode, opacity, and draw-style controls.
- Live edits are sent through Hyde's semantic figure `comm` path rather than through
  GUI-generated matplotlib source.
- The GUI stores only transient dialog state, including the opening appearance snapshot
  needed for `Cancel` revert behavior.
- `Cancel` is implemented by sending semantic restore actions for the opening trace
  appearance rather than by mutating live matplotlib objects directly in the GUI.
- Shared helper logic for active-figure validation, snapshot seeding, message dispatch,
  and refresh coordination lives with the dialog plugin so later figure control dialogs
  can reuse it.
- The first version excludes behaviors that require unsupported semantics, even if they
  appear in Igor's dialog or screenshot family.

## Testing Decisions

- Good tests should verify externally visible behavior and command emission rather than
  internal widget wiring details.
- Tests should verify that the dialog opens only from a valid active first-class figure
  context.
- Tests should verify that the dialog seeds its controls from the selected trace's
  current appearance.
- Tests should verify that supported control changes emit semantic live-update actions
  through the figure-edit path.
- Tests should verify that `Apply` preserves the current edited live state.
- Tests should verify that `Cancel` restores the exact opening appearance snapshot.
- Tests should verify that unsupported trace targets do not trigger GUI-side fallback
  behavior.
- Tests should prefer behavior and contract assertions over incidental Qt signal-order
  assertions.
- Prior art exists in Hyde's first-class figure tests, figure `comm` tests, and other
  dialog-focused tests that validate command dispatch and live kernel-backed behavior.

## Out of Scope

- multi-trace batch editing
- non-first-class figures
- arbitrary matplotlib artist classes beyond supported ordinary line traces
- GUI-side raw source editing
- GUI-side direct mutation of live matplotlib artists
- `f(z)`-driven style controls from auxiliary waves
- grouping, stacking, and adding modes
- error-bar editing
- bar-fill and non-line fill semantics
- offset controls that change plotted data semantics
- gap and missing-data policies beyond Hyde's existing ordinary line behavior
- direct trace hit-testing entry points such as double-click or per-trace popup launch
  in the first deployment

## Further Notes

- The dialog should preserve the broad composition and practical feel of Igor's
  `Modify Trace Appearance` dialog without copying unsupported controls literally.
- The first version should feel close to feature-complete for ordinary matplotlib line
  appearance editing, even though advanced Igor-specific semantics remain excluded.
- This feature establishes the reusable dialog-family foundation for later figure
  control dialogs such as axis editing, append/remove trace workflows, text tools, and
  fitting surfaces.
