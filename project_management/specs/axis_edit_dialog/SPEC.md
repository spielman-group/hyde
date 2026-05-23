# Axis Edit Dialog PRD

## Problem Statement

Hyde has first-class figure windows, figure-scoped menu infrastructure, and a
command-driven figure-edit path, but it does not yet provide a broad axis-editing
workflow for existing first-class figures.

Users currently lack a GUI way to perform the ordinary graph-editing work that Igor's
`Modify Axis` dialog supports: changing axis mode, limits, mirrored-side presentation,
tick generation, grids, zero lines, label text, label placement, and related axis-side
presentation choices without dropping into handwritten matplotlib code.

This missing workflow is not a narrow follow-on to the existing trace editor. The
expected product is an Igor-style tabbed dialog with a broad surface area. The rule for
this feature is:

- if an Igor axis-dialog feature has a defensible matplotlib equivalent, Hyde should
  expose it
- only truly Igor-specific behavior without a clean matplotlib mapping should be
  excluded

The PRD therefore describes a broad `Modify Axis` dialog rather than a minimal first
slice. Another agent should be able to implement the feature from this document
directly, without reopening the screenshot folder or the Igor excerpt.

## Solution

Hyde adds a `Modify Axis` dialog for first-class figure windows inside the existing
`figure_control_dialog` plugin family. The dialog is launched from the active
`Figure` menu and from the figure right-click menu. The right-click menu is a fresh
popup render from the shared figure-menu registry, not the same physical `QMenu`
instance as the hidden menu-bar `Figure` menu.

The dialog is modal, preserves the Igor-style tabbed shell, and includes all seven tabs
shown in the reference family:

- `Axis`
- `Auto/Man Ticks`
- `Ticks and Grids`
- `Tick Options`
- `Axis Label`
- `Label Options`
- `Axis Range`

The dialog also includes:

- an `Axis` selector with `left`, `bottom`, `right`, and `top`
- a `Live Update` checkbox
- a large lower preview/status pane
- footer buttons `Do It`, `To Cmd Line`, `To Clip`, `Help`, and `Cancel`

The dialog operates on the active first-class figure only. In the current Hyde figure
deployment, that means one live kernel-owned figure and one subplot. The selected
subplot is therefore always the active figure's only subplot. The `Axis` selector
chooses the edited side presentation:

- `bottom` and `top` edit x-axis semantics plus x-side presentation
- `left` and `right` edit y-axis semantics plus y-side presentation

Hyde must stay honest here:

- `left`, `bottom`, `right`, and `top` all exist as selectable sides
- `top` and `right` are mirrored presentation sides in the first implementation
- they are not independent secondary data axes
- `floating` / free axes are excluded

Edits apply through Hyde's ordinary command-driven Python path against kernel-owned
figure IR and live matplotlib artists. The GUI may keep transient draft form state,
but the kernel remains authoritative for all durable figure and axis semantics.

### Tab Contract

The first implementation includes all tabs and all controls with defensible matplotlib
equivalents.

#### `Axis`

Supported:

- axis mode: `linear`, `log`, `log2`
- `LogLin` as a Hyde translation for log-axis tick formatting policy
- mirrored-side controls for `left`, `bottom`, `right`, `top`
- axis line thickness
- `Shift axis` for `left`, `bottom`, `right`, `top`, mapped to subplot margin edits
- `Offset axis` for `left`, `bottom`, `right`, `top`, mapped to spine outward positioning
- `draw on top of traces`
- font family, style, and size for axis-side presentation
- separate color controls for axis line, axis label, and tick labels

Excluded:

- `date/time` mode
- `category` mode
- axis standoff
- category gap
- bar gap
- floating/free axis positioning

#### `Auto/Man Ticks`

Supported:

- automatic tick mode with approximate tick-count guidance
- minor ticks on/off
- computed manual tick mode as an explicit locator policy
- manual controls for canonic tick, tick increment, digits after decimal,
  minor-per-major, emphasize-every
- `Set to Auto Values`
- user-provided tick locations and labels backed by Python/namespace objects rather
  than Igor waves

Excluded:

