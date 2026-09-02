# Save Graphics Dialog Specification

## Purpose

`Save Graphics...` is Hyde's figure-scoped export dialog for writing the active
first-class figure to a graphics file.

`Copy` and `Copy As` are the clipboard half of the same feature. They place a
rendering of the active first-class figure on the system clipboard without a
dialog. Both halves share one output-option contract and one reuse boundary,
which is why they are specified together. They no longer share a format list:
save takes a file format, copy takes a clipboard representation.

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

- `OK`
- `To IPython`
- `Copy`
- `Help`
- `Cancel`

The lower pane follows the normal Hyde preview/status contract:

- when the dialog resolves to a concrete output path, the pane shows the executable
  Python backing string
- when the dialog is incomplete or invalid, the pane shows validation/status text
- `OK`, `To IPython`, and `Copy` all use the same backing string when that
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
- Overwrite is handled through Hyde's normal confirmation flow on `OK`.
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
- The width/height display always shows the values that would be used if `OK` were
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
- `OK` may dispatch the already generated preview string without regenerating it

The generated command:

- resolves the figure with `hyde.get_figure(...)`
- calls standard matplotlib `savefig(...)` semantics on that live figure
- passes the selected format, `DPI`, and transparency option
- applies a temporary size override only when `Custom` is active
- restores the original figure size after a temporary custom-size export

`OK` dispatches that command through Hyde's hidden execution path.

## Clipboard Copy

### Entry Points

- `Copy` appears in the `Edit` menu carrying the platform copy shortcut, in the
  `Figure` menu, and in the figure window context menu.
- `Copy As` is a submenu in the same three surfaces, listing one entry per
  clipboard representation.
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

A clipboard distinguishes *representations*, not file formats. The receiving
application asks for a picture, or a drawing, or some text, and every raster
encoding answers the first question identically -- measured on macOS, all twelve
of the clipboard-capable raster and vector formats produced the same native
flavours, because the platform republishes the image rather than the encoding it
was handed. So copy offers three representations:

- `Vector` -- a drawing, rendered as `pdf` or `svg`
- `Image` -- a picture, rendered as `png`
- `LaTeX` -- source, rendered as `pgf`

`Copy` with no representation named carries every representation a
picture-or-drawing consumer might want, and the receiving application picks the
best it understands. Naming one through `Copy As` forces it, which is how to
insist on a vector when an application would otherwise settle for the raster.
Forcing a representation omits the others entirely: an application that cannot
take a vector then pastes nothing, which is the point, because a silent raster
fallback is the behaviour being escaped.

`LaTeX` is exclusive and never travels with an image. It is source, and what
someone copying it intends to paste is the source; an image alongside it would
mean pasting into a word processor silently yields a picture instead.

Which format serves a representation is Hyde's choice rather than the user's. A
representation names candidate formats in preference order and the running
platform picks one, so a user chooses *vector*, never *PDF-on-macOS-SVG-on-Linux*.
Only the chosen format is rendered: asking the kernel for every candidate would
render figures nothing on that machine can paste. That choice is the one place
platform knowledge lives, and a platform Hyde has not been verified on is absent
from it rather than guessed at, falling back to a representation's first
candidate.

Save is unaffected and keeps every format matplotlib can write. Save takes a
file format, a deliberate choice with real consequences; copy takes a
representation, and the receiving application decides. Different questions,
different lists.

The dialog reads one generated table of matplotlib's export formats. It does not
query matplotlib at runtime: the query imports `matplotlib.pyplot` and resolves
an interactive backend as a side effect, which the GUI process must not do. The
table is regenerated by its own script rather than at run time, and a commit
hook refuses a stale one.

### Clipboard Payload

- The kernel renders exactly the formats it was asked for and decides nothing
  about representation: it reports one rendering per format, and which MIME type
  each becomes is the GUI's business.
- Each rendering is placed under its format's MIME type. That reaches other Qt
  applications and nothing else.
- A raster rendering is additionally placed as an image rather than only as
  bytes. Everything outside Qt reads the platform's own clipboard, where Qt
  publishes an unrecognised MIME type under a private flavour no application can
  paste -- so a copy that only set bytes put nothing usable on the clipboard at
  all. Set as an image, it is republished as the platform's own image flavours.
- A vector rendering is published under the identifier the platform knows it by,
  through a converter registered for the life of the process. Without one, the
  vector bytes are on the clipboard and invisible to everything outside Qt.
- `LaTeX` is placed as text, which every platform already understands.

### Output Options

Copy has no dialog, so it takes fixed options rather than exposing controls:

- the formats rendered come from the invoked representation
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
hyde.copy_figure(fig, formats=('pdf',), dpi='figure')
```

Copy is a distinct command from save rather than a save with a null target: copy
carries no output path and save requires one, so separate commands keep both
validations honest and give the `'figure'` DPI sentinel a home where it is the
only valid value.

The emitted call is a Hyde helper rather than plain matplotlib because the
clipboard is GUI-owned and matplotlib cannot express it. `IR-CONTROL.md` permits a
Hyde helper in emitted Python exactly when it is the necessary contract for a
Hyde-owned operation.

`OK` dispatches the command through Hyde's hidden execution path, matching the
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

A copy is answered twice, by routes nothing orders against each other. The
kernel's reply to the render command says whether it ran, and carries the reason
when it did not. The rendered bytes arrive separately. Either can be first, so
copy waits for whichever it still needs and succeeds as soon as the bytes are
in hand.

Only one copy is outstanding at a time. A second copy while one is in flight is
refused with a status message rather than queued, because the rendered bytes do
not say which copy they answer.

The kernel executes one request at a time, so a copy issued while the user's own
code is running waits its turn. That wait is unbounded and is not a failure: a
copy queued behind a long-running cell completes when the kernel reaches it.

Copying does not alter the live figure's size, DPI, or any other state.

### Feedback

Copy's entire effect is invisible until the user pastes elsewhere, so it reports
what happened:

- the status bar names the format that reached the clipboard on success
- a render that produces nothing reports failure rather than confirming success
- a render that raises reports what the kernel said, rather than a generic
  failure. The reply carries the exception, so the copy does not have to guess
- a copy fails if the kernel goes away while it is outstanding
- a busy cursor appears only if the copy has not completed within a short delay,
  so a fast copy does not flicker the cursor
- the busy cursor comes back down after a short hold even though the copy is
  still outstanding. It says something started, not how long it will take; held
  for a minute behind a long user cell it would read as a hung application, and
  the status message carries the rest
- a copy whose render succeeded but whose bytes never arrive fails after a short
  bounded wait. That wait bounds a transport gap, not the kernel's work: the
  render has already run and the bytes are in transit
- however a copy ends, the cursor is restored. This is mandatory: an unrestored
  busy cursor makes the whole application look hung, which is worse than no
  feedback at all

### Controls

- `Copy`, `Copy As`, and every representation entry: `active`
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
