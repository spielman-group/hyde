# Branch Review Issues

Source: a maximum-effort code review of `plugins/export_graphics` against
`4a25f45`, run with four independent finder angles plus verification. Every
finding below was confirmed by execution or by a quoted rule, not accepted on
an agent's word. This file is the plan of record.

Purpose: repair two regressions this branch shipped, and settle the structural
shortcuts it took. Most of these are self-inflicted: the branch added a request
owner and a clipboard feature, then updated only the paths its own tests
exercised.

## Progress Checklist

- [x] Slice 1: Stop A Figure Macro Re-Run From Raising
- [x] Slice 2: Stop A Macro From Adopting And Overwriting Another Figure
- [x] Slice 3: Trivial Fixes, Bundled
- [x] Slice 4: Survive A Raising Request Consumer
- [x] Slice 5: Report Only What Reached The Clipboard
- [x] Slice 6: Move Clipboard Policy Into The Figure Export Plugin
- [x] Slice 7: One Owner For The Request-Then-Await-Payload Lifecycle
- [x] Slice 8: One Format Field On FigureIR
- [ ] Slice 9: Declare The zprocess Requirement, And Delete The Runtime Probe
      — probe deleted; the version floor still waits on the upstream `v2.28.0` tag
- [x] Slice 10: Retire `current_ir` And Its Second Source Of Truth
- [x] Slice 11: Guard The Start-Up Pyplot Rule By Observation
- [ ] Slice 12: Put The Callable `enabled` Contract Where The Key Is Documented
- [ ] Slice 13: Figure Backend Leftovers
- [ ] Slice 14: Trivia, Second Bundle
- [ ] Slice 15: Let The Feature-Module Guard See Re-Exports
- [ ] Slice 16: Stop The Variables Tool Stalling On A Lost Callback
- [ ] Slice 17: Settle The Orphaned `tracked_names` Payload Field

## How to work these

Each slice is independently grabbable. Run the whole suite in one process
before and after — `test_project_save_load` fails spuriously if a Hyde instance
is already running, so close the app first:

```bash
QT_QPA_PLATFORM=offscreen /Users/ispielma/miniforge3/envs/labscript/bin/python - <<'PY'
import os, unittest
mods = sorted('tests.'+f[:-3] for f in os.listdir('tests')
              if f.startswith('test_') and f.endswith('.py'))
suite = unittest.TestSuite()
for m in mods:
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(m))
unittest.TextTestRunner(verbosity=1).run(suite)
PY
```

There is no pytest and `conda` does not work here. Tests assert what the code
does, not how it is; a guard must be verified by breaking what it guards.

## Slice 1: Stop A Figure Macro Re-Run From Raising

### Type

`AFK`

### What to build

Re-running a `@hyde.figure` macro raises. `hyde/features/matplotlib_figure_state.py:663`
emits `fig.clear()` into generated recreation source. That deletes the axes
carrying `_hyde_subplot_id`, and `FigureHyde.add_subplot`
(`hyde/matplotlib_backend.py:1763`) only stamps that id while
`_hyde_ir["layout"]["subplots"]` is still empty — which it is not on a re-run.
The trailing `fig.show()` then reaches `_resolve_live_axis` through
`figure_snapshot_payload` and raises, and `_push_draw`'s `try` wraps only
`self._comm.send`, so it escapes.

Reproduce:

```python
# after execute_procedures_bootstrap on a template project
@hyde.figure(register=False)
def _hyde_figure(f):
    fig = plt.figure('Graph0', figsize=(4.0, 3.0))
    fig.clear()
    ax = fig.add_subplot(111)
    ax.plot(f, label='f')
    fig.show()
_hyde_figure(f)   # OK
_hyde_figure(f)   # ValueError: Unknown live subplot id: 'subplot0'
```

**Start by reverting the emitted `fig.clear()`.** That restores the older
behaviour, where a re-run silently stacked another axes — which is worse than
correct but strictly better than raising, and it is one line. Land that first
and separately, so the repair is not blocked on the redesign.

Then fix the real problem, which is that a recreation macro has no way to
replace a figure's contents. The emitted `fig.clear()` was reaching for
something the backend does not support: clearing a Hyde figure has to reset the
IR's subplot bookkeeping too, or `add_subplot` has to re-stamp ids when the
live axes no longer match the IR. Decide which, in the backend rather than in
emitted source.

### Acceptance criteria

- [ ] Re-running a generated figure macro succeeds, twice or more.
- [ ] Re-running does not stack axes: after two runs the figure has one axes and
      the data from the second run.
- [ ] `figure_snapshot_payload` succeeds after a re-run, with a comm open and
      without one.
- [ ] A saved figure macro still rebuilds its figure after a project reload.
- [ ] A test fails if the emitted source regains an unconditional `fig.clear()`
      without backend support for it.

### Blocked by

None - can start immediately.

## Slice 2: Stop A Macro From Adopting And Overwriting Another Figure

### Type

`AFK`

### What to build

`finalize_figure_build_session` (`hyde/matplotlib_backend.py:345`) falls back to
`_active_hyde_figure()` when a macro registered nothing, then unconditionally
assigns `_hyde_source_artifact`, `_hyde_ast_artifact`, `_hyde_bound_values`,
`_hyde_metadata` and recomputes `_hyde_defaults` from the calling function. So a
macro that creates nothing adopts whatever figure is current and destroys that
figure's ability to rebuild itself.

Reproduced: with `Alpha` current and holding
`_hyde_bound_values == {'f': array([1., 2., 3.])}`, calling

```python
@hyde.figure(register=False)
def unrelated_macro():
    return None
```

returns `Alpha` and leaves `Alpha._hyde_bound_values == {}`. `resolved is None`
on this path, so the "must resolve to the one created figure" guard never fires.
A macro that only plots onto the current figure triggers it too.

The fallback exists because a macro re-run against an existing figure registers
nothing — the same root cause as Slice 1. Decide whether the fallback should
exist at all once a re-run can register its figure properly, and if it stays,
it must not adopt a figure the macro did not build.

