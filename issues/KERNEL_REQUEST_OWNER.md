# Scope: one owner for GUI-initiated kernel requests

Status: steps 1-3 landed. Step 4 next.

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

Four features have independently hand-rolled the same request lifecycle, with
four timeout constants and four sets of failure semantics:

- `figure_interactive/window.py` — `REFRESH_TIMEOUT_MS`, `CLOSE_TIMEOUT_MS`
- `table_interactive/window.py` — `REFRESH_TIMEOUT_MS`
- `save_graphics_dialog` — `copy_timeout_ms`, and a `FigureCopyRequest` object
- `python_variables_tool` — `_execute_requests_in_flight`, a set keyed by
  `(session, parent_header.msg_id)` from iopub `status` messages, with no timeout

The last of those is the one that got closest. It already correlates replies to
requests by `msg_id`; it just does it privately, on the iopub channel, for its
own refresh trigger.

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
  readiness. Having done so once, it **disconnects itself from the shell
  channel**, so no `execute_reply` after startup is ever seen at all.

Hyde therefore does not need a new protocol, a request token in emitted Python,
or a change to any public runtime signature. It needs to keep an identifier it
is already given and keep listening after startup.

## What the owner provides

1. **Identity.** A GUI request gets a handle when issued, carrying the `msg_id`.
2. **Completion.** The `execute_reply` for that `msg_id` resolves the request as
   ran or raised, with the kernel's error attached.
3. **No timeout before the reply.** A request queued behind a long user cell is
   waiting, not failing, however long that takes.
4. **Uniform failure reporting**, so a raised command says what raised rather
   than timing out generically.
5. **Serialization policy**, enforceable in one place: refuse or queue a second
   GUI request while one is outstanding.

Payload-bearing replies stay on the parent-message channel. The owner correlates
the *execution*; serialization is what lets a feature trust that the next payload
is its own.

**Two transports, no ordering between them.** The `execute_reply` for a copy
travels the Jupyter shell channel while the rendered bytes travel the zprocess
parent-message channel. The kernel sends the bytes first, but nothing guarantees
they arrive first. A feature must therefore not read `execute_reply` as "stop
listening":

- reply `status="error"` — fail now, with the kernel's message
- reply `status="ok"` — the render *happened*; the payload is in transit, so
  wait for it

That second wait is bounded work on a completed operation, which is what makes a
short timeout legitimate there and not before.

## Not in scope

- **Kernel-initiated events.** Table opens from a user's own
  `hyde.create_table(...)`, figure draws, project lifecycle. The GUI never
  requested them, so a request owner cannot order or correlate them. This is
  most of the inbound traffic, and no amount of GUI serialization touches it.
- **Execution ordering.** Jupyter kernels already process shell requests strictly
  in order. Ordering was never missing; correlation was.
- **The user's own terminal cells.** The owner must not queue GUI requests behind
  a policy that makes the GUI appear frozen, nor block the user.
- **Making the GUI usable while a script runs.** The owner makes the wait honest;
  it does not remove it. That is a real defect with its own mechanism and its own
  hazards, recorded in `CONCURRENT_KERNEL_ACCESS.md`. The owner is a prerequisite
  for it, so nothing here should be read as a fix for it.
- **`hyde.copy_figure` and the other public runtime helpers.** Their signatures
  and emitted Python do not change.

## Migration

Each step leaves the suite green on its own.

1. **Done.** Keep the `msg_id` from `execute`, and stop `_on_shell_message`
   disconnecting once ready. No behavior change; the data is simply no longer
   discarded.
2. **Done.** `KernelRequest` plus request tracking in `FrontendKernelService`,
   reached through a third verb on `python_execution_service`: `request`.
   `execute_hidden` and `execute_visible` answer "was it sent"; `request`
   answers "what happened". Outcomes are ran / raised / abandoned, and `stop()`
   abandons everything outstanding at once. No policy attached; nothing uses it
   yet.
3. **Done.** Copy moved onto it. `FigureCopyRequest` now holds the copy open
   until it has what it needs from either channel, refuses a second copy while
   one is outstanding, reports what the kernel said when a render raises, and
   fails the copy when the kernel goes away. Its wall-clock `copy_timeout_ms`
   is gone; the only remaining clock bounds the transport gap after a
   successful render. The wait cursor now lowers itself after a short hold
   rather than staying up for as long as the kernel takes.
4. Move table refresh, then figure refresh and close. Delete their timers and
   timeout constants as each moves.
5. Surface `status="error"` replies, which retires the "hidden execution
   failures are invisible" debt recorded during the figure copy work.

## Decisions settled

- **Serialization policy.** Refuse a second GUI request while one is
  outstanding. No queue.
- **`execute_visible` is out of scope.** Every call site is fire-and-forget
  dispatch to the terminal — "To Cmd Line", window macros, table append. None
  waits, none has a timeout, none expects a payload. It also does not travel
  `FrontendKernelService` at all: it goes through the qtconsole widget, which
  owns its own path to the same client. It is the user typing, by proxy, so it
  neither blocks a GUI request nor is blocked by one.

## Decisions settled (continued)

**A GUI request never times out before its `execute_reply`.** Refusal governs
*Hyde's* queue, of which there is now at most one entry. It does not govern the
*kernel's* queue, which Hyde does not control: the terminal and `execute_hidden`
share one shell channel to a kernel that runs one cell at a time. Press copy
during a 60-second fit and the request is the only one Hyde has outstanding, yet
no `execute_reply` can arrive for 60 seconds. See "Timeouts measure wall-clock"
above for what that produces today.

So a pending request stays pending. The kernel always sends `execute_reply` —
that is protocol, not best-effort — and interrupting the cell produces an error
reply, so the request resolves either way. The only case a per-request timer
would catch is a dead kernel, which Hyde already detects through
`on_kernel_crashed`; that must settle every outstanding request at once rather
than each waiting out its own timer.

While waiting, the surface says so. The wait cursor reverts after a couple of
seconds — it is cosmetic and does not block input, but a minute-long wait cursor
reads as a hung application — and the status message carries the state instead.

The one timeout that stays is the bounded wait for a payload *after* an
`execute_reply` with `status="ok"`, per the two-transport note above.

## Known gap: a stray payload after a failed copy

A copy that renders successfully but whose bytes never arrive fails after a
bounded wait. Those bytes can still land afterwards. While no copy is
outstanding they are dropped, which is correct -- but if the user starts another
copy inside that window, the stale bytes satisfy the new one.

The window is short and needs a copy started immediately after a failure, so
this is a real but narrow exposure, and it is no worse than what the wall-clock
timeout allowed before. Closing it means tagging the payload with the `msg_id`
of the request that produced it. ipykernel exposes that to kernel-side code
through the parent header of the executing request, so it does not require a
change to `hyde.copy_figure`'s signature or to the emitted Python. Step 5.

## Risk

The owner sits under every command-emitting surface in Hyde, so a regression is
broad rather than local. Steps 1 and 2 are additive and carry little risk; step 4
rewrites the refresh paths of the two most-used windows and is where care is
needed. The step order exists so that copy proves the shape before the widely
used paths move onto it.
