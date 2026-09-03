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
- [x] Slice 13: Figure Backend Leftovers
- [x] Slice 14: Trivia, Second Bundle
- [x] Slice 15: Let The Feature-Module Guard See Re-Exports
      — the re-export was already caught, unactionably, by the existing closure
      guard; the forked copy was not caught by any import rule, so it took a
      second name-collision guard
- [x] Slice 16: Stop The Variables Tool Stalling On A Lost Callback
      — `KernelPayloadRequest` was not reused: a comm request has one callback,
      not a reply plus a payload, so its one clock has no legitimate moment to
      start. The comm request got its own recovery, driven by evidence of loss
      rather than by elapsed time
- [x] Slice 17: Settle The Orphaned `tracked_names` Payload Field
      — removed. The field was derived kernel-side from the very `figure_ir`
      shipped beside it, so reading it would have bought no authority the IR
      does not already carry, and would have made the ordering hazard live.
      There was a fourth assertion site the filing missed,
      `test_figure_comm_actions.py:422`
- [x] Slice 18: Make A Plugin That Fails To Load Visible
      — no product decision was needed: the suite already has a mechanism for a
      caught failure that must still reach the user, `raise_exception_in_thread`
      into `labscript_utils.excepthook`, which BLACS and lyse both use and Hyde
      used nowhere. Following it made the change small. The one place Hyde had
      to choose was the missing `Plugin` attribute, which became a warning
      rather than an error because a helper package beside the plugins is a
      legitimate thing to find
- [x] Slice 19: A Failed Macro Still Leaves Non-Trace Mutations On A Neighbour

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

`AFK` — was `HITL`; the maintainer resolved it by choosing to extend the
framework.

### What to build

This branch widened the menu-contribution `enabled` key to accept a callable, so
six plugins now pass `self.has_active_editable_figure`. Hyde resolves it in
`resolve_menu_enabled` (`shared/plugin.py:470`), but the framework base class
Hyde subclasses does `action.setEnabled(enabled)` on the raw value
(`labscript-utils/labscript_utils/plugins.py:1053`) and documents `enabled` as a
plain action property (line 353).

**Correction, measured.** This slice originally said a bound method is truthy, so
a contribution rendered through the base path becomes permanently enabled. That
is wrong under the real binding. Verified against PyQt6:

```
setEnabled(bound method) -> TypeError: setEnabled(self, a0: bool): argument 1 has unexpected type 'method'
setEnabled(lambda)       -> TypeError: ... unexpected type 'function'
setEnabled(False)        -> accepted
```

So the latent failure is louder than described: it raises out of
`MenuContext.render()` and aborts the whole menu build, rather than silently
enabling a copy action whose shortcut then fires on nothing. The truthy reading
holds only for a duck-typed stand-in like the framework tests' `FakeAction`.
That *strengthens* the case that no other application can have depended on the
current behaviour — none could have shipped it. `HydeMenuContext.render` fully
overrides `render` today, which is why Hyde never hits it.

**Resolved by the maintainer: extend the labscript-utils framework**, on its
`Development` and `Production` branches only — never `master`.

Impact assessed across all thirteen local suite repositories before deciding,
and the change is safe. `enabled` exists in exactly one place, `MenuContext.render()`;
the legacy `MenuBuilder.create_menu()` has no notion of it. **BLACS — the
reference the maintainer named — never reaches that path at all**: it imports
only `MenuBuilder` and `PluginManager`, never registers a `menus` context, and
never constructs a `MenuContext`, so `render()` is unreachable from it. Swept
all refs of every repo including `PluginRefactor`: no consumer outside Hyde
passes `enabled` at all, let alone a callable, and nothing reads it back except
Hyde's own `refresh_enabled_states`, which reads the contribution dict rather
than the framework's local.

Three things shape the implementation:

- **Adopt Hyde's exception policy in the framework.** `MenuContext.render()` has
  no `try/except` around its per-contribution loop, so an `enabled` that raises
  propagates out and leaves the action's state unset. Hyde's
  `resolve_menu_enabled` deliberately catches and returns `False`, on the
  reasoning that a broken precondition should disable an action rather than take
  the menu down. If the framework does not adopt the same policy, Hyde can never
  delete its own resolver and delegate, because the two would disagree on the
  failure path.
