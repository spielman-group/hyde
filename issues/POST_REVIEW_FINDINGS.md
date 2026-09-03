# Post-Review Findings

Source: findings the branch-review agents reported as out of scope while
implementing `BRANCH_REVIEW_ISSUES.md`, unified here. Each was re-verified
against the current tree before filing; the evidence is inline. Nothing in this
file was filed on an agent's word alone.

`BRANCH_REVIEW_ISSUES.md` is closed (19/19). This is the follow-on backlog.

## Progress Checklist

- [x] Slice 1: `force_close` Does Not Close
- [x] Slice 2: Dead And Unreachable Code In The Figure Backend
- [x] Slice 3: Two Half-Finished Shutdown Paths
- [x] Slice 4: `group_order`, The Other Drifted Contribution Key
- [ ] Slice 13: The Last Unquittable Path, And The Eighth Sender
- [x] Slice 5: Test Hygiene, Round Three
- [x] Slice 6: Stale Documentation Left By The Review
- [x] Slice 7: The Pre-Commit Hook Runs The Wrong Interpreter
- [x] Slice 8: Generate `plt.figure(name, clear=True)`
- [x] Slice 9: Retire The `figure_command` Feature
- [x] Slice 12: A Kernel Signal That Cannot Be Delivered Says Nothing
- [x] Slice 10: The Project Lane Still Clears Messages It Did Not Post
- [x] Slice 11: Hyde Can Become Unquittable

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

- [x] `force_close()` leaves the window closed, shown by execution.
- [x] `FigureWorkspaceService.clear()` leaves no open figure window behind.
- [x] A test fails if `force_close()` stops closing, asserting on
      `mdi_area.subWindowList()` and on no command being issued for the next
      namespace view — not on `workspace.figures`.
- [x] A kernel project switch closes the figure comms rather than stranding
      them.
- [x] The kernel-initiated close path still works: a window closed by the kernel
      does not re-notify the kernel.

### Landed

All three places, as filed.

`force_close` no longer routes through `close_from_kernel`, whose guard returns
on exactly the flag `force_close` sets. It settles every payload lane rather
than `"close"` alone, then closes through `_close_without_kernel_round_trip`,
the tail it now shares with `close_from_kernel` so neither can drift into
promising a close it does not perform. Closing the inner widget alone leaves
the MDI frame behind — measured — so the subwindow is closed in preference to
it.

`FigureWorkspaceService.clear()` retires entries the way `close_figure`
already did, by asking whether the subwindow actually went, instead of
emptying the registry over the top. Measured: `clear()` retires through
`_remove_figure`, not through a blanket wipe. This half is defence in depth
rather than a fix — with `force_close` corrected, no window survives for a
late close to find — so it is guarded by its comment and by `close_figure`'s
existing tests, not by a test of its own; reproducing "a window that refuses
to close" needs a state the first fix removes.

`clear_live_matplotlib_managers()` destroys each manager through
`Gcf.destroy(manager)`, one at a time so a manager that cannot be destroyed
does not keep the rest alive, and still clears `Gcf.figs` afterwards.
Before: `comm messages sent: []`, `_destroyed: [False, False]`. After: the
`close` and `comm_closed` pair per figure, `_destroyed: [True, True]`.

Measured on two IR-bearing windows across `on_project_loaded` and
`on_kernel_crashed`. Before: 2 subwindows, 2 namespace listeners, and two
`hyde.get_figure(...)` + `hyde.refresh_figure(...)` commands on the next
namespace view. After: none of any, and zero save prompts either way, because
`is_close_complete()` routes `closeEvent` to `complete_interactive_close`.

The guards are `test_loading_another_project_closes_the_open_figure_windows`,
`test_kernel_crash_closes_the_open_figure_windows` and
`test_project_switch_closes_the_kernel_side_figure_comms`. The first two fail
against the shipped `force_close` and pass against the shipped
`clear_live_matplotlib_managers`; the third does the reverse.
`test_plugin_discards_pending_batched_payloads_when_workspace_is_cleared` now
asserts on `mdi_area.subWindowList()` instead of `workspace.figures` — that
test never created a window, so it passed either way, and the registry it was
reading is the fingerprint the fix removes rather than anything the test was
about.

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

3. **A whole feature may be unreachable, not just one method.** Slice 8 found
   that `FigureCommandModel._creation_lines`
   (`hyde/features/matplotlib_features.py:502`, reached via
   `MatplotlibCodec.state_to_python` for the `figure_command` feature) emits
   `fig = plt.figure('Name')` with no clear and no `@hyde.figure` wrapper, and
   its `state_to_macro_source` builds an undecorated macro. Slice 8 found no
   production caller: `"figure_command"` appears only as the model's own
   constants, and the new-graph dialog dispatches the FigureIR path instead —
   its preview equals `widget_ir.python_source()`.

   So establish the reachability of the `figure_command` feature as a whole,
   not just the method below. If it is dead, it is a third spelling of
   "recreate this figure" that would drift; if it is live, find what reaches it,
   because its output disagrees with what Slice 8 just standardised.

4. **`MatplotlibCodec.tracked_names` may have no production caller.** Slice 17
   removed what it believed was the last one and deliberately left the method,
   on the grounds that it is one arm of the codec's uniform feature-kind dispatch
   and its remaining test is a legitimate two-implementations-agree contract.
   Confirm that reading: the other `tracked_names` definitions in the same file
   and in `matplotlib_ir.py` are live, so the sweep has to distinguish the
   classes rather than match the name.

### Acceptance criteria

- [x] `draw_idle`/`flush_events` are deleted, or moved to the class that can
      actually receive them, with the reason stated.
- [x] No conditional with identical branches remains in the backend.
- [x] `MatplotlibCodec.tracked_names` is either shown to have a production caller
      or removed with its test.
- [x] Figure creation, refresh, close and copy all still work.

### Landed

**Item 1 was a deletion, not a canvas fix.** Three separate reasons, measured
against matplotlib 3.11.1. `_Backend` carries zero plain functions -- every
member is a `classmethod`, a `staticmethod` or a class attribute, and
`_Backend.__init__ is object.__init__` -- so matplotlib uses the class as a
namespace and never instantiates it. `_Backend.export` copies exactly eight
names onto the backend module and neither `draw_idle` nor `flush_events` is
among them, confirmed live: after `matplotlib.use("module://hyde...")`,
`hasattr(hyde.matplotlib_backend, "draw_idle")` is `False`. And the canvas does
not want them: `FigureCanvasHyde` already answers `draw_idle` through
`FigureCanvasBase.draw_idle`, which routes to `self.draw` and so to Hyde's own
override and `manager._push_draw()` -- measured, one push per call. Moving the
dead body across would have been a regression, because the base version wraps
the draw in the `_is_idle_drawing` re-entrancy guard that the dead one lacked;
and `FigureCanvasBase.flush_events` is already a documented no-op returning
`None`, which is what the dead body did. `flush_events` has no production
caller at all.

`canvas.draw_idle()` does, though -- five of them in the backend
(`remove_traces_from_figure`, `abandon_figure_build_session`,
`regenerate_figure_from_ir` twice, `apply_figure_action`) and both source
generators emit `fig.canvas.draw_idle()` into the Python they produce -- and
nothing pinned that it reaches the window. That is why a
`draw_idle` on a class that cannot receive it read as harmless. The guard is
`test_an_idle_redraw_request_pushes_the_figure_to_its_window`; give
`FigureCanvasHyde` a `draw_idle` that calls `FigureCanvasBase.draw` directly
and it fails on `_push_draw` called 0 times.

**Item 2: `"111"` is not a default, it is the only admissible value.** The
equal branches were not masking a multi-argument spelling. `subplot_code` is
validated against exactly `"111"` in two places -- `FigureIRAuthority`
(`matplotlib_figure_state.py:195`) and `FigureCommandModel`
(`matplotlib_features.py:479`) both raise on anything else -- and
`regenerate_figure_from_ir` replays the subplot as
`figure.add_subplot(int(subplot["subplot_code"]))`, which no `"2, 1, 1"`
survives. So emitting the matplotlib-correct multi-arg code would have made
the next `figure_snapshot_payload` raise rather than fix anything. What the
collapse leaves standing is a real defect, recorded in the comment: a tracked
`fig.add_subplot(2, 1, 1)` records a layout the figure does not have. The fix
for that is a multi-subplot IR, not a different string at that line, and the
import path already warns that extra axes are dropped. An AST sweep confirms
zero identical-branch conditionals -- ternary or `if`/`else` -- remain anywhere
under `hyde/`, not just at the named line.

