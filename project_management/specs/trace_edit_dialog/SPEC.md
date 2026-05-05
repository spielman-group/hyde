# Trace Edit Dialog Specification

## Feature Checklist
- [x] Present a Hyde-native dialog for editing one supported trace in a first-class
  figure.
- [x] Target semantic `TraceIR` nodes rather than GUI-side source rewriting.
- [x] Apply accepted edits as kernel-side transactions against both `fig._hyde_ir`
  and the live matplotlib trace artist.
- [x] Use Jupyter `comm` actions for routine live edits.
- [ ] Support multi-trace batch editing.
- [ ] Support unsupported artist classes beyond the initial line-trace surface.

## Purpose

The Trace Edit dialog is Hyde's focused GUI editor for a supported trace inside a
first-class figure.

It is not a raw matplotlib command generator. It is a semantic editor over the
kernel-owned figure IR. The dialog identifies a supported `TraceIR` node, lets the
user change bounded trace properties, and sends a semantic edit request to the kernel.

The authoritative truth remains in the kernel:

- the live matplotlib `Figure` and trace artist remain the runtime truth
- `fig._hyde_ir` remains the authoritative internal state for recreation and future
  figure editing

## Initial Deployment Scope

The initial deployment supports one-trace-at-a-time editing for traces represented as
supported `TraceIR` nodes in a first-class figure.

It includes:

- opening the dialog from a supported first-class figure context
- targeting exactly one supported trace at a time
- editing the initial trace properties needed by v1 figure editing, such as at least
  one styling property like trace color or marker type
- mutating both the authoritative `TraceIR` node and the live matplotlib artist in the
  kernel
- redrawing the figure after an accepted edit

It does not include:

- editing traces in second-class figures
- arbitrary raw source editing
- multi-trace editing in one dialog submission
- editing unsupported artist types through fallback command strings

## Window Layout

The dialog is a compact modal editor opened from a figure-specific action.

It contains:

- a trace identity summary for the currently targeted trace
- the bounded property editors supported in the initial deployment
- confirmation and cancel actions

The dialog does not expose a live source preview, matplotlib command box, or IR text
editor.

## Visible Controls

- trace identity display: `active`
  - identifies the trace currently being edited
- supported trace property controls: `active`
  - edit only the bounded v1 trace properties
- `Apply` or equivalent confirmation action: `active`
  - commits the semantic edit request
- `Cancel`: `active`
  - dismisses the dialog without applying a new edit

No raw-source editing control is part of this dialog.

## Editable Operations

The dialog edits one supported `TraceIR` node at a time.

Each supported edit:

- targets exactly one trace in exactly one first-class figure
- updates the semantic trace property on that trace's `TraceIR` node
- updates the corresponding live matplotlib trace artist in the kernel
- triggers a figure redraw after acceptance

The edit is not authoritative in the GUI before the kernel accepts it.

If the selected figure, subplot, or trace is unsupported, the dialog does not invent a
GUI-side workaround. Hyde rejects the edit path or disables the action.

## Command Generation

Routine trace edits do not generate Python strings in the GUI and do not rewrite saved
source.

Instead, the dialog emits a semantic Jupyter `comm` action that identifies:

- the target figure by its registry-backed Hyde figure identity
- the target subplot and trace node
- the semantic property being changed
- the replacement value

The kernel then performs the edit transaction against `fig._hyde_ir` and the live
matplotlib trace artist.

Equivalent standard matplotlib Python for the edited trace is produced later by the
IR-to-source path used for saved macros and explicit regenerate-from-IR workflows.

## Synchronization

The synchronization path for an accepted trace edit is:

1. the dialog emits a semantic `comm` action
2. the kernel resolves the target figure and `TraceIR` node
3. the kernel mutates the authoritative IR
4. the kernel applies the corresponding live matplotlib trace mutation when practical
5. the kernel redraws and publishes the updated figure metadata/render
6. the GUI viewport reflects the accepted change

The dialog may hold only the transient control values needed to build the semantic
action. It does not own canonical trace styling state after the edit.

## Explicit Exclusions

- GUI-side source rewriting such as appending or replacing raw `ax.plot(...)` or
  `line.set_*` calls
- editing traces in non-first-class figures in the initial deployment
- command transport through `ProcessTree`
- arbitrary fallback strings for unsupported trace operations

## Future Work

- broader line-style and marker editing
- multi-trace editing workflows
- support for additional artist classes once they have first-class IR nodes