- **Resolve into a local; do not write the resolved value back into the
  contribution dict.** Hyde stores the raw callable for
  `refresh_enabled_states`, and mutating the dict would break re-rendering.
- **The framework's existing tests do not need changing.** They pass
  `enabled: False` and omit the key, both non-callable, so the new branch never
  fires — confirmed by patching a copy of `plugins.py` in memory and running the
  labscript-utils suite against it, 31/31 unchanged. The callable case needs a
  *new* test.

Note the docstring update is real published API documentation, not a comment:
`docs/source/api/index.rst` autosummaries `labscript_utils` with `:recursive:`.

Also worth knowing for any follow-up: `enabled` is not the only drifted key.
Hyde's contributions carry `group_order`, which the framework does not
understand — it derives group ordering from sorted group names. So this
extension is necessary but not sufficient for Hyde to drop its `render`
override.

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

- [x] No attribute's name contradicts what it holds.
- [x] No per-figure state is retained for the process lifetime with no reader.
- [x] A macro that fails does not leave a partial trace in another figure's IR,
      or the reason it must is written down.
- [x] No dead branch survives in `finalize_figure_build_session`.

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

- [x] Only one `FakeShellChannel` and one `FinishedCollector` remain, and the
      suite still passes — proving the surviving copy is the one in use.
- [x] `apply_figure_state` is gone, with zero callers shown first.
- [x] No test claims to check the installed matplotlib while reading the
      checked-in table.
- [x] Each sentinel in item 5 is either deleted as vacuous or kept with a stated
      contract.
- [x] Every import removed is shown to have no reader; the template's imports are
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

- [x] A feature module that re-exports a plugin's symbol fails the guard.
      Demonstrate by adding such a re-export, showing the failure, and removing
      it.
- [x] The guard states which module and which symbol, so a failure is
      actionable without reading the test.
- [x] No new structural assertion beyond the architecture contract itself; the
      guard tests the rule, not any particular symbol's current home.
- [x] The existing feature-module tests still pass unchanged — the inline
      definition collector in
      `test_no_feature_module_redefines_another_feature_module_name` was
      extracted to a shared helper so the new guard does not carry a second
      copy of it. Its assertion is untouched, and it was re-verified to still
      fail on an injected duplicate.

### Settled: which rule, and what each shape costs

The direction rule was chosen — a feature module must never import from
`hyde/user_interface/plugins/` — asserted as a direct-import scan that names
the file, the symbol and the plugin module.

Two corrections to the premise above, both established by execution:

- The direction is **already** asserted, at closure granularity, by
  `test_kernel_side_modules_never_reach_gui_plugins_or_qt`. Injecting the
  re-export makes it fail. It is inadequate rather than absent: it reported 252
  violations in a 27k-character diff truncated by `maxDiff`, whose first entry
  was `hyde -> GUI plugin hyde.user_interface.plugins` — naming neither the
  feature module responsible nor the symbol — while two neighbouring tests
  buried it under circular-import errors.
- The direction rule does **not** catch the forked copy. A copy re-typed as a
  literal imports nothing, so both import-direction guards stay green on it.
  Verified: with a forked `GRAPHICS_CLIPBOARD_MIME_TYPES` literal in
  `hyde/features/matplotlib_features.py`, the new import guard and the existing
  closure guard both passed. That shape needs the separate name-collision rule,
  `test_no_public_name_lives_in_both_a_feature_module_and_a_gui_plugin`.

The wider rule "a feature module never imports from `hyde/user_interface/`"
was rejected: `hyde/features/hyde_ir.py`, `lmfit_ir.py` and `matplotlib_ir.py`
all import `HydeIR` / `HydeIRDiff` from `hyde.user_interface.shared.core`, which
IR-CONTROL sanctions as the base IR contract. It would need three carve-outs on
day one. The `plugins/`-scoped rule needs none.

