# Axis Edit Dialog Specification

## Feature Checklist
- [ ] Open an axis-edit dialog for a first-class Hyde figure.
- [ ] Target one subplot node in the figure feature's IR/internal state.
- [ ] Apply supported edits through semantic figure `comm` actions.
- [ ] Keep advanced screenshot-inspired controls excluded until matching IR semantics exist.

## Purpose

The Axis Edit Dialog is a follow-on figure-editing surface for first-class
`@hyde.figure` figures.

Its job is to expose axis-level figure edits without moving authoritative figure state
into the GUI. The dialog is not a second figure model. It is a viewport-local control
surface that edits one subplot of one live kernel-side figure.

In this feature family, figure `IR` means the same thing that `internal state` means in
the table state-to-Python generation path: it is the authoritative feature-owned
internal representation used for semantic editing and for lowering back to standard
matplotlib Python source. Hyde keeps this IR in the kernel on the live figure.

## Current Deployment Boundary

This dialog is not part of the current figure-window deployment.

The current figure implementation limits the initial figure semantic surface to:

- one figure
- one subplot
- line traces
- subplot title
- x label
- y label
- x limits
- y limits
- legend enable/disable
- minimal trace styling needed for the prompt trace editor follow-on

Advanced axis-edit workflows remain follow-on work.

## Future Deployment Scope

When the dialog is introduced, it operates only on first-class `@hyde.figure` figures
that already have:

- a live kernel-side matplotlib `Figure`
- a figure-specific IR attached to that figure
- a strict figure-window-to-registry identity mapping

The dialog targets one `SubplotIR` node within that figure IR.

## Visible Controls

For the current deployment boundary:

- axis-edit entry point: `excluded`
- `Basic Settings` tab: `excluded`
- `Graph` tab: `excluded`
- `Analysis` tab: `excluded`
- `Advanced` tab: `excluded`
- live preview/update behavior: `excluded`

For the first axis-dialog deployment, Hyde should activate only the controls whose
semantics already exist in the figure IR. Screenshot-inspired controls that do not yet
map cleanly onto supported IR nodes remain excluded rather than being implemented as
GUI-only mutations.

## Editable Operations

The first useful axis-dialog deployment should stay within the current figure IR
surface.

Supported edits should therefore be limited to semantic axis operations such as:

- set subplot title
- set x label
- set y label
- set x limits
- set y limits
- toggle legend visibility when that control is presented at axis scope

These edits target the selected subplot node in the figure IR and then
update the corresponding live matplotlib objects.

Operations that require unsupported matplotlib semantics, multi-subplot coordination, or
nontrivial analysis metadata remain excluded until the figure IR grows to support them.

## Command Generation

The dialog does not generate ad hoc matplotlib Python snippets for routine edits.

Instead, it sends semantic figure-edit actions over the dedicated figure `comm` path,
for example:

- `set_axis_limits`
- `set_axis_label`
- `set_subplot_title`
- `set_legend_visible`

This is a private Hyde figure-edit protocol. It remains compatible with Hyde's broader
reproducibility rule because each semantic action mutates authoritative figure internal
state that can later be lowered back to ordinary matplotlib Python source.

## Synchronization

The kernel is authoritative for both:

- the live matplotlib `Figure`
- the figure IR/internal state attached to that figure

When the user confirms or applies an edit:

1. the dialog sends a semantic action over the figure `comm`
2. the kernel resolves the target figure and subplot
3. the kernel mutates the authoritative figure IR
4. the kernel applies the corresponding live matplotlib mutation when practical
5. the figure window redraws from the same live figure

The GUI may hold only transient form values needed to emit the action. It must not keep
a mirrored editable copy of axis state.

## Explicit Exclusions

- support for second-class non-`@hyde.figure` figures
- GUI-owned semantic axis state
- source rewriting in the GUI
- advanced analysis tabs without defined figure IR semantics
- multi-subplot axis-edit workflows in the initial axis-dialog deployment

## Screenshot Notes

### 07_axis_editor.png
![Axis Editor](07_axis_editor.png)
- What it shows: the axis editor with tabbed controls and live update.
- Hyde interpretation: a future axis-edit surface for first-class figure windows, with
  only the subset that maps cleanly onto figure IR semantics becoming
  active at first.

*(Images 15 through 21 continue this screenshot family with deeper tabbed controls such
as Basic Settings, Graph controls, Analysis, and Advanced sync. Hyde adopts only the
controls that fit the first-class figure IR model.)*