**A second defect in the same area, found while landing Slice 1 and reproduced
independently.** A re-run silently un-parameterises the figure's saved macro.
`FigureHyde.__init__` sets `_hyde_build_session` once
(`hyde/matplotlib_backend.py:1732`) and never updates it, and
`AxesHyde.plot` resolves operand names against that stored session's
`named_values` (`:1659`), which is keyed by `id(value)`. On a re-run with fresh
arrays no id matches, so a trace's `y_source` degrades from
`{'kind': 'name', 'value': 'y'}` to `{'kind': 'array_literal', ...}` and the
figure stops being namespace-tracked.

Observed across three runs of one macro: `y_source` is `name` on the first run
and `array_literal` on every run after. The figure still draws correctly; what
is lost is its ability to be saved as a macro that takes its data as a
parameter. This was unreachable before Slice 1 — a re-run either raised or
stacked axes — so it is newly exposed rather than newly broken.

The candidate fix is for `AxesHyde.plot` to prefer `_current_build_session()`
over the figure's stored session, but that is the same ownership question as the
adoption fallback: which session is authoritative while a macro runs. Decide
both together.

### Acceptance criteria

- [ ] A macro that creates nothing and returns nothing does not adopt a live
      figure; it reports that it built no figure.
- [ ] A macro that plots onto an existing figure without creating one does not
      silently become that figure's recreation macro.
- [ ] An adopted figure's `_hyde_bound_values`, `_hyde_source_artifact` and
      `_hyde_defaults` are never replaced by a macro that did not build it.
- [ ] A legitimate re-run still updates the figure it rebuilds.
- [ ] A re-run keeps a trace's `y_source` as a namespace name, so the figure's
      saved macro still takes its data as a parameter.

### Blocked by

- Slice 1 (same root cause; do not fix the fallback before the re-run works)

## Slice 3: Trivial Fixes, Bundled

### Type

`AFK`

### What to build

Ten mechanical fixes with no design decision between them. Land as one change.

1. **`project_management/specs/save_graphics_dialog/SPEC.md:258`** documents
   `hyde.copy_figure(fig, format='pdf', dpi='figure')`. The keyword is `formats`
   and is keyword-only, so the documented call raises `TypeError`. It is the only
   stale `copy_figure` caller left anywhere.
2. **`.agents/skills/hyde-dialog-widget/assets/template_plugin/tests/test_example_dialog.py:8`** —
   the template's `FakeExecutionService` implements only `execute_hidden`, but
   `HydeDialogWidget.execute_ok_payload` now dispatches through
   `request_command`. Every plugin scaffolded from this template raises
   `AttributeError` on OK. Mirror `tests/kernel_fakes.KernelRequestRecorder`.
3. **`hyde/features/matplotlib_ir.py:1144`**, `FigureIRDiff.from_irs` omits
   `clipboard_formats` from the field enumeration, so a copy IR through the diff
   path loses its formats and then fails its own validation with
   `ValueError: Figure copy_graphics requires clipboard_formats`.
4. **`hyde/features/matplotlib_ir.py:206`**, `__post_init__` normalizes every
   field except `clipboard_formats`, so `['PDF','png']` survives verbatim and
   compares unequal to the tuple-valued equivalent.
5. **`hyde/features/matplotlib_ir.py:249`**, `debug_state` omits
   `clipboard_formats` — the one field that distinguishes one copy from another.
6. **Seven inert sentinels** assert a pre-refactor name is absent from an
   instance dict: `tests/test_figure_window_session_save.py:88-89`,
   `test_matplotlib_features.py:583`, `test_trace_edit_dialog.py:306`,
   `test_remove_from_graph_dialog.py:438`, `test_axis_edit_dialog.py:445`,
   `test_hyde_tool_widget.py:828`, `test_file_dialog_plugin.py:209`. One is
   provably inert: `FigureWindow.current_ir` exists as a class-level property, so
   it is never in `__dict__` and the guard passes while the forbidden name is
   present. Delete them; they cannot catch a defect in the running app.
7. **`tests/test_save_graphics_dialog.py:1085`**,
   `test_copy_offers_only_formats_the_table_can_export` draws both sides from the
   same hand-written module it guards. Compare against
   `runtime_graphics_export_filetypes()`, as the sibling test at line 1072 does.
8. **`hyde/user_interface/plugins/save_graphics_dialog/__init__.py:110`** —
   `copy_active_figure` returns `False` with no message when `_clipboard_formats`
   is empty. Every other failure path reports.
9. **`FigureCopyRequest.label`** (`copy_request.py:45`) is assigned and never
   read, and `_copy_label` exists only to feed it. Remove both, or read the label.
10. **Dead imports**: `QtCore` in `save_graphics_dialog/__init__.py`, `textwrap`
    in `hyde/features/hyde_features.py`, `ordered_unique` in
    `matplotlib_figure_schema.py`, `apply_figure_state` in `matplotlib_backend.py`,
    and the unused names imported into `matplotlib_features.py`. Confirm each is
    genuinely unreferenced before removing it.

### Acceptance criteria

- [ ] The spec's documented `copy_figure` call runs without `TypeError`.
- [ ] The plugin template's own test passes against the current dialog base.
- [ ] A copy IR survives `current_diff()` with its formats and validates.
- [ ] Two `FigureIR` copy objects built by different routes with the same intent
      compare equal.
- [ ] `debug_state()` shows a copy's formats.
- [ ] No test asserts a name's absence from an instance dict.
- [ ] The format guard fails when the generated table drifts from matplotlib.
- [ ] Removing any dead import leaves the suite green.

### Blocked by

None - can start immediately.

## Slice 4: Survive A Raising Request Consumer

### Type

`AFK`

### What to build

`_settle_request` and `_abandon_pending_requests`
(`hyde/user_interface/plugins/kernel_runtime/__init__.py:174` and `:183`) call
`on_finished(request)` with no `try/except`. `_settle_request` runs inside
`_on_shell_message`, a Qt slot invoked from C++, where an unhandled Python
exception calls `qFatal()` — the process aborts with SIGABRT rather than
raising. `HydeApp.emit_plugin_event` wraps every handler in `try/except`; this
path does not.

