# Post-Review Findings

Source: findings the branch-review agents reported as out of scope while
implementing `BRANCH_REVIEW_ISSUES.md`, unified here. Each was re-verified
against the current tree before filing; the evidence is inline. Nothing in this
file was filed on an agent's word alone.

`BRANCH_REVIEW_ISSUES.md` is closed (19/19). This is the follow-on backlog.

## Progress Checklist

- [ ] Slice 1: `force_close` Does Not Close
- [ ] Slice 2: Dead And Unreachable Code In The Figure Backend
- [ ] Slice 3: Two Half-Finished Shutdown Paths
- [ ] Slice 4: `group_order`, The Other Drifted Contribution Key
- [ ] Slice 5: Test Hygiene, Round Three
- [ ] Slice 6: Stale Documentation Left By The Review
- [ ] Slice 7: The Pre-Commit Hook Runs The Wrong Interpreter
- [ ] Slice 8: Generate `plt.figure(name, clear=True)`

## Slice 1: `force_close` Does Not Close

### Type

`AFK`

### What to build

`FigureWindow.force_close()` promises closure and delivers none. Verified by
reading the shipped source:

```python
def force_close(self):
    self._closing_from_kernel = True
    self.settle_payload_request("close")
    self.close_from_kernel()
```

and `close_from_kernel()` opens with

```python
if self._closed or self._closing_from_kernel:
    return
```

So `force_close()` sets the flag, then calls the one method that returns early on
exactly that flag. It never calls `self.close()`. Confirmed: `".close()" in
inspect.getsource(FigureWindow.force_close)` is `False`.

**It has a production caller.** `FigureWorkspaceService.clear()`
(`figure_interactive/__init__.py:82`) iterates every open figure calling
`force_close()`, then empties `self.figures`. So clearing a workspace drops
figure windows from the registry without closing them, leaving windows whose
owner no longer tracks them. This is the same family as the tool-window leak
already fixed once on this branch, where a window from one project survived into
the next.

Roughly twenty test call sites use `force_close()` as teardown, and they pass —
which means none of them asserts that the window actually closed. Whatever the
fix, it needs a test that would have failed.

Decide what `force_close` is for. Either it is "close regardless of who asked",
in which case it should close and the flag exists only to mark provenance for
`closeEvent`, or it is "mark this as kernel-initiated and let the normal path
run", in which case the name is wrong and the caller in `clear()` wants
something else.

### What the investigation established

Reported by the user as a regression: two figures open, switch to a project with
none, the windows stay and the kernel terminal fills with
`ValueError: Could not resolve first-class figure 'Figure1'.` from
`hyde.get_figure(...)` + `hyde.refresh_figure(...)`.

**It is not a regression.** `force_close` is identically broken on `master`:

```python
def force_close(self):                      # master
    self._closing_from_kernel = True
    self._kernel_close_in_progress = False
    self.close_from_kernel()                # returns immediately on that flag
```

The `_closing_from_kernel` term in `close_from_kernel`'s guard arrived in
`36a23e2`, which is contained in `master`. At the repo's first commit the guard
tested only `self._closed`, so `force_close` worked then.

What the branch changed is that the hole became **loud**. `master` and the
branch's first six commits carry `@classmethod` twice on
`MatplotlibCodec._range_lines`, which Python 3.13+ rejects as non-callable, so
every figure snapshot raised `TypeError` in the GUI, no window ever received an
IR, `tracked_names` stayed empty and refresh was gated off. `4442be8` re-pointed
the codec at a correct copy, so IRs finally landed — and the always-broken
teardown finally had live, namespace-tracking windows to orphan. Before: windows
survived but were blank and silent. After: populated, and talking to the new
kernel. Slices 7, 10 and 17 are cleared — identical behaviour either side of
each.

**Two independent causes, one per process.** Both must fail for the windows to
survive:

- **Kernel.** `hyde.load_project()` calls
  `project_tools.clear_live_matplotlib_managers()`, which is `Gcf.figs.clear()`.
  That bypasses `FigureManagerHyde.destroy()`, the only thing that emits the
  close event, so the kernel forgets its figures without telling the GUI and
  never closes the comms. Measured: `comm messages sent: []`,
  `manager._destroyed: False`, versus `Gcf.destroy_all()` which sends
  `{'event': 'close'}` then `{'event': 'comm_closed'}`. Unchanged since the
  repo's first commit.