- minimum separation in points as a first-class semantic control
- tick-in-center without category-axis semantics

#### `Ticks and Grids`

Supported:

- engineering vs scientific numeric formatting policy
- low-trip / high-trip thresholds
- exponent prescale
- tick direction: `inside`, `outside`, `both`
- major and minor tick length and thickness
- grid on/off
- grid style, thickness, and color
- zero-line on/off
- zero-line style and thickness
- normalized partial extent via `draw from ... to ... %`

Excluded:

- date/time label formatting
- separate `5th` and `subminor` tick tiers as first-class semantics

#### `Tick Options`

Supported:

- enable ticks only between a numeric range
- inhibit up to three explicit tick values
- max log cycles with minor ticks
- max log cycles with minor tick labels
- formatter toggles for thousands separator, zero formatting, trailing-zero trimming,
  leading-zero trimming, and exponent-preferring display

Excluded:

- unit-bearing tick-label controls that require a real Hyde axis-units model

#### `Axis Label`

Supported:

- main axis-label text editor
- label preview
- line spacing
- whole-label font family
- whole-label absolute or relative font size
- limited special insertion through defensible Unicode or matplotlib mathtext
- character insertion as text editing assistance

Excluded:

- Igor text-info variables and other Igor-only inline text machinery
- semantic `Units` insertion
- `Trial Exponent`

#### `Label Options`

Supported:

- labels on/off for the selected side
- automatic vs manual label-position mode
- axis label margin
- manual axis label position along the selected side
- axis label lateral offset
- axis label rotation
- tick label rotation
- tick label offset
- log minor tick label offset when applicable

#### `Axis Range`

Supported:

- reverse axis
- autoscale policy family
- per-end manual/auto checkboxes for minimum and maximum
- numeric min/max fields
- numeric entry format for ordinary Python-style numbers
- `Check Both` / `Uncheck Both`
- `Set to Autoscale Values`
- `Expand 5%`
- `Swap`
- quick-set list backed by Python/namespace-visible data sources
- `Y Min/Max`
- `X Min/Max`
- `Full Scale`

Per-end manual/auto is supported as a Hyde-owned resolved-range policy:

- each endpoint may be `manual` or `auto`
- if one endpoint is manual and the other auto, Hyde computes the unchecked end from
  the active autoscale policy
- the dialog dispatches a complete resolved range pair to the live figure

### Live Update And Footer Contract

- `Live Update` on: valid committed changes execute immediately through Hyde's hidden
  Python command path
- `Live Update` off: the dialog keeps transient draft state only; nothing is sent
  until `Do It`
- switching `Live Update` from off to on applies the current valid draft immediately
- `Do It`: executes the current valid patch block and closes
- `To Cmd Line`: emits the same canonical patch block visibly to the terminal
- `To Clip`: copies the current valid preview source to the clipboard
- `Help`: disabled or hidden unless Hyde has a real local help target
- `Cancel`: if live edits were sent during the session, executes a rollback patch that
  restores the opening snapshot for the dialog-owned region; otherwise closes without
  mutating the figure

The lower pane is a read-only draft preview/status surface:

- when the draft is valid, it shows figure recreation Python lowered from the draft IR
- when the draft is incomplete or invalid, it shows validation/status text
- it is never authoritative state
- it is never a command log
- it is not saved with the figure

## User Stories

1. As a Hyde user, I want a `Modify Axis` dialog for first-class figures, so that I
   can edit graph axes without writing matplotlib code manually.
2. As a Hyde user, I want the dialog to open from the active `Figure` menu, so that it
   fits the existing figure workflow.
3. As a Hyde user, I want the same figure actions available from right-click, so that
   contextual editing is fast.
4. As a Hyde user, I want the right-click menu to match the registered `Figure` menu
   content, so that the UI stays consistent.
5. As a Hyde user, I want the dialog to preserve the Igor-style tabbed interface, so
   that the workflow feels familiar.
6. As a Hyde user, I want all seven axis-dialog tabs present, so that Hyde does not
   collapse the feature into a smaller unrelated UI.
7. As a Hyde user, I want to select `left`, `bottom`, `right`, or `top`, so that I can
   edit the side I care about.