Not caught by either guard: a dynamic
`importlib.import_module("hyde.user_interface.plugins...")`, which is a string
rather than an import node; and a forked copy renamed on the way in, which a
name-based rule cannot see. No kernel-side module uses a dynamic import today.

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

- [x] A refresh whose callback never arrives is shown to stall the tool at
      `HEAD` — demonstrated by execution, with a later refresh returning early
      and the view staying stale.
- [x] After the fix, that same lost callback leaves the tool able to refresh
      again, and says why it failed.
- [x] A refresh that succeeds normally is unaffected, including the pending-
      refresh coalescing that already works.
- [x] Whether `KernelPayloadRequest` was reused or not is stated with the
      reason.

### Blocked by

None - can start immediately. Independent of Slices 8 and 10 to 15; touches a
plugin none of them edit.

### What was done

Reproduced at `HEAD` by driving the real `SpyderFrontendComm` over a fake
Jupyter comm. A refresh went out, the kernel answered it with an error reply,
spyder-kernels popped the waiting callback off `_reply_waitlist` and routed the
failure to `_async_error` — which printed and moved on. Three further
`refresh_namespace()` calls then dispatched **zero** requests, the view kept
showing the pre-failure values, and `_refresh_in_flight` was still set, with the
comm still open and a kernel perfectly willing to answer. The same permanent
stall was reproduced for a comm closed mid-request.

`KernelPayloadRequest` was **not** reused. Its lifecycle is reply-then-payload:
`_on_reply` arms `PAYLOAD_TIMEOUT_MS` only once the shell reply says the command
ran, at which point the data is already in transit. A comm request has no
separate reply — `RemoteCall` sends one message and exactly one comes back,
either the payload or an error — so that clock has no moment at which it could
legitimately start. Arming it at dispatch would be a fifth wall-clock timeout on
a kernel that may be busy with the user's own cell, which is what this branch
removed four of. Its `owner` contract is also `python_execution_service`-shaped
(`dispatch` calls `request_command`), and this request rides Spyder's comm
instead. What *was* reused is `KernelCommands.report_kernel_failure`, so the
failure speaks with the same voice — log *and* status bar — as every other
kernel-facing surface; `PythonVariables` mixes in `KernelCommands` the way both
widget roots already do.

Recovery therefore runs on **evidence of loss, never on elapsed time**. Lost is
one of: the request never went out (`RemoteCall` silently drops a non-blocking
call to a disconnected comm, so `request_namespace_view` now reports whether it
dispatched); the kernel answered with an error, so spyder-kernels dropped the
callback (`_async_error` now tells the widget instead of printing); or the comm
that would carry the answer is gone, checked when the next refresh is asked for.
Slow is everything else — comm open, send accepted, no error — and is left to
wait indefinitely. A comm message genuinely lost in transit on a live comm is
**not** distinguishable from slow, and is deliberately not covered: on this
transport that distinction cannot be drawn, and a recovery that fired on a
slow-but-healthy kernel would be worse than the stall.

The coalescing was left in place as this surface's own concern, as in the figure
and table windows.

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

**Settled: removed.** The premises were re-verified first. No reader exists
anywhere — the payload crosses the comm whole, and both consumers of the
`snapshot` dict read named keys only (`figure_interactive/__init__.py` and
`window.py`), while `FigureIR.from_snapshot` reads four keys and not this one.
Nothing in `project_management/` mentions the field, gitignored `_source/`
included. There were **four** assertion sites, not three: the filing missed
`test_figure_comm_actions.py:422`.

The two candidate divergences were then separated by execution, and only one is
real:

- **The read-back-fails path does not diverge.** On the Slice 13 path
  (`line.set_data(np.zeros((2,3)), ...)`),
  `_refresh_first_class_figure_metadata` sets the import warning and returns
  without replacing `figure._hyde_ir`, and `figure_snapshot_payload` then
  derives *both* the shipped `figure_ir` and the `tracked_names` list from that
  one stale IR. Driven for real, both said `y`. They go stale together, which is
  self-consistent: the figure keeps refreshing on the last names Hyde could
  read.
