- [x] Slice 1: Rewrite Docs To Reflect The Remaining IR Migration Gaps
- [x] Slice 2: Make Figure Lowerers Package-Pure Again
- [x] Slice 3: Move Python Variables Onto A Real Tool IR
- [x] Slice 4: Put Table Live Mutation Commands Back On The Widget IR Path
- [x] Slice 5: Restore The Remote Request Hidden-Lane Contract
- [x] Slice 6: Resync Docs, Specs, And Tests To The Landed Remediation

This file is now a completed execution record for the remediation plan. Slices 1-6
landed, and the repository describes the remediated architecture in present tense.
The slice sections below are retained as historical work records.

The landed remediation delivered:

- package-pure figure lowerers
- tool-owned `widget_ir` deletion flow in Python Variables
- widget-owned `TableIR` / `TableIRDiff` live mutation lowering
- `remote_requests` dispatch over the shared hidden lane with `silent=True`
- final doc/spec/test resync so the temporary Slice 1 gap language is removed

## Slice 1: Rewrite Docs To Reflect The Remaining IR Migration Gaps

### Type

`AFK`

### What to build

Update the authoritative Hyde docs and this remediation plan so they describe the
actual current state of the migration: the IR migration is close, but not fully
complete. The docs should stop implying that package-pure lowerers, tool/widget IR
ownership, and the hidden-lane runtime contract are already fully satisfied until
the remaining code fixes land.

### Acceptance criteria

- [x] The authoritative docs describe the remaining noncompliance accurately in
      present tense.
- [x] The docs no longer overstate completion of the package-pure feature boundary
      or the tool/widget IR migration.
- [x] The docs give later workers one current source of truth for the remaining
      remediation work.

### Blocked by

None - can start immediately.

### User stories covered

- Problem Statement
- User Stories 14, 16, 17

## Slice 2: Make Figure Lowerers Package-Pure Again

### Type

`AFK`

### What to build

Repair the figure-lowering boundary so `matplotlib_features.py` emits only
matplotlib strings again. Any Hyde-owned orchestration such as `hyde.get_figure`,
`hyde.refresh_figure`, decorators, macro publication, or Hyde helper calls must
move out of `matplotlib_features.py` and onto the appropriate IR or Hyde-owned
lowering path.

This is a true vertical slice: figure creation, figure refresh, macro publication,
macro generation, remove-from-graph, and save-graphics behavior must still work
end-to-end after the package boundary is corrected.

### Acceptance criteria

- [x] `matplotlib_features.py` no longer emits Hyde strings or Hyde decorators.
- [x] Figure-related Hyde helpers are emitted from IR-owned orchestration or
      Hyde-owned lowerers instead of the matplotlib feature module.
- [x] Figure creation, refresh, remove-from-graph, and save-graphics behaviors
      still work end-to-end through the corrected lowering boundary.
- [x] End-to-end figure-family tests cover the corrected package-pure contract.

### Blocked by

- Slice 1: Rewrite Docs To Reflect The Remaining IR Migration Gaps

### User stories covered

- Solution
- User Stories 9, 10, 14, 15, 16

## Slice 3: Move Python Variables Onto A Real Tool IR

### Type

`AFK`

### What to build

Redo the remaining Python Variables migration so the tool actually owns a
meaningful `widget_ir`. Its command-emitting behavior, including object deletion
and any persisted filter/view state that belongs in the tool contract, should be
expressed through IR-owned behavior instead of raw widget state and direct string
dispatch.

### Acceptance criteria

- [x] `PythonVariables` owns a real tool IR in `widget_ir`.
- [x] Delete-object behavior lowers through IR-owned `python_source()` instead of
      raw `execute_hidden(f\"del {name}\")`.
- [x] Tool state that belongs to the Python Variables workflow is represented by
      the tool IR rather than only by direct widget fields.
- [x] End-to-end tests cover the rewritten Python Variables IR ownership and
      deletion behavior.

### Blocked by

- Slice 1: Rewrite Docs To Reflect The Remaining IR Migration Gaps

### User stories covered

- Solution
- User Stories 2, 4, 8, 15, 16

## Slice 4: Put Table Live Mutation Commands Back On The Widget IR Path

### Type

`AFK`

### What to build

Bring table live mutation commands back to the final table IR ownership model.
Live edit/append/create/delete actions should be expressed from the live
widget-owned table IR / diff path rather than by constructing scratch `TableIR()`
objects at the point of dispatch.

### Acceptance criteria

- [x] Live table mutation commands no longer build fresh scratch IR objects as the
      main dispatch path.
- [x] The live widget-owned table IR / diff path is the real owner of table
      mutation command generation.
- [x] Table edit/append/create/delete behaviors remain correct end-to-end after
      the ownership fix.
- [x] End-to-end tests cover the corrected live table mutation path.

### Blocked by

- Slice 1: Rewrite Docs To Reflect The Remaining IR Migration Gaps

### User stories covered

- Solution
- User Stories 3, 7, 15, 16

## Slice 5: Restore The Remote Request Hidden-Lane Contract

### Type

`AFK`

### What to build

Bring `remote_requests` back into compliance with the runtime contract by using
the shared hidden execution lane with `silent=True`, and update the tests and docs
that currently encode the wrong behavior.

### Acceptance criteria

- [x] `remote_requests` dispatches through the shared hidden lane with
      `silent=True`.
- [x] The implementation matches the IPC/runtime docs.
- [x] The runtime tests assert the corrected hidden-lane behavior instead of the
      superseded non-silent dispatch path.

### Blocked by

- Slice 1: Rewrite Docs To Reflect The Remaining IR Migration Gaps

### User stories covered

- Solution
- User Stories 6, 15, 16

## Slice 6: Resync Docs, Specs, And Tests To The Landed Remediation

### Type

`AFK`

### What to build

After the remediation slices land, update docs, specs, and any touched tests so
the repository again has one current source of truth. This slice exists to remove
the temporary Slice 1 remediation-gap language and to describe the
finally-corrected package boundary, tool IR ownership, table mutation ownership,
and remote-request runtime behavior in present tense.

### Acceptance criteria

- [x] The authoritative docs and specs describe the landed remediated architecture
      in present tense.
- [x] Tests and helper documentation no longer encode the pre-remediation
      behavior.
- [x] No stale statements remain claiming either premature completion or
      superseded behavior.

### Blocked by

- Slice 2: Make Figure Lowerers Package-Pure Again
- Slice 3: Move Python Variables Onto A Real Tool IR
- Slice 4: Put Table Live Mutation Commands Back On The Widget IR Path
- Slice 5: Restore The Remote Request Hidden-Lane Contract

### User stories covered

- Problem Statement
- User Stories 16, 17, 18
