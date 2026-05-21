# Hyde UI Spec Patterns

Use this reference when drafting or revising a Hyde UI feature spec from screenshots, `SPEC.md`, or `IGOR.md`.

## Control Classification

Every meaningful visible control inferred from screenshots should be classified as one of:

- `active`
  The control is live in the initial deployment.
- `inert-but-visible`
  The control remains visible for layout continuity, but intentionally has no effect in the initial deployment.
- `excluded`
  The control is not part of the Hyde feature and should not appear in the spec as an implemented or visible element.

If the correct classification is not already clear from the artifacts or prior Hyde decisions, ask the user instead of guessing.

## Required Spec Structure

For most Hyde frontend features, prefer these sections when they apply:

- `Feature Checklist`
- `Purpose`
- `Initial Deployment Scope`
- `Window Layout`
- `Visible Controls`
- `Context Menu Actions`
- `Command Generation`
- `Synchronization`
- `Explicit Exclusions`
- `Future Work`

Do not include every section mechanically. Include the sections needed to make the feature implementation decision complete.

## Window Layout Sketches

When layout fidelity matters, `Window Layout` should include one or more ASCII sketches.

Use the sketches to preserve:

- the overall shell shape
- left/right and top/bottom placement
- grouped controls
- major row or column spans
- preview panes, lists, tables, canvases, and footer button rows

If the UI has tabs, stacked pages, wizard steps, or mode switches that materially change
placement, include a separate ASCII sketch for each visible arrangement. Do not collapse
all tabs into one blended diagram.

Optimize the sketch for Qt Designer and `.ui` grid thinking: another agent should be able
to infer which controls share a row, which groups stack vertically, and which widgets
need to span multiple columns.

The sketch does not need pixel precision. It should be structurally precise enough to
prevent a correct-widget / wrong-layout outcome.

## Mutable Widget Requirements

If the feature allows the user to mutate scientific state, the spec must make that explicit.

Use an `Editable Operations` section that states:

- which edits are live in the initial deployment
- what objects those edits target
- the Python-level effect of each edit
- whether each edit is immediate, confirmed, or batched
- what happens for invalid edits or unsupported selections

The spec should also make clear that:

- the GUI must not own authoritative scientific state
- the backend remains authoritative
- GUI edits are allowed only when they generate explicit backend-directed commands
- transient GUI edit state is acceptable only when it exists to produce those commands and is not the canonical scientific state
- in-GUI editing must not become authoritative before the kernel accepts the corresponding command

## Backend Guardrails

When the UI implies backend behavior, the spec should say:

- which backend or kernel state is authoritative
- what metadata the GUI may cache
- what existing machinery must be reused before inventing a new protocol
- what the GUI must never own directly
- whether the feature is read-only, editable, or mixed

Prefer explicit reuse statements such as:

- use existing Spyder namespace machinery rather than inventing a Hyde tracker
- use standard Jupyter execution or comm paths before inventing Hyde-specific IPC

## Common Igor-to-Hyde Translation Traps

Watch for these and translate or reject them explicitly:

- data folders
- root/current-folder selectors
- waves vs Python objects
- packed experiments vs `.hy` projects
- command insertion behavior that does not map to Hyde's terminal model
- edit affordances that could mean either GUI-local mutation or kernel-directed mutation
- buttons or menus that may be visually important but intentionally inactive in the initial deployment

When a screenshot element is visually prominent but semantically unclear, do not silently remove it and do not silently keep its Igor behavior. Ask the user how Hyde should classify it.
