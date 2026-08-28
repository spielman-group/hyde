---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable markdown work items under the repo's issues/ directory using tracer-bullet vertical slices. Use when user wants to convert a plan into issues, create implementation tickets, or break down work into issues.
metadata:
  uuid: "f3ed88b9-aa26-4d5b-a013-9e10cc335ff0"
---

# To Issues

Break a plan into independently-grabbable markdown work items using vertical slices (tracer bullets).

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes a local markdown path, read it in full.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Issue titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

### 3. Draft vertical slices

Break the plan into **tracer bullet** issues. Each issue is a thin vertical slice that cuts through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Slices may be 'HITL' or 'AFK'. HITL slices require human interaction, such as an architectural decision or a design review. AFK slices can be implemented and merged without human interaction. Prefer AFK over HITL where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Prefer many thin slices over few thick ones
</vertical-slice-rules>

When the plan involves code developed with TDD, include a final or near-final
`test-cleanup` slice. That slice must use the test-cleanup skill to remove or
rewrite leftover TDD scaffolding tests that over-constrain implementation
details. The expected outcome is to remove almost all tests that only served the
development loop, while preserving durable tests that enforce desired behavior,
public interfaces, or intentional seams. Do not treat the test-cleanup slice as
a broad coverage deletion pass; it should leave behind the smallest useful
behavioral safety net for future changes.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Type**: HITL / AFK
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories this addresses (if the source material has them)

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are the correct slices marked as HITL and AFK?

Iterate until the user approves the breakdown.

### 5. Write the work-item markdown artifact

For the approved slices, write a markdown file under `issues/`. Use a user-provided filename when available. Include a checklist at the top that lists every slice title so progress can be tracked in one place.

List slices in dependency order (blockers first).

<issue-template>
## Slice N: <Title>

### Type

`AFK` or `HITL`

### What to build

A concise description of this vertical slice. Describe the end-to-end behavior, not layer-by-layer implementation.

Avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it here and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.

### Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

### Blocked by

- Slice title(s) this depends on, if any

Or "None - can start immediately" if no blockers.

### User stories covered

- List the relevant user stories or PRD sections this slice covers.

</issue-template>

Keep the output focused on the local markdown artifact.