8. As a Hyde user, I want `top` and `right` available as real selectable sides, so
   that mirrored-axis presentation is editable.
9. As a Hyde user, I want axis-mode controls for `linear`, `log`, and `log2`, so that
   I can change numeric scale directly from the dialog.
10. As a Hyde user, I want `LogLin`-style control when a log axis is selected, so that
    I can influence log tick-label formatting behavior.
11. As a Hyde user, I want mirror-axis controls, so that I can show or hide mirrored
    same-scale sides.
12. As a Hyde user, I want axis thickness controls, so that I can emphasize or soften
    axis presentation.
13. As a Hyde user, I want axis-edge shift controls, so that I can move the plot-area
    edges using matplotlib-native subplot margin edits.
14. As a Hyde user, I want axis offset controls, so that I can move axis spines
    outward using matplotlib's spine positioning.
15. As a Hyde user, I want to draw axes on top of traces when needed, so that I can
    improve readability for dense plots.
16. As a Hyde user, I want axis font controls, so that labels and tick text can match
    the intended presentation.
17. As a Hyde user, I want separate color controls for axis line, axis label, and tick
    labels, so that I can style those elements independently.
18. As a Hyde user, I want automatic tick generation controls, so that Hyde can choose
    sensible ticks with mild guidance from me.
19. As a Hyde user, I want manual tick generation controls, so that I can define the
    major-step scheme explicitly.
20. As a Hyde user, I want minor-tick controls, so that I can control readability on
    dense or log-scaled plots.
21. As a Hyde user, I want `Set to Auto Values`, so that I can start manual editing
    from the current automatic tick solution.
22. As a Hyde user, I want user-provided tick locations and labels backed by Python
    objects, so that I can fully specify tick placement when needed.
23. As a Hyde user, I want engineering and scientific label modes, so that numeric
    axes can display scaled values clearly.
24. As a Hyde user, I want low-trip and high-trip controls, so that I can decide when
    axis labels switch formatting regimes.
25. As a Hyde user, I want exponent prescale controls, so that the displayed exponent
    convention can be forced when appropriate.
26. As a Hyde user, I want tick-direction controls, so that ticks can point inward,
    outward, or both.
27. As a Hyde user, I want grid visibility, style, thickness, and color controls, so
    that the plot area can be tuned for reading and presentation.
28. As a Hyde user, I want zero-line controls, so that an x=0 or y=0 reference line
    can be shown and styled from the same dialog.
29. As a Hyde user, I want tick-range filtering and explicit tick suppression, so that
    unwanted ticks can be removed without rewriting the whole axis.
30. As a Hyde user, I want log-specific minor-tick policies, so that wide log ranges
    remain readable.
31. As a Hyde user, I want numeric tick-label formatting toggles like thousands
    separators and trimmed zeros, so that labels match my preferred notation.
32. As a Hyde user, I want an axis-label editor and preview, so that I can change
    label text safely.
33. As a Hyde user, I want controlled character and math-like insertion helpers, so
    that ordinary scientific notation and symbols are convenient without exposing
    Igor-only text machinery.
34. As a Hyde user, I want label positioning controls, so that axis labels can be
    placed and rotated precisely.
35. As a Hyde user, I want side-specific tick-label rotation and offset controls, so
    that mirrored `top` and `right` presentation can be cleaned up independently.
36. As a Hyde user, I want reverse-axis control, so that I can invert an axis without
    hand-editing code.
37. As a Hyde user, I want autoscale policy controls, so that Hyde can compute ranges
    according to explicit rules.
38. As a Hyde user, I want minimum and maximum to be independently auto or manual, so
    that I can pin one end while allowing the other to follow data.
39. As a Hyde user, I want quick-set buttons from plotted data, so that common range
    operations are one click instead of a manual transcription.
40. As a Hyde user, I want `Expand 5%`, `Swap`, and `Set to Autoscale Values`, so that
    ordinary range manipulations are fast.
41. As a Hyde user, I want `Live Update`, so that I can see the figure respond while I
    work.
42. As a Hyde user, I want `Live Update` off when needed, so that I can prepare a set
    of changes before sending them.
