# Save Graphics Dialog Specification

## Feature Checklist
- [x] Present a Hyde-native export dialog for the active figure window.
- [x] Export from the authoritative live kernel `Figure`.
- [x] Support multiple standard graphics formats.
- [x] Support width, height, DPI, and transparency options for export.
- [x] Keep graphics export separate from figure recreation macro saving.
- [ ] Support batch export workflows.

## Purpose

The Save Graphics dialog exports the currently active Hyde figure window to a standard
graphics file.

It is an export surface, not an editor and not a recreation-macro surface.

The authoritative export source is always the live kernel matplotlib `Figure`
associated with the active registry-backed figure window. The dialog does not export
from GUI-local image caches.

That means:

- the dialog operates on the active first-class figure window
- export reads the live figure runtime truth
- export does not mutate the authoritative figure IR

## Initial Deployment Scope

The initial deployment exports the active figure to standard graphics formats using
bounded export options.

It includes:

- choosing a destination path
- choosing one of the supported output formats
- setting export width
- setting export height
- setting export DPI where meaningful for the selected format
- choosing transparent-background export when supported
- exporting from the active live kernel figure

It does not include:

- recreation macro authoring
- figure-state mutation
- batch export
- multi-figure export from one dialog

## Window Layout

The dialog is a compact modal export window containing:

- destination-path selection
- format selection
- width and height controls
- DPI control
- transparent-background option
- confirmation and cancel actions

## Visible Controls

- destination path chooser: `active`
- format selector such as PNG / JPG / PDF / SVG: `active`
- width field: `active`
- height field: `active`
- DPI field: `active`
- transparent-background option: `active`
- `Save`: `active`
- `Cancel`: `active`

No recreation-macro name field or raw export-command editor is part of this dialog.

## Editable Operations

The dialog does not edit scientific state.

Its only mutable state is transient export configuration:

- output path
- format
- width
- height
- DPI
- transparency option

That state exists only long enough to perform one export request.

## Command Generation

The dialog does not generate recreation source and does not rewrite figure IR.

On confirmation, it sends a bounded export request for the active registry-backed
figure identity plus the chosen export options. The kernel then performs the export
against the authoritative live `Figure`, equivalent to using that figure's standard
matplotlib save path.

The GUI owns only the transient export options and file-selection interaction. The
kernel-owned live figure remains the export source of truth.

## Synchronization

The dialog operates against the currently active Figure window.

The export path is:

1. the GUI resolves the active figure window identity
2. the GUI collects export options from the dialog
3. the GUI sends the export request for that figure identity
4. the kernel resolves the live figure from the registry-backed Hyde figure identity
5. the kernel exports from the live `Figure`

Export does not require a full figure redraw, does not mutate `fig._hyde_ir`, and does
not change figure editability classification.

## Explicit Exclusions

- using GUI-local cached pixels as the authoritative export source
- saving recreation macros through this dialog
- mutating figure structure or trace styling as part of export
- opening a GUI export surface for non-decorated figures that are outside Hyde's
  figure-window system

## Future Work

- export presets
- batch export
- tighter coordination with later publish/presentation workflows
