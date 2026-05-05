# New Graph Dialog Specification

## Feature Checklist
- [x] Present a Hyde-native dialog for creating a new first-class figure from live
  kernel objects.
- [x] Generate a first-class figure through the `@hyde.figure` path.
- [x] Keep GUI-side creation state transient and non-authoritative.
- [x] Create a live figure window backed by the Hyde matplotlib backend.
- [x] Seed the kernel-owned figure IR from observed instrumented matplotlib calls.
- [ ] Support multi-subplot layout authoring.
- [ ] Support arbitrary matplotlib scene authoring from the dialog.

## Purpose

The New Graph dialog is Hyde's bounded GUI surface for creating a new first-class
figure from live kernel objects.

It does not become the owner of figure truth. The dialog owns only transient
command-generation state long enough to describe the requested initial figure and
lower that request into a bounded creation command.

That transient dialog state plays the same role that internal state plays in the
table feature's state-to-Python path. It is not the same thing as the figure's
authoritative IR. Once the creation request executes, the live kernel `Figure` becomes
the runtime truth and the kernel-attached `fig._hyde_ir` becomes the figure's
authoritative internal state for recreation and later semantic editing.

## Initial Deployment Scope

The initial deployment creates a first-class single-subplot line figure through a
bounded GUI workflow.

It includes:

- choosing the live kernel objects to plot in the new figure
- constructing a first-class figure on the `@hyde.figure` path
- opening the resulting figure as a native MDI Figure window
- seeding `fig._hyde_ir` and `fig._hyde_command_log` from the instrumented build
  session
- immediate compatibility with later semantic trace editing because created traces are
  represented as first-class `TraceIR` nodes

It does not include:

- GUI-side authorship of multi-subplot layout
- direct raw source entry in the dialog
- creation of a second-class figure when a first-class one is possible
- arbitrary artist authoring beyond the supported line-plot surface

## Window Layout

The dialog is a compact modal window adjacent to the active Hyde workspace.

It contains:

- controls for identifying the kernel objects that seed the new plot
- controls for the bounded single-subplot line-plot configuration supported in the
  initial deployment
- confirmation and cancel actions

The dialog is not a persistent editor. It collects enough information to create one
new first-class figure and then closes.

## Visible Controls

- object-selection fields or pickers: `active`
  - choose the live kernel objects that define the new plot
- single-subplot figure options: `active`
  - cover only the bounded initial creation surface
- `Create`: `active`
  - emits the creation request
- `Cancel`: `active`
  - closes the dialog without creating a figure

No raw matplotlib source editor, subplot-grid designer, or trace-style dialog is part
of this window.

## Editable Operations

The New Graph dialog does not edit an existing figure. It creates one new first-class
figure.

Its editable surface is the transient GUI-side creation state required to generate the
initial figure request. That state may include:

- the selected kernel object names
- the bounded initial single-subplot plot choices supported by the dialog

This state exists only to generate the initial creation command. It is discarded once
the figure is created or the dialog is canceled.

## Command Generation

The dialog follows Hyde's creation-time string-generation model.

On confirmation, it lowers its transient GUI-side internal state into bounded Python
source that creates exactly one first-class figure through the `@hyde.figure` path.

That creation source must:

- use standard matplotlib code inside the decorated figure build path
- create exactly one live figure
- avoid introducing a GUI-owned recreation model
- leave the kernel backend free to initialize the authoritative IR from the observed
  instrumented plotting calls that occur during execution

The dialog does not generate figure-edit source for later mutations. Once the figure
exists, later edits use semantic `comm` actions against the kernel-owned figure IR.

## Synchronization

After the dialog dispatches the creation request:

1. the kernel executes the decorated figure build session
2. the Hyde backend resolves exactly one live figure
3. the backend updates `fig._hyde_ir` and `fig._hyde_command_log` from observed
   instrumented matplotlib calls
4. the GUI opens the corresponding Figure window using the resulting registry-backed
   figure identity

If the decorated build session creates zero figures, multiple figures, or no
resolvable figure, Hyde rejects the request and no first-class figure window opens.

## Explicit Exclusions

- GUI-owned canonical figure state
- second-class figure creation as the primary dialog path
- GUI-side source rewriting after the figure has been created
- multi-figure creation from one dialog submission

## Future Work

- GridSpec subplot authoring using the existing `FigureIR -> LayoutIR -> SubplotIR[]`
  shape
- richer initial trace configuration
- direct creation affordances that cooperate with later trace and axis editors
