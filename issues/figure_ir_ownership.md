# Figure IR Ownership PRD

## Problem Statement

Hyde's first-class figure system has one intended authority path, but figure ownership is currently blurred across multiple plugins. The figure feature owns kernel-side IR and semantic `comm` actions, yet consumer plugins still read raw figure IR, maintain local figure-semantic draft state, lower preview source directly, and construct figure action payloads themselves.

This makes the figure feature harder to evolve because semantic figure behavior is split across `figure_interactive`, `figure_control_dialog`, and `curve_fit_dialog`. It also keeps duplication alive between the figure IR path and plugin-local figure-edit logic.

## Solution

Establish a single figure-owned edit-session boundary for first-class figures.

The figure system keeps ownership of figure semantics, action construction, dispatch, draft lifecycle, preview generation, and revert behavior. Consumer plugins stop working with raw figure IR and instead open one consumer-agnostic figure session from the figure context. That session exposes fine-grained getters plus matplotlib-aligned mutating methods, with a small number of structured bulk methods where they map to real figure concepts.

The resulting boundary should be small, non-Qt, ephemeral per dialog opening, and easy to merge into a larger unified figure object later without changing the conceptual ownership split.

## User Stories

1. As a Hyde developer, I want first-class figure semantics to stay owned by the figure system, so that figure behavior can evolve in one authoritative place.
2. As a Hyde developer, I want consumer plugins to stop reading raw figure IR, so that they cannot silently reimplement figure semantics locally.
3. As a Hyde developer, I want consumer plugins to stop constructing raw figure action payloads, so that the figure action protocol remains internal to the figure system.
4. As a Hyde developer, I want one `open_session()` figure entry point, so that the figure system stays consumer-agnostic.
5. As a Hyde developer, I want the session object to be non-Qt, so that figure semantics remain testable without dialog wiring.
6. As a Hyde developer, I want the session to own opening state, draft state, revert state, and dirty tracking, so that edit-session lifecycle is no longer duplicated in dialogs.
7. As a Hyde developer, I want preview and lowered source generation to come from the session boundary, so that dialogs do not choose their own lowering path.
8. As a user editing axes, I want axis dialogs to keep their current behavior, so that ownership cleanup does not regress the editing workflow.
9. As a user editing trace appearance, I want trace styling dialogs to keep live updates and cancel rollback, so that the tool still feels interactive.
10. As a user using Curve Fit against an attached figure, I want fit/residual display traces to remain stable and recoverable, so that figure-attached fit display is predictable.
11. As a Hyde developer, I want attached display trace lifecycle to be figure-owned policy, so that non-figure plugins do not become trace managers.
12. As a Hyde developer, I want the session API to use matplotlib-aligned names where practical, so that the boundary reads like figure semantics instead of plugin semantics.
13. As a Hyde developer, I want consumers to use fine-grained getters and compose their own higher-level helpers, so that the figure service does not presume consumer types.
14. As a Hyde developer, I want the first pass to cover only current figure consumers, so that the refactor stays narrow and tracer-bullet sized within a broader program.
15. As a Hyde developer, I want the design centered on first-class `figure_ir` figures, so that split-authority fallback paths do not shape the new boundary.

## Implementation Decisions

- Figure semantic ownership remains split across two existing Hyde layers:
  - the feature layer owns figure codec and IR semantics
  - the figure plugin owns the runtime/UI boundary and session entry point
- Consumer plugins must stop working with raw figure IR as a public contract.
- `EditableFigureContext` exposes a single `open_session()` entry point instead of consumer-specific session factories.
- The returned session is consumer-agnostic and does not encode axis-dialog, trace-dialog, or curve-fit-specific types in its public contract.
- The session exposes fine-grained read methods and matplotlib-aligned write methods where practical.
- A small number of structured bulk methods are allowed when they correspond to real figure concepts and materially reduce call-site complexity.
- The session owns:
  - figure action construction
  - dispatch to the figure action path
  - opening/current/revert draft lifecycle
  - dirty tracking
  - preview/source generation
  - live apply, commit, and revert behavior
- Consumer plugins may build higher-level local helpers on top of session getters and methods, but they do not own figure-semantic state or protocol details.
- Attached-display trace lifecycle for Curve Fit is figure-owned policy parameterized by curve-fit intent.
- Sessions are ephemeral per dialog opening rather than persistent per figure.
- The refactor should cover current figure consumers only and avoid speculative future-generalization.
- The design should be written so that separate internal service shapes can later be merged into a larger unified figure object without changing the public ownership model.

## Testing Decisions

- Good tests should verify figure-facing behavior and session contracts rather than incidental helper structure.
- Tests should prove that consumer plugins no longer need raw IR or raw action payload construction for the covered workflows.
- Tests should focus on externally meaningful contracts:
  - session getters reflect the current first-class figure state
  - session mutators produce the expected live figure behavior and preview/source
  - cancel/revert restores prior figure state
  - attached display trace management remains stable under apply/revert/collision scenarios
- Priority modules to test:
  - figure session boundary and lifecycle behavior
  - axis-edit integration through the new session boundary
  - trace-appearance integration through the new session boundary
  - curve-fit attached-display integration through the new session boundary
- Existing first-class figure, comm-action, axis dialog, trace dialog, and curve-fit tests provide prior art for behavior-focused coverage.

## Out of Scope

- General redesign of non-first-class or legacy live-state figure paths
- Multi-subplot/GridSpec figure editing
- New figure-edit surfaces beyond current consumers
- Broader Curve Fit product growth outside attached display ownership cleanup
- UI redesign of the existing dialogs
- Speculative general framework work for hypothetical future consumers

## Further Notes

- This PRD describes the first step in a broader figure-ownership program.
- The immediate goal is to stop ownership leakage, not to finalize the entire long-term figure architecture in one patch.
- The new session boundary should make later consolidation easier, not harder.
