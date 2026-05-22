---
name: hyde-code-review
description: Review Hyde diffs, pull requests, and local changes using Hyde-specific architectural standards in addition to normal code review behavior. Use when Codex reviews Hyde application code, tests, or specs and must enforce the smallest clear patch rule, the `features/..._features.py` command-generation boundary, Hyde's kernel-authoritative command-driven model, and concise contract-focused tests.
---

# Hyde Code Review

Use this skill to add Hyde architectural enforcement on top of the default review behavior.

Keep the normal review structure: findings first, ordered by severity, with file/line references where available. Treat Hyde-compliance failures as real findings even when the patch appears functionally correct.

## Required Context

Read these Markdown sources before finalizing a review:

1. `AGENTS.md`
2. `project_management/ARCHITECTURE.md`
3. `project_management/STYLE.md`
4. `project_management/PLAN.md`
5. `project_management/STATUS.md`
6. [references/hyde-review-standards.md](references/hyde-review-standards.md)

Then read only the relevant feature/spec Markdown files for the patch under review. Prioritize:

- `project_management/specs/IPC_PROTOCOL.md`
- `project_management/specs/python_terminal/SPEC.md`
- `project_management/specs/project_save_load/SPEC.md`
- `project_management/specs/new_table_dialog/SPEC.md`
- `project_management/specs/data_browser/SPEC.md`
- `project_management/specs/table/SPEC.md`

Prefer Hyde's Markdown architecture and spec files over legacy implementation details. Do not excuse a patch by appealing to existing non-compliant code.

## Review Posture

- Start from the normal code review posture: find bugs, regressions, architectural risks, and missing tests.
- Elevate over-complexity, command-path violations, split ownership, and non-minimal design to the same level as correctness issues.
- Review tests with the same rigor as application code.
- Bias toward narrow, local fixes that preserve Hyde's documented architecture.

## Hyde Review Questions

Ask these questions explicitly while reviewing:

- Is this the smallest clear change?
- Has the patch kept static dialog/window structure in `.ui` files where Hyde expects
  `.ui`-first layout ownership?
- Does the GUI only generate command strings and react to kernel results?
- Are GUI-triggered kernel command strings generated in `features/..._features.py` rather than in GUI widgets, dialogs, or runtime helpers?
- Is there exactly one authoritative implementation path?
- Does the patch preserve Hyde's two-process, command-driven model?
- Are the tests concise and aligned with intended behavior rather than incidental structure?

## Findings To Raise

Raise findings for any of the following:

- unnecessary abstractions, speculative refactors, broad cleanups, extra state machines, or single-use helpers that are not required for the task
- large static dialog or tool-window layouts hand-built in Python when they should be
  defined in `.ui` files, unless there is a clear runtime-widget exception
- GUI-built kernel command strings outside the `features/..._features.py` translation layer
- direct imperative GUI-to-backend behavior where Hyde should have used a visible or deliberate kernel command path
- patches that create separate GUI and non-GUI implementations of the same feature
- backend or kernel ownership drifting into the GUI layer
- redundant state, compatibility shims, defensive policy, or fallback behavior that Hyde did not request
- tests that are verbose, brittle, tightly coupled to helper structure, or written around workaround behavior instead of Hyde's intended contract

## Output Rules

- Present findings first.
- Keep summaries brief and secondary.
- If no findings are discovered, say so explicitly and note any residual risk or testing gaps.
- When a review concern is architectural rather than purely functional, say that directly.
- When appropriate, cite the Hyde Markdown document that establishes the requirement.