- **GUI.** `force_close()` is a no-op and `clear()` then empties
  `self.figures`.

Symptom 2 is downstream of symptom 1: an orphaned window keeps its
`namespace_view_service` subscription, because only `complete_interactive_close`
→ `_disconnect_namespace_updates` drops it, and that never runs.

**A kernel-only fix is not enough, and is racy.** In `load_project`,
`signal_enter_no_project_state()` (→ `clear()`) runs *before*
`clear_live_matplotlib_managers()`, and `clear()` poisons the comm-close route:
it sets `_closing_from_kernel` on every window so `close_from_kernel` can never
fire again, and empties `figures` so `close_figure` returns early. Measured: a
late comm close after `clear()` leaves the subwindow open.

Two corrected variants were verified by monkeypatching the probe, repo
untouched — a corrected `force_close`, and a comm close arriving *before*
`clear()`. Both fixed both symptoms with zero save prompts, so
`is_close_complete()` correctly routes to `complete_interactive_close`.

### The fix: three places, the first required

1. **`FigureWindow.force_close()` — necessary and sufficient.** Set the flag,
   then `settle_payload_requests()` — **all lanes, not just `"close"`**; there is
   a live `"refresh"` lane — then actually close: the bound subwindow if there is
   one, else `self.close()`.
2. **`FigureWorkspaceService.clear()`.** `self.figures.clear()` is what makes the
   failure unrecoverable. Let `_remove_figure` / `_on_subwindow_destroyed` retire
   entries, or at least keep entries for windows that did not actually close, so
   a late close still has something to act on.
3. **`clear_live_matplotlib_managers()` (kernel).** Destroy the managers rather
   than dropping the dict, so the GUI is told and the comms are closed. Not
   sufficient alone, but it fixes a comm leak — one stranded comm per figure per
   project switch — and stops `Gcf` and the GUI disagreeing about what exists.

The same defect makes `on_kernel_crashed` leak identically: stale figure windows
survive a kernel restart and refresh against the fresh kernel.

### Why 126 passing tests missed it

All ~20 `force_close()` call sites are `finally:` teardown and none asserts
closure; several build a `FigureWindow` with no subwindow and no services, where
`force_close` has nothing to close. `test_figure_comm_actions._figure_workspace()`
sets `"get_shutting_down": lambda: True`, so those tests only ever reach the
shutdown fast path.

The test that should have caught it is
`test_plugin_discards_pending_batched_payloads_when_workspace_is_cleared`, the
only one driving `plugin.on_project_loaded(...)`. It fails twice over: it feeds a
*pending* payload and clears it before the 0-ms flush timer fires, so no window
is ever created; and it asserts `plugin.workspace.figures == {}`, which is **the
bug's fingerprint rather than its absence** — `figures.clear()` makes that pass
whether or not anything closed.

A regression test needs an open, IR-bearing figure window,
`get_shutting_down: False`, and assertions on `mdi_area.subWindowList()` plus
"no command issued on the next namespace view" — never on `workspace.figures`.

### Acceptance criteria

- [ ] `force_close()` leaves the window closed, shown by execution.
- [ ] `FigureWorkspaceService.clear()` leaves no open figure window behind.
- [ ] A test fails if `force_close()` stops closing, asserting on
      `mdi_area.subWindowList()` and on no command being issued for the next
      namespace view — not on `workspace.figures`.
- [ ] A kernel project switch closes the figure comms rather than stranding
      them.
- [ ] The kernel-initiated close path still works: a window closed by the kernel
      does not re-notify the kernel.

### Blocked by

None - can start immediately.

## Slice 2: Dead And Unreachable Code In The Figure Backend

### Type

`AFK`

### What to build

Three pieces, all in `hyde/matplotlib_backend.py`.

1. **`_BackendHyde.draw_idle` and `flush_events` can never be called.**
   Defined as instance methods at lines 1902 and 1905 on a subclass of
   matplotlib's `_Backend`. Verified against the installed matplotlib 3.11.1:
   every member of `_Backend` is a `classmethod` or `staticmethod` — a static
   scan for plain functions on the class returns **none** — so `_Backend` is
   never instantiated and no instance method on a subclass is reachable. They
   look like they were meant for the canvas; establish whether the canvas needs
   them before deleting, and if it does, that is a bug fix rather than a
   deletion.

