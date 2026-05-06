# Kernel Runtime Plugin For Hyde

## Purpose

This document defines the next Hyde architecture step for stronger task isolation:
move kernel runtime ownership out of the core shell and into a dedicated first-party
plugin.

The goal is not merely to relocate startup code. The goal is to create two clean
seams:

- one module that owns kernel lifecycle, the shared frontend kernel client, and Lane 1
  `ProcessTree` control traffic
- one module that owns Python execution requests from GUI features

Today those responsibilities are spread across `HydeApp`, `RuntimeHelper`, the Python
Terminal plugin, and callers that reach through shell wrappers. That lowers locality,
makes threading harder to reason about, and leaves plugin boundaries shallower than
Hyde's architecture intends.


## Hyde Constraints That Bind This Design

This work stays inside Hyde's existing architecture:

- the kernel remains authoritative for scientific state
- the GUI remains a string factory for normal command paths
- first-class figure editing continues to use the existing semantic `comm` path
- Hyde uses the narrowest existing transport that fits the feature
- the core shell must not grow wrapper methods over plugin-owned behavior

This means the kernel-runtime move must preserve Hyde's current two-lane model:

- Lane 1: `ProcessTree` control and narrow kernel-to-GUI notifications
- Lane 2: Jupyter execution, metadata, and `comm` traffic


## Current Problem

The current runtime path spreads one concept across too many modules:

- `HydeApp` creates the kernel subprocess, creates `FrontendKernelService`, starts
  `RuntimeHelper`, and exposes `execute_command` plus `queue_background_command` to
  every plugin.
- `RuntimeHelper` handles both Lane 1 control messages and queued execution requests.
- queued hidden execution runs from a background Python thread through
  `FrontendKernelService.execute(...)`, even though the shared frontend client is a
  Qt-owned object created in the GUI process.
- the Python Terminal plugin is the visible execution path, but hidden execution does
  not use the same module.
- the Python Variables plugin still contains a fallback path that creates its own
  `QtKernelClient` when it cannot obtain one from the terminal path.
- the Figure plugin registers figure comm targets by reaching through the terminal
  widget to find the shared kernel client.

This leaves Hyde with a shallow runtime seam. Deleting `HydeApp.execute_command` or
`HydeApp.queue_background_command` would not remove complexity; it would force each
caller to rediscover execution policy, thread rules, and client lookup for itself.
That is a sign Hyde needs a deeper module, not more shell wrappers.


## Goals

1. Make one plugin the sole owner of the kernel subprocess, `ProcessTree` child
   handles, shared `FrontendKernelService`, and runtime crash/shutdown policy.
2. Remove all shell wrapper methods whose only job is to forward Python execution into
   plugin-owned behavior.
3. Ensure no background worker thread calls into the shared frontend kernel client.
4. Give plugins one clear execution module for visible and hidden Python strings.
5. Give plugins one clear kernel-client module for comm registration and metadata paths.
6. Eliminate accidental coupling where non-terminal plugins depend on the terminal
   widget to reach the shared kernel client.


## Non-Goals

- changing `zprocess` internals
- changing the Jupyter connection protocol
- redesigning project save/load semantics
- redesigning figure editing semantics
- introducing third-party runtime plugin loading


## Decision Summary

### 1. Add a dedicated kernel runtime plugin

Create a first-party plugin under `hyde.user_interface.plugins` that owns:

- kernel subprocess startup via `ProcessTree.subprocess(...)`
- connection-file cleanup and startup parameters
- the shared `FrontendKernelService`
- the Lane 1 background listener for `from_kernel.get(...)`
- kernel crash detection and restart policy
- ordered kernel shutdown and forced termination fallback

After this change, `HydeApp` no longer creates or tears down those runtime objects.


### 2. Keep `HydeApp` shell-only

`HydeApp` continues to own:

- Qt application and main-window setup
- plugin discovery and event dispatch
- MDI shell behavior
- project watcher ownership
- session and history persistence
- shell-owned project status and message boxes

`HydeApp` exposes shell lifecycle actions as plugin services where the kernel runtime
plugin needs to instruct the shell. These are shell-owned adapters, not wrappers over
plugin behavior.

The required shell services are:

- `on_kernel_ready`
- `on_kernel_crashed`
- `enter_no_project_state`
- `activate_project`
- `on_project_state_result`
- `request_gui_quit`

The exact service names may vary in implementation, but the seam is fixed: the kernel
runtime plugin calls shell-owned lifecycle adapters instead of reaching into shell
internals.


### 3. Split the kernel-client seam from the execution seam

The kernel move needs two real modules, not one overloaded service.

