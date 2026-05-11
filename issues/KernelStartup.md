## Problem Statement

Hyde’s initial kernel launch can start in a different output-routing state than later restarted kernels. In practice, the first kernel may emit its `hyde-kernel` logger output directly to the launch terminal instead of through the runtime output redirection path used by restarted kernels. This makes early-session diagnostics inconsistent and can hide important kernel-side debug output from the Logging window.

During investigation, this showed up as a clear asymmetry:

- the first kernel sometimes behaved as though runtime output redirection was unavailable or not yet fully ready
- restarted kernels behaved differently and produced richer in-kernel diagnostic output at the terminal
- the code path that acquires the runtime output port silently ignored failures, making it impossible to tell whether the initial launch was redirected correctly

[DONE] The related shutdown issue where Hyde could fall back to forcibly terminating the kernel after the 2 second shutdown wait is also fixed in this branch. Hyde now sends the real Jupyter shutdown request before waiting for the fallback path.

## Solution

Make the initial kernel launch deterministic and diagnosable.

From the user’s perspective, Hyde should launch the first kernel only after the UI/plugin setup is far enough along that runtime output redirection is ready to be used consistently. If redirection is unavailable, Hyde should say so explicitly instead of silently falling back. The first kernel and restarted kernels should therefore behave the same with respect to where kernel stdout/stderr and logger output appear.

As part of the same startup-sequence work, Hyde should emit explicit launch-time diagnostics describing whether runtime output redirection is active. `File -> Kill Kernel` should send `SIGTERM` from the GUI to the managed kernel process, and the kernel should emit a distinct in-kernel marker from its signal handler when it receives `SIGINT` or `SIGTERM` before accepting the signal. This lets investigators distinguish “the signal reached the kernel but logs were routed differently” from “the signal never reached the kernel.”

## User Stories

1. As a Hyde user, I want the first kernel launched after app startup to route its output the same way as a restarted kernel, so that diagnostics appear consistently across the whole session.
2. As a Hyde user, I want the Logging window to receive initial kernel output whenever runtime output redirection is available, so that I do not lose the earliest debug information.
3. As a Hyde user, I want Hyde to say explicitly when the first kernel is launched without runtime output redirection, so that I can tell the difference between missing logs and missing failures.
4. As a Hyde developer, I want failures while acquiring the runtime output port to be logged instead of silently swallowed, so that startup-sequence bugs are observable.
5. As a Hyde developer, I want the initial kernel launch to happen only after plugin setup has completed its current turn of initialization, so that launch-time services are less likely to be half-ready.
6. As a Hyde debugger, I want the kernel launch path to record which output redirection port was used, so that I can compare first-launch and restart behavior directly.
7. [DONE] As a Hyde debugger, I want an explicit in-kernel marker for `File -> Kill Kernel`, so that I can tell whether the GUI-originated termination signal actually reached the kernel.
8. As a Hyde debugger, I want the first kernel and restarted kernels to expose the same diagnostic surface, so that reproduction results are comparable.
9. As a Hyde maintainer, I want startup logging behavior to be deterministic, so that bug reports are easier to interpret.
10. As a Hyde maintainer, I want output-routing failures to surface through normal Hyde logging rather than only through ad hoc terminal observation, so that they are preserved in logs.
11. As a Hyde tester, I want the startup sequence to be structured so it can be tested without relying on race timing, so that regressions are easier to catch.
12. As a Hyde tester, I want to assert whether kernel launch runs after ordinary plugin setup and whether a runtime output port was requested, so that tests can cover the startup contract directly.
13. As a Hyde user investigating kernel crashes, I want confidence that missing traceback output is not caused by a startup-sequence routing bug, so that later crash analysis is based on reliable evidence.
14. As a Hyde developer, I want first-launch behavior to match restart behavior as closely as possible, so that kernel lifecycle bugs are isolated from logging-path differences.
15. As a Hyde operator, I want startup diagnostics to clarify whether output is expected in the terminal, the Logging window, or both, so that I know where to look during debugging.

## Implementation Decisions

- [DONE] The kernel runtime startup sequence uses ordered plugin setup activities so launch occurs after ordinary plugin setup and output-window setup have completed.
- [DONE] The kernel runtime launch path should explicitly log whether a runtime output service is present and which output redirection port, if any, is being used for the child kernel process.
- [DONE] Failure to obtain the runtime output port should be logged as a normal Hyde exception path rather than silently falling back to no redirection.
- The startup-sequence work is about making launch-time routing deterministic and observable, not about redesigning Hyde logging architecture.
- [DONE] `File -> Kill Kernel` is provided by the `hyde/user_interface/plugins/kernel_runtime` plugin as a File menu action.
- [DONE] `File -> Kill Kernel` sends `SIGTERM` from the GUI to the managed kernel process rather than asking the kernel to kill itself.
- [DONE] Hyde GUI mode installs kernel-side `SIGINT`/`SIGTERM` marker handlers when `hyde` is activated in the managed kernel. The marker is emitted when the kernel catches the signal and before it delegates to the previous/default handler, specifically to disambiguate routing problems from signal-delivery problems during debugging.
- The issue should treat “first kernel launch” and “restart kernel” as behavior that ought to be equivalent from an output-routing perspective.
- [DONE] The shutdown behavior where Hyde fell back to forcibly terminating the kernel after the shutdown grace period was caused by using the wrong Jupyter shutdown keyword. Hyde now requests shutdown with `restart=False`.
- Existing crash-investigation instrumentation and branch research are inputs to this issue; this issue now covers startup-sequence output-routing consistency plus the shutdown fallback regression fixed during verification.

## Testing Decisions

- Tests should verify external behavior and lifecycle contracts, not internal implementation details or incidental call ordering beyond what defines the startup contract.
- [DONE] The kernel runtime plugin should be tested to confirm that ordered plugin setup leaves the runtime output service available before launch and that the kernel is launched with the expected output redirection port.
- [DONE] The kernel runtime plugin should be tested to confirm that launch still proceeds in the absence of a runtime output service, but with an explicit logged indication that redirection is unavailable.
- [DONE] The kill-kernel command path should be tested to confirm that the GUI sends termination to the managed kernel process.
- [DONE] The kernel signal-marker path should be tested to confirm that `SIGINT`/`SIGTERM` receipt is logged before the previous/default handler is accepted.
- Prior art should come from the existing Hyde kernel-runtime/plugin tests that already exercise kernel launch, restart, shutdown timing, and command dispatch behavior.

## Out of Scope

- Fixing the underlying spontaneous macOS self-`SIGTERM` source, unless the fix is a side-effect of the in-scope work.
- Redesigning the Logging window, zlog, or general Hyde logging architecture.

## Further Notes

- The motivating evidence is that the first kernel and restarted kernels did not appear to share the same output-routing behavior.
- This issue exists to remove that ambiguity first, so subsequent crash debugging is based on consistent observability.
- [DONE] The shutdown fallback is now covered by live shutdown behavior tests that assert normal File -> Quit does not use fallback `SIGTERM`.