2. **A conditional whose branches are identical**, line 1883:

   ```python
   subplot_code = "111" if len(args) == 1 else "111"
   ```

   Slice 13 removed the sibling dead branch in `finalize_figure_build_session`
   and named only that one, so this was left. Note the two branches being equal
   may be hiding an intended `subplot_code` for the multi-arg case — check what
   `add_subplot(*args)` is expected to do with more than one argument before
   collapsing it, rather than assuming the answer is `"111"`.

3. **`MatplotlibCodec.tracked_names` may have no production caller.** Slice 17
   removed what it believed was the last one and deliberately left the method,
   on the grounds that it is one arm of the codec's uniform feature-kind dispatch
   and its remaining test is a legitimate two-implementations-agree contract.
   Confirm that reading: the other `tracked_names` definitions in the same file
   and in `matplotlib_ir.py` are live, so the sweep has to distinguish the
   classes rather than match the name.

### Acceptance criteria

- [ ] `draw_idle`/`flush_events` are deleted, or moved to the class that can
      actually receive them, with the reason stated.
- [ ] No conditional with identical branches remains in the backend.
- [ ] `MatplotlibCodec.tracked_names` is either shown to have a production caller
      or removed with its test.
- [ ] Figure creation, refresh, close and copy all still work.

### Blocked by

None - can start immediately.

## Slice 3: Two Half-Finished Shutdown Paths

### Type

`AFK`

### What to build

1. **`PythonVariables.shutdown()` overrides `HydeToolWidget.shutdown()` without
   calling `super()`**, so `_shutdown_requested` is never set and
   `allows_subwindow_close()` cannot see that the widget has shut down. Harmless
   today only because `_closed` gates the paths that matter — which means the
   widget now has two answers to "is this thing done". Found while doing Slice
   16.

2. **`clear_kernel_progress()` clears the status bar unconditionally**, so an
   unrelated message posted while a short-lived announced request is in flight is
   cleared along with it. Introduced by Slice 7's consolidation and strictly
   better than the previous behaviour of never clearing, so this is a
   refinement, not a regression: clear only what this request posted.

### Acceptance criteria

- [ ] One answer to "has this widget shut down", used by
      `allows_subwindow_close()`.
- [ ] A message posted by something else survives an announced request
      completing.
- [ ] The status bar is still cleared when the request that posted it settles.

### Blocked by

None - can start immediately.

## Slice 4: `group_order`, The Other Drifted Contribution Key

### Type

`HITL` — the same cross-repo shape as the `enabled` extension, so it needs the
same decision.

### What to build

Slice 12 extended the labscript-utils framework so a menu contribution's
`enabled` may be a callable, and landed it on `Development` and `Production`.
That was necessary for Hyde to stop carrying a private extension of a shared
contract, but it is **not sufficient** for Hyde to drop its `render` override.

Hyde's contributions also carry `group_order` — 18 occurrences in
`hyde/user_interface/shared/plugin.py`. The framework does not understand the
key: it derives group ordering from sorted group names, and its five
`group_order` hits are a local variable named `group_orders`, not the key.

So Hyde's contribution dictionaries are still not base-renderable, and
`HydeMenuContext.render` still has to exist. Until that is settled, the
`enabled` extension buys correctness of contract rather than the deletion it was
meant to enable.

Decide the same way: extend the framework to understand explicit group ordering
and document it where the keys are documented, or keep it in Hyde and accept the
override permanently. If the framework changes, it is a separate reviewable
commit in labscript-utils on `Development` and `Production` — never `master`.

Worth checking first whether sorted group names are actually insufficient for
Hyde's menus, or whether Hyde could drop `group_order` by naming its groups so
they sort correctly. That would need no framework change at all.

### Acceptance criteria

- [ ] Either the framework understands explicit group ordering, or Hyde no longer
      needs `group_order`, or the override is documented as permanent with the
      reason.
- [ ] Hyde's menu order is unchanged for the user, whichever route is taken.
- [ ] If `resolve_menu_enabled` can now be deleted and delegated, that happens
      here.

### Blocked by

- Slice 12 of `BRANCH_REVIEW_ISSUES.md`, which is done.

## Slice 5: Test Hygiene, Round Three

### Type

`AFK`

Use the test-cleanup skill.

### What to build