**Items 3 and 4, measured together.** Both are reachability questions, so both
were answered by running the whole 657-test suite in one process with
`FigureCommandModel`'s classmethods, `MatplotlibCodec._feature_kind`,
`MatplotlibCodec.tracked_names` and `figure_ir_from_live_state` wrapped in
recorders that log the nearest calling frame inside the repo. Every single hit
came from a `tests/` frame. Not one production frame reached any of them.

Slice 17's reading of `MatplotlibCodec.tracked_names` is **refuted twice**. It
has no production caller: across 657 tests it was called exactly once, from
`test_lowering_and_tracked_names_match_across_the_process_boundary`. And the
"two implementations agree" contract does not exist -- the codec method's whole
body is `return model.tracked_names(...)`, so the assertion compared
`FigureIRAuthority.tracked_names` with a two-line forward to itself and could
not fail unless the forward were edited. Nor was it an arm of a uniform
dispatch: `tracked_names` is not on `FeatureCodec`, no other codec has it, and
only two of the four matplotlib models implemented it, so the "uniform" arm
raised `AttributeError` for the patch and export kinds. Deleted, with the
`tracked_names` half of its test; the `state_to_python` half stays, because
that forward *is* production-live (`figure_snapshot_payload`), and the test is
renamed `test_lowering_matches_across_the_process_boundary` to say what it now
covers.

**The `figure_command` feature is production-dead as a whole**, confirming
Slice 8. `"figure_command"` is named nowhere outside `matplotlib_features.py`'s
own constants, five test files and this backlog -- not in a spec, a template, a
session TOML or any other data file. The 13 production `MatplotlibCodec` call
sites all pass figure IR, explicitly or through `_hyde_ir`, which is
`FigureIRAuthority.default_state()`. Every `_feature_kind` fall-through to
`figure_command` in the suite came from `figure_ir_from_live_state`, which is
itself production-dead: a fixture builder living in a production module, called
only by tests. `FigureCommandModel.state_to_macro_source` was never called by
*anything*, test included.

That last one was the drift hazard item 3 named -- an undecorated macro, a
third spelling of "recreate this figure" -- so it is deleted, and
`FigureCommandModel.tracked_names` with it, since it existed only to name that
macro's parameters. `MatplotlibCodec.state_to_macro_source` now raises
`NotImplementedError` for the kind, which is the honest answer.

Removing the rest of `FigureCommandModel` was **deliberately not done here**.
The model is still the codec's fallback normalizer -- `_feature_kind` returns
`figure_command` for any unrecognised state, which
`test_matplotlib_codec_rejects_the_ambiguous_figure_feature_name` pins on
purpose -- so removing it is a redesign of that fallback plus a rehoming of
`figure_ir_from_live_state` and its roughly sixty fixture uses across five test
files. That is a slice, not a deletion; filed as Slice 9.

Beyond the suite, one figure was driven end to end through the real backend:
built by a `@hyde.figure` macro, snapshotted, refreshed against a changed
namespace, regenerated straight from its IR, copied to the clipboard in two
formats, and closed. 33 checks, all passing -- IR one subplot with
`subplot_code` `"111"`, command log `add_subplot` then `plot`, `save_error`
`None`, `call_source` and the recreation source both asking
`plt.figure('DelayGraph', clear=True)`, y data going `[1, 4, 9]` to
`[5, 6, 7]` on refresh, a `COPY_TO_CLIPBOARD_REQUEST` carrying rendered PDF and
PNG bytes, and the figure gone from `Gcf` and from `_iter_windowed_figures()`
after the close.

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

- [x] One answer to "has this widget shut down", used by
      `allows_subwindow_close()`.
- [x] A message posted by something else survives an announced request
      completing.
- [x] The status bar is still cleared when the request that posted it settles.

### Blocked by

None - can start immediately.

### Landed

**Item 1: `allows_subwindow_close()` was returning the wrong answer, and the
other half of the base's shutdown promise never fired either.** Measured on the
shipped code, against a `HydeToolWidget` that overrides nothing as the control:

```
PlainTool        allows_close after shutdown=True  own filter swallows close=False
PythonVariables  allows_close after shutdown=False own filter swallows close=True
```

So a shut-down variables tool insisted on persisting: `close_policy()` is
`"hide"`, `_shutdown_requested` was never set, and because `super().shutdown()`
was never called the `PersistentToolWindowFilter` was never removed either.
Both of the base's escape hatches were shut. `_closed` gated the refresh paths,
which is why nothing had noticed.

**`_closed` is gone; the base's flag is the one answer,** reached through a new
`HydeToolWidget.has_shut_down()`. Keeping `_closed` and calling `super()` would
have left the two flags in place, which the slice ruled out; the base's flag is
the one `allows_subwindow_close` reads and the one the base sets, so the
subclass reads it rather than shadowing it. `refresh_namespace` and
`_on_namespace_view` now ask `has_shut_down()` too, so the widget answers "am I
done" exactly once. `HydeToolWidget.shutdown()` is now idempotent, which it had
to become: `allows_subwindow_close` calls it on every close event once the
application is going down, and it was handing the mounted child a fresh
shutdown each time.

The symptom is latent rather than live in this tree, and that is worth writing
down: the one production path that shuts a tool widget down without quitting is
`on_kernel_crashed` -> `destroy_mdi_widget`, and `HydeMDIContext.destroy`
removes the subwindow *before* it calls `shutdown()`, so no close event reaches
the widget while it is in the wrong state. It is a wrong answer waiting for a
caller, not a bug the user can currently reach.
`tests/test_python_variables_final.py::TestPythonVariablesWindowClose` pins the
observable through the real plugin, a real `QMdiSubWindow` and both close
filters: it fails on the shipped code with `subwindow.close()` returning False.

`figure_interactive` and `table_interactive` keep their own `_closed`. Those are
`HydeInteractiveWidget`s with a separate two-phase close (`is_close_complete`,
kernel confirmation) and no `_shutdown_requested` of their own, so there is no
second answer to unify there.

**Item 2: a message now carries who posted it.** `show_kernel_progress` returns
the message it posted rather than a bool, the request keeps it as
`_progress_message`, and `settle()` hands it back to
`clear_kernel_progress(message)`. The decision itself is in `HydeApp`, which
owns the status bar: it clears only if `statusbar.currentMessage()` still equals
the label handed in. That reads the surface rather than a private ledger, so it
also covers writers that never went through `StatusMessageService` -- the
shell's own project-operation messages included. `StatusMessageService` and
`HydeApp.clear_status_message` both take the label now, which is the honest
consequence: the only way to clear the bar is to name what you are retracting.

Outcomes and failures were checked in both directions, since the whole risk of
this change is on that side. Every consumer already settles before it speaks --
`_fail_copy` and the success path both call `_end_copy()` and then
`_outcome_message(...)`, and `KernelPayloadRequest.fail` settles before
`report_kernel_failure` -- so the clear happens first and the message that
replaces it is never touched. Measured end to end over a real `QStatusBar`:

```
in flight, bar shows        : 'Copying figure as Vector...'
another surface reports     : 'Refreshing figure Figure1 failed: the kernel is gone'
copy settles, bar still     : 'Refreshing figure Figure1 failed: the kernel is gone'

in flight, bar shows        : 'Closing figure 7 in the kernel...'
settled, bar shows          : ''

kernel refused it, bar shows: 'Copying figure as Vector failed: MemoryError: too big'
```

`TestKernelProgressOwnsItsOwnStatusMessage` in `tests/test_hyde_tool_widget.py`
holds all four of those, driving the real `StatusMessageService` over a real
`QStatusBar` and ending requests through `settle` rather than by calling the
clear helper. Only the "survives" one fails on the old unconditional clear; the
other three are there to catch a fix that eats outcomes.

Suite: 663 tests, OK (658 before).

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

- [x] Either the framework understands explicit group ordering, or Hyde no longer
      needs `group_order`, or the override is documented as permanent with the
      reason.
- [x] Hyde's menu order is unchanged for the user, whichever route is taken.
- [x] If `resolve_menu_enabled` can now be deleted and delegated, that happens
      here.