Candidate raisers are real: `_on_session_restore_command_finished` reaching
`finalize_subwindow_state` on a subwindow torn down while `session.py` ran, or
`_fail_copy` touching `self.ui.statusbar` during teardown.

The second variant is worse than a crash: `_abandon_pending_requests` raising
inside `stop()` inside `_handle_kernel_crash` means the `start_runtime()` on the
next line never runs, leaving Hyde with no kernel *and* no kernel watcher,
permanently and silently.

### Acceptance criteria

- [x] A consumer that raises in `on_finished` does not abort the process.
- [x] The failure is logged with the consumer identified.
- [x] One raising consumer does not prevent other pending requests from
      settling.
- [x] A raising consumer during `_handle_kernel_crash` still leaves the runtime
      restarted.
- [x] A test drives a raising consumer through the real settle path.

### Blocked by

None - can start immediately.

## Slice 5: Report Only What Reached The Clipboard

### Type

`AFK`

### What to build

Two ways a copy claims success it did not achieve.

`save_graphics_dialog/__init__.py:281` builds the success message from every
decoded representation rather than from what `clipboard_mime_data` attached.
Verified: a `pdf`+`png`+`pgf` payload reports "Copied figure to the clipboard as
PDF, PNG, PGF" while the exclusive-text branch placed only `text/plain`.

`clipboard.py:63` skips `setImageData` when `QImage.fromData` returns null but
still returns a non-`None` `QMimeData`, so the copy reports success having
placed only a raw `image/png` entry — which the module's own comment describes
as putting nothing usable on the clipboard.

Both are latent today and both are wrong the moment a representation is added.
The fix is for the builder to report what it placed, and for the caller to
describe that rather than what it asked for.

### Acceptance criteria

- [x] The status message names only representations actually on the clipboard.
- [x] A rendering that cannot be turned into a usable clipboard entry is
      reported as a failure, not a success.
- [x] An undecodable raster does not produce a success message.
- [x] Tests assert the message against what the payload placed, not against the
      formats requested.

### Blocked by

None - can start immediately.

## Slice 6: Move Clipboard Policy Into The Figure Export Plugin

### Type

`AFK`

### What to build

Two placement violations with one destination.

`hyde/features/matplotlib_features.py:159` holds `GRAPHICS_CLIPBOARD_MIME_TYPES`
and `GRAPHICS_CLIPBOARD_REPRESENTATIONS`, so a package-pure matplotlib lowerer
owns clipboard MIME types (`application/pdf`, `image/png`, `text/plain`) and
user-facing menu labels (`Vector`, `Image`, `LaTeX`). IR-CONTROL: "The boundary
is package-pure: `hyde_features.py` emits only Hyde strings,
`matplotlib_features.py` emits only matplotlib strings." Neither a MIME type nor
a menu label is a matplotlib string.

`hyde/user_interface/shared/clipboard_platform.py` decides which format a vector
copy renders and registers the platform's mime converters. IR-CONTROL Placement
Rules: "Supporting material that carries runtime authority for one IR family
belongs in that plugin directory, not in `hyde/user_interface/shared/`", and "Do
not hide feature authority in `shared/` modules. This file-shape rule is
first-class."

**The destination is settled and is not part of this slice's work.** The figure
clipboard is part of the figure export feature — `SPEC.md` states that `Copy`
and `Copy As` are "the clipboard half of the same feature" as
`Save Graphics...` — so all of it belongs in
`hyde/user_interface/plugins/save_graphics_dialog/`, beside the `clipboard.py`
and `copy_request.py` that are already there.

Both files were misplaced by reasoning about a table and terminal copy that do
not exist. When they arrive they will make their own decision; the rule is to
place authority where it is used now.

### Acceptance criteria

- [x] `matplotlib_features.py` contains no MIME types and no user-facing labels.
- [x] No module under `hyde/user_interface/shared/` owns clipboard policy.
- [x] The moved code lives under `save_graphics_dialog/`.
- [x] `hyde/features/` no longer needs importing for anything clipboard-shaped.
- [x] Copy behaviour is unchanged: all three representations still paste, and a
      vector still publishes natively on macOS. Verify the last one against the
      system clipboard, not through Qt's own reading of it.

### Blocked by

None - can start immediately.

## Slice 7: One Owner For The Request-Then-Await-Payload Lifecycle

### Type

`AFK`

### What to build

The lifecycle is written four times: figure refresh
(`figure_interactive/window.py:503`), table refresh
(`table_interactive/window.py:355`), figure close
(`figure_interactive/window.py:632`), and `FigureCopyRequest` as a class. Each
repeats a single-shot payload timer, a `_clear_*_in_flight`, an `_on_*_finished`
that arms the timer only when the reply says the command ran, and an
`_on_*_payload_timeout`.

They have already drifted: only `FigureCopyRequest` restores the override
cursor, only the table path reports failure to the user, only the close path
logs. The invariant that a pending request is *waiting* rather than *late* now
has to hold in four places, and the next kernel-facing surface will write a
fifth.

`KernelCommands` (`base_hyde_widgets.py`) was introduced on this branch as the
owner for exactly this. `FigureCopyRequest` generalizes with one change — its
retry hook becomes a callable.

### Acceptance criteria

- [x] One object owns the payload timer, the in-flight flag, and the settle path.
- [x] The two windows keep only their own `refresh_data` / `refresh_figure` and
      lose the duplicated lifecycle methods.
- [x] Cursor restoration, user-facing failure reporting, and logging behave the
      same for every consumer, rather than differing per copy.
- [x] A refresh or close still waits indefinitely for a busy kernel, and still
      bounds only the gap after the reply says the command ran.

### Landed

`KernelPayloadRequest` (`base_hyde_widgets.py`), reached through
`KernelCommands.begin_payload_request(lane, code, ...)`. `lane` names the one
outstanding request of its kind, so a figure window keeps a refresh and a close
apart while still refusing a second of either. `FigureCopyRequest` is gone.
Four payload-timeout constants became one `PAYLOAD_TIMEOUT_MS`.

Two deliberate differences remain, both with two callers on each side rather
than one:

- **Whether progress is announced.** The owner always restores the cursor and
  always reports and logs a failure. Whether it *raises* a wait cursor and holds
  a status message is declared per request: yes for copy and close, which are
  gestures the user is waiting on; no for the two refreshes, which are reactive
  syncs. A figure refresh runs on every namespace update, so announcing it would
  flicker a wait cursor through ordinary typing.
- **A command the kernel never took.** `begin_payload_request` returns None
  without reporting: the lifecycle never started, and reporting it would put
  start-up refreshes in the status bar. Each consumer keeps the "no kernel"
  message it already had.

Each window also keeps a three-line `_retry_pending_refresh`: coalescing a
refresh asked for while one was in flight is the refresh surfaces' own policy
(copy refuses a second request, and a close cannot recur), not part of the
lifecycle.

### Blocked by

None - can start immediately.

## Slice 8: One Format Field On FigureIR

### Type

`AFK`

### What to build

`FigureIR` carries two parallel format concepts. `with_copy_graphics`
(`matplotlib_ir.py:419`) sets `output_format=None` to mean not-applicable, and
`__post_init__` immediately coerces it back to `'pdf'`, so every copy IR carries
a format field nothing reads and validation never checks. Verified: a copy IR
reports `output_format == 'pdf'` alongside `clipboard_formats == ('pdf','png')`,
and `validate()` accepts it. `FigureIRDiff` then propagates the dead field while
dropping the live one.

Separately `dpi: int = 300` legally holds the string `'figure'`, which forces
three dpi branches in `validate()`.

One `output_formats: tuple[str, ...]` — length 1 for save, several for copy —
removes a field, a lying type annotation, and the ambiguity about which field a
copy honours. `dpi: int | None = None` with `None` meaning "defer to the live
figure" removes two validate branches.

This supersedes items 3, 4 and 5 of Slice 3; if Slice 3 has landed, the
mechanical fixes simply disappear with the field.

### Acceptance criteria

- [x] `FigureIR` has one format field, normalized in `__post_init__` and carried
      by `FigureIRDiff` and `debug_state`.
- [x] Save validates exactly one format; copy validates at least one.
- [x] The `'figure'` dpi sentinel no longer requires a string in an `int` field.
- [x] Emitted Python is unchanged for both save and copy.

### Blocked by

- Slice 3 (avoid conflicting edits to the same lines)

## Slice 9: Declare The zprocess Requirement, And Delete The Runtime Probe

### Type

`AFK`

### What to build

Delete `_require_permissive_heartbeats` (`kernel_runtime/__init__.py:322`) and
let the call fail. Then declare the requirement where requirements are declared.

This was a versioning problem being solved at the wrong layer. Hyde passes
`heartbeat_interval` and `allowed_missed_heartbeats` to
`ProcessTree.subprocess()`, which exist only on zprocess's unmerged
`PermissiveHeartBeat` branch — `git log -S heartbeat_interval` over
`zprocess/process_tree.py` finds them on that branch and nowhere else. So **no
released zprocess satisfies what Hyde actually needs**, while `pyproject.toml`
declares `zprocess>=2.18.0`, which happily accepts the `2.27.1` on `master`
that does not work. That mis-declaration is the defect. A probe that inspects a
function signature at launch is Hyde guessing at a dependency's version at
runtime, and it guesses wrong: verified by execution, any `ProcessTree` whose
`subprocess` forwards `**kwargs` is refused, so Hyde declines to start and tells
the user to check out a branch they may already be on.

Express the truth in the metadata instead. **The branch has since been merged
into zprocess's `Production` and pushed**, so a version floor can be honest now.
Two measurements decide which floor, and both rule out the obvious candidates.

First, what the versions actually are. The heartbeat commit sits two commits past
the `v2.27.1` tag with no release tag containing it (`git describe` →
`v2.27.1-2-g5da28e4`). zprocess has no version literal anywhere in the tree; it
derives one from git via setuptools-scm with `version_scheme =
"release-branch-semver"` and `local_scheme = "no-local-version"`, so an
untagged commit past a tag reports the *guessed next release* as a pre-release:
`2.28.0.dev2`. Under PEP 440 that sorts *below* `2.28.0`.

Second, and decisive: for an editable install the metadata a resolver reads and
the version the code reports **disagree**. Measured in the working environment:

| source | reports |
| --- | --- |
| `importlib.metadata.version("zprocess")` — what pip and any check read | `2.27.0.dev19` |
| `import zprocess; zprocess.__version__` — recomputed from git per import | `2.28.0.dev2` |

The `.dist-info` was frozen when the package was installed; `__version__.py`
re-derives from git on every import. So a floor tuned to the pre-release the
*code* reports would be tested against the stale number in the *metadata* and
fail on a machine that works. Chasing `.dev` versions is a trap, not a fix, and
`>=2.28.0.dev0` must not be what Hyde declares.

The floor Hyde should declare is the plain `zprocess>=2.28.0`, which requires
one action upstream first: **tag `v2.28.0` on zprocess's `Production` and push
the tag**. Verified in a throwaway clone — tagging that commit makes
setuptools-scm report exactly `2.28.0`, with no pre-release suffix, and commits
after the tag report a higher version, so the floor keeps holding as `Production`
moves. The editable install then needs reinstalling once so its `.dist-info`
catches up; until it does, no floor above `2.27.0.dev19` can be satisfied on
that machine regardless of what the code contains.

Renaming the version to carry a marker — `2.28.0.spielman`, `2.28.0.production`
— is not available: both are invalid PEP 440 and `packaging` rejects them, so no
resolver could compare against them. Only a `+local` suffix admits arbitrary
text, and local versions are prohibited on PyPI and order confusingly in
specifiers.

Do not pin a git ref: the code is on a pushed branch of the upstream project,
and a floor expresses the requirement without freezing Hyde to one commit.

Note also what the floor does and does not buy. Nothing in `hyde/` calls
`check_version` or any runtime version gate, so the declaration is install-time
documentation rather than a live guard. That is the correct place for it — a
dependency's version is a packaging fact — but it means deleting the probe
removes the only thing that was failing loudly, and an incompatible zprocess
will surface as a `TypeError` from zprocess itself. That is the intended
outcome: the error names the real problem instead of Hyde guessing at it.