1. **A test whose named subject never runs.**
   `test_the_cursor_is_never_left_busy_after_a_completed_copy` feeds the flat
   legacy payload shape (`payload_base64`/`output_format` at top level, no
   `representations` list), which the current parser reads as **zero**
   representations. Measured messages were
   `['Copying figure as Vector...', 'Could not copy the figure to the clipboard.']`
   — a *failed* copy. The test passes only because the cursor is restored on
   every path, so its assertions hold while its subject does not. Either give it
   a completed copy or rename it to what it checks.
   `test_a_failed_render_does_not_confirm_success` uses the same shape, where it
   is correct.

2. **Two near-duplicate tests.** `test_pgf_payload_carries_no_image_representation`
   and `test_a_pgf_copy_carries_no_image_the_platform_could_paste` both assert a
   pgf payload has text and no image, in different classes.

3. **An unused import.** `tests/test_remove_from_graph_dialog.py:28` imports
   `FigureIR` and `FigureIRDiff`; only `FigureIRDiff` is read.

4. **A ~50-line stub duplicated across modules.** `make_plugin_host` in
   `tests/test_save_graphics_dialog.py` is a HydeApp stub, and
   `TestCopyAsSubmenu._host` and others build partial variants of the same
   thing. A shared helper would suit several modules — but note this touches
   several test files at once, so weigh the churn against the duplication.

### Acceptance criteria

- [ ] No test's name claims a subject the test does not exercise.
- [ ] The duplicate pgf assertion exists once.
- [ ] No unused import remains in the touched test modules.
- [ ] The suite's coverage of copy feedback is unchanged in substance.

### Blocked by

None - can start immediately. Item 1 touches
`tests/test_save_graphics_dialog.py`, so sequence it against any other slice
editing that file.

## Slice 6: Stale Documentation Left By The Review

### Type

`AFK`

### What to build

1. **`BRANCH_REVIEW_ISSUES.md` Slice 6's rationale** still describes
   `copy_request.py` as a module "already there" beside `clipboard.py`. Slice 7
   deleted it when it collapsed the request lifecycle into
   `KernelPayloadRequest`. A completed slice's record should not be rewritten to
   change what was decided, but a reference to a file that no longer exists will
   mislead the next reader — add a forward note rather than editing the
   reasoning.

2. **`IR-CONTROL.md`'s field counts are approximate.** It says "eight of its
   fields apply to only the two export-shaped ones" and refers forward to "a
   ninth conditional field". Slice 8 counted the export-only fields as six
   before its change and five after, and decremented both numbers to keep the
   document internally consistent rather than rewrite a count whose intent could
   not be verified. Settle what the sentence is actually counting.

3. **Slice 2's ticked text in `BRANCH_REVIEW_ISSUES.md`** names
   `_hyde_source_artifact` and `_hyde_ast_artifact`, which Slice 13 removed.
   Same treatment as item 1: annotate, do not rewrite history.

### Acceptance criteria

- [ ] No tracked document points at a file or attribute that no longer exists
      without saying so.
- [ ] `IR-CONTROL.md`'s counts match the code, or say what they count.
- [ ] Completed slices' decisions are not rewritten, only annotated.

### Blocked by

None - can start immediately.

## Slice 7: The Pre-Commit Hook Runs The Wrong Interpreter

### Type

`AFK`

### What to build

`scripts/hooks/pre-commit:7` runs

```
python scripts/regenerate_graphics_formats.py --check || exit 1
```

Bare `python` resolves to whatever is first on `PATH`, which is the base conda
environment rather than the `labscript` environment Hyde runs in. The hook
checks the generated graphics-format table against *that* interpreter's
matplotlib. It is correct today only by coincidence: both environments currently
carry matplotlib 3.11.1. The moment they diverge, the hook either blocks a
correct commit or passes a stale table.

Point it at an interpreter that is actually Hyde's. Note the repo should not
hard-code one developer's absolute path, so decide between resolving the
environment by name, honouring an environment variable, or documenting a
required `PATH` — and say why.

### Acceptance criteria

- [ ] The hook checks the table against the same matplotlib Hyde imports.
- [ ] It does not hard-code a single machine's interpreter path.
- [ ] A stale table still fails the hook, shown by regenerating against a
      deliberately different format list.

### Blocked by

None - can start immediately.

## Findings recorded, deliberately not filed

- **A failed macro that built its own figure leaves it tracked and windowed in
  `Gcf` but never first-class.** Pre-existing and arguably correct: the user sees
  the half-drawn figure beside the error that explains it.