### Blocked by

- Slice 12 of `BRANCH_REVIEW_ISSUES.md`, which is done.

### Landed

**No framework change. `group_order` was inert.** Every value Hyde gave the key
reproduced the order sorted group names already produce: rendering the real
plugin set through the base `MenuContext` differs from Hyde's rendering in
exactly two menus, File and Windows -- and neither of those declared
`group_order` at all. The Figure menu, the only place the key carried a
non-default value, comes out the same either way. So extending the shared
contract would have bought a key with no remaining use.

**What the key was actually holding up was a Hyde-local bug.** It arrived in
`f124378`, the commit that made submenus interleave with actions, and that is
all it ever did. `_submenu_sort_key` gives a submenu the position of its first
entry, but resolved that entry's group against the *submenu's own* path. A
submenu is usually the only thing in its own first group, so its key came out as
group zero and it sorted to the top of whatever the parent's first group is.
Setting `group_order` to the same literal on both paths forced the two indices
to agree. Dropping the key without fixing the lookup moves Copy As from beside
Copy up among the figure controls -- measured. The lookup now resolves against
the parent path, which is the menu the submenu is being placed in, and a group
the parent has no entry in sorts last rather than first.

**Group names are internal keys, so they can carry the ordinal.** They are never
displayed -- a group only decides ordering and where `addSeparator()` goes --
and never persisted; the `tool_windows` in `session.toml` is an unrelated TOML
section. Hyde's groups are now `10_project`, `20_save`, `30_application` and so
on, and `HydeMenuContext.render` orders groups by name, which is the framework's
rule and its stated reason.

**That fixed a live defect.** Hyde's fallback ordered groups by first
contribution, and contributions arrive in `os.listdir()` order over the plugins
directory. `file` and `kernel_runtime` both contribute to the `application`
group, so which of them was listed first decided where it sat: with the listing
reversed, the shipped code puts **Quit and Kill Kernel at the top of the File
menu** and scrambles the Windows menu. After the change the rendered menus are
identical under both listings.

**The override stays, and now says why.** `enabled` and `group_order` were not
the only blockers; they were not even the main ones. `HydeMenuContext.render`
exists for four things the base renderer has no notion of, all load-bearing:
rendered actions are retained for `lookup_action`; the computed grouping is
retained rather than consumed, which is how `build_popup_menu` renders the same
contributions again into the figure and table right-click menus; `aboutToShow`
is wired to `refresh_enabled_states`; and submenus interleave with actions. Its
docstring records this.

`resolve_menu_enabled` cannot be delegated either, and its docstring now says
why: the framework resolves `enabled` inline in `render()` and reports a raising
precondition through the context's logger, which in Hyde is
`VisibleFailureLogger` -- so a persistently broken precondition would put an
error dialog in front of the user on every menu open, and this runs on every
`aboutToShow` and every subwindow activation.

Before and after, the full rendered structure of all six menus -- every group,
item, separator, shortcut and enabled state -- is byte-identical. The only
change in the dump is the diagnostic group table, whose names gained their
ordinals.

Three tests in `tests/test_plugin_tools.py`: groups order by name and not by
arrival, the Windows menu renders the same under a reversed plugin order, and a
submenu sits in the group its first entry names. All three fail against the
behaviour they replace. `test_kernel_runtime.py` no longer pins the whole
contribution dict -- it reads the group Quit is in off the file plugin, so the
requirement it states is that the two agree rather than how they spell it.

Judgement call: renaming the `file` and `window` groups was not strictly needed
to drop the key, since those never carried it. It is here because leaving them
would have left the File menu's layout a function of the machine, which fails
the "unchanged for the user" criterion in every sense but the local one.

Suite: 680 tests, OK (677 before; three added).

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

- [x] No test's name claims a subject the test does not exercise.
- [x] The duplicate pgf assertion exists once.
- [x] No unused import remains in the touched test modules.
- [x] The suite's coverage of copy feedback is unchanged in substance.

### Blocked by

None - can start immediately. Item 1 touches
`tests/test_save_graphics_dialog.py`, so sequence it against any other slice
editing that file.

### Landed

All four filed items, plus the two later slices added.

**Item 1: the cursor test now completes a copy, and says so.** It takes
`copy_payload` like every other completed copy in the module, and asserts
`Copied figure to the clipboard as Vector.` before it reads the cursor. That
assertion is the subject: feeding the flat legacy shape back in fails on it with
`['Copying figure as Vector...', None, 'Could not copy the figure to the
clipboard.']`, which is the failed copy the test used to be quietly making.
`test_a_failed_render_does_not_confirm_success` keeps the flat shape, where it is
the point, and the cursor after a *failed* copy stays covered by
`test_a_rendered_copy_whose_data_never_arrives_reports_failure`,
`test_a_render_that_raises_reports_what_the_kernel_said`,
`test_a_copy_fails_when_the_kernel_goes_away` and
`test_a_reply_naming_an_unpasteable_format_settles_the_request`.

**Item 2: the pgf duplicate is one test.** `TestCopyPgfAsText` now holds
`test_a_pgf_copy_offers_no_image_to_qt_or_the_platform`, which makes both
observations the two tests made separately -- no image MIME type, which is what
another Qt application reads, and `hasImage()` false, which is what the platform
pasteboard reads. Nothing was dropped; the copy in
`TestClipboardPayloadRepresentations` is gone, with a comment where it was
pointing at its replacement, because its positive counterpart
(`test_a_copy_carries_an_image_the_platform_can_republish`) lives there.

**Item 3: four unused imports, not one.** `FigureIR` in
`tests/test_remove_from_graph_dialog.py`, and two local `import base64`
statements in `tests/test_save_graphics_dialog.py` that no longer had a caller.
Consolidating the host stub retired `HydeAppIR` from five more modules.

**Item 4: consolidated, because the duplication was six copies of a real
interface rather than a fixture with options.** `make_plugin_host` was defined
in six test modules -- four byte-identical, `test_curve_fit`'s differing in two
lines and `test_plugin_tools`'s in three. Every attribute it sets names an
actual `HydeApp` method, all thirty checked against the class, so it is a fake
of a contract and not a per-test shape. The copies had already drifted:
`get_procedures_init` existed in one of the six, so a plugin asking its host for
procedures worked in one module's tests and not another's.

`tests/plugin_host_fakes.py` holds it once, with **one** keyword --
`menu_class`, for the recording menus `test_plugin_tools` needs -- and five of
the six callers pass nothing. The two divergences are now one visible line each
in the module that wants them, rather than a buried edit in a 53-line copy:
`test_plugin_tools` wraps it to pass `menu_class=RecordingMenu`, and
`test_curve_fit` wraps it to rebind `emit_plugin_event` to the real bus.
`get_current_app_ir` reads `app.get_current_project_dir()` in the shared body,
which is what `test_curve_fit` had diverged to do and is identical for the rest
because they all leave that accessor returning `None`.

Within `tests/test_save_graphics_dialog.py`, `TestEditMenuCopy._host_with_figure`
and `TestCopyAsSubmenu._host` were the same seventeen lines twice; they are now
`make_copy_host(figure_context, kernel)`, which returns the host and the copy
plugin instead of assigning it onto the test case.

Net: 396 lines out of the test modules, 71 back in, 87 in the shared module.

**Item 5: the `_quit_command_sent` pin is gone, and the overlap was measured
rather than assumed.** Removing `self._quit_command_sent = False` from
`HydeApp.on_kernel_crashed` fails
`test_the_close_button_still_closes_after_the_kernel_crashed` --
`[('hyde.quit()', True)] != [('hyde.quit()', True), ('hyde.quit()', True)]`, the
close button refusing to answer -- alongside the pin, so the behavioural test
covers the same ground and says why it matters.
`test_on_kernel_crashed_resets_shell_state_without_runtime_restart` keeps
everything else it was asserting (the project dropped, the operation ended, the
crash event, the warning, no restart) and now names where the quit half lives.

**Item 6: two more leftovers, both in files already open.**
`test_begin_shutdown_from_close_event_emits_shutdown_events_once` no longer
asserts `_runtime_shutdown`; the assertion below it -- two calls, one set of
events -- is what the guard is for, and Slice 11's
`test_a_quit_that_landed_shuts_hyde_down_once` holds the same rule through a
real close event. `ProjectLaneApp.__init__` no longer sets
`_quit_command_sent`: Slice 10 needed it to drive
`on_visible_command_executed`, which Slice 11 deleted, and nothing that class
exercises reads it.