Deleting the probe also removes `_PERMISSIVE_HEARTBEAT_BRANCH`, a dependency's
branch name embedded in production code.

Note what is *not* being fixed here, deliberately: a failed `start_runtime`
activity is caught by labscript-utils' plugin host and only logged, which is why
a broken kernel launch let Hyde come up looking normal with no kernel. That
swallowing is the host's design — one bad plugin must not stop the app — and
making Hyde's own setup failures visible is a separate question about that seam,
not part of a versioning fix.

### Acceptance criteria

- [x] `_require_permissive_heartbeats` and `_PERMISSIVE_HEARTBEAT_BRANCH` are
      gone, along with the test that pins the probe.
- [x] An incompatible zprocess produces its own `TypeError`, not a Hyde refusal.
      Measured against a checkout of the `v2.27.1` tag, the last release before
      the heartbeat options existed: `TypeError: ProcessTree.subprocess() got an
      unexpected keyword argument 'heartbeat_interval'`.
- [ ] `pyproject.toml` declares `zprocess>=2.28.0` in place of `>=2.18.0`.
- [x] A `ProcessTree` whose `subprocess` forwards `**kwargs` does not prevent
      startup.

### Blocked by

**One upstream action, which only the maintainer can take:** tag `v2.28.0` on
zprocess's `Production` and push the tag, then reinstall the editable zprocess
so its `.dist-info` reports `2.28.0` rather than the frozen `2.27.0.dev19`.

Deleting the probe is not blocked by that and can land first — the probe is
currently refusing to start a working kernel, so removing it is the urgent
half. The floor is only honest once the tag exists, so if the tag has not
happened yet, land the deletion and leave `pyproject.toml` for a follow-up
rather than declaring a floor nothing satisfies.

**Status: the deletion has landed; the floor has not.** As of 2026-09-02 the
zprocess tags stop at `v2.27.1` (`git describe` → `v2.27.1-2-g5da28e4`), so
`pyproject.toml` still declares `zprocess>=2.18.0` — a floor that is knowingly
false, since no released zprocess carries the heartbeat options. It stays that
way until the tag exists; the remaining work is that one line.

## Slice 10: Retire `current_ir` And Its Second Source Of Truth

### Type

`AFK`

### What to build

`FigureWindow.current_ir` (`figure_interactive/window.py:240`) is a property that
returns `self.widget_ir` and nothing else. AGENTS.md: "Do not add trivial
pass-through helpers or wrapper methods that only rename or forward to a shared
helper without adding real local policy. Prefer making the shared helper the
actual interface." The sibling `table_interactive/window.py` uses `widget_ir`
directly, so the two windows name the same base-class attribute differently.

The alias also hides that the window answers one question from two sources:
`tracked_namespace_names()` answers from `current_ir.tracked_names()` while
`refresh_figure()` gates on `snapshot_state.tracked_names()`. If the two
disagree, a figure can be namespace-tracked yet never refreshed. Eight methods
branch `if self.current_ir is not None: ... else: self.snapshot_state...`.

`FigureIR.from_snapshot` already carries most of what `FigureSnapshotState`
holds; the remainder is the warning text and the figure size.

**Verified before the fix: the defect is real in the code and unreachable from
the kernel.** Driving `FigureWindow` over all eighteen `(figure_ir,
tracked_names)` payload shapes, four of them produced a window that reported a
name from `tracked_namespace_names()` which no namespace change could ever
refresh — the failure named above, demonstrated by execution. All four need a
payload carrying `tracked_names` without a `figure_ir`, and
`figure_snapshot_payload` never emits one: its first-class branch always ships
`figure_ir`, its other branch ships `tracked_names: []` and the workspace
discards it before a window sees it. Over real payloads from real figures the
two sources agreed every time, because the kernel computes `tracked_names` from
the very `figure_ir` it ships, and `FigureSnapshotState` re-derives from that
`figure_ir` whenever the shipped list is empty. Neither half of that invariant
was stated anywhere, and it spanned the kernel/GUI boundary. After the fix the
same eighteen shapes all agree, and by construction rather than by coincidence.

### Acceptance criteria

- [x] `current_ir` is gone and call sites use `widget_ir`.
- [x] One source answers "which namespace names does this figure track", used by
      both tracking and refresh.
- [x] The dual-source branches are gone or reduced to a stated minimum.
      `FigureSnapshotState` no longer holds the IR, the figure defaults, the
      resolved axis limits, the trace styles or the tracked names, so no
      question has two holders. Four `widget_ir is None` checks remain, all
      answering the one question the IR cannot answer — whether Hyde could
      describe this figure at all: `figure_ir()` (the editability gate),
      `tracked_namespace_names()` (the single source itself),
      `saveable_default_macro_name()` (IR title, else the name the kernel
      reported) and `macro_definition_source()` (an IR recreation, else the
      call the kernel recorded).
- [x] Session save and restore of a figure window still round-trip.
      `test_a_saved_figure_session_restores_the_same_figure` writes a real
      figure's `session.toml` and `session.py` through `write_session`, closes
      everything, executes the written `session.py` in the Hyde backend, and
      compares the restored window's tracked names, handle, figure IR and drawn
      appearance against the saved one's.

### Blocked by

- Slice 3 (removes the inert sentinel that names `current_ir`)

## Slice 11: Guard The Start-Up Pyplot Rule By Observation

### Type

`AFK`

### What to build

`tests/test_save_graphics_dialog.py:1098`,
`test_building_the_copy_menu_never_imports_pyplot`, reads one module's text and
asserts the substring `runtime_graphics_export` is absent. A reintroduced
`import matplotlib.pyplot`, or a call routed through any other module, passes.

Meanwhile the live trap is invisible to it:
`graphics_export_suffixes_for_format(format_key, filetypes=None)`
(`matplotlib_features.py:89`) defaults to `runtime_graphics_export_filetypes()`,
whose own docstring says nothing on a GUI or start-up path may call it because it
resolves an interactive backend. The only in-repo caller passes `filetypes`
explicitly, so the landmine is armed for the next caller.

