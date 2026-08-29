# Save Graphics Dialog Specification

## Purpose

`Save Graphics...` is Hyde's figure-scoped export dialog for writing the active
first-class figure to a graphics file.

`Copy` and `Copy As` are the clipboard half of the same feature. They place a
rendering of the active first-class figure on the system clipboard without a
dialog. Both halves share one format vocabulary, one output-option contract, and
one reuse boundary, which is why they are specified together.

The dialog owns only transient export configuration. The authoritative export source is
always the live kernel matplotlib `Figure` resolved from the opening figure identity.
The dialog does not export cached GUI pixels, does not patch figure IR, and does not
participate in figure-dialog patch workflows.

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
- the figure family's `FigureIR` path owns export request normalization and lowering
- `hyde/features/matplotlib_features.py` owns the export-command lowering
- execution runs against the live kernel figure looked up by stable Hyde figure name
- `Do It` may dispatch the already generated preview string without regenerating it

The generated command:

- resolves the figure with `hyde.get_figure(...)`
- calls standard matplotlib `savefig(...)` semantics on that live figure
- passes the selected format, `DPI`, and transparency option
- applies a temporary size override only when `Custom` is active
- restores the original figure size after a temporary custom-size export

`Do It` dispatches that command through Hyde's hidden execution path.

## Clipboard Copy

### Entry Points

- `Copy` appears in the `Edit` menu carrying the platform copy shortcut, in the
  `Figure` menu, and in the figure window context menu.
- `Copy As` is a submenu in the same three surfaces, listing one entry per
  clipboard-capable format.
- The `Figure` menu and the figure context menu render the same location, so a
  single contribution reaches both.
- `Edit` is a shell-owned menu location. Each widget family contributes its own
  copy actions into it, so later table and terminal copy need no central
  dispatcher.
- Every copy action requires an active first-class figure and is disabled
  without one. A disabled action's shortcut is inert, so the keyboard is gated by
  the same precondition as the menu.

### Format Behavior

`Copy` copies PDF. `Copy As` offers the clipboard-capable subset of the export
formats, in the same order and with the same labels the dialog uses:

- offered as images: `pdf`, `png`, `avif`, `eps`, `gif`, `jpeg`, `jpg`, `ps`,
  `svg`, `tif`, `tiff`, `webp`
- offered as text: `pgf`
- not offered: `raw` and `rgba`, which are raw buffers with no clipboard MIME
  type, and `svgz`, which is gzipped SVG that no application pastes and which
  `svg` supersedes

Whether a format has a clipboard representation, and which MIME type it carries,
is data about the format rather than dialog policy, so that mapping lives in the
feature layer beside the other graphics-output helpers.

The dialog derives its format list from the matplotlib runtime; the copy menus
use Hyde's static clipboard mapping. They differ because menus are built during
application start-up and the runtime query imports `matplotlib.pyplot` and
resolves an interactive backend as a side effect, which the GUI process must not
do. The two lists agree on keys, labels, and suffix aliases today. The cost of
the divergence is that if a matplotlib build ever dropped one of these formats,
the copy menu would still offer it and the copy would fail at render time rather
than the entry being absent.

### Clipboard Payload

- An image-format copy places the rendering under that format's MIME type and
  additionally attaches an `image/png` representation. A clipboard payload can
  carry several representations of one content, so the paste succeeds in
  applications that reject the requested type while applications preferring
  vector still receive it. Without the companion, a PDF copy appears to do
  nothing in a great many applications.
- `png` carries no companion, which would only duplicate itself.
- `pgf` is placed as text, because it is LaTeX source and what someone copying it
  intends to paste is the source. It deliberately carries no image
  representation: an image companion would mean pasting into a word processor
  silently yields a picture instead of the source.

### Output Options

Copy has no dialog, so it takes fixed options rather than exposing controls:

- format comes from the invoked menu entry
- `DPI` is passed as matplotlib's `'figure'` sentinel, so the kernel resolves it
  against the live figure instead of the GUI mirroring kernel state
- transparency is off
- there is no size override; the figure's current size is used

Because Hyde figures inherit the matplotlib default figure DPI, raster copies are
correspondingly modest. Raising that is a figure-creation concern, not a
copy-specific override.

### Command Generation

Copy lowers through the figure IR family, like every other command-emitting Hyde
surface. `FigureIR.with_copy_graphics()` produces a copy command that resolves the
figure by its stable Hyde name and calls a Hyde runtime helper:

```
fig = hyde.get_figure('Graph12')
hyde.copy_figure(fig, format='pdf', dpi='figure')
```

Copy is a distinct command from save rather than a save with a null target: copy
carries no output path and save requires one, so separate commands keep both
validations honest and give the `'figure'` DPI sentinel a home where it is the
only valid value.

The emitted call is a Hyde helper rather than plain matplotlib because the
clipboard is GUI-owned and matplotlib cannot express it. `IR-CONTROL.md` permits a
Hyde helper in emitted Python exactly when it is the necessary contract for a
Hyde-owned operation.

`Do It` dispatches the command through Hyde's hidden execution path, matching the
dialog. Copy is the highest-frequency action in the application, so it is not
echoed to the terminal.

### Synchronization

Rendering happens in the kernel, which owns the figure; the rendered bytes are
handed to the GUI, which owns the clipboard. `hyde/__init__.py` must not import
Qt, so the runtime helper renders and hands off and never touches the clipboard
itself.

Copy is therefore asynchronous: the clipboard is not populated when the menu
action returns. This is the accepted cost of keeping the kernel authoritative
over rendering. The round trip is fast in practice, but the semantics differ from
a synchronous clipboard operation.

Copying does not alter the live figure's size, DPI, or any other state.

### Feedback

Copy's entire effect is invisible until the user pastes elsewhere, so it reports
what happened:

- the status bar names the format that reached the clipboard on success
- a render that produces nothing reports failure rather than confirming success
- a busy cursor appears only if the copy has not completed within a short delay,
  so a fast copy does not flicker the cursor
- a copy that never completes times out, restores the cursor, and reports
  failure. This guard is mandatory: an unrestored busy cursor makes the whole
  application look hung, which is worse than no feedback at all

### Controls

- `Copy`, `Copy As`, and every format entry: `active`
- there is no copy dialog, preview pane, or footer; these are menu actions only

## Reuse Boundary

The graphics-output option lowering for format, `DPI`, transparency, and temporary
size override lives in the shared matplotlib feature layer. It normalizes the export
dialog's options; the copy path does not use it, because copy takes fixed options and
carries no size override.

What the two halves genuinely share is the format vocabulary: the clipboard-capable
set and its MIME mapping sit beside that lowering, and copy consumes those.

## Out Of Scope

The initial deployment does not include:

- batch export
- multi-figure export from one dialog
- figure recreation macro export
- figure IR edits as part of export
- monochrome/color-mode export controls
- format curation beyond runtime-derived ordering and clear transparency disablement