Left alone: `table._closed` in `tests/test_table_features.py`, which Slice 3
explicitly kept -- `table_interactive` has its own two-phase close and no
`_shutdown_requested` to unify with -- and `browser._shutdown_requested = False`
in `tests/test_python_variables_final.py`, which is a fixture set on a stub, not
an assertion.

Suite: 673 tests, OK (674 before). The one test is the pgf duplicate, folded
into its twin.

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

- [x] No tracked document points at a file or attribute that no longer exists
      without saying so.
- [x] `IR-CONTROL.md`'s counts match the code, or say what they count.
- [x] Completed slices' decisions are not rewritten, only annotated.

### Blocked by

None - can start immediately.

### Landed

**Item 2 first, because it decides the other two.** What the sentence counts is
`FigureIR` fields that only the two export-shaped commands read, and there are
**five**: `output_path`, `output_formats`, `dpi`, `transparent` and
`size_inches`. Established by reading `validate()` and `_python_source()` --
outside `__post_init__` normalization and `debug_state`, which touch every field
regardless of command, each of those five is read only under the
`save_graphics` or `copy_graphics` arm. `figure_name` is shared with `refresh`,
`figure_number` belongs to `close`, and `creation_x_name`/`use_bound_values`
belong to `create`/`refresh`, so none of them counts. The sentence now names the
five and gives the denominator (fourteen fields, six commands), so the next
reader can re-check it instead of decrementing it again.

Its forward reference is fixed the same way. "An eighth conditional field and a
sixth pair of branches" was two counts, one wrong and one unverifiable:
`validate()` branches on four commands and `_python_source()` on six, so there
is no count of "pairs" to increment. It now reads "a sixth export-only field and
another pair of branches" -- the field count is checkable, and the branch claim
is the design point it was always making.

`IR-CONTROL.md` is rewritten rather than annotated, deliberately: it is a
present-tense control document, and its own Revision Rule says Hyde does not
keep superseded guidance as a parallel truth.

**Items 1 and 3, annotated not rewritten.** Three forward notes in
`BRANCH_REVIEW_ISSUES.md`, in the style that file already established at Slice
17:

- Slice 6's rationale, which placed the clipboard beside "the `clipboard.py` and
  `copy_request.py` that are already there". The note says Slice 7 deleted the
  module with `FigureCopyRequest`, and confirms the destination it settled did
  land -- `clipboard.py` and `clipboard_platform.py` are both under
  `save_graphics_dialog/` now.
- Slice 2, where `_hyde_source_artifact` and `_hyde_ast_artifact` appear in the
  prose and in an acceptance criterion that is still unticked. The note says
  Slice 13 item 2 removed both, and that `_hyde_bound_values` and
  `_hyde_defaults` still exist, so the rule that criterion states still has
  subjects.
- Slice 3, found by the sweep rather than filed: item 9 names
  `copy_request.py:45` for the same deleted module, and items 3, 4 and 5 name
  `clipboard_formats`.

**The sweep.** All thirteen candidate names, plus the moved clipboard symbols
(`clipboard_platform`, `GRAPHICS_CLIPBOARD_MIME_TYPES`,
`GRAPHICS_CLIPBOARD_REPRESENTATIONS`) and `FigureCopyRequest`, searched across
every tracked `.md` under `project_management/` and `issues/` with `git grep`,
which sees tracked files whatever `.gitignore` says. Nothing under any
`_source/` was read, quoted or referenced.

Two hits looked stale and are not:

- `specs/IPC_PROTOCOL.md:233` documents `output_format` inside a clipboard
  payload's `representations` list. That is the live wire key, still built at
  `hyde/execution/ipc.py:69` and read at
  `save_graphics_dialog/__init__.py:208`; the field Slice 8 removed was
  `FigureIR.output_format`, a different thing with the same name.
- `REFACTOR_STATUS.md:172` calls `MatplotlibCodec.state_to_macro_source` "the
  surviving public surface". It survives, at
  `hyde/features/matplotlib_features.py:595`. Only
  `FigureCommandModel.state_to_macro_source` is gone, and Slice 17's existing
  forward note already says so.

Left alone as already self-saying: every remaining hit sits in a record whose
own subject is the removal -- `apply_figure_state` and `_hyde_building` under
Slice 13, `current_ir` under Slice 10 ("Retire `current_ir`", with a ticked
"`current_ir` is gone"), `_closed` and the project status-message pair under
this file's Slices 1, 10 and 11, and the removed-symbol names in test-cleanup
records that exist to say they went.

Also swept, and clean: every `.py` path named in a present-tense document
(`project_management/**`, `AGENTS.md`, `README.md`) resolves in the tree today,
and none of those documents names a symbol this branch removed. `widget_ir`
appears throughout them and is current -- it is Slice 10's replacement for
`current_ir`.

Suite: 673 tests, OK. Documentation only; no test added, and none needed --
a test that grepped documents for symbol names would be the structural
assertion this project excludes.

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

- [x] The hook checks the table against the same matplotlib Hyde imports.
- [x] It does not hard-code a single machine's interpreter path.
- [x] A stale table still fails the hook, shown by regenerating against a
      deliberately different format list.

### Blocked by

None - can start immediately.

### Landed

The hook resolves the `labscript` conda environment **by name**, beside the conda
installation the `python` on PATH already belongs to:

```
conda_root=$(python -c '... sys.prefix, minus a trailing envs/<name> ...')
interpreter=$conda_root/envs/labscript/bin/python
```

Why that and not the alternatives. The environment's *name* is already this
repo's documented convention (`AGENTS.md`: "Run Hyde tests in the `labscript`
conda environment"), so naming it in a tracked file adds no new fact and no
machine-specific one; the only per-machine part, where conda itself is
installed, is derived at run time. `conda run -n labscript` was rejected because
it is not reliable here and costs seconds on every commit; an environment
variable alone was rejected because its default would still have to be *some*
interpreter, and a default of bare `python` is the defect being fixed. So
`HYDE_PYTHON` exists as the override for a differently named environment or a
non-conda install, not as the mechanism.

When neither resolves, the hook fails with `set HYDE_PYTHON to it and commit
again` rather than falling back to `python`. That is deliberate: a fallback to
the wrong interpreter is exactly the silent staleness the hook exists to
prevent, so it fails closed and says what to do.

Also in passing: the hook now takes its paths from `git rev-parse
--show-toplevel` instead of assuming the caller's working directory, so running
it by hand from a subdirectory checks the same table git does.

Demonstrated in both directions. Regenerating against a deliberately different
format list (`avif` and `webp` dropped, `bmp` invented) makes both the direct
run and a real `git commit` refuse:

```
STALE: matplotlib_graphics_formats.py does not match matplotlib 3.11.1. Run
scripts/regenerate_graphics_formats.py
```

`scripts/regenerate_graphics_formats.py` restores the table -- `git diff` on it
empty again -- and the hook reports `up to date against matplotlib 3.11.1` and
exits 0. `sh -x` confirms the interpreter it picks is
`.../envs/labscript/bin/python` and not the base-environment `python` first on
PATH. `HYDE_PYTHON` pointing at a nonexistent path, and a `PATH` with no conda
python on it, both produce the loud failure rather than a wrong answer.

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

- [x] Generated macro source calls `plt.figure(..., clear=True)` and contains no
      separate `fig.clear()` line.
- [x] Re-running a generated macro replaces the figure's contents, verified by
      execution on the emitted source rather than on a hand-written equivalent.
- [x] A macro written the old way, with an explicit `fig.clear()`, still works.
- [x] Neighbour drawing through plain `plt.figure(name)` is unchanged, and
      `test_a_macro_may_draw_on_another_figure_while_building_its_own` passes
      untouched.
- [x] The guard's message recommends `clear=True`.

### Landed

Nothing about the mechanism moved. `FigureIRAuthority.state_to_python` appends
`clear=True` to the `plt.figure(...)` arguments instead of appending a second
`fig.clear()` statement, and the guard's refusal names
`plt.figure(name, clear=True)`.

