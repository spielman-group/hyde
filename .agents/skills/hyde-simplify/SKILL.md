---
name: hyde-simplify
description: Simplify Hyde patches, plans, and local changes to the smallest clear patch that still satisfies Hyde's documented architecture. Use when Codex is planning a Hyde implementation, trimming an overbuilt patch, collapsing unnecessary helpers or abstractions, or doing a simplification pass before or after broader code review.
---

# Hyde Simplify

Use this skill for a narrow simplification pass, not for a full code review.

The goal is to reduce a Hyde change to the smallest clear shape that preserves the documented architecture, command path, and user-visible behavior.

This skill is used in two common places:

- after `to-issues`, to simplify the planned slices before implementation starts
- after implementation, to simplify the resulting code patch

In the standard dialog workflow that means:

1. `add-hyde-ui-feature`
2. `grill-me`
3. `to-prd`
4. widget-shape skill plus `to-issues`
5. `hyde-simplify`
6. implementation with `tdd` plus the widget-shape skill

## Required Context

Read these Markdown sources before simplifying:

1. `AGENTS.md`
2. `project_management/ARCHITECTURE.md`
3. `project_management/STYLE.md`
4. `project_management/PLAN.md`
5. `project_management/STATUS.md`
6. [references/hyde-simplification-rules.md](references/hyde-simplification-rules.md)

Then read only the feature/spec Markdown files relevant to the change. Prioritize:

- `project_management/specs/IPC_PROTOCOL.md`
- `project_management/specs/python_terminal/SPEC.md`
- `project_management/specs/project_save_load/SPEC.md`
- `project_management/specs/new_table_dialog/SPEC.md`
- `project_management/specs/data_browser/SPEC.md`
- `project_management/specs/table/SPEC.md`

Prefer Hyde's Markdown docs over inherited implementation shape. Existing code is not a justification for keeping non-essential complexity.

## Simplification Workflow

1. Restate the minimum required behavior.
2. Identify the Hyde architectural constraints that are actually binding.
3. Strip away everything not required by that behavior and those constraints.
4. Prefer editing an existing function, module, queue, thread, or command path over adding a new one.
5. Collapse duplicated or split ownership until one clear authoritative path remains.
6. Keep only the tests needed to prove the intended contract.
7. If you are simplifying an issue file or implementation plan, delete slices that
   only preserve base-class shims, duplicate launcher dispatch, or split one dialog
   command path into multiple near-identical variants.

## What To Simplify

Simplify aggressively when you see:

- single-use private helpers
- wrapper layers that only rename or forward behavior when removing them actually makes the code smaller or clearer overall; keep small wrappers that preserve domain clarity or avoid expanding call sites
- repeated call-site logic that would become shorter and clearer with one small domain wrapper
- new abstractions without repeated call sites
- broad refactors mixed into a narrow task
- large static dialog or tool-window layouts assembled in Python instead of being moved
  into `.ui` files
- extra state variables, flags, or policy branches
- GUI-side behavior that should be a command string plus kernel-owned execution
- separate GUI and non-GUI implementations of the same user-visible behavior
- verbose tests that mirror plumbing rather than contract
- dialog plans that fail to use the standard `HydeDialogWidget` footer contract when
  the spec does not require an exception
- duplicate ownership or presentation-policy paths that are already decided in the
  docs or active spec
- new abstractions whose main effect is to restate feature policy already documented
  elsewhere

## Hyde Simplification Questions

Ask these questions explicitly:

- What is the smallest clear change that satisfies the request?
- Can this be done inside an existing function or module instead of a new helper?
- Should this static UI structure live in a `.ui` file instead of Python code?
- Can an existing queue, thread, IPC path, or public command carry this behavior?
- Is the GUI doing anything beyond collecting UI state, generating a command string, and reacting to kernel results?
- Has the patch created two implementation paths where Hyde should have one?
- Does this dialog really need an exception to the shared `HydeDialogWidget` footer
  contract, or is the plan keeping a subclass shim for no reason?
- Am I restating feature policy in code, issue slices, or new abstractions when the
  governing docs/spec already answer it?
- If I remove this wrapper, does the total code actually get shorter or clearer, or am I just pushing the same lines outward into call sites?
- Would one small wrapper make the total code shorter or clearer by collapsing repeated call-site logic?
- Do the tests prove the contract with less structure and fewer incidental assertions?

## Boundaries

- Do not broaden this pass into a general bug hunt unless the user asks.
- Do not preserve complexity just because it is already present in code.
- Do not invent new framework or infrastructure to "clean things up."
- Do not add compatibility shims, fallback behavior, or speculative edge-case handling unless explicitly required.

## Output Rules

- If you are simplifying a proposal or patch, present the smaller shape first.
- Name what should be deleted, inlined, merged, or moved.
- Call out any complexity that is architecturally wrong even if it appears to work.
- When useful, cite the Hyde Markdown document that makes the simpler path possible or required.