#### Kernel runtime module

The kernel runtime plugin exports a service for shared Lane 2 infrastructure:

- access to the shared frontend kernel client
- comm-target registration against that shared client
- readiness state for consumers that need it

This is the module Python Terminal, Python Variables, and Figure all use when they need
the shared client or the shared comm manager.

#### Python execution module

The Python Terminal plugin exports the execution module used by feature callers. It
owns:

- visible execution
- hidden execution
- visible command history capture
- terminal history restore

Its public interface is:

- `execute_visible(code)`
- `execute_hidden(code)`

This keeps Hyde on one execution policy while letting the terminal plugin continue to
own visible-console behavior.


### 4. Remove shell execution wrappers

`HydeApp.execute_command` and `HydeApp.queue_background_command` are deleted.

Callers stop depending on shell forwarding and instead use the execution module
directly:

- File Dialogs
- Table
- Figure
- Python Variables
- remote requests
- shell-owned session restore and procedure reload paths

This is the main locality win. Execution policy lives in one module instead of being
partly hidden in the shell.


### 5. Remove execution from the background helper thread

The current `RuntimeHelper` mixes two jobs:

- waiting for Lane 1 control messages
- draining queued hidden execution

After this change, the background worker only handles Lane 1 control traffic and kernel
death detection. It does not call the shared frontend kernel client.

Hidden execution is marshalled onto the GUI thread and runs through the Python
execution module.

Whether the implementation keeps the name `RuntimeHelper` or adopts a clearer name is
not architecturally important. The important rule is that the worker thread no longer
owns any Lane 2 execution behavior.


### 6. Enforce a single shared frontend kernel client for UI plugins

The Python Variables plugin no longer creates its own `QtKernelClient` fallback from
`CONNECTION_FILE`. It consumes the shared-client service exported by the kernel runtime
plugin.

The Figure plugin no longer reaches through the terminal widget to register figure
comm targets. It uses the shared-client or comm-registration service exported by the
kernel runtime plugin.

The Python Terminal widget also consumes that same shared-client service. It does not
become the owner of the client.

This gives Hyde one real Lane 2 adapter instead of several partial ones.


### 7. Keep current external behavior where possible

This refactor preserves current user-visible behavior:

- Hyde still auto-starts the kernel during application startup
- Hyde still reconnects to a fresh kernel after an unexpected crash
- visible commands still appear in terminal history
- hidden commands still avoid visible terminal history
- project load and session restore still reopen windows through the current paths
- lyse-compatible remote requests still enqueue work into the kernel

The goal is better module depth and thread ownership, not a product redesign.


## Expected Module Changes

The final file layout may vary, but the architecture should converge on something close
to this:

- `hyde/user_interface/plugins/kernel_runtime/...`
  Owns kernel startup, shared frontend client, Lane 1 worker, crash handling, and
  shutdown handling.
- `hyde/user_interface/plugins/python_terminal/...`
  Owns terminal widget plus the execution module.
- `hyde/user_interface/main/__init__.py`
  Owns shell setup and shell lifecycle adapters only.

The old `hyde.user_interface.main.frontend_kernel` and
`hyde.user_interface.main.runtime_helper` modules may move or be retained in place as
implementation details, but they are no longer shell-owned runtime policy modules.


## Testing Decisions

Tests should validate behavior at the module seam rather than overfitting to thread
internals.

Required coverage:

1. The kernel runtime plugin starts the kernel subprocess and shared frontend client
   during setup.
2. Lane 1 messages still dispatch the correct shell lifecycle actions:
   `ENTER_NO_PROJECT_STATE`, `ACTIVATE_PROJECT`, `PROJECT_STATE_RESULT`, and
   `QUIT_REQUESTED`.
3. Hidden execution runs through the Python execution module on the GUI thread rather
   than directly from the background worker.
4. The Python Variables plugin consumes the shared frontend kernel client and does not
   instantiate its own fallback client.
5. The Figure plugin registers its comm target through the shared-client seam rather
   than through the terminal widget.
6. `HydeApp` no longer exports `execute_command`, `queue_background_command`, or direct
   frontend-kernel ownership through `build_plugin_services()`.

Existing runtime and plugin-manager tests are the natural prior art for this work.


## Rollout Notes

This refactor is easiest to land in this order:

1. introduce the kernel runtime plugin and move kernel ownership into it
2. introduce the explicit execution module with `execute_visible(...)` and
   `execute_hidden(...)`
3. migrate callers off shell wrappers
4. remove thread-based hidden execution
5. remove fallback client creation and terminal-widget client lookup from other plugins

This ordering keeps each step small while converging on the intended final seam.
