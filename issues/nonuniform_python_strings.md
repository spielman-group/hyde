## Problem Statement

Hyde currently lacks one uniform rule for how GUI-originated Python strings are
created, previewed, logged, and dispatched to the kernel. The intended rule,
clarified during the export-graphics review, is narrower than first assumed:

- Python generation should come from a `python_source()` path, with
  `preview_python_source()` accepted as the non-logging preview variant when the
  same state object is responsible for the command.
- `Do It` does not need to rerun `python_source()` if it is sending the exact
  string that was already generated for preview.
- Hidden and visible transport logging should live at the transport layer so all
  dispatched commands are observable regardless of which feature generated them.

The current system is inconsistent in two ways.

First, command logging is incomplete. The `[Hyde state] ...` debug messages are
currently emitted by `python_source()`-level helpers and a few feature-local
manual log calls, not by the actual hidden/visible transport service. This means
Hyde logs only some GUI-generated commands, not all kernel-bound commands.

Second, source generation is nonuniform. Some features generate source through a
`python_source()` or `preview_python_source()` path and then dispatch that exact
string. Others bypass that contract by calling codec `state_to_python(...)`
helpers directly, building raw helper strings from dialog widgets, or emitting
figure-patch commands through specialized helpers with no authoritative
`python_source()` owner.

This broad issue is larger than `Save Graphics...`, but `Save Graphics...`
exposed it clearly because it currently sits below even the current
figure-patch-family level of command generation.

## Solution

Adopt one package-wide rule for GUI-originated Python command generation and
logging.

- GUI-side Python generation should have one authoritative path:
  `python_source()`
- `preview_python_source()` is acceptable when it is the preview form of that
  same state-owned command-generation path
- `Do It` may dispatch a previously generated preview string without rerunning
  `python_source()`
- hidden and visible execution transport should own command logging so every
  kernel-bound command is observable regardless of feature family
- feature-local manual logging should disappear once the transport layer logs the
  actual dispatched source
- figure-family features should continue to share figure/matplotlib lowering
  through the existing figure feature layer, but they should stop inventing
  dialog-local or helper-only source-generation paths when a state-owned
  `python_source()` path is expected

This does not require one monolithic state class across the entire application.
It does require that each command-emitting GUI feature have one authoritative
`python_source()` family path, and that transport logging observe the final
string actually sent.

## User Stories

1. As a Hyde developer, I want every GUI-generated kernel command to have one
   authoritative source-generation path, so that command ownership is easy to
   reason about.
2. As a Hyde developer, I want hidden command logging to live in the transport
   layer, so that all dispatched commands are logged rather than only some
   features.
3. As a Hyde developer, I want visible command logging to follow the same rule,
   so that logging behavior is symmetric across dispatch modes.
4. As a Hyde user, I want the log window to show the actual GUI-generated
   command activity consistently across features, so that debugging does not
   depend on which plugin I happened to use.
5. As a Hyde developer, I want preview generation and commit generation to come
   from the same authoritative source-generation family, so that preview and
   execution cannot drift apart.
6. As a Hyde developer, I want figure-family dialogs to reuse the shared figure
   and matplotlib lowering path, so that figure-edit semantics stay consistent
   across plugins.
7. As a Hyde developer, I want feature-local widget trees to avoid inventing
   ad hoc command IR when the feature already has a shared state/lowering
   family, so that new plugins do not fragment the architecture.
8. As a Hyde developer, I want export-style dialogs to reach parity with the
   current figure-patch family before attempting deeper cleanup, so that the
   narrow feature work can converge with existing figure behavior first.
9. As a Hyde developer, I want the broad rule violation inventory written down
   with concrete examples, so that future cleanup can be scoped intentionally
   instead of rediscovered piecemeal.
10. As a Hyde tester, I want behavior tests that assert transport-observable
    logging and final dispatched source, so that architecture regressions are
    caught through user-visible behavior.
11. As a Hyde tester, I want feature-family tests to avoid direct codec or
    helper bypasses in command-generation paths, so that new features are pushed
    toward the uniform source-generation contract.
12. As a Hyde developer, I want exceptions to the single source-generation rule
    to be treated as explicit violations, so that future deviations are surfaced
    early.

## Implementation Decisions

- The transport-layer logging problem and the nonuniform source-generation
  problem are distinct, but they reinforce one another and should be documented
  together.
- The authoritative package-wide rule is:
  - GUI-generated Python source comes from a `python_source()` family path
  - `preview_python_source()` is acceptable when it is the preview form of that
    same path
  - `Do It` may send the already generated preview string
  - hidden/visible transport logs the final dispatched string
