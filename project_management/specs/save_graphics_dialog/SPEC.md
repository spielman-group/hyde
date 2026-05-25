# Save Graphics Dialog Specification

## Purpose

`Save Graphics...` is Hyde's figure-scoped export dialog for writing the active
first-class figure to a graphics file.

The dialog owns only transient export configuration. The authoritative export source is
always the live kernel matplotlib `Figure` resolved from the opening figure identity.
The dialog does not export cached GUI pixels, does not patch figure IR, and does not
participate in figure-edit session workflows.

## Entry Points

- `Save Graphics...` appears in the `Figure` menu.
- The same action appears in the figure window context menu.
- Both menu surfaces use the same figure action and place it in a new section below
  the existing figure actions, after a separator.
- The dialog is bound to the opening active first-class figure and does not provide an
  internal figure picker.

## Dialog Contract

The dialog is a standard `HydeFileDialog` using the shared `HydeDialogWidget` footer:

- `Do It`
- `To Cmd Line`
- `To Clip`
- `Help`
- `Cancel`

The lower pane follows the normal Hyde preview/status contract:

- when the dialog resolves to a concrete output path, the pane shows the executable
  Python backing string
- when the dialog is incomplete or invalid, the pane shows validation/status text
- `Do It`, `To Cmd Line`, and `To Clip` all use the same backing string when that
  string exists
- `Help` is visible but inert in the initial deployment

## Layout

The dialog title is `Save Graphics`.

The body is stacked in this order:

1. full embedded `HydeFileWidget` save-target browser
2. `Format` section
3. `Size` section
4. shared preview/footer block

The `Format` section uses a two-column layout:

- left: runtime-derived single-selection format list
- right: general options panel

The initial options panel contains:

- `DPI`
- `Transparent`

The `Size` section contains:

- `Same`
- `Custom`
- visible width and height fields in inches

## File Target Behavior

- The suggested export directory is `<project>/exports/`.
- `Save Graphics` creates that suggested directory when the dialog opens if it does
  not already exist.
- The default basename comes from the stable Hyde figure name, sanitized only as
  needed for filesystem safety.
- The dialog defaults to the suggested project-local export path but does not restrict
  the user to saving inside `exports/`.
- Overwrite is handled through Hyde's normal confirmation flow on `Do It`.
- There is no `Force Overwrite` checkbox.
- The dialog does not remember prior selections between openings in the initial
  deployment.

## Format Behavior

- Available export formats come from the current matplotlib runtime.
- The format list is always visible and scrolls when needed.
- Ordering is:
  - `pdf` first when available
  - `png` second when available
  - remaining formats alphabetized
- The default selected format is the first available format in that order.
- The dialog shows user-facing format labels while using matplotlib format keys
  internally.
- The selected format is authoritative for:
  - the export format passed to `savefig`
  - the embedded file-browser name filter
  - Hyde-managed filename suffix recommendation
- When Hyde is still managing the suffix, changing format rewrites the suggested
  filename extension to match the selected format.
- Hyde does not overwrite a deliberate user-entered suffix variant such as `.jpeg`.

## Output Options

- `DPI` is a positive-integer control.
- Default `DPI` is `300`.
- `DPI` remains active for all formats, including vector outputs.
- `Transparent` defaults off.
- `Transparent` remains visible across format changes.
- `Transparent` is disabled only when support is clearly absent for the selected
  format/backend.
- Initial proactive disablement covers clearly opaque formats such as `jpg` and
  `jpeg`.

## Size Behavior

- Size is inches-only in the initial deployment.
- There is no units dropdown.
- `Same` means export using the figure's current size for this modal session.
- Width and height are always visible.
- Under `Same`, width and height are disabled and display the current figure size in
  inches.
- When switching to `Custom`, width and height initialize from that current figure
  size.
- Under `Custom`, width and height become the active export override values.
- The width/height display always shows the values that would be used if `Do It` were
  pressed immediately.
- Switching back to `Same` discards the prior custom draft and returns the display to
  the current figure size.
- Changing export format does not reset a current custom size.

## Command Generation

The dialog follows Hyde's string-factory rule:

- GUI state stays transient and UI-local
- `hyde/features/matplotlib_features.py` lowers the export request to the executable
  Python string
- execution runs against the live kernel figure looked up by stable Hyde figure name

The generated command:

- resolves the figure with `hyde.get_figure(...)`
- calls standard matplotlib `savefig(...)` semantics on that live figure
- passes the selected format, `DPI`, and transparency option
- applies a temporary size override only when `Custom` is active
- restores the original figure size after a temporary custom-size export

`Do It` dispatches that command through Hyde's hidden execution path.

## Reuse Boundary

The graphics-output option lowering for format, `DPI`, transparency, and temporary
size override lives in the shared matplotlib feature layer so it can be reused by a
future figure-copy workflow.

That reuse seam is limited to graphics-output options. This feature does not implement
clipboard export, `Copy...`, or any other copy surface.

## Out Of Scope

The initial deployment does not include:

- batch export
- multi-figure export from one dialog
- figure recreation macro export
- figure IR edits as part of export
- clipboard/copy export
- monochrome/color-mode export controls
- format curation beyond runtime-derived ordering and clear transparency disablement
