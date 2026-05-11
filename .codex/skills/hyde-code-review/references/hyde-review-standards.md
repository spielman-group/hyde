# Hyde Review Standards

Use this reference to turn Hyde's architecture and spec documents into concrete review checks.

## Source Priority

Prioritize sources in this order:

1. explicit user direction
2. `AGENTS.md`
3. `project_management/ARCHITECTURE.md`
4. relevant `project_management/specs/**/*.md`
5. `project_management/STYLE.md`
6. `project_management/PLAN.md` and `project_management/STATUS.md`

Do not treat the current implementation as authoritative when it conflicts with the Markdown docs. Hyde is still being actively corrected and refactored.

## Core Architectural Frame

Apply these Hyde rules throughout the review:

- The GUI is a dumb viewport for scientific state.
- The GUI is a string factory for user actions.
- The kernel execution namespace is authoritative.
- Public Hyde commands remain authoritative.
- The `features/...` layer is reserved for GUI representation to Python strings, and Python strings or metadata back to GUI representation.
- Hyde is intentionally early-stage, so bias against speculative infrastructure, compatibility shims, and invented policy.

Hyde currently operates as two processes plus an existing GUI-owned helper thread. Treat that helper thread as a narrow in-process detail, not as a license to create a second backend or a second authoritative execution path.

## 1. Smallest Clear Patch

Flag a patch when it solves the immediate bug or feature request with more machinery than Hyde needs.

Raise findings for:

- single-use private helpers that only hide a short local change
- new abstraction layers without repeated call sites or a real architectural need
- broad cleanup or refactor mixed into a narrow feature change
- extra queues, threads, processes, watchers, relays, or state machines when an existing path could carry the behavior
- compatibility shims, migration paths, or fallback behavior that the user did not request
- defensive policy decisions that are not grounded in Hyde docs or the task

Treat "functionally valid but overbuilt" as a real review issue.

## 2. `features/..._features.py` Owns Command Strings

The review should enforce the documented translation boundary.

Raise findings when GUI-triggered kernel actions are expressed by:

- command strings built directly in widgets, dialogs, windows, menus, or runtime helpers
- direct imperative GUI calls into backend behavior when Hyde should have emitted a command string
- helper APIs created in the GUI layer purely to avoid generating the documented command string

Accept patches that keep GUI-facing translation in `features/..._features.py` modules and keep GUI code focused on collecting UI state, dispatching the command, and reacting to results.

## 3. Preserve One Authoritative Implementation Path

Flag any patch that effectively creates separate implementations for GUI mode and non-GUI mode, or separate public and GUI-only execution paths.

Raise findings when:

- the same user-visible feature has one path through public Hyde commands and a second hidden path for the GUI
- GUI mode behaves differently from non-GUI mode in a way that creates two implementation paths rather than one authoritative command path
- the patch introduces GUI-only work that should have remained kernel-owned
- the GUI starts owning scientific state, serialization, analytical transformations, or business logic that the kernel should own

Prefer: GUI sends command, kernel executes, GUI reacts.

Reject: GUI partially executes feature logic locally and only uses the kernel for the remainder.

## 4. Command-Driven Architecture

Public Hyde commands such as `hyde.load_project(...)`, `hyde.save_project(...)`, `hyde.new_project(...)`, and `hyde.quit()` should remain authoritative command paths when the feature is in their scope.

Raise findings when:

- the GUI bypasses those public commands with hidden implementation shortcuts
- a patch adds a GUI-only orchestration path that is not reproducible through terminal text
- runtime-helper behavior replaces the public visible command contract instead of supporting it
- a feature mixes ownership so that neither the GUI nor the kernel is clearly authoritative

The guiding question is whether the full user action remains reproducible as a human-readable Hyde/Python command plus kernel-driven results.

## 5. Avoid Redundant State And Invented Policy

Flag redundant or speculative state management.

Raise findings when:

- new state duplicates existing Hyde state or derives from data Hyde already tracks elsewhere
- GUI state is retained beyond what is needed to generate commands or render the viewport
- fallback policy, hidden defaults, or extra defensive checks are introduced without architectural or user-driven justification
- compatibility logic is added for superseded designs in an early-stage codebase

Hyde is biased toward explicit, current behavior, not transitional infrastructure.

## 6. Review Tests Too

Always review tests, not just application code.

Prefer tests that are:

- concise
- contract-focused
- grounded in public behavior and documented architecture
- targeted at the smallest behavior that proves the requirement
- capable of failing for the real running-system defect they claim to cover

Raise findings for tests that:

- encode incidental helper structure or call sequencing that is not the real contract
- mirror workaround behavior rather than intended Hyde behavior
- become verbose because the implementation is over-factored
- validate private plumbing when a public command or documented flow would test the requirement more directly
- assert imports, mocks, or callback order while leaving the actual user-visible or
  contract-visible behavior untested

When the architecture is the contract, it is valid to test that contract. For example:

- command generation belongs to the documented translation layer
- public Hyde commands remain the visible authoritative path
- GUI-only paths do not replace kernel-owned behavior

## Review Checklist

Use this quick pass before finalizing the review:

1. Identify the user-visible behavior change.
2. Map that behavior to the authoritative Hyde Markdown docs.
3. Check whether the patch took the smallest clear path.
4. Check whether GUI actions still resolve to command strings through the documented translation layer.
5. Check whether the kernel remains authoritative and the GUI remains a viewport/string factory.
6. Check whether the patch created a second implementation path or a hidden bypass.
7. Check whether new state or policy is actually required.
8. Check whether the tests verify the contract concisely.
9. Check whether each test would fail for the defect it is meant to prevent.

## Spec Selection Guide

Load additional Markdown specs only when relevant:

- Read `project_management/specs/IPC_PROTOCOL.md` for process ownership, runtime-helper boundaries, and command-path rules.
- Read `project_management/specs/command_window/SPEC.md` for visible user command behavior versus silent runtime-helper execution.
- Read `project_management/specs/project_save_load/SPEC.md` for authoritative public save/load command paths.
- Read `project_management/specs/new_table_dialog/SPEC.md` for string-factory behavior in a GUI dialog.
- Read `project_management/specs/data_browser/SPEC.md` for viewport-only and command-source behavior.
- Read `project_management/specs/table/SPEC.md` for kernel-authoritative editing and synchronization.