**The no-title case: omitted.** With no figure arguments the generator emits
`plt.figure()`, which constructs a new figure on every call, so there is never
a previous one to replace. matplotlib's `clear` means "if the figure already
exists, clear it", and a figure identified by nothing cannot already exist, so
the kwarg would be inert noise in source a user reads and copies. This is not a
behaviour change either: `FigureHyde.clear()` on a figure `__init__` has just
built resets an IR that is already empty and re-registers a figure the session
already holds — `register_figure` is identity-guarded. First-class figures
always carry a name (`set_label` refuses an empty one), so they always get
`clear=True`; the bare `plt.figure()` shape belongs to untitled IR previews.

Confirmed rather than assumed, against the installed matplotlib 3.11.1:
`pyplot.figure` ends with `if clear: manager.canvas.figure.clear()`, so
`clear=True` reaches `FigureHyde.clear()` — the same path an explicit
`fig.clear()` takes, which is why the create-exactly-one-figure guard did not
have to change.

Measured by executing Hyde's own emitted source, generated from a figure built
at the prompt and run twice. Before, the emitted body opened
`fig = plt.figure('Graph0')` / `fig.clear()`; after, `fig = plt.figure('Graph0',
clear=True)` and no `fig.clear()` line. Both revisions rebuild identically: same
figure object across the two runs, one axes, `[1.0, 4.0, 9.0]` replaced by
`[5.0, 6.0, 7.0]`, IR carrying one subplot and one trace, `save_error` `None`.
No `Unknown live subplot id`. The neighbour case is untouched: `N0` reached with
plain `plt.figure("N0")` keeps its own line plus the one `N1` drew, and `N1`
still builds its own distinct figure.

The guards are
`test_a_saved_recreation_macro_asks_plt_figure_to_clear`, which takes the source
from Hyde, pins the one-line call, and executes it twice, and
`test_the_guard_names_a_spelling_that_rebuilds_the_figure`, which runs a macro
spelled the way the refusal recommends and then reads the refusal. Each fails
against its shipped half — the first on the two-line emission, the second on the
old message — and the rebuild half of the second passes either way, because
`clear=True` always worked. `test_a_re_run_updates_the_figure_it_rebuilds` still
covers the old explicit `fig.clear()` spelling, untouched.

Twelve assertions on emitted source in `test_matplotlib_features.py` and
`test_figure_window_session_save.py` gained `clear=True`. Two that read like
they belong to this generator do not, and were left alone: the `figure_command`
codec's create source (`MatplotlibCodec.state_to_python` for that feature) and
`figure_call_source`, which describes a figure Hyde owns no IR for and cannot
save as a macro.

`specs/figure_window/SPEC.md` now shows the emitted call and states the two
meanings side by side: `plt.figure(name, clear=True)` replaces a figure,
plain `plt.figure(name)` reaches one as it stands.

### Blocked by

None - can start immediately. Independent of Slice 1, which touches teardown.

## Slice 9: Retire The `figure_command` Feature

### Type

`AFK`

### What to build

Slice 2 established, by running the whole 657-test suite in one process with
recorders on `FigureCommandModel`'s classmethods,
`MatplotlibCodec._feature_kind`, `MatplotlibCodec.tracked_names` and
`figure_ir_from_live_state`, that **every** entry into the `figure_command`
feature comes from a `tests/` frame. Not one production frame reaches it. The
sweep covered the whole tree, not just `.py`, with explicit paths for the
gitignored material: `"figure_command"` is named nowhere outside
`hyde/features/matplotlib_features.py`'s own constants, five test files and
this backlog -- no spec, template, session TOML or other data file.

Slice 2 removed the two members with zero callers anywhere,
`FigureCommandModel.state_to_macro_source` and the
`FigureCommandModel.tracked_names` that only fed it. What remains is dead in
production but load-bearing for tests, so retiring it is a refactor rather than
a deletion:

1. **`FigureCommandModel` is still the codec's fallback normalizer.**
   `MatplotlibCodec._feature_kind` returns `figure_command` for any state it
   cannot otherwise classify, and
   `test_matplotlib_codec_rejects_the_ambiguous_figure_feature_name` pins that
   on purpose -- its comment says an unrecognised kind must fall through rather
   than be rejected, so that a plausible-looking `"figure"` is caught. Deciding
   what the fallback should be instead is the design question this slice has to
   answer. `figure_ir` is the obvious candidate; raising is the other.

2. **`figure_ir_from_live_state` (`matplotlib_features.py:715`) is a test
   fixture living in a production module.** It takes a `figure_command` state
   and returns a figure IR, and all of its callers are tests -- roughly sixty
   uses across `test_matplotlib_features.py`, `test_figure_comm_actions.py`,
   `test_axis_edit_dialog.py`, `test_trace_edit_dialog.py` and
   `test_remove_from_graph_dialog.py`. Those fixtures want a terse way to say
   "a figure IR with these traces", not a `figure_command` state; rehoming that
   shorthand into the tests is most of the work.

3. **`FigureCommandModel._creation_lines` still emits the drifted spelling.**
   `fig = plt.figure('Name')` with no clear and no `@hyde.figure` wrapper,
   asserted by `test_matplotlib_figure_lowerers_emit_only_matplotlib_python`,
   which Slice 8 deliberately left alone. Once the feature goes, so does that
   arm of the test.

4. **`MatplotlibCodec.state_to_macro_source` has no production caller either**
   -- checked while confirming item 4 -- and after Slice 2 its only remaining
   behaviour for a `figure_command` state is to raise. Its one test
   (`test_graphics_export_macro_source_raises_not_implemented`) exercises the
   export kind. Settle it in the same pass rather than leaving a second dead
   public method behind.

### Acceptance criteria

- [x] The codec has one spelling of "recreate this figure", not two.
- [x] `_feature_kind`'s fallback for an unclassifiable state is a deliberate,
      stated choice, and its guard still fails for the ambiguous `"figure"`.
- [x] No production module holds a function whose only callers are tests.
- [x] Figure creation, refresh, close and copy all still work.

### Blocked by

Slice 2, which is done. Independent of Slices 3-7.

### Landed

`FigureCommandModel` is gone, and with it `_creation_lines` and the drifted
`fig = plt.figure('Name')` it emitted. `matplotlib_features.py` went 1179 ->
984 lines; `matplotlib_ir.py` and `base.py` were not touched, so the codec's
one remaining spelling of "recreate this figure" is `FigureIR`'s, which Slice 8
standardised. The suite is 673 tests, OK, before and after -- the same count,
because nothing was deleted from it.

**The fallback is `figure_ir`, not a raise, and the decision was forced by a
live bug rather than taste.** The one production expression that can reach the
fallback is
`MatplotlibCodec.validate_state(getattr(figure, "_hyde_ir", None))` in
`_import_first_class_figure_ir` (`matplotlib_backend.py:1197`), which is
written to tolerate a figure that has no IR yet and then reads `["layout"]` off
the answer. A `figure_command` state has no `layout`, so importing a live
figure Hyde had not seen before raised `KeyError: 'layout'` -- executed against
the shipped revision on a plain `matplotlib.figure.Figure` with one axes and
one line. It now returns an empty figure IR and the import succeeds. Raising
instead would have turned that defensive `getattr(..., None)` into a hard error
and bought nothing: a patch and a graphics export are both operations *on* an
existing figure and both announce themselves, by name or by the settings
sniffed just above, so what is left when neither matches is a figure. The
fallback names the only remaining candidate rather than guessing among several.

**The ambiguity guard is unchanged in what it asserts and still load-bearing.**
`test_matplotlib_codec_rejects_the_ambiguous_figure_feature_name` still expects
`ValueError` matching `"Ambiguous matplotlib feature"` for
`{"feature": "figure", ...}`. What it protects is not the retired kind: it is
the permissiveness of the fallback itself. `"figure"` names none of the three
surviving kinds and is a prefix of all of them, so without the guard it would
be silently classified rather than corrected. Keeping the fallback permissive
is what keeps the guard necessary; a raising fallback would have made it
redundant and free to rot. The message now recommends the three real names, and
the test's comment says `figure_ir` where it said `figure_command`.

**`figure_ir_from_live_state` is rehomed as `figure_ir_with_traces` in
`tests/figure_ir_fixtures.py` (39 lines), beside `kernel_fakes.py` and
`plugin_host_fakes.py` rather than inside either** -- it is not a fake of a
collaborator, it is a real figure IR. It composes the production builder,
`FigureIR().with_title().with_x_name().with_items()`, so it cannot drift from
the IR production emits; a hand-shaped dict could, and would have taken sixty
tests with it. Byte-equality with the retired function was checked over the
seven argument shapes the call sites use, including no traces and a null
`x_name`, before any call site moved.