The behavioural guard is three lines: snapshot `sys.modules`, build the menu,
assert `matplotlib.pyplot` did not appear. Then decide whether that default
argument should exist at all.

Done as a subprocess instead, because a snapshot taken in this process observes
nothing: `tests/test_curve_fit.py` imports pyplot at module scope, so in a
one-process suite run it is in `sys.modules` before the first test starts.
Measured, not assumed. `test_the_gui_start_up_never_imports_pyplot` runs a clean
interpreter that imports the GUI application, discovers and instantiates every
plugin, runs `HydeApp.setup_plugins` up to the menu render, and then imports
every remaining `hyde.user_interface` module -- reporting per stage whether
pyplot arrived, so a failure names the step that reached it. The kernel launch
that follows the render is out of scope on purpose: that is a different process,
and `spyder_kernels` has pyplot imported there before Hyde runs.

`filetypes` is now a required argument.

### Acceptance criteria

- [x] The guard fails if any start-up path imports `matplotlib.pyplot`, however
      it is reached.
- [x] Verified by deliberately adding such an import and watching it fail.
      Four locations: a module-level import in the menu-building plugin; a
      call-time import routed through `matplotlib_features` while the menu is
      built; a module-level import in a lazily-loaded GUI module the start-up
      path never touches; and the landmine itself, re-armed and stepped on.
- [x] A caller cannot reach `runtime_graphics_export_filetypes()` by omitting an
      argument.

### Blocked by

None - can start immediately.

## Slice 12: Put The Callable `enabled` Contract Where The Key Is Documented

### Type

`HITL`

### What to build

This branch widened the menu-contribution `enabled` key to accept a callable, so
six plugins now pass `self.has_active_editable_figure`. Hyde resolves it in
`resolve_menu_enabled` (`shared/plugin.py:470`), but the framework base class
Hyde subclasses does `action.setEnabled(enabled)` on the raw value
(`labscript-utils/labscript_utils/plugins.py:1053`) and documents `enabled` as a
plain action property (line 353).

A bound method is truthy, so any Hyde contribution rendered through the base path
becomes permanently enabled — including copy actions that must be disabled
without an active figure, whose shortcuts would then fire on nothing.
`HydeMenuContext.render` fully overrides `render` today, so this is latent.

Needs a decision, and it is cross-repo: extend the framework's contract and its
documentation, or keep the extension in Hyde and make the base path unreachable
by construction rather than by coincidence.

### Acceptance criteria

- [ ] A callable `enabled` cannot silently render as permanently enabled.
- [ ] The contract is documented where the key is documented.
- [ ] If the framework changes, the labscript-utils change is a separate,
      reviewable commit in that repository.

### Blocked by

None - needs a decision, not other slices.

## Slice 13: Figure Backend Leftovers

### Type

`AFK`

### What to build

Four things Slice 2 surfaced in the figure backend and deliberately left alone.

1. **`_hyde_building` never turns off.** `finalize_figure_build_session` does not
   reset it, so a macro-built figure carries it for life. The name reads as
   "currently building"; the value means "Hyde-tracked". It is what makes a
   prompt-level `ax.plot(z)` append a trace to a first-class figure's IR, and
   Slice 2 made `_is_windowed_figure` depend on it — so it is now load-bearing
   under a misleading name. Rename it to what it means, or split the two ideas.
2. **`_hyde_source_artifact` and `_hyde_ast_artifact` have no readers.** Written
   at `hyde/matplotlib_backend.py:403-404`; nothing in the product reads either,
   only `tests/test_window_macros.py:232-233` asserts they are non-`None`. A
   parsed AST is retained per figure for the life of the process with no
   consumer. Establish whether anything is meant to read them; if not, remove
   them and the test that pins them.
3. **A macro that raises leaves its appended trace behind.** A macro that draws
   onto another figure and then fails in `finalize` leaves that trace in the
   other figure's IR. Pre-existing, and drawing onto a neighbour is intended
   (`test_a_macro_may_draw_on_another_figure_while_building_its_own`), but a
   half-applied side effect from a failed macro is still a defect.
4. **`hyde/matplotlib_backend.py:374`** — `figure = created_figure if resolved
   is None else resolved` is dead branching, because the guard three lines above
   already proves `resolved is created_figure` whenever it is not `None`.

### Acceptance criteria

- [ ] No attribute's name contradicts what it holds.
- [ ] No per-figure state is retained for the process lifetime with no reader.
- [ ] A macro that fails does not leave a partial trace in another figure's IR,
      or the reason it must is written down.
- [ ] No dead branch survives in `finalize_figure_build_session`.

### Blocked by

- Slice 2

## Behaviour change accepted in Slice 2

Accepted by the maintainer. Recorded because it changes what existing user code
does.

A hand-written `@hyde.figure` macro that rebuilds a figure **without clearing
it** now raises on the second run, with a message naming the missing
`fig.clear()`. Before, it returned a figure carrying two live axes against a
one-subplot IR — which could not be saved as a macro
(`save_error: 'unsupported live figure features were omitted during Hyde
import'`). So nothing that worked stopped working; an incorrect result became an
actionable error.

Verified: run 1 succeeds, run 2 raises. `fig.clf()`, `plt.clf()` and
`plt.figure(name, clear=True)` all route through `FigureHyde.clear()` and
register correctly, so only the no-clear form is affected.
`specs/new_graph_dialog/SPEC.md:123` already specifies rejection when a macro
creates no figure, so this moves the implementation toward the spec.

## Environment notes

- **The suite can hang for ~15 minutes with no zlog server running.** The kernel
  launcher's `ensure_connected_to_zlog` starts a daemon, whose cold start can
  run past its 15-second ping while matplotlib builds its font cache;
  labscript-utils' excepthook then opens a **Tk** dialog that blocks forever.
  `QT_QPA_PLATFORM=offscreen` does not affect Tk, so nothing suppresses it.
  Starting a zlog daemon first — `python -m zprocess.zlog`, the same one the
  product starts for itself — avoids it.

## Findings deliberately not filed

