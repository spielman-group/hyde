---
name: hyde-code-review
description: Audit finished Hyde work for runtime design-document violations, missed reuse and refactor seams, and a PRD-ready path forward. Use at the end of a feature, refactor, or bugfix when Codex should inspect the changed area against Hyde docs, prefer runtime evidence where possible, and optionally hand off the resulting path forward to to-prd.
---

# Hyde Code Review

Use this skill at the end of Hyde development work.

This is a report-only audit skill. It does not instruct the agent to make fixes. Its
job is to:

1. find runtime design-document violations first
2. find missed reuse and refactor opportunities second
3. design a PRD-ready path forward

If the task is to shrink a plan or patch rather than audit it, use `hyde-simplify`
instead.

## Required Context

Read these Markdown sources every time:

1. `AGENTS.md`
2. `project_management/ARCHITECTURE.md`
3. `project_management/IR-CONTROL.md`
4. `project_management/STYLE.md`
5. `project_management/PLAN.md`
6. `project_management/STATUS.md`
7. [references/hyde-review-standards.md](references/hyde-review-standards.md)

Then read the feature/spec docs for the changed area only. Expand to nearby features
only when the audit reveals a real cross-feature seam.

Do not restate Hyde policy from memory when the Markdown docs can be cited directly.

## Default Scope

Start with the changed area plus nearby impacted code.

Do a broader sweep only when:

- the user asks for one
- the first pass reveals a repeated runtime violation pattern
- the first pass reveals a repeated missed shared seam

## Evidence First

Prefer runtime evidence over static suspicion whenever practical:

- run targeted tests
- inspect emitted command strings
- trace the live execution path
- verify actual GUI or backend behavior when that is the contract

Use static code inspection to explain or extend a finding, not to replace available
runtime evidence.

## Test Audit

Audit nearby tests as part of the review, especially tests added or changed by the
task.

Treat these as review targets when they are not required by the real contract:

- assertions against private flags, caches, or in-flight markers
- direct calls to private widget or controller methods
- tests that prove helper wiring, call order, or temporary lowering shape instead of
  user-visible behavior
- tests that assert exact internal command fragments when the real contract is only a
  broader interface property
- mock-heavy tests that could exercise the same behavior through the real product
  surface

General rule: ask what defect the test would catch in the running application. If the
answer is only "this implementation changed," treat it as a test-quality finding.

Do not flag legitimate architecture-contract tests as implementation-detail tests. It
is still valid to test stable public APIs, documented emitted strings, debug logging
contracts, shared shell contracts, or runtime metadata that Hyde explicitly treats as
part of the product surface.

## Audit Workflow

### 1. Runtime Boundary Violations

Inspect the changed area first for live Hyde seam violations.

Priorities:

- runtime ownership violations
- command-path violations
- translation-boundary violations
- split authoritative paths
- GUI/kernel drift that is visible in running behavior

Order this section by runtime severity. For each item, include:

- the concrete problem
- the evidence
- the file reference
- the governing Hyde doc, to the extent possible

### 2. Reuse And Refactor Opportunities

After the runtime pass, do a second deliberate pass for duplicated behavior and missed
shared seams, even when the code is otherwise legal.

Include test-shape problems here when the issue is not a live runtime violation but a
missed chance to express the contract through a better shared or more behavioral test
surface.

Focus first on clear, near-term consolidations justified by the changed area.

If the local audit exposes a deeper architectural opportunity, include it here or in
the next section, but keep it separate from the immediate cleanup path.

For this section, and for the deeper architecture part of the next section, use the
shared vocabulary from:

- `/Users/ispielma/.agents/skills/improve-codebase-architecture/LANGUAGE.md`

Use that vocabulary only when discussing reuse, refactoring, seams, leverage, depth,
and locality. Use plain Hyde language for runtime violations.

### 3. Path Forward

Produce a PRD-ready path forward, not just a generic recommendation.

Each path-forward item should make clear:

- what seam or ownership location should change
- what should consolidate
- what should stay where it is
- what the narrow next step is
- whether the item is near-term cleanup or a deeper follow-on opportunity

Keep this section shaped so it can hand off cleanly into `to-prd` and then
`to-issues`.

## Parallel Exploration

When subagents are available, parallelize only across distinct audit surfaces such as:

- runtime evidence gathering
- nearby-code reuse and refactor exploration
- nearby-test audit for implementation-coupled tests

Do not split one tight reasoning thread across multiple subagents for no gain.

## Output Structure

Always use these three sections in this order:

1. `Runtime Boundary Violations`
2. `Reuse And Refactor Opportunities`
3. `Path Forward`

If a section has no items, say so explicitly.

## Output Rules

- In `Runtime Boundary Violations`, order items by runtime severity.
- Prefer concrete evidence and file references.
- Cite the governing Hyde Markdown doc for each item to the extent possible.
- Do not restate Hyde design-document content when a direct document reference is
  enough.
- Treat architecturally wrong live behavior as a real finding even if tests happen to
  pass.
- Include test-quality findings when changed or nearby tests drift away from Hyde's
  behavior-first testing rule.
- Keep the report concise and actionable.
- End by asking whether to turn the `Path Forward` section into a PRD with `to-prd`.

## Boundaries

- This skill is report-only.
- Do not silently broaden into a repo-wide architecture survey unless the user asks or
  the local audit clearly justifies it.
- Do not turn the report into a rewrite plan for every possible improvement.
- Do not duplicate Hyde document content inside the audit when citing the doc is
  sufficient.
