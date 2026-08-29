# Defect: the GUI cannot act on the kernel while the user's script runs

Status: documented, not scheduled. Recorded because it is the defect *underneath*
`KERNEL_REQUEST_OWNER.md`, and that work must not be mistaken for a fix to it.

## The expectation, and why it is reasonable

A user runs a long fit in the terminal, looks at a figure produced an hour ago,
and presses Copy. Nothing about that asks the running script for anything. They
expect it to work.

It does not. Hyde's hidden commands and the user's terminal cells share one
Jupyter shell channel to a kernel that executes one request at a time, so the
copy waits for the fit. The same holds for figure refresh, table refresh, and
every other GUI-initiated command. `KERNEL_REQUEST_OWNER.md` makes that wait
*honest* — the request stays pending instead of falsely reporting failure — but
the user still waits.

## The mechanism already exists in the installed kernel

Verified against `ipykernel` 6.31.0 / `jupyter_client` 8.10.0 in the `labscript`
env:

- `Kernel.control_thread` is a **separate thread with its own io_loop**, serving
  the control channel while the shell thread executes.
- `Kernel.control_msg_types` **includes `execute_request`** — the control
  channel accepts the full shell message set, plus `debug_request` and
  `usage_request`.
- `IPythonKernel` does **not** override `control_msg_types`, so a control-channel
  `execute_request` reaches the same `do_execute` and the same
  `InteractiveShell` — the same namespace, the same figures.
- `_control_lock` is an `asyncio.Lock` serializing control messages **against
  each other**. There is no lock between control and shell.

So a second thread with full access to the first's memory is not something Hyde
would have to build. It is running right now, and Hyde only ever sends
`shutdown_request` down it.

## Why that last bullet is a hazard, not a green light

The absence of a control/shell lock is exactly what makes concurrent execution
possible and exactly what makes it unsafe. Four constraints, none of them
addressed by simply changing which channel a command goes down:

1. **One `InteractiveShell`, two threads, no lock.** Execution counter, stdout
   redirection, last traceback and the user namespace are shared mutable state.
2. **The GIL bounds the benefit.** A second thread progresses only while the busy
   cell releases it. numpy/scipy inner loops do; a pure-Python loop does not.
   Fortunately that favours the case that motivates this — long numerical work.
3. **matplotlib is not thread-safe, and copy renders.** Copying a figure the
   running script is actively drawing to is a data race on the artist tree, not a
   slow read. Copying a figure the script never touches — the motivating case —
   is safe, but Hyde cannot tell those apart from the outside.
4. **Output routing is per-request.** ipykernel binds stdout/stderr to the
   parent message of the executing request. Concurrent execution can attribute
   the script's output to the copy, or the reverse.

Upstream's own answer to this is subshells (JEP 91), which give a second shell
sharing one namespace rather than borrowing the control channel. That landed in
`ipykernel` 7, which is **not** installed here — so it is the likely destination,
unverified in this environment.

## What Hyde would need beyond a transport

- A distinct lane for GUI requests that are short and free of side effects, so
  only those bypass the queue. `execute_hidden` today carries commands that
  mutate the namespace; those must keep their place in line.
- A stated position on constraint 3: either accept that copying an
  actively-drawn figure can tear, or find a snapshot the running script cannot
  be mutating. Hyde cannot lock the user's own code.
- Failure handling for a lane whose requests can now overtake each other, which
  is the first thing in this note that `KERNEL_REQUEST_OWNER.md` does build.

## Relationship to the request owner work

The request owner is a prerequisite, not a competitor. It gives every
GUI-initiated request an identity and a correlated reply, which is what a second
lane needs before it can exist at all — with two lanes in flight, "the next
payload is mine" stops being true by construction and correlation becomes the
only way to route an answer. Doing the owner first is right regardless of whether
this note is ever scheduled.
