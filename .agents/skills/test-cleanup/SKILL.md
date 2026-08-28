---
name: test-cleanup
description: Clean up test suites after TDD or agent-driven development by removing or rewriting tests that pin implementation details, one-off bug histories, temporary guardrails, or test harness/tooling probes. Use when tests should be converted into durable user-facing behavior tests, public API/CLI contract tests, or library interface tests that survive refactors, UI rewrites, ports, and algorithm changes.
metadata:
  uuid: "1bec3ecd-efc7-4beb-9003-a4a7d7bad5b4"
---

# Test Cleanup

## Goal

Convert temporary development tests into durable tests of public behavior and interfaces.
Treat implementation-coupled TDD tests as scaffolding: useful during red/green work, but
not automatically worth keeping after the behavior is implemented.

## Workflow

1. Identify the public contract before editing tests.
   - Frontend: visible text, accessible roles/names, keyboard and pointer interactions, form behavior, menu/dialog behavior, and user-visible state changes.
   - CLI: command names, arguments, exit status, stdout/stderr, JSON schemas, filesystem effects, and documented examples.
   - Library/core: exported function signatures, documented data contracts, errors, side effects, and behavior through public APIs.

2. Classify each suspect test.
   - Keep: tests that would fail when the public behavior breaks.
   - Rewrite: tests that assert a real behavior through private structure, CSS selectors, exact DOM shape, mocks, helper call order, or algorithm steps.
   - Delete: tests that only preserve a temporary implementation path, old UI structure, an incidental refactor choice, a one-time bug misunderstanding, or a bootstrap/tooling probe.

3. Replace implementation checks with behavior checks.
   - Prefer accessible queries over DOM selectors for UI tests.
   - Prefer CLI helpers over direct process plumbing when a project has shared helpers.
   - Prefer public API calls over private helper calls for library tests.
   - Verify outcomes, not the path used to produce them.

4. Keep only intentional interface locks.
   - Public CLI JSON fields and public function signatures may be tested.
   - Private helper signatures, class names, CSS declarations, DOM nesting, algorithm order, and component/library internals should not be long-lived contracts.
   - If a detail is intentionally public, name why in the test title or assertion message.

5. Run the relevant suite and commit only the cleanup slice.
   - Do not change production behavior just to satisfy old tests.
   - Preserve unrelated dirty worktree changes.
   - Mention deleted/replaced test categories and any remaining coupling risks.

## Heuristics

- A test is probably too coupled if a refactor, UI component swap, CSS rewrite, or algorithm change can break it while the user experience or public contract stays the same.
- A test is probably valuable if it can be understood from the product or API contract without reading the implementation.
- Development-only tests should be removed before commit unless rewritten as public behavior tests.
- Visual UI bugs need visual/user-facing verification. Static CSS assertions are a last resort and should usually be temporary.
- Be skeptical of historical regression sentinels: spelling checks, old artifact names, deleted command names, migration scaffolding, or "this exact bug must never return" cases usually age into noise unless they protect a documented compatibility promise.
- Remove tests of test infrastructure itself, build-system smoke probes, JSX/bootstrap probes, architecture-guard fixtures, and direct permission/configuration assertions when broader build, release, or behavior tests already exercise the same user-facing path.
- Keep compatibility and safety tests when the old shape is still an explicit contract, such as documented metadata migration, ignored-but-preserved user files, stale-write conflict handling, or package validation behavior.

## Examples

- Replace `querySelector(".mantine-Menu-dropdown .task-menu-panel")` with a menu interaction and assertions on visible menu item names.
- Replace `assert.match(styles, /\.timeline-event-label/)` with assertions that every event has a selectable control named `Select event <name>` and that task bars describe their event span.
- Replace tests of a private topological-sort helper with CLI/API behavior showing dependencies are reported or rejected correctly.
- Replace duplicate CLI subprocess setup with the repository's shared command helper, then assert exit status and JSON output.
- Delete a scan for a past misspelled product name once normal branding tests and release verification cover the shipped name; do not keep a bespoke sentinel for the historical typo.
- Delete TSX/toolchain probe components and their tests when the production build plus real React shell tests already prove the stack works.
- Replace direct checks for specific desktop permission strings with an end-to-end window behavior test, or delete them if that behavior is already covered elsewhere.