It absorbed a seventh near-copy the slice did not know about:
`test_figure_window_session_save.py` had already invented the same fixture
independently, spelled `FigureIR().with_title().with_x_name().with_items()
.normalized_state()` under the misleading name `_live_state_with_title`. That
it converged on the same composition is the strongest evidence the shape is
right.

**`MatplotlibCodec.state_to_macro_source` is deleted rather than rewritten.**
No model this codec dispatches to has the method -- Slice 2 removed the last
one -- so the override could only ever end in its own `hasattr` "not supported"
branch, which is exactly what `FeatureCodec.state_to_macro_source` already
says. `test_graphics_export_macro_source_raises_not_implemented` still passes,
now against the base, and still pins the same contract: the matplotlib codec
does not generate recreation macros.

Every production file shrank and no test file grew:

| file | before | after |
| --- | --- | --- |
| `hyde/features/matplotlib_features.py` | 1179 | 984 |
| `hyde/matplotlib_backend.py` | 1921 | 1920 |
| `tests/test_matplotlib_features.py` | 3140 | 3086 |
| `tests/test_figure_comm_actions.py` | 776 | 767 |
| `tests/test_axis_edit_dialog.py` | 702 | 687 |
| `tests/test_trace_edit_dialog.py` | 616 | 601 |
| `tests/test_remove_from_graph_dialog.py` | 642 | 627 |
| `tests/test_figure_window_session_save.py` | 467 | 457 |
| `tests/figure_ir_fixtures.py` | - | 39 |

Beyond the suite, one figure was driven end to end through the real backend:
built by a `@hyde.figure(register=False)` macro over namespace arrays,
snapshotted, refreshed against a changed `fit_delay`, regenerated from its own
IR, round-tripped through its emitted macro source, copied to the clipboard in
two formats, resized and closed. 52 checks, 0 failures. The refresh picked up
the changed array and left the untouched trace alone; the emitted macro reused
the one window rather than opening a second; the copy handed one
`COPY_TO_CLIPBOARD_REQUEST` to the GUI carrying PDF and PNG bytes; the name
stopped resolving after the close. The last four checks cover the fallback
itself: `validate_state(None)` yields a `figure_ir` state carrying a `layout`,
the ambiguous `"figure"` is still rejected, and the import that used to raise
`KeyError` now succeeds.

## Slice 10: The Project Lane Still Clears Messages It Did Not Post

### Type

`AFK`

### What to build

Slice 3 made the kernel-request lane name what it retracts: a progress message
is cleared only if the status bar still shows that exact label. The **project**
lane was not changed and has the same bug on a far more reachable path.

`HydeApp.clear_project_status_message()` (`hyde/user_interface/main/__init__.py:481`)
still calls `statusbar.clearMessage()` unconditionally, and
`end_project_operation()` (`:484`) is called from three places — including
`on_visible_command_executed` (`:635`):

```python
def on_visible_command_executed(self, msg):
    content = msg.get("content", {})
    if content.get("status") != "ok":
        self._quit_command_sent = False
        self.end_project_operation()
```

So **any** visible terminal command whose status is not `ok` wipes the status
bar. A typo, a `NameError`, any raising expression the user types clears
whatever is showing: a kernel failure they have not read, or a live progress
message from a copy or a figure close still in flight. It fires even when no
project operation was ever begun.

This is a plausible contributor to what the maintainer observed while testing —
status-bar messages disappearing faster than they could be read. The progress
message being replaced by its outcome is correct and expected; this is a second,
unrelated mechanism that eats messages, and it is driven by ordinary terminal
use.

The fix is the shape Slice 3 already put in place for the kernel lane: a caller
names the label it is retracting, and the clear is a no-op if the bar has moved
on. `begin_project_operation(label)` already knows the label it posted, so the
end can name it.

Consider also whether `end_project_operation()` should fire at all from
`on_visible_command_executed`. Its two other call sites are a kernel crash and
the completion of an actual project operation; a failing terminal command is
neither. If the `_quit_command_sent = False` reset is the real purpose of that
branch, the status-bar call may simply not belong there.

### Acceptance criteria

- [x] A failing terminal command does not clear a status message posted by
      something else, shown by execution.
- [x] A real project operation still clears its own message when it ends.
- [x] A kernel crash still clears whatever the project lane posted.
- [x] `_quit_command_sent` is still reset when a visible command fails.
      *(Retired by Slice 11: the quit now retracts its own record, and the
      branch this pinned no longer exists.)*

### Blocked by

- Slice 3, which is done and provides the pattern.

### Landed

Both halves: the lane learned Slice 3's rule, and the status-bar call is gone
from `on_visible_command_executed` because the prior question has an answer.

**The status-bar call does not belong in that branch, on the archaeology.** The
branch was written when the commands it watched were the project lane's own.
`eed9916` introduced it alongside

```python
def _load_startup_project(self, path):
    self.begin_project_operation("Loading Hyde project...")
    self.execute_command(format_load_project_command(path), visible=True)
```

and `22339c0` added the `_quit_command_sent = False` line to the same branch
next to `request_quit` doing `self.execute_command(format_quit_command(),
visible=True)`. A non-`ok` reply on the visible lane genuinely *was* that
operation's or that quit's own failure, and nothing else would have retracted
the progress message. Every one of those dispatches is now hidden --
`execute_hidden` for a save or a load, a correlated request for a project
dialog, whose `ok_dispatch_mode()` is `"hidden"` -- and reports through
`on_project_state_result` or the request's own reply. What still reaches the
visible lane is what the user typed, a table append (`table_interactive`, the
one `ok_dispatch_mode() == "visible"`) and a window macro; none of them posts a
project message, so the call could only ever take down something else's. Making
it conditional would have kept a call that has nothing to name.

`_quit_command_sent = False` stays -- it is the branch's remaining purpose, and
with the quit now hidden it is the only reset a user can reach besides a kernel
crash -- and is pinned in both directions.

**The lane names what it retracts, through the same decision as the kernel
lane.** `begin_project_operation` remembers the label it posted and
`end_project_operation` hands that label to `HydeApp.clear_status_message`, the
method Slice 3 gave the rule to; both lanes post through `show_status_message`
and retract through `clear_status_message`, so "has my message been replaced" is
answered once, by the status bar, and not twice. The label lives on the app
because at most one project operation is in flight and the call sites that end
one -- a state result arriving, a kernel crash -- hold no handle to it, where a
`KernelPayloadRequest` can keep its own. `set_project_status_message` and
`clear_project_status_message` are gone: the first duplicated
`show_status_message` and the second was the unconditional clear, and
`finalize_startup` now begins and ends its connecting message like any other
operation instead of posting one nobody owns.

Measured over a real `QStatusBar`, driving the real entry points:

```
something else posted                    : 'Refreshing figure Figure1 failed: the kernel is gone'
after a typo in the terminal, bar still  : 'Refreshing figure Figure1 failed: the kernel is gone'

save in flight, bar shows                : 'Saving Hyde project...'
after a typo in the terminal, bar still  : 'Saving Hyde project...'

in flight, bar shows                     : 'Creating Hyde project...'
state result arrived, bar shows          : ''

a figure close spoke first               : 'Closing figure Figure1 failed: the kernel is gone'
state result arrived, bar still          : 'Closing figure Figure1 failed: the kernel is gone'

in flight, bar shows                     : 'Loading Hyde project...'
kernel crashed, bar shows                : ''

quit sent, then a command failed         : _quit_command_sent=False
quit sent, then a command worked         : _quit_command_sent=True

mid-startup, bar showed                  : 'Connecting to Jupyter Kernel Socket...'
startup finished, bar shows              : ''
```

`TestProjectOperationOwnsItsOwnStatusMessage` in `tests/test_kernel_runtime.py`
holds all of those. It subclasses `HydeApp` over a real `QStatusBar` so that
everything the paths do to the bar is the real code, and ends operations
through `on_project_state_result`, `on_kernel_crashed` and
`on_visible_command_executed` rather than by reaching for a clear helper. Three
of the eight fail on the old unconditional clear -- the two "a failing terminal
command leaves ... showing" and "a project operation ending leaves a message
that replaced it"; the other five are regression guards that pass in both
directions, so a later fix cannot start leaving messages stuck instead.