- **A stale payload with an empty `request_msg_id`** can satisfy a later copy
  (`save_graphics_dialog/__init__.py:297`). Triggered only when
  `_executing_request_id()` returns `""`, which needs a degraded or foreign
  kernel; a healthy Hyde kernel always names the request. Recorded in
  `issues/KERNEL_REQUEST_OWNER.md` as the known stray-payload gap.
- **`session_source_has_statements` catches only `SyntaxError`**, so a
  `session.py` with a UTF-8 BOM is classed as having statements and fails in the
  kernel with `invalid non-printable character U+FEFF`. That is the intended
  "the kernel's error is more use than silence" behaviour; noted so the next
  reader does not mistake it for an encoding bug.
- **`scripts/hooks/pre-commit` uses bare `python`**, which resolves to the base
  environment rather than the `labscript` env Hyde runs in. Both carry matplotlib
  3.11.1 today, so the generated-table check is correct by coincidence. Worth an
  absolute interpreter path, but it is a one-line hook change with no user-facing
  behaviour.

## What the review cleared

Worth recording, because these were the branch's riskiest areas and they held up
under direct probing:

- **The two-transport copy race.** All four orderings of reply and payload, plus
  kernel-abandonment, end with the copy settled, the override-cursor stack back
  to zero, and exactly one outcome message. Real timers were driven, including
  `busy_cursor_hold_ms = 0` and a copy settling before the busy timer fires.
- **`_pending_requests`.** No leak reachable, including across `stop()`/`start()`.
  It ignores replies it never issued, replies with no `parent_header`, and
  non-`execute_reply` messages for its own id; it settles exactly once on a
  duplicate reply.
- **The `QUtiMimeConverter` subclass.** Declines every MIME type it does not
  claim, round-trips PDF bytes both directions, and returns `[]` rather than
  crashing on non-buffer data.
- **`hyde.task_complete` removal and the `shared/figure.py` deletion.** Both
  fully migrated: no stale caller anywhere, including saved projects on this
  machine, and all 26 symbols from the deleted module accounted for.

## Slice 14: Trivia, Second Bundle

### Type

`AFK`

### What to build

Findings the Slice 3 and Slice 4 agents surfaced while working, each verified
but outside the slice that found it. Independent of each other; land them
together.

1. **A duplicate definition that silently shadows its twin.**
   `tests/test_kernel_runtime.py` defines `FakeShellChannel` and
   `FinishedCollector` twice, at lines 50-63 and 65-77. Verified identical by
   diff, so the second pair wins and an edit to the first has no effect. Delete
   the first pair. This is the trap that matters most in this bundle: it makes a
   future test change appear to do nothing.

2. **`apply_figure_state` has no callers.** Defined at
   `hyde/features/matplotlib_features.py:635`. Removing the dead import in
   `hyde/matplotlib_backend.py` during Slice 3 took its last reference anywhere,
   tests included. Confirm zero callers, then delete it.

3. **A guard that names the wrong subject**, the same defect Slice 3 item 7
   fixed one instance of. `tests/test_save_graphics_dialog.py:409`,
   `test_each_representation_renders_through_a_format_matplotlib_exports`,
   claims "matplotlib exports" while `exportable` comes from
   `graphics_export_formats()` — the checked-in table, not the installed
   matplotlib. Source it from `runtime_graphics_export_filetypes()` as item 7
   did, or rename it to say it checks the table.

4. **A doubled import.** `tests/test_save_graphics_dialog.py` imports
   `graphics_export_formats` in two separate `matplotlib_features` import
   blocks, around lines 21-23 and 30-34.

5. **More structural sentinels**, the same shape Slice 3 item 6 removed seven
   of. These assert the absence or presence of a name rather than a behaviour,
   which the project's test rule excludes: `tests/test_table_features.py`
   lines 517-518, 646-647 (`initial_ir`/`current_ir`), 220-221 (`shell_ui`,
   `lower_text_edit`) and 481 (`dialog.ui.buttonBox`);
   `tests/test_matplotlib_features.py:573` (`buttonBox`);
   `tests/test_hyde_tool_widget.py:328` (`shell_ui`). Establish each one is
   inert the way item 6 did — does the name resolve in the object's MRO, and can
   anything write it — and delete what is vacuous. Keep any that turns out to
   assert a real contract, and say which and why.

6. **Unused imports** beyond Slice 3 item 10's five:
   `CALCULATED_X_NAME` and `attached_display_label` in
   `curve_fit_dialog/dialogs.py:3`, and `QtWidgets` in
   `figure_control_dialog/trace_edit_dialog.py:1`.

   Three more look deliberate and need judgement rather than deletion:
   `labscript_utils` in `hyde/execution/kernel_launcher.py:21` may be an
   intentional side-effect import; `HydeIR`/`HydeIRDiff` in
   `hyde/user_interface/__init__.py:3` are probably intentional re-exports; and
   the `project_templates/default.hy/procedures/__init__.py` ones exist for the
   user's namespace and **must stay**. Decide each by what removing it would
   change, and leave the template alone.

7. **A misindented line**, cosmetic and valid Python:
   `tests/test_kernel_runtime.py:560`, where `request_gui_quit,` inside
   `FakeRuntimeHelper.__init__`'s `del` tuple sits four columns deeper than its
   siblings.

### Acceptance criteria

- [ ] Only one `FakeShellChannel` and one `FinishedCollector` remain, and the
      suite still passes — proving the surviving copy is the one in use.
- [ ] `apply_figure_state` is gone, with zero callers shown first.
- [ ] No test claims to check the installed matplotlib while reading the
      checked-in table.
- [ ] Each sentinel in item 5 is either deleted as vacuous or kept with a stated
      contract.
- [ ] Every import removed is shown to have no reader; the template's imports are
      untouched.

### Blocked by

None - can start immediately. Item 3 overlaps Slice 5's file; sequence them
rather than running both at once.

## Slice 15: Let The Feature-Module Guard See Re-Exports

### Type

`AFK`

### What to build

Slice 6 moved clipboard policy out of `hyde/features/matplotlib_features.py`
and left no shim. Nothing mechanically stops the next change from putting one
back.