- **A latent name divergence.** With an IR whose title is `None` and a payload
  `default_macro_name` of `"Figure8"`, the window proposes `"Figure"` from
  `FigureIR.default_macro_name()`'s `or "Figure"` fallback while the kernel called
  it `"Figure8"`. Unreachable in production: a bare `plt.figure()` gets its
  canonical name into both `figure.get_label()` and the IR title.
- **A stale payload with an empty `request_msg_id`** can satisfy a later copy.
  Needs a degraded or foreign kernel; a healthy Hyde kernel always names the
  request. Already recorded in `KERNEL_REQUEST_OWNER.md`.
- **`session_source_has_statements` catches only `SyntaxError`**, so a
  `session.py` with a UTF-8 BOM fails in the kernel instead. That is the intended
  "the kernel's error is more use than silence" behaviour.
- **`test_user_interface_package_exports_only_current_ir_contract` asserts
  `__all__` membership**, which is structural — but it is the sanctioned
  architecture-contract exception, and it is load-bearing: it is why the
  `HydeIR`/`HydeIRDiff` imports in `hyde/user_interface/__init__.py` are
  deliberate re-exports rather than unused imports.
- **Warnings now print twice on the console**, once through the logger and once
  bare, because labscript-utils' `logwarning` logs and then calls the original
  `showwarning`. BLACS behaves identically; this is the cost of the suite
  pattern, not a Hyde defect.

## Slice 8: Generate `plt.figure(name, clear=True)`

### Type

`AFK`

### What to build

A rebuild-in-place already works, through matplotlib's own `clear` kwarg. What
is wrong is only what Hyde writes and what it says.

Measured against the current tree, with no code change:

- `fig = plt.figure("G", clear=True)` inside a macro, run twice: same figure
  object, one axes, data replaced (`[1,4,9]` → `[5,6,7]`), IR carrying one
  subplot and one trace, `save_error` `None`. No exception.
- A neighbour reached with plain `plt.figure("N0")` is **not** cleared: it kept
  its own line plus the one the second macro drew, and that macro still built its
  own distinct figure.

So the two intents are already separable with no Hyde-specific divergence:
`plt.figure(name, clear=True)` means *replace this figure*, plain
`plt.figure(name)` means *reach this figure as it stands*. Both are plain
matplotlib. `FigureHyde.clear()` resets `_hyde_ir` and `_hyde_command_log` and
registers the figure with the build session, which is why the rebuild satisfies
the create-exactly-one-figure guard without touching the guard.

The maintainer's decision: **macros overwrite.** So:

1. **The generator should emit one line, not two.**
   `hyde/features/matplotlib_figure_state.py` currently emits
   `fig = plt.figure(...)` and then appends `fig.clear()` as a separate
   statement. Emit `clear=True` in the call instead. Generated source is what a
   user reads and copies, so it should teach matplotlib's own idiom rather than
   a two-line Hyde habit.

   Watch the no-title case: with no figure args the generator emits
   `plt.figure()`, which creates a *new* figure every call, so `clear=True`
   there is harmless but meaningless. Decide whether to emit it anyway for
   uniformity or omit it when there is no name, and say which.

2. **The error message should name `clear=True`.**
   `@hyde.figure functions must create exactly one figure. plt.figure(name)
   hands back the figure that already exists rather than creating one, so call
   fig.clear() to replace its contents, the way a saved Hyde figure macro does.`
   Point it at `plt.figure(name, clear=True)`, which is both shorter and what
   the generator will then emit. `fig.clear()` still works and should keep
   working — this is about which one Hyde recommends.

3. **Check the spec and any documented example** for the two-line idiom and
   resync, since `project_management/specs/` describes generated figure source.

### Acceptance criteria

- [ ] Generated macro source calls `plt.figure(..., clear=True)` and contains no
      separate `fig.clear()` line.
- [ ] Re-running a generated macro replaces the figure's contents, verified by
      execution on the emitted source rather than on a hand-written equivalent.
- [ ] A macro written the old way, with an explicit `fig.clear()`, still works.
- [ ] Neighbour drawing through plain `plt.figure(name)` is unchanged, and
      `test_a_macro_may_draw_on_another_figure_while_building_its_own` passes
      untouched.
- [ ] The guard's message recommends `clear=True`.

### Blocked by

None - can start immediately. Independent of Slice 1, which touches teardown.