- **The ordering hazard is the only divergence, and keeping the field is what
  would arm it.** With `state_to_python` forced to raise on a figure whose IR
  tracks `y`, the payload shipped `tracked_names: []` beside a `figure_ir` the
  GUI still reads `('y',)` off. A GUI reading the field would have had a figure
  that reports nothing and never refreshes — the Slice 10 defect exactly, moved
  across the process boundary where it is harder to see. Removal retires it: the
  `try` no longer guards anything whose loss is silent.

So the field bought no authority the IR does not already carry, and its only
possible effect was to contradict it.

Left alone deliberately, as a consequence outside this slice: the removed line
was the last production caller of `MatplotlibCodec.tracked_names`
(`hyde/features/matplotlib_features.py:623`), so that classmethod is now
reached only from
`test_matplotlib_features.py::test_lowering_and_tracked_names_match_across_the_process_boundary`.
It is not part of the `FeatureCodec` ABC, but it is one arm of the codec's
uniform feature-kind dispatch and its test is a legitimate
two-implementations-agree contract, so removing it is a separate judgement about
the codec's surface rather than about this payload field. The kernel-side
`FigureCommandModel.tracked_names` it delegates to is still live, via
`state_to_macro_source`.

### Acceptance criteria

- [x] `tracked_names` is either gone from the payload, or read by production
      code — not produced-and-ignored. Gone from both payload branches.
- [x] If removed, the ordering hazard at `matplotlib_backend.py:777-785` goes
      with it or is stated as moot. Gone with it.
- [x] The three tests assert tracked names the GUI acts on, or are removed with
      the field. Two now assert `FigureIR.tracked_names()` — the window's own
      call — and both were confirmed to fail when that call is sabotaged. The
      other two lines were dropped as second statements of an assertion already
      in the same test (`figure_ir is None` for a figure Hyde does not
      describe; the frozen `np.array(...)` literal for a second-class figure
      that did not adopt the namespace names it happened to be plotted from).
- [x] Figure refresh on a namespace change still works, and a figure that tracks
      nothing still does not refresh. Verified by execution, not by the suite
      alone: a real `@hyde.figure` payload from the real backend drove a real
      `FigureWindow`, which reported `('y',)` and issued exactly one
      `hyde.refresh_figure` when `y` changed; a figure built from a literal
      reported `()` and issued none.

### Blocked by

- Slice 10, which is done.

## Slice 18: Make A Plugin That Fails To Load Visible

### Type

`AFK` — filed as `HITL` asking what the user should see. The maintainer
resolved it by pointing at the existing pattern: Hyde follows the labscript
suite, and BLACS already uses plugins. There was no product decision to make,
only research to do.

The pattern the suite already has, with evidence:

- `labscript_utils/plugins.py` reports every swallowed plugin failure through
  `self.logger` and nothing else — `discover_modules`, `instantiate_plugins`,
  `setup_plugins`, `_get_contributions`, `setup_complete`. Its module docstring
  states the reason: "Import or instantiation failures are logged and skipped so
  one broken plugin does not stop the application from starting."
- The suite's mechanism for a *caught* failure that must still reach the user is
  `zprocess.raise_exception_in_thread` (`zprocess/zprocess/utils.py:112`), which
  re-raises on a new thread so that the exception reaches `sys.excepthook`
  without unwinding the caller. `labscript_utils.excepthook` replaces
  `sys.excepthook` with one that opens an error window in a subprocess
  (`labscript_utils/excepthook/__init__.py:64`, `tk_exception.py`).
- BLACS uses it for a device tab that will not instantiate
  (`blacs/blacs/__main__.py:270`); lyse for its shot-add and analysis loops
  (`lyse/lyse/filebox.py:911` and `:955`), with the comment "Keep this incoming
  loop running at all costs, but make the otherwise uncaught exception visible
  to the user"; runmanager in four places. Hyde used it nowhere.
- So the surface is not a new one. It is the suite's error window, reached the
  way the suite reaches it. Hyde already installs the excepthook
  (`hyde/__main__.py:20`) for its own uncaught exceptions.
- Hyde's in-app log pane cannot be the surface, and this is structural rather
  than a choice: it is itself a plugin, and `HydeApp.__init__` connects the
  logger to it only after every plugin has already loaded.