No test fake needed changing: `begin_project_operation` and
`end_project_operation` keep their signatures, and the two methods that were
deleted had no callers outside `main/__init__.py`.

Suite: 671 tests, OK (663 before).

## Slice 11: Hyde Can Become Unquittable

### Type

`AFK`

### What to build

A failed quit dispatch permanently refuses every later quit, **including the
window's close button**, and the only escapes are a kernel crash or a raising
terminal command.

`Plugin.quit_application` (`hyde/user_interface/plugins/file/__init__.py:128`):

```python
if self.services["get_shutting_down"]() or self.services["get_quit_command_sent"]():
    return False
...
self.services["set_quit_command_sent"](True)      # set BEFORE the dispatch
return bool(self.services["python_execution_service"].execute_hidden(...))
```

The flag goes up *before* the command is dispatched, and `execute_hidden`
answers only "was this handed off", not "did it run". So if the dispatch returns
`False` because the kernel is not ready, or the kernel never acts on the
command, the flag stays `True` for the life of the session and the first branch
refuses everything afterwards.

`HydeMainWindow.closeEvent` (`hyde/user_interface/main/__init__.py:148`) routes
the close button through `self.app.request_quit()` when not already shutting
down, and that reaches the same refused path — so the window will not close
either. The application stops responding to both Quit and the close box, with no
message.

The only resets are `on_kernel_crashed` (`main/__init__.py:587`) and the
visible-command branch (`:659`). Slice 10 kept that second one deliberately;
this slice is why it mattered. Typing an expression that raises in the terminal
is currently a user's way out of an unquittable Hyde, which is not a design.

The shape of the fix: set the flag only on a **successful** dispatch, and make
the quit observable rather than fire-and-forget, so a quit that never lands does
not wedge the application. `FrontendKernelService.request` already provides the
correlated form, and the branch's Slice 7 made `KernelPayloadRequest` the one
owner for request-then-await lifecycles — but a quit is not a payload request,
so decide whether it wants that machinery or simply a reply-checked request, and
say which.

Do not remove the guard itself: refusing a *second concurrent* quit while one is
genuinely in flight is correct. The defect is that "in flight" is recorded
before the fact and never retracted.

### Acceptance criteria

- [x] A quit whose dispatch fails leaves the application still quittable, shown
      by execution.
- [x] A quit that is genuinely in flight still refuses a second concurrent quit.
- [x] The window's close button still works after a failed quit.
- [x] A successful quit still shuts down exactly once.
- [x] `on_kernel_crashed` still resets the flag.

### Blocked by

- Slice 10, which is done and kept the accidental escape hatch alive.

### Landed

The quit is observable, and the escape hatch is gone with the reason it
existed.

**What `execute_hidden` actually answers.** `Plugin.execute_frontend`
(`kernel_runtime/__init__.py:524`) returns `False` when there is no
`frontend_kernel_service` yet, when it is not `is_ready()`, and -- on the GUI
thread -- when `FrontendKernelService.execute` hands back no `msg_id`, which is
that same readiness check one layer down plus a client that declined the send.
Off the GUI thread it returns `True` unconditionally, having only emitted a
signal to marshal the call, so its `True` is not even a claim that anything was
sent. None of it says the kernel *ran* the code. Startup is the reachable case:
`is_ready()` is false until the readiness probe comes back, and the Quit item
is enabled the whole time.

**The quit is a reply-checked `request`, not a `KernelPayloadRequest`.** The
narrow fix -- set the record only when the dispatch succeeds -- leaves a second
wedge standing: a `hyde.quit()` that reaches the kernel and raises there. It
raises whenever `hyde` is not in the user's namespace, which the user can
arrange from the terminal, and a raise on the hidden lane is reported nowhere
the app was listening. So `quit_application` now dispatches through
`python_execution_service.request` and retracts the record in `on_quit_reply`
unless the reply says the quit ran. `KernelPayloadRequest` is the wrong owner
for it: that machinery exists for a command answered *twice*, where the reply
and a separate payload race, and it is bound to a widget owner for its progress
message, busy cursor and payload timeout. A quit has one answer and no payload,
and the file plugin is not a widget. A plain `KernelRequest` is the whole need.

**What is still not covered, and why.** A kernel that replies `ok` and then
fails to deliver `QUIT_REQUESTED` -- `signal_quit_requested` swallows its own
exceptions -- leaves Hyde up with a quit on the books. Covering it would need a
timeout on the quit, and `KernelRequest` deliberately has none: the kernel runs
one request at a time, so a quit issued behind the user's own long cell waits
its turn, and a watchdog could not tell that from a lost one. It would trade a
rare wedge for a quit that fires twice. The case already has a designed way
out: Kill Kernel takes the kernel down, `_handle_kernel_crash` runs
`on_kernel_crashed`, and that clears the record.

**The visible-command lane is gone.** With the quit retracting its own record,
`on_visible_command_executed` had nothing left to do -- Slice 10 had already
established that every project command reports elsewhere, and kept the reset
only because this defect made it a user's last way out. Keeping it now would be
worse than dead: a typo in the terminal would clear a quit that is legitimately
in flight and let a second one go out behind it. `HydeApp.on_visible_command_executed`,
`VisibleCommandNotificationService`, the service entry and the
`terminal.executed` connection in `python_terminal_tool` are all removed, and
with them five tests that pinned the lane.

Measured by driving the real entry points -- `quit_application`, `request_quit`,
`HydeMainWindow.closeEvent` through `ui.close()`, `on_kernel_crashed` -- over a
real `HydeMainWindow` and the real file plugin, with only the kernel stood in
for:

```
1. A quit whose dispatch fails leaves Hyde quittable
kernel not up, Quit chosen, kernel received         : []
kernel up, Quit chosen again, kernel received       : ['hyde.quit()']

2. A quit genuinely in flight refuses a second concurrent quit
Quit, then Quit again with no reply yet             : ['hyde.quit()']

3. The window's close button still works after a failed quit
close button with no kernel, window visible         : True
close button with no kernel, kernel received        : []
close button again, kernel received                 : ['hyde.quit()']
kernel ran the quit, window visible                 : False
close button, then hyde.quit() raised, visible      : True
close button again, kernel received                 : ['hyde.quit()', 'hyde.quit()']

4. A successful quit still shuts down exactly once
kernel received                                     : ['hyde.quit()']
application_shutdown events                         : 1
request_runtime_shutdown events                     : 1
window visible                                      : False
Quit chosen after the shutdown, kernel received     : ['hyde.quit()']

5. on_kernel_crashed still resets the flag
close button, kernel received                       : ['hyde.quit()']
kernel crashed, close button again, received        : ['hyde.quit()', 'hyde.quit()']
```

The same probe on the shipped body, over the two entry points both revisions
support, is the defect itself:

```
                                               before          after
Quit chosen before the kernel was up         : []              []
kernel up now, Quit chosen again             : []              ['hyde.quit()']
close button, kernel received                : []              ['hyde.quit()']
```

`TestClosingHydeKeepsWorking` in `tests/test_file_dialog_plugin.py` holds the
close-button half, through `ui.close()` rather than by calling
`quit_application`, because the close button is what a user reaches for when
the Quit item has stopped answering. Four of its five fail on the shipped body,
as do three of the four plugin-level quit tests beside it. None of them asserts
the flag: they assert that the kernel was asked, that the window closed, and
that one quit produced one shutdown.

Suite: 674 tests, OK (671 before; eight added, five removed with the lane).

## Slice 12: A Kernel Signal That Cannot Be Delivered Says Nothing

### Type

`AFK`

### What to build

`hyde/execution/ipc.py` carries **nine** bare `except Exception` blocks across
seven senders. A signal the kernel cannot deliver to the GUI fails with no log
line anywhere, in either process.

Found while doing Slice 11, which named it the last remaining unquittable path.
Slice 11 made the quit *command* observable — the GUI now learns if
`hyde.quit()` did not run — but this is the other direction: the kernel
successfully running `hyde.quit()` and then failing to tell the GUI.

The consequence is ordered badly. `hyde.quit()` (`hyde/__init__.py:485`) calls
`signal_enter_no_project_state()` **before** `signal_quit_requested()`. So a
swallowed quit signal leaves the GUI having already dropped its project and
still running — worse than not having tried.

