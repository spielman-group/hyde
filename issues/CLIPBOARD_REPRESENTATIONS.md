# Clipboard Representations Issues

Source: design agreement reached by interview, recorded under **Agreed Design
Decisions** below. There is no separate PRD; this file is the plan of record.

Purpose: make a copied figure paste as vector wherever the receiving application
can take one, and reduce the copy menu from thirteen file formats to the three
representations a clipboard actually distinguishes.

## Progress Checklist

- [x] Slice 2: Reduce Copy To Vector, Image And LaTeX
- [x] Slice 3: Carry Vector And Raster Together, And Let Copy As Force One
- [x] Slice 4: Publish A Native Vector Flavour On macOS
- [x] Slice 6: Test Cleanup And Spec Resync

Deferred until a Linux machine with the labscript suite is available. Nothing
below depends on them:

- [ ] Slice 1: Establish What Linux Already Publishes
- [ ] Slice 5: Publish A Native Vector Flavour On Linux

## Why

Copy offers thirteen formats. Twelve of them paste identically.

Measured on macOS by putting each format on the clipboard through Hyde's own
builder and asking the system what it received: every raster format --
`png`, `avif`, `gif`, `jpeg`, `jpg`, `tif`, `tiff`, `webp` -- and every vector
format -- `pdf`, `eps`, `ps`, `svg` -- reported the same set of native flavours,
because Qt republishes the image rather than the chosen encoding. `pgf` reported
text. So eleven of the thirteen menu entries are choices with no consequence at
the paste site, and the two that differ do so only for another Qt application
reading the raw MIME type.

The reason a vector format pastes as a picture is that Qt publishes an
unrecognised MIME type under a private flavour no native application can read.
Vector bytes are on the clipboard; nothing outside Qt can see them.

## Agreed Design Decisions

- **Save and Copy stop sharing a format list.** Save takes a *file format*, a
  deliberate choice with real consequences, and keeps all thirteen. Copy takes a
  *clipboard representation*, and the receiving application decides what it can
  use. Different questions, different lists.
- **Copy carries vector and raster together.** The receiving application picks
  the best it understands: a drawing program takes the vector, a chat window
  takes the picture. The user does not have to know which.
- **Copy As forces exactly one representation**: `Vector`, `Image`, or
  `LaTeX`. Negotiation is best-effort, and applications do sometimes take the
  raster when the user wanted the vector. Forcing is the escape hatch.
- **Forcing vector omits the raster entirely**, so an application that cannot
  take vector pastes nothing. That is the accepted cost: a silent raster
  fallback is the behaviour being escaped.
- **Vector is a user concept, not a format.** Hyde attaches PDF and SVG under
  their MIME types and each platform publishes whichever it understands
  natively. The user picks *vector*, never *PDF-on-macOS-SVG-on-Linux*.
- **Image means PNG.** The other raster encodings are indistinguishable once
  pasted.
- **LaTeX is text and carries no image.** An image alongside it means pasting
  into a word processor silently yields a picture instead of the source.
- **Copy reproduces what is shown.** No implicit cropping, resizing or DPI
  change. lyse passes `bbox_inches='tight'` when copying, so what it puts on the
  clipboard is not the figure the user is looking at. Hyde does not follow it.

## What lyse does, and what is worth taking

`lyse.utils.worker.figure_to_clipboard` saves a temp PNG and hands it to a
detached process that loads it, deletes the file, and calls
`clipboard().setImage()`. It copies **PNG only** -- no vector, no format
choice -- so this work is not about matching lyse.

The temp file is transport between processes, not a clipboard mechanism. What is
worth taking is the reason for the separate process, which lyse's own comment
gives: clipboard data is not requested until it is pasted, so the application
that copied must still be running. Hyde's GUI owns the clipboard and stays
running, so it already satisfies this. A short-lived helper process would not.

## Slice 1: Establish What Linux Already Publishes

### Type

`HITL` - **deferred**, no Linux machine with the labscript suite installed.

Slices 2 to 4 do not depend on this. Slice 4 puts the platform mapping behind a
seam whose Linux side is simply absent, which is also the correct shape if it
turns out Linux needs nothing, so deferring costs no rework.

### What to build

Nothing. Determine whether Ubuntu already publishes vector MIME types natively.
X11 and Wayland selections are MIME-typed at the protocol level, so Qt may map
`application/pdf` and `image/svg+xml` straight through to selection targets with
no converter at all.

Copy a figure from Hyde on the Ubuntu machine, then read the offered targets:

```bash
xclip -selection clipboard -t TARGETS -o
```

Record whether `application/pdf` and `image/svg+xml` appear, and whether pasting
into Inkscape or LibreOffice yields vector.

### Acceptance criteria

- [ ] The target list Ubuntu offers after a Hyde copy is recorded in this file.
- [ ] It is stated whether Slice 5 is needed at all.

### Blocked by

None - can start immediately.

## Slice 2: Reduce Copy To Vector, Image And LaTeX

### Type

`AFK`

### What to build

Copy offers three representations rather than thirteen formats. The `Copy As`
submenu lists `Vector`, `Image` and `LaTeX` in both the Edit menu and the figure
context menu. The clipboard format table shrinks to what Hyde actually
publishes. `Save Graphics...` is untouched and keeps every format matplotlib can
write.

### Acceptance criteria