- No first-party/third-party distinction exists in the suite, so none was
  invented. It is not needed: raising on another thread preserves the tolerance
  the framework was built for by construction.

### What to build

A plugin that raises on import is silently absent from a running Hyde — its
menus, windows and commands simply are not there. The app starts and looks
merely featureless rather than broken.

`HydePluginManager` (`hyde/user_interface/shared/plugin.py`) swallows and logs in
three places — `discover_modules`, `instantiate_plugins` and
`_get_contributions` — and `discover_modules` skips a plugin directory whose
module has no `Plugin` attribute **without logging at all**. Separately,
labscript-utils' plugin host catches a failed `start_runtime` activity and only
logs it, which is why a broken kernel launch once let Hyde come up looking
normal with no kernel.

This has now surfaced twice from different directions: as the reason a kernel
launch failure was invisible (noted in Slice 9, deliberately not fixed there),
and as the one framework path a start-up guard could not observe (found while
building Slice 11's guard, whose disk-vs-discovered comparison covers it only
inside that test).

The swallowing is partly the host's design — one bad plugin must not stop the
app — so this is not simply "raise instead".

### What was done

Small, because the suite already had the mechanism. `report_plugin_failure` in
`hyde/user_interface/shared/plugin.py` logs as before and then hands the failure
to `zprocess.raise_exception_in_thread` as a `HydePluginFailure` carrying the
original traceback, so the user gets the suite's error window naming the plugin
and why it broke while start-up carries on.

The plugin host has no seam for "report a failure" other than its logger, so its
logger is the seam: `HydePluginManager` and `HydeMenuContext` wrap the logger
they are given in `VisibleFailureLogger`, which delegates everything unchanged
except `error`/`exception`/`critical`. That covers every swallow site in one
place — import, instantiation, contributions, menu rendering, and
`setup_complete`'s setup activities, which is the kernel launch. `HydeApp`'s
`emit_plugin_event` calls the same helper directly, which covers the tool
windows built from a `kernel_ready` handler.

Warnings are deliberately not escalated, following the host's own level
convention: a warning records something odd, an error records a plugin that is
not working. That is what the missing `Plugin` attribute became — a warning, not
an error, because `test_plugin_manager_discovers_only_plugin_packages` documents
a package without a `Plugin` as a legitimate helper rather than a defect.

### Acceptance criteria

- [x] A first-party plugin that raises on import produces something the user can
      see, or a written decision that it should not. Driven for real with
      `labscript_utils.excepthook` installed as `hyde/__main__.py` installs it,
      with the dialog subprocess captured rather than opened: a plugin whose
      `__init__.py` imports a missing module produced an error window titled
      "Unhandled exception in <script>", headed `HydePluginFailure: Could not
      import plugin 'figure_export'. Skipping. Original exception was:
      ModuleNotFoundError: No module named 'nonexistent_module_xyz'`, with the
      plugin's own traceback frame in the body.
- [x] A plugin directory with no `Plugin` attribute is at least logged. Now a
      warning naming the package; verified by observation, and by removing the
      log line and watching the guard fail.
- [x] One bad third-party plugin still does not prevent Hyde from starting. The
      mechanism preserves this by construction — the exception is raised on
      another thread, so nothing unwinds the caller. Verified: alongside a
      plugin that raises `ImportError` on import, the sound plugin beside it was
      still discovered and instantiated, and alongside a `start_runtime`
      activity that raises, the neighbouring plugin still completed its own
      setup.
- [x] The kernel-launch case is covered by whatever surface is chosen, since
      that is the failure that motivated it. It is the same surface: a
      `start_runtime` setup activity that raises is reported through the host's
      logger, so it now reaches the error window. Verified by execution.

### Related, found while doing Slice 16

`SpyderFrontendComm.wait_until_ready(timeout=5)` is a wall-clock timeout on
kernel readiness that raises `TimeoutError` from inside
`PythonVariables.__init__`. `HydeToolWindowPlugin` would surface that as a
failed widget construction — which, given this slice's subject, means the
variables tool silently does not appear on a slow machine.

