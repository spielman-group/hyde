# Figure Copy Issues

Source: design agreement reached by interview, recorded under **Agreed Design
Decisions** below. There is no separate PRD; this file is the plan of record.

Purpose: add clipboard copy of the active first-class figure to Hyde, reusing the
figure graphics-output path that `Save Graphics...` already owns.

## Progress Checklist

- [x] Slice 1: Enable And Disable Menu Actions From Live Preconditions
- [x] Slice 2: Copy The Active Figure As PDF
- [x] Slice 3: Add The Edit Menu With Copy And Its Shortcut
- [x] Slice 4: Offer Copy As Over The Clipboard-Capable Format Set
- [x] Slice 5: Copy PGF As Text
- [x] Slice 6: Attach A PNG Companion Representation
- [ ] Slice 7: Report Copy Progress And Failure
- [ ] Slice 8: Resync The Save Graphics Spec And Architecture Docs
- [ ] Slice 9: Test Cleanup Pass

## Agreed Design Decisions

These were settled deliberately. Do not re-litigate them while implementing; if
one turns out to be wrong, say so explicitly and record the change here.

1. **Transport.** A public `hyde.copy_figure(...)` renders in the kernel and
   hands the bytes to the GUI over the existing parent-message channel that
   `signal_open_table` uses. The GUI stays a string factory and the kernel stays
   authoritative over rendering.

   Rejected: a temp file the GUI reads back (emitted Python would misdescribe
   the user's intent as "save to /tmp"), and a new comm request/response
   (`IR-CONTROL.md` records moving figure work *off* separate semantic figure
   transports).

   `IR-CONTROL.md` permits a Hyde helper in emitted Python "when they are the
   necessary or clearer contract for a Hyde-owned operation". The clipboard is
   GUI-owned and plain matplotlib cannot express it, so this is that carve-out
   rather than an abuse of it.

2. **Copy is asynchronous, by construction.** The clipboard is not populated
   when the menu action returns. This is the price of keeping the kernel
   authoritative. If the race ever bites in practice, the fix is the synchronous
   temp-file route, not a patch to this one.

3. **DPI resolves in the kernel.** Emitted Python passes `dpi='figure'`, which
   is matplotlib's own default (`rcParams['savefig.dpi']` is `'figure'`), so the
   GUI never mirrors the figure's DPI. The copy path's validation accepts that
   sentinel; the save path continues to require a positive integer.

   Consequence, accepted: Hyde figures inherit `rcParams['figure.dpi']` of 100,
   so raster copies are 640x480 rather than 1920x1440. The fix for that, if
   wanted, is a Hyde-wide figure creation DPI - not a hardcoded number buried in
   the copy path.

   Note also that `Figure.set_dpi()` after construction does not affect
   `savefig(dpi='figure')`; only DPI set at construction is honoured. This is a
   matplotlib behaviour, not something Hyde can fix.

4. **Format set.** Copy offers a curated subset of what Save offers, because
   some savefig formats are not clipboard data at all:

   - offered as images: `pdf`, `png`, `avif`, `eps`, `gif`, `jpeg`, `jpg`, `ps`,
     `svg`, `tif`, `tiff`, `webp`
   - offered as text: `pgf`, which is LaTeX source and has no image reading
   - excluded: `raw` and `rgba` (raw buffers with no MIME type), and `svgz`
     (gzipped SVG that no application pastes, superseded by `svg`)

   Ordering and user-facing labels match the Save dialog exactly, so the two
   surfaces stay consistent.

5. **Default copy is PDF.**

6. **Menu surfaces.** `Copy` and `Copy As` appear in the Edit menu, the Figure
   menu, and the figure window context menu. Three surfaces rather than the two
   originally wanted, because `contextMenuEvent` re-renders the whole `figure`
   location into the popup - the same mechanism by which `Save Graphics...`
   already reaches both the Figure menu and the context menu.

7. **Ownership.** Copy lives in the `save_graphics_dialog` plugin beside the
   graphics-output path it reuses. `edit` becomes a shared menu location, and
   each widget family contributes its own copy actions into it, so table copy
   and terminal copy later land in their own plugins with no central dispatcher.

   The package name carries a `_dialog` suffix that `STYLE.md` reserves for
   dialog plugins, and copy has no dialog. Accepted as a wart; the `file`
   plugin already sets that precedent.

8. **IR shape.** A distinct copy command with its own
   `FigureIR.with_copy_graphics(...)`, not an overload of the save path with a
   null output path. Copy has no output path and save requires one, so separate
   commands keep both validations honest and give the `'figure'` DPI sentinel a
   home where it is the only valid value.

   Refined while implementing: this is a `FigureIR` command, not a
   `MatplotlibCodec` feature kind. Copy lowers to `hyde.copy_figure(...)`, which
   is a Hyde string, so it emits from `hyde_features.py`. A `matplotlib_features`
   model emitting Hyde strings would break the package-purity rule that
   `IR-CONTROL.md` sets for those lowerers.

9. **Dispatch.** Hidden, matching `Save Graphics`' `Do It`. Copy is the
   highest-frequency action in the application and echoing every keypress into
   the terminal would make it unusable.

10. **Boundary.** `hyde/__init__.py` must not import Qt. `copy_figure` renders
    bytes and hands them off; it must never touch the clipboard itself. The
    architecture guard in `tests/test_hyde_feature_modules.py` polices this.

## Global Rules

- Run tests in the `labscript` conda environment. It has no `pytest`; use
  `QT_QPA_PLATFORM=offscreen python -m unittest <module>`. Prefer loading every
  module into one process over a per-module loop, which hides cross-module state
  leaks.
- After each slice, run the architecture guard
  `tests/test_hyde_feature_modules.py::TestHydeFeatureModuleLayout::test_kernel_side_modules_never_reach_gui_plugins_or_qt`.
  Do not weaken it to a direct-import check.
- Use TDD for implementation slices.
- Do not add production fallbacks for stale fake fixtures. Update the fixtures.
- Do not add speculative infrastructure. Every seam introduced here must have a
  real consumer inside these slices.

## Slice 1: Enable And Disable Menu Actions From Live Preconditions

### Type

`AFK`

### What to build

Let a menu contribution declare its precondition as a callable rather than a
static boolean, and have the menu machinery re-evaluate that callable whenever
the user could act on it.

Today menus are rendered once at startup and never refreshed, so figure actions
stay permanently enabled and silently do nothing when no figure is active. That
is tolerable in the Figure menu, where the precondition is self-evident, and
wrong in an Edit menu.

Three facts shape this work:

- `MenuContext` lives in `labscript-utils`, but `HydeMenuContext` already
  overrides `render()` and `_render_menu_tree()` inside Hyde, so this is a
  Hyde-local change.
- The contribution schema already carries an `enabled` key that nothing uses
  with a non-default value.
- Context menus need no extra work: `build_popup_menu` re-renders the whole tree
  on every popup, so a callable precondition is evaluated fresh each time.

That leaves the menu bar, which needs re-evaluation when a menu is about to be
shown, and when the active window changes so that keyboard shortcuts are gated
correctly even if the user never opens the menu.

A disabled `QAction` ignores its own shortcut - verified with a real key event,
not a programmatic trigger - so correct enablement gates shortcuts for free with
no separate shortcut-handling path.

### Acceptance criteria

- [x] A contribution may supply `enabled` as a callable, and the menu machinery
      calls it to decide the action's state.
- [x] Static boolean and absent `enabled` values keep working unchanged.
- [x] Menu-bar actions re-evaluate when their menu is about to be shown, and
      when the active MDI window changes.
- [x] Context-menu actions reflect the current precondition on every popup.
- [x] A disabled action does not fire on its keyboard shortcut.
- [x] `Figure` menu figure actions, including `Save Graphics...`, appear disabled
      when no first-class figure is active and enabled when one is. This is
      observable before any copy code exists.
- [x] Every existing menu contribution still renders in the same order, groups,
      and separators as before.

### Blocked by

None - can start immediately.

### User stories covered

- Agreed Design Decision 6 (menu surfaces) and the requirement that Edit-menu
  copy entries become active only when copying is possible.

## Slice 2: Copy The Active Figure As PDF

### Type

`AFK`

### What to build

The tracer bullet: one format, one surface, every layer.

A `Copy` action on the active first-class figure puts a PDF rendering of that
figure on the system clipboard, so it can be pasted into another application.

The path runs: GUI emits Python from figure IR, the kernel resolves the live
figure and renders it, the kernel hands the bytes to the GUI, and the GUI writes
them to the clipboard as `application/pdf`.

This slice necessarily introduces the public runtime helper, the kernel-to-GUI
byte hand-off, the `figure_graphics_copy` feature kind and its IR constructor,
the `'figure'` DPI sentinel on the copy path, and a single `Copy` entry in the
Figure menu and figure context menu. Dispatch is hidden. The action declares its
precondition through Slice 1 so it is disabled with no active figure.

### Acceptance criteria

- [x] `Copy` on an active figure results in a PDF on the clipboard that another
      application can paste.
- [x] The emitted Python resolves the figure by its stable Hyde name and passes
      `dpi='figure'`; it contains no GUI-side clipboard call.
- [x] The copy feature kind validates without an output path, and rejects a
      state carrying one.
- [x] The save feature kind still requires a positive integer DPI and still
      rejects the `'figure'` sentinel.
- [x] `hyde/__init__.py` gains no Qt import; the architecture guard passes.
- [x] `Copy` is disabled when no first-class figure is active.
- [x] Copying does not alter the live figure's size, DPI, or any other state.

### Blocked by

- Slice 1: Enable And Disable Menu Actions From Live Preconditions

### User stories covered

- Agreed Design Decisions 1, 2, 3, 5, 8, 9, 10.

## Slice 3: Add The Edit Menu With Copy And Its Shortcut

### Type

`AFK`

### What to build

Hyde has no Edit menu. Add one as a shell-owned menu location, in the same way
File, Figure, Table, Window and Analysis already work: the application owns the
menu object and plugins contribute actions into it.

Contribute the existing `Copy` action into that menu with the platform copy
shortcut, so the default copy is reachable both from Edit and from the keyboard.

The menu is deliberately shell-owned rather than plugin-owned so that table copy
and terminal copy can later contribute into it without renegotiating ownership.

### Acceptance criteria

- [x] An Edit menu exists in the menu bar, positioned conventionally, and is
      registered as a menu location plugins can contribute to.
- [x] `Edit > Copy` copies the active figure as PDF, identically to the Figure
      menu entry.
- [x] The platform copy shortcut triggers the same action.
- [x] Both are disabled, and the shortcut inert, when no figure is active.
- [x] No existing menu changes contents or order.

### Blocked by

- Slice 2: Copy The Active Figure As PDF

### User stories covered

- Agreed Design Decisions 5, 6, 7.

## Slice 4: Offer Copy As Over The Clipboard-Capable Format Set

### Type

`AFK`

### What to build

A `Copy As` submenu listing the clipboard-capable formats, each entry copying
the active figure in that format.

Which formats are clipboard-capable, and what MIME type each carries, is data
about the format rather than dialog policy, so it belongs in the feature layer
beside the existing graphics-output helpers - where the Save Graphics spec's
reuse boundary already says graphics-output lowering lives, and where this slice
finally gives that seam a real consumer.

The list is the curated set from Agreed Design Decision 4, in the same order and
with the same labels the Save dialog uses. `pgf` appears here but its text
behaviour is Slice 5.

The submenu appears in the Edit menu, the Figure menu, and the figure context
menu.

### Acceptance criteria

- [x] `Copy As` lists exactly the curated format set, ordered and labelled as in
      the Save Graphics dialog.
- [x] `raw`, `rgba` and `svgz` do not appear.
- [x] Each image-format entry places data on the clipboard under that format's
      MIME type, pasteable in an application that accepts it.
- [x] The submenu appears in the Edit menu, Figure menu, and figure right-click
      menu, and its entries are disabled when no figure is active.
- [x] Clipboard-capability and MIME mapping are queryable from the feature layer
      without importing Qt or any plugin module.

### Note

Contributing a submenu to a location that also holds plain actions was new
ground, and it surfaced a latent lifetime bug elsewhere: figure and table
workspaces connected `QMdiSubWindow.destroyed` to `functools.partial`
callbacks, which Qt keeps and calls even after cyclic GC has cleared them.
Fixed by connecting those signals to bound methods and passing the workspace
handle through a Qt property. `STYLE.md` carries the general rule.

The `Copy As` menu is built from Hyde's static clipboard format mapping rather
than from the live matplotlib runtime. Menus are constructed during application
start-up, and the runtime query imports `matplotlib.pyplot` and resolves an
interactive backend as a side effect; the GUI process does not own figures, and
once pyplot is imported `configure_gui_matplotlib_backend()` becomes a no-op.
The static mapping yields identical keys, labels and suffix aliases, because
MIME values group `jpg`/`jpeg`, `tif`/`tiff` and `eps`/`ps` exactly as the
runtime descriptions do.

The trade-off is deliberate and belongs in the spec: `Save Graphics` remains
runtime-derived, while `Copy As` is a fixed Hyde-curated list. If a matplotlib
build ever drops one of these formats, the copy menu would still offer it and
the copy would fail at render time rather than the entry being absent.

### Blocked by

- Slice 3: Add The Edit Menu With Copy And Its Shortcut

### User stories covered

- Agreed Design Decisions 4, 6, 7.

## Slice 5: Copy PGF As Text

### Type

`AFK`

### What to build

`Copy As > PGF` puts the generated LaTeX source on the clipboard as text, not as
an image, because that is what someone copying PGF intends to paste.

This is the one format in the set with no image reading, so it is also the one
format excluded from the companion representation added in Slice 6.

### Acceptance criteria

- [x] `Copy As > PGF` yields text that pastes into a text editor as LaTeX
      source.
- [x] The PGF clipboard payload carries no image representation.
- [x] Image formats are unaffected.

### Blocked by

- Slice 4: Offer Copy As Over The Clipboard-Capable Format Set

### User stories covered

- Agreed Design Decision 4.

## Slice 6: Attach A PNG Companion Representation

### Type

`AFK`

### What to build

A clipboard payload can carry several representations of the same content.
Attach a PNG rendering alongside the requested image format, so a paste succeeds
in applications that do not accept the primary type while applications that
prefer vector still receive it.

Without this, the default PDF copy appears to do nothing in a significant number
of applications.

PGF is excluded: attaching an image to a text copy would mean pasting into a
word processor silently yields a picture instead of the LaTeX source that was
asked for.

### Acceptance criteria

- [x] An image-format copy carries both the requested format and a PNG
      representation.
- [x] An application that accepts only PNG can paste the result of a PDF copy.
- [x] An application that prefers the primary format still receives it.
- [x] A PGF copy carries text only.

### Blocked by

- Slice 4: Offer Copy As Over The Clipboard-Capable Format Set
- Slice 5: Copy PGF As Text

### User stories covered

- Agreed Design Decision 4.

## Slice 7: Report Copy Progress And Failure

### Type

`AFK`

### What to build

Copy is asynchronous and its entire effect is invisible until the user pastes
somewhere else, so it needs to say what happened.

Report progress and outcome in the status bar, reusing the existing project
status-message idiom, exposed so plugins can use it. Show a busy cursor only if
the copy has not completed within a short delay, so a fast copy does not flicker
the cursor.

A timeout guard is mandatory rather than optional. If the kernel never replies -
dead kernel, exception during render, dropped message - an unrestored busy
cursor makes the whole application look hung, which is worse than no feedback at
all. The timeout path is also the first failure surface copy has.

Hidden-execution failures remain generally invisible across Hyde; that is
existing debt and is not in scope here.

### Acceptance criteria

- [ ] A completed copy confirms in the status bar which format reached the
      clipboard.
- [ ] A copy that has not completed within a short delay shows a busy cursor; a
      fast copy shows none.
- [ ] A copy that never completes restores the cursor and reports failure in the
      status bar.
- [ ] A failed render reports failure rather than silently confirming success.
- [ ] The cursor is never left in a busy state on any path.
- [ ] The status-message surface is available to plugins rather than private to
      the shell.

### Blocked by

- Slice 2: Copy The Active Figure As PDF

### User stories covered

- Agreed Design Decisions 2, 9.

## Slice 8: Resync The Save Graphics Spec And Architecture Docs

### Type

`AFK`

### What to build

Extend `project_management/specs/save_graphics_dialog/SPEC.md` with the copy
contract, using the `add-hyde-ui-feature` skill. Copy and save share the format
list, the output options, and the reuse boundary, so one spec covering both
avoids duplicating all three.

The spec must state the present-tense system: entry points and surfaces, the
curated format set and why each exclusion is excluded, PGF as text, the
companion representation, DPI resolution in the kernel, the asynchronous
clipboard and its accepted race, and the feedback contract.

Record in the architecture and IR-control docs that clipboard copy is the second
consumer of the figure graphics-output path, and that `edit` is a shared menu
location each widget family contributes into. Note the raster-size consequence
of `dpi='figure'` as remaining work rather than leaving it implicit.

### Acceptance criteria

- [ ] The Save Graphics spec describes copy in the present tense, including
      every agreed decision that a reader would otherwise have to infer.
- [ ] Each format exclusion carries its technical reason.
- [ ] The spec states that `Save Graphics` derives its format list from the
      matplotlib runtime while `Copy As` uses Hyde's static clipboard mapping,
      why they differ, and what that costs.
- [ ] The asynchronous clipboard and its accepted race are documented, not
      omitted.
- [ ] `IR-CONTROL.md` records the `figure_graphics_copy` feature kind and the
      `'figure'` DPI sentinel.
- [ ] `STATUS.md` lists the figure-DPI raster-size follow-up.
- [ ] No historical narrative in the spec; progress notes stay in progress docs.

### Blocked by

- Slice 2 through Slice 7

### User stories covered

- All Agreed Design Decisions.

## Slice 9: Test Cleanup Pass

### Type

`AFK`

### What to build

Use the `test-cleanup` skill on the tests written across these slices.

Keep tests that fail when copy behaviour or an intentional architecture boundary
breaks. Rewrite tests that assert real behaviour through private structure.
Delete tests that only preserved a development-loop implementation path.

The durable safety net this should leave behind:

- a PDF copy reaches the clipboard and the live figure is unchanged
- the copy feature kind rejects an output path and the save kind rejects the DPI
  sentinel
- the curated format set and its exclusions
- PGF as text, with no image companion
- the PNG companion on image formats
- menu actions disabled without an active figure, and shortcuts inert when
  disabled
- `hyde/__init__.py` stays Qt-free

### Acceptance criteria

- [ ] Every remaining test has a public behaviour or architecture-contract
      reason to exist.
- [ ] Tests asserting private wiring, call order, or stale fixture shape are
      removed or rewritten.
- [ ] No production fallback was added to keep an old test passing.
- [ ] The whole suite passes in a single process.

### Blocked by

- Slice 8: Resync The Save Graphics Spec And Architecture Docs

### User stories covered

- To-Issues required test-cleanup slice.