- The architectural target is not “every feature reruns `python_source()` on
  commit.” The target is “all GUI-generated Python is created through one
  authoritative source-generation path and logged at transport.”
- The broad cleanup should preserve the existing feature-family lowering seams:
  - generic Hyde commands in the Hyde feature codec layer
  - figure-family patch/export lowering in the matplotlib feature layer
  - lmfit lowering in the lmfit feature layer

Current findings by plugin family:

- Clearly compliant or acceptable under the clarified rule:
  - project-file dialogs and similar state-backed dialogs that generate preview
    text through `preview_python_source()` and then dispatch that exact cached
    string
  - the New Table dialog, which uses the same preview-backed pattern
  - direct state-dispatch paths that call `python_source()` immediately, such as
    runtime-command, namespace-mutation, and several table-mutation workflows
- Noncompliant because they generate Python without a `python_source()` family
  owner:
  - `Save Graphics...`, which lowers dialog widget state directly to a string
    through helper functions
- Noncompliant because they reuse good figure plumbing but still bypass a
  `python_source()` family path:
  - `Remove from Graph...`, which uses the shared figure session and figure
    patch lowering but commits through specialized patch helpers
  - `Curve Fit...`, which uses a state object for part of the workflow but still
    commits through specialized helper-generated command assembly and patch
    application rather than one authoritative `python_source()` family path
- Noncompliant because they expose direct codec/helper shortcuts alongside
  state-backed models:
  - figure and table convenience helpers such as `source_for_command(...)` that
    call codec `state_to_python(...)` directly
  - figure refresh/regenerate paths that generate helper strings directly and
    manually log them
- Noncompliant because they weaken observability rather than source generation:
  - kernel transport, which dispatches hidden and visible commands without
    logging the final command string

Specific examples of the current nonuniformity:

- `Save Graphics...`
  - direct widget-to-string lowering through dialog-local preview construction
  - helper lowering in the matplotlib feature layer
  - no authoritative `python_source()` family owner for export commands
- `Remove from Graph...`
  - uses the shared figure session and shared figure patch lowering
  - commit path runs through figure patch helpers instead of a
    `python_source()` family path
  - local manual logging compensates for missing transport logging
- `Curve Fit...`
  - mixes a state object with helper-built command assembly
  - attached-display updates and commit paths are not reduced to one
    authoritative `python_source()` family path
- Figure refresh/regenerate
  - helper-generated command string
  - manual logging
  - no authoritative `python_source()` owner
- Figure and table macro publication
  - helper shortcuts generate command strings directly instead of using the
    owning state object's `python_source()` family path
- Figure and table convenience helpers
  - `source_for_command(...)` helpers call codec `state_to_python(...)`
    directly
- Kernel transport
  - hidden and visible dispatch do not log the final command string

## Testing Decisions

- Good tests should verify the externally observable contract:
  - what command string is previewed
  - what command string is dispatched
  - what log line appears when a command is dispatched
- Tests should avoid asserting incidental helper boundaries when the same defect
  can be caught through preview text, transport-observable dispatch, or log
  output.
- Cached preview dispatch is acceptable. Tests should verify that the dispatched
  string matches the authoritative generated preview string, not that
  `python_source()` is rerun on `Do It`.
- Transport-layer logging tests should verify that raw dispatched commands are
  logged even when the feature itself does not log.
- Feature cleanup tests should verify that command generation comes from a
  `python_source()` family path rather than from direct codec or helper bypasses.
- Prior art should come from existing Hyde dialog tests, figure-patch tests,
  runtime command tests, and the export-graphics behavior tests.

## Out of Scope

- Redesigning Hyde’s public kernel API
- Changing the semantic meaning of existing figure patch or lmfit lowering
- Clipboard/copy export implementation
- Reworking every historical command-producing helper in one patch
- Defining a new serialization or persistence model for GUI state
- Requiring `Do It` to rerun `python_source()` when it is already dispatching the
  exact generated preview string

## Further Notes

- The export-graphics work exposed this issue, but the problem is package-wide.
- The broad cleanup should likely proceed in layers:
  - first make transport logging authoritative
  - then move the most visible violating features onto proper
    `python_source()`-family generation paths
  - then clean up convenience helpers and manual logging remnants
- Near-term export-graphics follow-up does not need to solve the entire
  package-wide inconsistency. It does need to bring `Save Graphics...` at least
  up to the current figure-patch family level and align the logging behavior
  with the transport-layer target.
