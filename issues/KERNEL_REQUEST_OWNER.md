# Scope: one owner for GUI-initiated kernel requests

Status: scope definition. Nothing here is implemented.

## The confusion is well founded

Hyde does have a single outbound interface. `PythonExecutionService` is the one
door GUI code uses to reach the kernel, and every command-emitting surface goes
through it.

It is **write-only**. `execute_hidden` returns `True` meaning "handed off", not
"happened". There is no return path through it at all. One door out, four doors
in:

| Inbound channel | Carries |
| --- | --- |
| Jupyter shell | `execute_reply` — did the command run, did it raise |
| Jupyter iopub | stream output, namespace notifications |
| zprocess parent messages | `COPY_TO_CLIPBOARD_REQUEST`, `TASK_COMPLETE`, `PROJECT_STATE_RESULT`, `TABLE_DATA_RESPONSE`, plus kernel-initiated events |
| figure comm | figure draws |

So the interface is single, and it is not doing enough: it models sending, not
requesting. Every surface that needs to know what happened has had to build its
own way of finding out.

## What that costs today

Three features have independently hand-rolled the same request lifecycle, with
four timeout constants and three sets of failure semantics:

- `figure_interactive/window.py` — `REFRESH_TIMEOUT_MS`, `CLOSE_TIMEOUT_MS`
- `table_interactive/window.py` — `REFRESH_TIMEOUT_MS`
- `save_graphics_dialog` — `copy_timeout_ms`, and a `FigureCopyRequest` object

Two defects follow directly from the gap, and both are live:

1. **Timeouts measure wall-clock, not kernel progress.** `execute` is
   fire-and-forget and the kernel runs one cell at a time, so a GUI request
   issued while a long user cell is running waits in the kernel's queue. Run a
   60-second fit, press the copy shortcut, and copy reports failure for an
   operation that will succeed. The figure and table refresh timeouts share the
   flaw.

2. **Errors in hidden execution are invisible.** A command whose kernel-side
   code raises produces an `execute_reply` with `status="error"`. Hyde never
   reads it, so the surface waits out its timeout and reports a generic failure,
   or reports nothing.

## Correlation already exists and is being discarded

This is the finding that sets the scope.

- `KernelClient.execute()` **returns the `msg_id` of the request.**
  `FrontendKernelService.execute` drops that return value.
- `execute_reply` carries `parent_header.msg_id` identifying the request it
  answers.
- `_on_shell_message` **already performs exactly this correlation** — it matches
  `parent_header.msg_id` against `_ready_probe_msg_id` to detect kernel
  readiness. It then returns early for every message once `self._ready` is set,
  so nothing after startup is ever correlated.

Hyde therefore does not need a new protocol, a request token in emitted Python,
or a change to any public runtime signature. It needs to keep an identifier it
is already given and keep listening after startup.

## What the owner provides

1. **Identity.** A GUI request gets a handle when issued, carrying the `msg_id`.
2. **Completion.** The `execute_reply` for that `msg_id` resolves the request as
   ran or raised, with the kernel's error attached.
3. **Timeout against kernel progress**, not wall-clock: a request queued behind a
   long user cell is waiting, not failing.
4. **Uniform failure reporting**, so a raised command says what raised rather
   than timing out generically.
5. **Serialization policy**, enforceable in one place: refuse or queue a second
   GUI request while one is outstanding.

Payload-bearing replies stay on the parent-message channel. The owner correlates
the *execution*; serialization is what lets a feature trust that the next payload
is its own.

## Not in scope

- **Kernel-initiated events.** Table opens from a user's own
  `hyde.create_table(...)`, figure draws, project lifecycle. The GUI never
  requested them, so a request owner cannot order or correlate them. This is
  most of the inbound traffic, and no amount of GUI serialization touches it.
- **Execution ordering.** Jupyter kernels already process shell requests strictly
  in order. Ordering was never missing; correlation was.
- **The user's own terminal cells.** The owner must not queue GUI requests behind
  a policy that makes the GUI appear frozen, nor block the user.
- **`hyde.copy_figure` and the other public runtime helpers.** Their signatures
  and emitted Python do not change.

## Migration

Each step leaves the suite green on its own.

1. Keep the `msg_id` from `execute`, and stop `_on_shell_message` returning early
   once ready. No behavior change; the data is simply no longer discarded.
2. Add the request handle and completion, with no policy attached. Nothing uses
   it yet.
3. Move copy onto it. Copy is the smallest consumer and already has an isolated
   `FigureCopyRequest` to fold in. This is also where serialization lands.
4. Move table refresh, then figure refresh and close. Delete their timers and
   timeout constants as each moves.
5. Surface `status="error"` replies, which retires the "hidden execution
   failures are invisible" debt recorded during the figure copy work.

## Decisions needed before step 3

- **Serialization policy.** Refuse a second request while one is outstanding, or
  queue it? Refusing is honest for millisecond operations and needs no queue.
  Queueing is friendlier if a request can ever be slow. Copy is settled: refuse.
- **Timeout semantics.** With correlation, a request that has not yet produced an
  `execute_reply` is *pending*, not late. Does a pending-but-queued request time
  out at all, and if so against what — kernel idle time, or a hard ceiling?
- **Scope of `execute_visible`.** Visible commands go to the terminal, where the
  user can see failures directly. Include them for uniformity, or leave them out
  because the user is already the observer?

## Risk

The owner sits under every command-emitting surface in Hyde, so a regression is
broad rather than local. Steps 1 and 2 are additive and carry little risk; step 4
rewrites the refresh paths of the two most-used windows and is where care is
needed. The step order exists so that copy proves the shape before the widely
used paths move onto it.