### The swallowing is deliberate, and the fix must respect that

One of the blocks states the reason: *"Silently fail if running outside a
Hyde-managed kernel."* These functions are reachable when `hyde` is imported
with no parent message channel at all — a plain IPython, a script, a test — and
doing nothing is correct there. So this is **not** "log everything".

Separate the two cases: *there is no channel*, which is expected and silent, and
*there is a channel and the send failed*, which is a fault and must be logged
against the `hyde` logger. Establish how to tell them apart by reading
`put_parent_message` and whatever it depends on, rather than catching narrower
exception types and hoping.

### One sender is explicitly out of scope

**`signal_copy_to_clipboard` must be left exactly as it is.** The maintainer
ruled on this directly earlier in the branch: it is unrelated and was
deliberately left alone, and it is not to be "fixed to match". Do not touch it,
and do not include it in any sweep that rewrites the others.

### Acceptance criteria

- [x] A send that fails while a parent channel exists is logged, with the signal
      named, shown by execution.
- [x] A call with no parent channel at all is still silent, shown by execution —
      importing `hyde` outside a Hyde kernel must not start logging errors.
- [x] `signal_copy_to_clipboard` is byte-identical afterwards.
- [x] A swallowed quit signal is no longer invisible: the failure is in the log
      even though the GUI never hears the signal.
- [x] The ordering in `hyde.quit()` is either changed so the project is not
      dropped before the quit is known to be deliverable, or the reason it must
      stay is written down.

### Blocked by

- Slice 11, which is done and established this as the residual path.

### Landed

**The two cases are told apart by the channel, not by the exception.**
`put_parent_message` already returns without raising when `_parent_tree()` is
None, so the swallowing could never have been catching "outside a Hyde-managed
kernel" -- and `_parent_tree` never returned None for that case anyway. Read
against zprocess: `ProcessTree.__init__` sets `self.to_parent = None`, and only
`_connect_to_parent` puts a `WriteQueue` there, so `to_parent` is the channel
and the attribute always exists. The shipped guard asked `hasattr`, which is
true of every process tree, so a plain interpreter got a top-level tree back
and `put_parent_message` died on `None.put(...)`. Measured on the shipped body:
`to_parent value: None`, `hasattr to_parent: True`,
`put_parent_message raised: AttributeError 'NoneType' object has no attribute
'put'`. The silence outside a kernel was an `AttributeError` landing in a bare
`except`, not a decision. `_parent_tree` now answers with the channel
(`getattr(tree, "to_parent", None) is None`), and treats a tree that cannot be
built at all as the same answer -- only the top-level construction path reads
labconfig, because a kernel child's instance is already built by
`connect_to_parent()`.

So `_report_undelivered_signal(signal)` asks one question -- is there a channel
-- and stays silent when there is none. Six senders name their lost signal
through it: `OPEN_TABLE_REQUEST`, `APPEND_TABLE_REQUEST`,
`ENTER_NO_PROJECT_STATE`, `ACTIVATE_PROJECT`, `QUIT_REQUESTED`,
`PROJECT_STATE_RESULT`. The report lives in the senders rather than in
`put_parent_message` so that `signal_copy_to_clipboard`, which shares that
helper, keeps its behaviour as well as its bytes: sha256 of the function is
`157aed07...` before and after, and the function does not appear in the diff.

**The logger is `hyde`, as every other Hyde module uses.** The kernel calls
`setup_logging('hyde-kernel')`, which configures that name and not `hyde`, so a
`hyde` record in the kernel has no handler of its own and reaches the user
through `logging.lastResort` on the kernel's stderr -- which `HydeApp` spawns
the kernel with redirected into the GUI's logging window
(`output_redirection_port` from `runtime_output_service`). Measured in a
kernel-shaped process with no logging configured: the error and its traceback
arrive on stderr, naming `QUIT_REQUESTED`.

**The quit no longer spends the project first.** `hyde.quit()` sends
`QUIT_REQUESTED` alone. Nothing depended on the drop going first: a GUI that
takes the quit sets `shutting_down`, closes, and `begin_shutdown_from_close_event`
stops the project watcher itself; there is no save-on-quit to lose; and
`RuntimeHelper.mainloop` returns the moment it takes the quit, so anything
queued behind it is never read -- a reordered `ENTER_NO_PROJECT_STATE` would be
provably dead, while the shipped one landed whether or not the quit behind it
did. Project-owned windows also come down more quietly this way: they check
`get_shutting_down()` and skip the kernel round-trip a no-project state would
have made them attempt. `IPC_PROTOCOL.md` no longer describes the old
precondition.

Four tests in `tests/test_kernel_ipc.py`, driving the real senders: a refused
send names its signal (over all six, and none of them raises), a process with
no channel logs nothing at all (both shapes -- a tree that never connected, and
no tree), a `hyde.quit()` the GUI never hears is in the log, and a quit asks for
the shutdown before anything else. Eight assertions fail on the shipped body,
including `Lists differ: ['ENTER_NO_PROJECT_STATE'] != ['QUIT_REQUESTED']`.

Left alone as out of scope: `_executing_request_id`'s empty-string fallback and
`push_table_data`'s per-name `np.asanyarray` fallback are not sends, and
`recreation_registry.publish_registry` is a sender outside this file. Its own
`except Exception: pass` still swallows, though `serialize_registry` can
genuinely raise inside it.

Suite: 677 tests, OK (673 before; four added).

## Slice 13: The Last Unquittable Path, And The Eighth Sender

### Type

`AFK`

### What to build

Two follow-ons from Slice 12, which its author raised rather than widening its
own scope.

**1. A lost `QUIT_REQUESTED` still wedges Hyde.** Slice 11 made the quit
*command* observable: the GUI retracts its quit record unless the reply says
`hyde.quit()` ran. Slice 12 made an undelivered signal *visible* in the log. But
the two do not meet. If the kernel runs `hyde.quit()` successfully and the
`QUIT_REQUESTED` signal is then lost, the reply still says the command **ran** —
so `_quit_command_sent` is never retracted, and Hyde refuses every later Quit
and every window close, exactly as before Slice 11.

Slice 12's author identified the fix and declined it as a public-contract change
beyond that slice's criteria: **`hyde.quit()` should raise when a present
channel refuses the quit signal.** That makes `request.ran()` false, which
retracts the record through the machinery Slice 11 already built. Note the
distinction Slice 12 established — a *present channel that failed* is a fault,
while *no channel at all* is expected and silent — so a `hyde.quit()` called
outside a Hyde-managed kernel must still not raise.

Check what else calls `hyde.quit()` before changing its contract, and whether
anything treats it as best-effort.

**2. An eighth sender, outside `ipc.py`.**
`recreation_registry.publish_registry` (`hyde/recreation_registry.py:149`) is
still `except Exception: pass`, and its `try` also wraps `serialize_registry`,
which can genuinely raise — so a serialisation bug and an undeliverable message
are swallowed by the same handler and neither is reported. Give it the treatment
Slice 12 gave the other seven, and separate the two failure modes: a
serialisation failure is a bug in Hyde, not a delivery problem.

### Also worth settling in the same pass

Slice 12 found two documentation defects while establishing the above. Neither is
urgent, both are cheap:

- **`hyde.create_table`'s docstring says `column_widths : sequence of int`.**
  Every producer and consumer treats it as `{name: width}`
  (`normalize_table_column_widths`), and an actual sequence would have raised
  inside the old silent `except` and opened no table. So the documented type has
  never worked.
- **`push_table_data` in a no-channel process** now raises its documented
  `RuntimeError` instead of an `AttributeError` — an improvement Slice 12 made
  as a side effect. Confirm the docstring matches what it now does.

### Acceptance criteria

- [ ] A `hyde.quit()` whose `QUIT_REQUESTED` is lost leaves Hyde quittable,
      shown by execution through the real quit path.
- [ ] A `hyde.quit()` outside a Hyde-managed kernel still does not raise.
- [ ] A successful quit still shuts down exactly once, and a quit genuinely in
      flight still refuses a second.
- [ ] `publish_registry` reports a delivery failure and a serialisation failure
      differently, and neither is silent.
- [ ] `hyde.create_table`'s documented `column_widths` type matches what the
      code accepts.

### Blocked by

- Slices 11 and 12, both done.