`test_no_feature_module_redefines_another_feature_module_name` inspects only
top-level `FunctionDef`, `ClassDef` and `Assign` nodes, so an `ImportFrom`
re-export is invisible to it: `from ...plugins.save_graphics_dialog.clipboard
import GRAPHICS_CLIPBOARD_MIME_TYPES` in a feature module would restore the old
import path and the guard would not notice. It also compares feature modules
only against each other, so a forked copy of the representation list re-added to
`hyde/features/` would not be caught at all.

This is the one place an architecture-contract test is warranted rather than
excluded. The project's test rule is that tests assert what the code does, not
how it is — *except* to the extent the codebase follows its desired modular
structure, which is exactly this. IR-CONTROL states the package-purity rule
normatively; today enforcement is review alone, and review already let this
particular violation through once.

Treat a re-export as a definition for the purposes of that guard, and consider
whether a feature module importing from `hyde/user_interface/plugins/` is ever
legitimate — if it is not, that direction is the simpler and stronger rule to
assert, since it catches the forked-copy case too.

### Acceptance criteria

- [ ] A feature module that re-exports a plugin's symbol fails the guard.
      Demonstrate by adding such a re-export, showing the failure, and removing
      it.
- [ ] The guard states which module and which symbol, so a failure is
      actionable without reading the test.
- [ ] No new structural assertion beyond the architecture contract itself; the
      guard tests the rule, not any particular symbol's current home.
- [ ] The existing feature-module tests still pass unchanged.

### Blocked by

- Slice 6, which is done.

## Slice 16: Stop The Variables Tool Stalling On A Lost Callback

### Type

`AFK`

### What to build

The Python Variables tool has a request-in-flight guard with no recovery, so a
namespace-view request whose callback never arrives stalls the tool for the life
of the window — silently, with no error, no log, and no way back short of
closing and reopening it.

In `hyde/user_interface/plugins/python_variables_tool/__init__.py`:
`refresh_namespace()` returns early when `_refresh_in_flight` is set, recording
`_refresh_pending`; `_refresh_in_flight` is cleared **only** in
`_on_namespace_view`, the success callback; and the request goes out through
`SpyderFrontendComm.request_namespace_view`. So a closed comm, a kernel that
died mid-request, or a dropped comm message leaves the flag set permanently and
every later refresh returns early. The view then shows stale variables
indefinitely while appearing to work.

Found while verifying Slice 7. It is **not** a fifth copy of the lifecycle that
slice collapsed: this surface rides Spyder's comm channel rather than the
shell-reply-plus-payload path, and it has no payload timer at all. The
`_refresh_in_flight` / `_refresh_pending` pair here is the same *coalescing*
policy Slice 7 deliberately left in the two windows, not the lifecycle Slice 7
took ownership of. So the name matches and the mechanism does not.

Decide, rather than assume, whether this should reuse `KernelPayloadRequest`
(`hyde/user_interface/base_hyde_widgets.py`). Read it first: its bounded timer
covers the gap *after* a reply says a command ran, and a comm request has no
separate reply, so the shapes may not map. A comm request may want its own
bounded recovery instead. Either way the outcome is the same three properties:
the flag clears on failure, the user or the log learns why, and the tool can
refresh again.

### Acceptance criteria

- [ ] A refresh whose callback never arrives is shown to stall the tool at
      `HEAD` — demonstrated by execution, with a later refresh returning early
      and the view staying stale.
- [ ] After the fix, that same lost callback leaves the tool able to refresh
      again, and says why it failed.
- [ ] A refresh that succeeds normally is unaffected, including the pending-
      refresh coalescing that already works.
- [ ] Whether `KernelPayloadRequest` was reused or not is stated with the
      reason.

### Blocked by

None - can start immediately. Independent of Slices 8 and 10 to 15; touches a
plugin none of them edit.

## Slice 17: Settle The Orphaned `tracked_names` Payload Field

### Type

`AFK`

### What to build

Slice 10 made `widget_ir.tracked_names()` the single source for "which
namespace names does this figure track". A consequence it did not address: the
kernel still computes and ships a `tracked_names` list in the figure snapshot
payload that **no production code reads any more**.

Verified after Slice 10 landed:

- `hyde/matplotlib_backend.py` still produces it — computed at line 783, shipped
  at 793, and shipped empty at 814.
- No module under `hyde/user_interface/` reads the field. The GUI derives
  tracking from the IR instead.
- It is not documented in `project_management/` as part of the IPC protocol.
- Three tests still assert on it: `tests/test_matplotlib_features.py:1104` and
  `:1268`, and `tests/test_figure_comm_actions.py:192`.

So it is dead protocol surface with a test suite pinning it — assertions on a
payload field that can no longer change any behaviour, which is the shape the
project's test rule excludes.

Decide which way it goes, and say why:

- **Remove it.** The IR the kernel ships already determines the tracked names,
  the GUI derives them from it, and a redundant field that can disagree with the
  IR is the very hazard Slice 10 removed from the GUI. The three tests then
  assert the tracked names the GUI actually acts on.
- **Keep it and make the GUI use it.** Hyde's rule is that the kernel is
  authoritative, and a list computed kernel-side is arguably more authoritative
  than one the GUI re-derives. But note the field is *already* derived from the
  IR kernel-side, so this buys no new authority — and it would make a dormant
  ordering bug live: `figure_snapshot_payload` computes `state_to_python` before
  `tracked_names` (`hyde/matplotlib_backend.py:777-785`), so a lowering failure
  silently zeroes the list even though computing it would have succeeded. That
  fault is currently harmless *only* because nothing reads the field.

Removal looks right, but the decision belongs to whoever holds the IPC protocol
in view; state the reasoning either way.

### Acceptance criteria

- [ ] `tracked_names` is either gone from the payload, or read by production
      code — not produced-and-ignored.
- [ ] If removed, the ordering hazard at `matplotlib_backend.py:777-785` goes
      with it or is stated as moot.
- [ ] The three tests assert tracked names the GUI acts on, or are removed with
      the field.
- [ ] Figure refresh on a namespace change still works, and a figure that tracks
      nothing still does not refresh.

### Blocked by

- Slice 10, which is done.
