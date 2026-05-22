# Hyde Simplification Rules

Use this reference to force a smallest-clear-patch pass for Hyde.

## Source Priority

Prioritize sources in this order:

1. explicit user direction
2. `AGENTS.md`
3. `project_management/ARCHITECTURE.md`
4. relevant `project_management/specs/**/*.md`
5. `project_management/STYLE.md`
6. `project_management/PLAN.md` and `project_management/STATUS.md`

Treat the Markdown docs as the intended system. Do not keep unnecessary complexity just because the current codebase contains it.

## Core Simplification Bias

Bias toward:

- one clear implementation path
- one authoritative owner
- local edits inside existing modules
- explicit command strings instead of helper indirection
- reuse of existing queues, threads, relays, and public commands
- concise contract-focused tests
- static plugin dialog/window structure living in `.ui` files rather than Python-built
  layout trees

Bias against:

- extra helpers that are only used once
- abstraction layers added before they are needed
- duplicated GUI and kernel logic
- invented policy or defensive behavior
- speculative infrastructure
- compatibility shims
- hand-built static widget trees in Python where a `.ui` file should own the layout
- tests that depend on internal choreography

## 1. Find The Irreducible Requirement

Before simplifying, identify:

- the exact user-visible behavior that must remain
- the Hyde architectural rules that are non-negotiable
- the smallest public contract the tests need to prove

Anything else is a candidate for deletion or collapse.

## 2. Prefer Local Edits Over New Helpers

In Hyde, a 10-20 line edit inside an existing module is usually preferable to:

- a new single-use private helper
- a new adapter or manager object
- a new state flag
- a new protocol or watcher
- a new thread/process/service

Add a helper only when it clearly removes repeated logic or marks a real architectural boundary already present in Hyde's docs.

## 3. Collapse Back To The Command Path

When simplifying GUI-related work, pull behavior back toward Hyde's documented command flow:

- GUI collects transient UI state
- `features/..._features.py` generates the human-readable Python string
- kernel or public Hyde command performs the authoritative work
- GUI reacts to metadata, relays, or command results

If the patch performs substantive feature logic in the GUI, ask whether that logic should instead be expressed as command generation plus kernel execution.

## 4. Remove Split Ownership

Simplify away any patch shape that leaves ownership ambiguous.

Common bad shapes:

- GUI path for one mode, kernel path for another
- public command path plus hidden GUI-only shortcut
- runtime helper doing work that should stay in the visible public command path
- both GUI and kernel each carrying part of the same feature logic

Prefer one authoritative implementation path and one clear owner.

## 5. Eliminate Redundant State And Policy

Delete or avoid:

- state duplicated from existing Hyde state
- caches of scientific state in the GUI
- fallback behavior not required by the request
- speculative checks for unsupported futures
- migration logic for superseded designs

Hyde is early-stage. Simpler explicit behavior is better than transitional machinery.

## 6. Simplify Tests With The Same Rigor

Tests should prove the contract, not the incidental structure.

Prefer tests that:

- target the public command path or documented architecture boundary
- assert the minimal observable behavior
- avoid depending on helper names, call choreography, or temporary plumbing
- become shorter as the implementation becomes smaller

When a test is long because the implementation is over-factored, simplify the implementation first if possible.

## Simplification Checklist

Use this pass before finalizing:

1. What must remain?
2. What can be deleted entirely?
3. What can be inlined into an existing function or module?
4. What can be merged back into an existing command path?
5. What state, policy, or abstraction is speculative?
6. Where has ownership split across GUI and kernel?
7. Can the tests prove the same contract with fewer moving parts?

## Suggested Uses

Use this skill:

- before implementation, to choose the narrowest Hyde-compliant approach
- during implementation, when a patch starts to grow extra helpers or infrastructure
- after implementation, to trim an overbuilt patch before or after full review
- when a code review found "works, but overbuilt" and the next task is to shrink it