43. As a Hyde user, I want `Do It` to apply the current valid draft and close, so that
    non-live editing still has an explicit commit path.
44. As a Hyde user, I want `Cancel` to restore the exact opening axis state when live
    updates were sent, so that experimentation is safe.
45. As a Hyde user, I want the lower pane to preview the current draft source, so that
    I can see what the saved figure recreation will become.
46. As a Hyde user, I want `To Clip`, so that I can copy the current preview source
    without executing it.
47. As a Hyde developer, I want all routine edits to go through the same
    command-driven Python path, so that Hyde keeps one authoritative figure-edit
    path.
48. As a Hyde developer, I want the kernel to remain authoritative for figure and axis
    state, so that the GUI never becomes the scientific state owner.
49. As a Hyde developer, I want shared dialog-family code for active-window checks,
    snapshot/revert, preview export, and message dispatch, so that figure dialogs do
    not duplicate plumbing.
50. As a Hyde developer, I want axis state stored in figure IR and regenerated from
    that IR, so that save/restore, preview, and live redraw all stay consistent.
51. As a Hyde tester, I want the dialog behavior to be specified in terms of visible
    outcomes and command emission, so that tests remain stable as widget wiring
    changes.

## Implementation Decisions

- The feature stays in the existing `figure_control_dialog` plugin family rather than
  creating a second figure-edit plugin.
- The runtime-owning figure plugin remains responsible for figure windows, identity,
  kernel transport, and base figure refresh behavior.
- The axis dialog contributes actions through the shared figure-menu registry and is
  reachable from both the hidden menu-bar `Figure` menu and a fresh right-click popup
  render from that same registry.
- The dialog is modal and uses the Igor-style tab shell shown in the screenshot family.
- The first implementation targets first-class Hyde figures only.
- The first implementation stays within Hyde's current one-figure / one-subplot figure
  deployment, but still exposes `left`, `bottom`, `right`, and `top` as selectable
  presentation sides.
- `top` and `right` are mirrored presentation sides of the underlying x/y axes in the
  first implementation. They are not independent secondary data axes.
- Free/floating axes are excluded even though matplotlib has spine-position tricks,
  because the product rule here is a clean equivalent, not a rough approximation.
- Date/time and category-axis semantics are excluded. Tabs remain present; only those
  truly non-equivalent controls stay out.
- The feature adds shared reusable modules for:
  - active first-class-figure resolution and gating
  - common command emission/logging
  - common edit-session snapshot plus `Live Update`, apply, and rollback behavior
  - preview-pane and clipboard export plumbing
- The feature adds an axis-specific draft state/codec layer that:
  - normalizes widget values
  - preserves incomplete local-only edits when `Live Update` is off or a field is mid-edit
  - validates numeric and text input
  - resolves side selection honestly against underlying x/y semantics
  - lowers the draft into minimal matplotlib patch Python for the dialog-owned region
- Figure IR must grow from the current minimal axis fields into a durable per-subplot
  axis model covering:
  - side presentation for `left`, `bottom`, `right`, `top`
  - scale/mode
  - mirrored-side policy
  - range policy and autoscale policy
  - axis extent / partial draw bounds
  - label model and label-placement state
  - locator policy
  - formatter policy
  - grid policy
  - zero-line policy
  - side-specific tick-label presentation state
- Backend figure resync must import those command-driven edits back into kernel-owned
  IR, and lowering/regeneration must use the same IR.
- The lower preview pane is derived from the draft IR and is never authoritative.
- `Live Update` on:
  - committed valid control changes execute immediately through the hidden command path
  - invalid or partial edits stay local and do not execute
- `Live Update` off:
  - dialog widgets update only local draft state
  - `Do It` validates and executes the accumulated patch once
- Switching `Live Update` from off to on applies the current valid draft immediately.
- `Cancel` executes a rollback patch only if edits were already applied during the
  session.
- Numeric validation rules for range fields:
  - blank text is acceptable only when the endpoint is in auto mode
  - partial tokens like `-`, `.`, and `1e` are local invalid states and do not dispatch
  - invalid text does not mutate IR
  - reversed bounds are invalid as numeric bounds even when axis reversal is enabled
  - if one endpoint is manual and the other auto, Hyde resolves the auto end first and
    dispatches one complete resolved pair
