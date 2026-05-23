# Hyde Review Standards

Use this reference to keep `hyde-code-review` in the right posture.

## Source Discipline

Anchor the audit in Hyde's Markdown docs, not in current implementation shape.

Use this priority:

1. explicit user direction
2. `AGENTS.md`
3. `project_management/ARCHITECTURE.md`
4. `project_management/IR-CONTROL.md`
5. relevant feature/spec docs
6. `project_management/STYLE.md`
7. `project_management/PLAN.md`
8. `project_management/STATUS.md`

## Review Discipline

- Start with runtime behavior where practical.
- Treat runtime design-seam violations as more important than code-shape complaints.
- After the runtime pass, look deliberately for duplicated behavior and missed shared
  seams in the changed area and nearby code.
- Audit changed and nearby tests for drift away from Hyde's behavior-first testing
  rule. Flag tests that primarily assert private state, private methods, helper
  wiring, or incidental lowering shape when a real contract could be exercised
  instead.
- Keep deeper architectural opportunities separate from the near-term cleanup path.
- Make the final section specific enough to hand off into `to-prd`.

## What Good Evidence Looks Like

Prefer:

- targeted tests
- emitted command strings
- live execution traces
- observed GUI/backend behavior

Use static inspection to support or extend the evidence, especially when the runtime
path is too expensive or unavailable.

## Output Discipline

- Always use the three fixed sections from the skill.
- Order runtime violations by severity.
- Cite Hyde docs to the extent possible instead of re-explaining them.
- Keep the report concise.
- End with the `to-prd` handoff question.
