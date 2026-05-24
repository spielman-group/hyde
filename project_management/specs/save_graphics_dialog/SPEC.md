# Save Graphics Dialog Specification

## Feature Checklist
- [x] Present a Hyde-native figure export dialog shaped by
  `project_management/specs/save_graphics_dialog/14_save_graphics.png`.
- [x] Launch the dialog for the active first-class figure window only.
- [x] Export from the authoritative live kernel `Figure`, not from GUI-local cached
  pixels.
- [x] Keep graphics export separate from figure recreation macro saving and figure IR
  editing.
- [x] Use Hyde's dialog-preview footer pattern with `Do It`, `To Cmd Line`,
  `To Clip`, `Help`, and `Cancel`.
- [x] Generate one executable export string when the dialog state resolves to a
  concrete destination path.
- [x] Support same-size and custom-size export modes.
- [x] Support bounded format, file-name, and overwrite options.
- [ ] Support batch export workflows.
- [ ] Define a Hyde-native monochrome export contract.

## Purpose

The Save Graphics dialog is Hyde's modal export surface for writing the currently
active first-class figure to a standard graphics file.

It is an export surface, not a figure editor and not a recreation-macro surface.

The dialog owns only transient export configuration state long enough to:

- choose an output format
- choose whether export uses the figure's current size or a custom export size
- choose the output filename and destination behavior
- preview the executable export string when one can be resolved
- execute or expose that export string through Hyde's standard dialog footer actions

The authoritative export source is always the live kernel matplotlib `Figure`
associated with the opening figure window. The dialog does not export from the GUI
pixmap cache, does not mutate `fig._hyde_ir`, and does not use the figure-edit session
boundary used by trace, axis, or Curve Fit dialogs.

This surface is a `HydeDialogWidget`-style dialog, not a `HydeFigureDialogWidget`
figure-edit dialog. It is figure-scoped because it targets one opening first-class
figure identity, but it is not an IR-patching surface.

## Initial Deployment Scope

The initial deployment provides one figure-scoped export dialog for the active
first-class figure window.

It includes:

- launching `Save Graphics...` from the active figure window
- resolving the opening figure window's stable Hyde figure identity
- defaulting the export basename from that opening figure identity
- choosing between `Same` and `Custom` export size modes
- entering custom width and height values
- choosing an export-size unit from a small Hyde-native set
- filtering the format list to recommended formats only
- choosing one supported export format from a bounded list
- entering a file name
- choosing a destination-path mode whose default visible entry is `_Use Dialog_`
- choosing whether an existing destination may be overwritten
- previewing the executable export string when the destination resolves to a concrete
  path
- running the export through hidden execution on `Do It`
- exposing the same executable export string through `To Cmd Line` and `To Clip`
  when that string exists

It does not include:

- recreation macro authoring
- figure-state mutation as a user-visible outcome of export
- batch export
- multi-figure export from one dialog
- GUI-pixmap export
- non-first-class figure export through Hyde's figure-window menu
- a finalized monochrome/grayscale export behavior in the initial deployment

## Window Layout

The dialog is a modal grouped form with one large lower preview/status region and the
shared Hyde footer.

It preserves the screenshot's major group placement while translating the lower
Igor-style command area into Hyde's standard preview pane.

```text
+------------------------------------------------------------------------+
| Save Graphics File                                                     |
|                                                                        |
| Size:                                                                  |
|  +------------------------------------------------------------------+  |
|  | (o) Same                                                         |  |
|  |                                                                  |  |
|  | ( ) Custom   Width [      ]   Height [      ]   Units [ inchesv]|  |
|  +------------------------------------------------------------------+  |
|                                                                        |
| Format:                                                                |
|  +------------------------------------------------------------------+  |
|  | [x] Show only recommended formats                                |  |
|  |                                                                  |  |
|  | +----------------------------+    [ ] Color                      |  |
|  | | PDF                        |                                   |  |
|  | | EPS                        |                                   |  |
|  | | PNG                        |                                   |  |
|  | | JPEG                       |                                   |  |
|  | | TIFF                       |                                   |  |
|  | | SVG                        |                                   |  |
|  | +----------------------------+                                   |  |
|  +------------------------------------------------------------------+  |
|                                                                        |
| File:                                                                  |
|  +------------------------------------------------------------------+  |
|  | Name [........................................] Path [.........v] |  |
|  |      [ ] Force Overwrite                                          |  |
|  +------------------------------------------------------------------+  |
|                                                                        |
| Preview / Status:                                                      |
|  +------------------------------------------------------------------+  |
|  | hyde.get_figure(...).savefig(...)                                 |  |
|  | or validation / path-resolution status text                       |  |
|  +------------------------------------------------------------------+  |
|                                                                        |
| [Do It] [To Cmd Line] [To Clip]                     [Help] [Cancel]    |
+------------------------------------------------------------------------+
```

The static grouped structure belongs in a `.ui` file.
Python owns:

- populating the format list
- populating any path-mode choices
- synchronizing file extension and format
- enabling and disabling size widgets by mode
- validating export state
- opening the native save dialog when required
- generating the executable preview string
- showing alternate status text when the export string is not yet available

## Visible Controls

The visible controls are classified as follows:

- `Size` group box: `active`
- `Same` radio: `active`
- `Custom` radio: `active`
- custom width field: `active`
- custom height field: `active`
- unit selector: `active`
- `Format` group box: `active`
- `Show only recommended formats`: `active`
- format list: `active`
- `Color`: `inert-but-visible`
- `File` group box: `active`
- `Name` field: `active`
- path-mode selector: `active`
- `Force Overwrite`: `active`
- lower preview/status pane: `active`
- `Do It`: `active`
- `To Cmd Line`: `active`
- `To Clip`: `active`
- `Help`: `active`
- `Cancel`: `active`

Hyde keeps the screenshot's visually prominent `Color` checkbox for layout continuity
in the initial deployment, but it does not yet define a committed monochrome-export
behavior behind that control.

The large lower pane is a preview/status surface, not a second editable path field,
even though the screenshot's source application labels that region differently.

## Context Menu Actions

The active figure window exposes `Save Graphics...` as a figure-scoped action.

That action:

- is available only for the active first-class figure window
- binds the dialog to the opening figure identity
- does not implicitly switch targets if another figure window becomes active while the
  dialog is open

## Editable Operations

The dialog does not edit scientific state.

Its mutable state is transient export configuration only:

- export size mode
- custom width
- custom height
- export-size unit
- recommended-format filter
- selected export format
- output file name
- destination-path mode
- force-overwrite choice

The only confirmed operation in the initial deployment is graphics export.

- Target object: the opening live first-class kernel `Figure`
- Python-level effect: run one explicit export command against that live figure and
  write one output file
- Timing: confirmed on `Do It`
- Invalid or incomplete state: the dialog shows status text in the lower pane and does
  not expose an executable backing string

Custom export size is an export-time override only.
It may require temporary backend-side figure sizing or equivalent save-time arguments,
but that export path must not become a persistent figure edit and must not be treated
as a user-visible mutation of the figure's authoritative IR.

## Command Generation

The Save Graphics dialog follows Hyde's string-factory rule.

It owns one GUI-side export state object and one export codec under Hyde's normal
state/control pattern. That state exists only to validate the export request and lower
it to executable Python.

When the dialog state resolves to a concrete destination path, the lower pane shows
the executable backing string directly.

When the dialog state does not yet resolve to a concrete destination path, the lower
pane may instead show alternate validation or path-resolution text. In that state:

- the backing string is empty
- `Do It` may still be allowed when the only missing step is a `_Use Dialog_`
  destination choice
- `To Cmd Line` and `To Clip` remain disabled because there is no concrete executable
  string yet

The generated source should prefer standard matplotlib save semantics after the target
figure has been resolved. Hyde-specific helper calls are acceptable only for the parts
that require Hyde-owned figure lookup or Hyde-owned save-option translation.

The command contract is:

- resolve the opening first-class figure by its Hyde figure identity
- derive the final output path
- apply the selected bounded export options
- export through the live matplotlib figure save path

`Do It`, `To Cmd Line`, and `To Clip` all use the same backing string whenever that
string exists.

`Do It` dispatches the export through Hyde's hidden execution path so it does not
consume visible terminal history.

## Synchronization

The dialog binds to the opening active figure window at launch time.

It may cache only transient metadata needed to seed the form, such as:

- the opening figure identity
- the opening figure's current display size
- the default export basename
- the currently available supported export formats

The authoritative export source remains the live kernel `Figure`.

The synchronization path is:

1. the GUI resolves the opening first-class figure identity
2. the dialog seeds transient export state from current figure metadata
3. the dialog lowers that state to executable Python when the destination is concrete
4. `Do It` executes that export string against the live kernel figure

If the opening figure is closed or becomes unavailable while the dialog is open:

- the dialog stops producing an export string
- the lower pane shows status text
- `Do It`, `To Cmd Line`, and `To Clip` are disabled

Export does not require a figure-IR resync, does not mutate `fig._hyde_ir`, and does
not change the figure's editability classification.

## Explicit Exclusions

- using GUI-local cached pixels as the authoritative export source
- saving recreation macros through this dialog
- mutating figure structure, trace styling, axis settings, or figure IR as part of
  export
- routing export through a private non-Python GUI transport when an explicit command
  string will do
- exporting non-first-class figures through Hyde's figure-window menu
- treating the screenshot's `Color` checkbox as a committed monochrome contract before
  that behavior is separately specified
- treating the lower pane as a free-form command editor

## Future Work

- define a Hyde-native monochrome/grayscale export contract for the visible `Color`
  control
- add export presets
- add batch export
- add richer destination presets and project-aware export locations
- coordinate later publish/presentation workflows with the same export-state model