- [ ] `Copy As` lists exactly `Vector`, `Image` and `LaTeX`.
- [ ] `Save Graphics...` still offers the full generated format table.
- [ ] The generated format table and its regeneration script are unchanged;
      only the clipboard-representation mapping shrinks.
- [ ] Choosing each representation still places a pasteable payload.

### Blocked by

None - can start immediately.

## Slice 3: Carry Vector And Raster Together, And Let Copy As Force One

### Type

`AFK`

### What to build

A copy renders a *set* of representations rather than one format plus an
optional companion. The default `Copy` carries vector and raster together.
`Copy As Vector` carries vector only, `Copy As Image` raster only, and
`Copy As LaTeX` text only.

This changes the payload the kernel sends: `hyde.copy_figure` currently renders
one format and an optional companion PNG, and the parent message carries a
single `payload_base64`. It needs to carry several named representations.

### Acceptance criteria

- [ ] A default copy places both vector and raster representations in one
      payload.
- [ ] `Copy As Vector` places no raster representation.
- [ ] `Copy As Image` places no vector representation.
- [ ] `Copy As LaTeX` places text and no image, as now.
- [ ] The rendered bytes still reach the clipboard through plugin event
      dispatch, not by calling the handler directly.

### Blocked by

- Slice 2

## Slice 4: Publish A Native Vector Flavour On macOS

### Type

`AFK`

### What to build

Register a `QUtiMimeConverter` mapping `application/pdf` to `com.adobe.pdf` and
`image/svg+xml` to `public.svg-image`, so a vector copy reaches applications
outside Qt. Qt 6 registers a converter when it is constructed and unregisters it
when it is destroyed, so the instance has to be owned for the life of the
application.

Implement it behind one seam that each platform fills in, empty where nothing is
needed, rather than a macOS branch in the copy path.

### Acceptance criteria

- [ ] After a vector copy on macOS, the system reports a PDF flavour.
- [ ] Pasting into an application that prefers vector yields vector.
- [ ] The raster representation still reaches applications that want a picture.
- [ ] The converter survives for the life of the GUI, with a test that fails if
      its owner is dropped.

### Blocked by

- Slice 3

## Slice 5: Publish A Native Vector Flavour On Linux

### Type

`AFK` - **deferred** with Slice 1.

### What to build

Whatever Slice 1 shows is missing. If Ubuntu already offers `application/pdf`
and `image/svg+xml` as selection targets, this slice is closed with a note and
no code.

### Acceptance criteria

- [ ] A vector copy on Ubuntu pastes as vector into Inkscape or LibreOffice.
- [ ] If no code was needed, that is recorded here with the evidence.

### Blocked by

- Slice 1
- Slice 3

## Slice 6: Test Cleanup And Spec Resync

### Type

`AFK`

### What to build

Use the test-cleanup skill. Remove tests that pinned the thirteen-format copy
menu, and keep the ones that assert what a paste receives. Resync
`project_management/specs/save_graphics_dialog/SPEC.md`, whose Format Behavior
and Clipboard Payload sections describe the old list, and `IPC_PROTOCOL.md`,
whose `COPY_TO_CLIPBOARD_REQUEST` payload changes shape in Slice 3.

### Acceptance criteria

- [ ] No test asserts the membership of the old thirteen-format copy list.
- [ ] Tests assert what a paste receives, not which MIME types were set.
- [ ] `SPEC.md` describes three representations and the forcing behaviour.
- [ ] `IPC_PROTOCOL.md` describes the new payload shape.

### Blocked by

- Slices 2, 3, 4

Slice 5 is deferred and does not block this. If Linux later needs a converter,
its spec wording lands with it.

## Outcome

Slices 2, 3, 4 and 6 are done. A copied figure now pastes as vector into
applications outside Qt on macOS, verified against the system pasteboard rather
than through Qt's own reading of it: a vector-only copy reports no usable
flavour without the converter and a PDF with it.

Copy offers three representations instead of thirteen formats, a plain Copy
carries a vector and a raster together, and Copy As forces one. Only the vector
format the running platform can publish is rendered.

Slices 1 and 5 remain deferred, so a vector copy on Linux is still untested. It
may already work, because X11 and Wayland selections are MIME-typed at the
protocol level, or it may need a converter of its own; the platform table has
one obvious line to gain once it is measured.

## Risks

- **Converter lifetime.** Qt registers a mime converter on construction and
  unregisters it on destruction. A converter created and dropped registers
  nothing, and the symptom is that vector paste works sometimes. This branch has
  already produced one intermittent segfault and one deadlock from Qt object
  lifetimes; assume this is where the next one comes from.
- **`QUtiMimeConverter` is Qt 6 only.** The environment is Qt 6.11 through
  PyQt6, but `qtutils` abstracts the binding, so confirm Hyde requires Qt 6
  before depending on it.
- **The parent-message payload changes shape** in Slice 3, and the GUI and
  kernel halves must move together.

## Not in scope

- **Windows.** `QWindowsMimeConverter` is the equivalent seam and can be filled
  in when Hyde runs there.
- **Linux, for now.** Slices 1 and 5 are deferred rather than dropped. Until
  they run, a vector copy on Linux is untested: it may already work, because X11
  and Wayland selections are MIME-typed at the protocol level, or it may need a
  converter. Neither is known, and nothing in this branch should claim it is.
- **Emitting only non-default Python in generated figure source.** A separate
  branch: it needs a default-state source independent of any live figure, which
  means matplotlib's own rcParams rather than a snapshot of an existing figure.
