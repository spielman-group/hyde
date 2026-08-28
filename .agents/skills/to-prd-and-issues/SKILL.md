---
name: to-prd-and-issues
description: Turn the current conversation findings, review notes, or implementation plan into a root-level ISSUES_PRD.md and then ISSUES.md by explicitly chaining the to-prd and to-issues skills. Use this whenever the user asks to convert findings into a PRD plus issue plan, asks for "ISSUES_PRD.md and ISSUES.md", or wants a fresh-agent kickoff prompt from review findings. This skill depends on to-prd and to-issues being available in the active skill list and must fail fast if either dependency is missing.
metadata:
  uuid: "82641e89-99e6-4345-ad3f-6dcd09c36800"
---

# To PRD And Issues

Convert the current conversation context into a PRD artifact, derive an issue
plan from it, and finish with a reusable prompt for a fresh agent to execute the
work with fresh subagents.

## Dependency Preflight

Before taking any task action, verify that both dependency skills are visible in
the active skills list for the current turn:

- `to-prd`
- `to-issues`

If either skill is absent, stop immediately. Tell the user which dependency is
missing and that `to-prd-and-issues` cannot run without both dependency skills
in scope. Do not draft fallback PRDs or issue plans by hand when the dependency
skills are missing.

When both are present, announce that you are using `to-prd` first and
`to-issues` second.

## Workflow

1. Preserve the user's current findings, review notes, or plan as the source of
   truth. If the current conversation already contains enough detail, do not
   interview the user.

2. Use `to-prd` to create a PRD from the current context. Direct it to write the
   artifact to the repository root as:

   ```text
   ISSUES_PRD.md
   ```

   The PRD should describe the problem, solution, user stories, implementation
   decisions, testing decisions, out-of-scope work, and notes in the style
   required by `to-prd`. Keep it focused on the findings or plan that triggered
   this skill.

3. Use `to-issues` on `ISSUES_PRD.md` to create a vertical-slice issue plan.
   Direct it to write the artifact to the repository root as:

   ```text
   ISSUES.md
   ```

   Respect `to-issues` slice structure: dependency-ordered slices, `AFK`/`HITL`
   type, acceptance criteria, blockers, user stories covered, and a checklist at
   the top.

4. After both files exist, read them back or otherwise verify they were written
   at the requested paths. If an existing `ISSUES.md` or `ISSUES_PRD.md` has
   unrelated user content, do not overwrite it without explicit user approval.

5. Provide a fresh-agent kickoff prompt in the final response. The prompt should
   be ready to paste into a new Codex thread and should explicitly instruct the
   fresh agent to:

   - Read `AGENTS.md` first, follow its project-specific read-first guidance,
     then read `ISSUES_PRD.md` and `ISSUES.md`.
   - Work through `ISSUES.md` in dependency order.
   - Use a fresh subagent for each issue or slice.
   - Keep each subagent scoped to one slice.
   - Use TDD for implementation slices.
   - Preserve unrelated worktree changes.
   - Run the relevant tests and architecture guard for each completed slice.
   - Commit each completed slice according to the repository instructions.
   - Report commit hashes, tests run, and remaining risks.

## Fresh-Agent Prompt Template

Use this template and fill in any project-specific context from the generated
files:

```text
We are moving this project through the cleanup plan in ISSUES.md.

First read AGENTS.md and follow its project-specific read-first guidance. Then
read ISSUES_PRD.md and ISSUES.md. Treat ISSUES_PRD.md as the
product/architecture source and ISSUES.md as the implementation checklist.

Work through ISSUES.md in dependency order. For each slice, spawn a fresh
subagent dedicated only to that slice; do not reuse subagents between slices.
Have each subagent use TDD through the public CLI/core interface where the
behavior is not visual, preserve unrelated worktree changes, and keep the patch
scoped to the slice.

After each subagent completes a slice, review the changes, run the relevant
tests and architecture guard, update the ISSUES.md checklist, stage only files
belonging to that slice, and commit with the repository's required slice commit
message. Continue until all unblocked AFK slices are complete or a real blocker
requires user input.

End with commit hashes, tests run, remaining risks, and any HITL decisions that
still need me.
```

## Final Response

Keep the final response short. Include:

- The paths written.
- Any dependency or overwrite issues encountered.
- The fresh-agent kickoff prompt.
- Any tests or validation commands run.