- The `Axis Label` tab stores a small structured label model rather than raw text only
  or a full rich-text AST:
  - text
  - syntax mode such as plain text or mathtext-oriented content
  - whole-label font properties
  - line spacing
- The `Tick Options` and `Ticks and Grids` tabs share one formatter-policy family and
  one locator-policy family rather than embedding formatting logic directly in widgets.
- Quick-set controls resolve Python-backed data already visible to Hyde rather than
  Igor waves or Igor scaling metadata.
- `To Clip` copies preview source only; it never applies edits by itself.
- `To Cmd Line` emits the same canonical patch block used by hidden execution; it does
  not invent a second lowering path.
- `Help` remains disabled or hidden unless Hyde gains a real user-facing local help
  target for this dialog.

## Testing Decisions

- Good tests verify visible behavior, command emission, regeneration, and save/restore
  effects rather than incidental Qt wiring details.
- Tests should verify that the dialog opens only for an active first-class figure
  window and uses the shared figure-control-dialog gating path.
- Tests should verify that the action is present in the shared figure-menu registry and
  available through both menu-bar and popup rendering.
- Tests should verify that the dialog seeds controls from the active figure's current
  axis state.
- Tests should verify `Live Update` behavior:
  - valid committed changes execute immediately when enabled
  - incomplete or invalid edits do not execute
  - turning `Live Update` on applies the current valid draft
- Tests should verify non-live behavior:
  - draft-only edits remain local until `Do It`
  - `Do It` executes the same canonical patch block previewed by the dialog and closes
- Tests should verify `Cancel` behavior:
  - restores the exact opening snapshot when live edits were sent
  - leaves the live figure untouched when nothing was applied
- Tests should verify that the preview pane and clipboard export reflect draft IR and do
  not mutate the figure by themselves.
- Tests should verify top/right honesty:
  - top/right side controls affect mirrored presentation state
  - they do not create fake independent secondary data axes
- Tests should verify that axis mode, range, tick, grid, zero-line, and label settings
  survive redraw/regeneration from figure IR.
- Tests should verify that save/restore lowers the expanded axis semantics back to
  ordinary matplotlib recreation source deterministically.
- Tests should verify that `To Cmd Line` emits the same canonical patch block as
  hidden execution.
- Tests should verify that quick-set controls resolve Python-backed data sources rather
  than Igor-specific objects.
- Tests should verify locator/formatter policy behavior at the contract level:
  - set-to-auto-values snapshots the current auto result into manual controls
  - explicit tick suppression is honored
  - grid and zero-line styling survive redraw
- Prior art exists in Hyde's current figure `comm` tests, figure-window tests, and the
  existing trace-edit dialog tests for dialog-family dispatch and cancel-revert
  behavior.

## Out of Scope

- non-first-class figures
- multi-subplot editing
- true independent top/right data axes or secondary-axis semantics
- date/time axis semantics
- category-axis semantics
- floating/free axes
- axis standoff
- category gap and bar gap
- Igor wave-specific language or data-folder behavior
- Igor text-info variables and other Igor-only inline text machinery
- unit-bearing tick-label semantics without a real Hyde units model
- extra tick tiers beyond major and minor as durable first-class semantics
- help-button wiring without a real local help target
- any GUI-owned scientific mirror of axis state beyond transient draft form state

## Further Notes

- This PRD intentionally replaces the earlier narrow axis spec. The product goal is the
  broad Igor-style axis dialog, not a minimal title/label/range patch.
- The feature should reuse the shared figure-control-dialog family aggressively so that
  active-window checks, preview/export behavior, `Live Update`, and cancel-revert
  semantics do not fork across sibling dialogs.
- Another agent implementing this PRD should not need to inspect the axis screenshot
  folder or the Igor excerpt to understand the intended behavior.
- The core design bias remains the Hyde architecture bias:
  - GUI stays transient
  - kernel-owned figure IR stays authoritative
  - routine figure edits emit canonical matplotlib patch Python through Hyde's
    ordinary command path