It is a startup handshake rather than a request, so it is not one of the four
wall-clock timeouts this branch removed, and Slice 16 deliberately left it. But
whatever surface this slice chooses for start-up failures should cover it: a
tool that vanished because a five-second handshake expired is exactly the
failure a user cannot diagnose.

Covered. The tool is built from a `kernel_ready` event handler, and
`HydeApp.emit_plugin_event` was the one swallow site outside the plugin host, so
it now reports through the same helper. A handler that raises `TimeoutError`
puts that timeout in the error window rather than leaving an absent tool.

### Blocked by

None.

## Slice 19: A Failed Macro Still Leaves Non-Trace Mutations On A Neighbour

### Type

`HITL`, and **resolved by decision rather than by implementation.** Asked which
of the two closures to build, the maintainer's answer was: neither — keep the
status quo. So no behaviour changed; what landed is the documentation the third
acceptance criterion asks for.

### What to build

Slice 13 stopped a failed macro leaving an appended *trace* on a neighbour
figure. Every **non-trace** mutation it made to that neighbour still survives.

Measured at both `205110b` and `63ec5dc`: a macro that calls
`ax.legend(["a","b"])` on a neighbour and then fails leaves the neighbour's
subplot IR carrying `legend: true`, while the appended trace is correctly rewound.
The same holds for a title, axis limits, or a scatter or image artist — anything
that is not one of the lines the rewind removes.

The underlying asymmetry, which is worth stating because it explains both this
gap and why part of Slice 13's rewind looked redundant: **the IR is normally a
projection of the live artists.** `_refresh_first_class_figure_metadata` ends
with `figure._hyde_ir = imported_ir`, re-deriving the IR from live state on every
publish. So anything the rewind cannot remove from the *live* figure comes back
on the next publish, and anything the rewind writes into the *IR* is discarded.
Slice 13's IR snapshot matters only in the one window where that projection is
unavailable — when the live-state read-back raises, which
`line.set_data(np.zeros((2,3)), ...)` reaches with
`ValueError: Only 1D line data can be imported into Hyde figure macros`.

Closing the general case means one of:

- **Undo every artist a macro adds to a neighbour**, not just lines — which
  means tracking artist creation across the whole matplotlib surface a macro can
  touch, and reversing property mutations that created no artist at all
  (`legend`, limits, labels). Broad, and `abandon_figure_build_session`'s
  docstring already declines general undo of live matplotlib mutations for the
  figure the macro was *building*.
- **Suppress the re-import for the rest of the failed run**, so the neighbour's
  IR keeps its pre-macro projection until something legitimately redraws it.
  Narrower, but it makes the IR and the live figure disagree on purpose, and
  that divergence is what the projection design exists to avoid.

Neither is obviously right, and the status quo may be defensible: the user can
see the stray legend on the neighbour, and a failed macro is already an error
they must act on. Decide the intended behaviour first.

### Acceptance criteria

- [x] The intended behaviour for a neighbour's non-trace mutations after a
      failed macro is written down, with the reasoning.
- [ ] ~~If they are to be undone~~ — not chosen; the maintainer kept the status
      quo, so nothing was undone.
- [x] If they are to be kept, the rewind's scope is documented so the next
      reader does not mistake the asymmetry for a bug.
- [x] Drawing on a neighbour from a macro that *succeeds* keeps working —
      unchanged, and the suite is unmoved at 652 tests.

### Outcome

`abandon_figure_build_session`'s docstring now states the limit as deliberate
and gives the mechanism behind it, because the asymmetry was misread twice
during this review — once as a missing fix, once as redundant code. A figure's
IR is a projection of its live artists, re-derived on every publish, so what the
rewind removes from the live figure stays removed, what it writes into the IR is
discarded, and the IR snapshot matters only in the window where the read-back
raises. The traces are the whole scope; a legend, title, axis limit or non-line
artist survives, and that residue is accepted — it is on screen where the user
can see it, and a failed macro is already an error they must act on.

No test was added, deliberately. A test asserting that the legend *is* left
behind would pin an accepted limitation as a contract, and would become an
obstacle rather than a guard if this decision is ever revisited.

### Blocked by

- Slice 13, which is done.
