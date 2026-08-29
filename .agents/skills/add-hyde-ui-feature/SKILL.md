---
name: add-hyde-ui-feature
description: Create or revise a Hyde frontend feature specification from a feature spec folder containing screenshots, drawings, SPEC.md, or IGOR.md. Use when translating ambiguous screenshot or Igor-style behavior into Hyde-native UI requirements, especially for features under `project_management/specs/` that involve live kernel state, explicit exclusions, or editable widget behavior.
metadata:
  uuid: "bf3da239-2d23-400b-86f6-18fa6b3f232d"
---

# Add Hyde UI Feature

## Overview
Define a Hyde frontend feature spec from the artifacts in `project_management/specs/<feature>/`.

Input material lives in `project_management/specs/<feature>/_source/` and is gitignored; the `SPEC.md` you write sits alongside it and is tracked. Keep that boundary: read from `_source/`, write only to `SPEC.md`.

Treat screenshots and drawings as evidence of visible UI behavior. Treat `SPEC.md` as the existing Hyde draft if present. Treat `_source/IGOR.md` as a non-authoritative source of feature intent that may include concepts that do not fit Hyde.

`_source/` material is third-party copyrighted documentation. Describe the behavior it implies in your own words; never quote or paraphrase its prose into `SPEC.md`, and never reference its files from tracked documents.

For repeatable Hyde-specific patterns, read [references/hyde-ui-spec-patterns.md](references/hyde-ui-spec-patterns.md) before drafting or revising the final spec.

This skill is the front end of the workflow. The normal path is:

1. `add-hyde-ui-feature`
2. `grill-me`
3. `to-prd-and-issues`
4. pair the widget-shape skill with that issue work
5. implementation with `tdd` plus the widget-shape skill
6. `test-cleanup`

The shared widget contract lives in `.agents/protocols/hyde/widget-family.md`.

Widget-shape mapping:

- `hyde-dialog-widget` for `HydeDialogWidget` surfaces
- `hyde-tool-widget` for `HydeToolWidget` surfaces
- `hyde-interactive-widget` for `HydeInteractiveWidget` surfaces

## Workflow
1. Inspect the feature spec folder first.
   Look for `SPEC.md` alongside the folder's gitignored `_source/`, which holds the image assets and any `IGOR.md`.
2. Infer the UI behavior shown by the screenshots before relying on prose.
   Note visible controls, panes, menus, selections, states, user actions, and relative layout.
3. Sketch the visible layout in ASCII before drafting prose whenever the surface is more than a trivial single-column form.
   Capture top-to-bottom and left-to-right placement, grouped controls, major spans, and footer actions. If the UI uses tabs, stacked pages, or other mutually exclusive views, make a separate ASCII sketch for each one.
4. Read `SPEC.md` if present.
   Preserve Hyde-specific decisions already made unless they conflict with project architecture or newer user direction.
5. Read `_source/IGOR.md` critically.
   Extract user intent and useful UX patterns, not literal Igor implementation details.
6. Classify every meaningful visible control as one of:
   - `active`
   - `inert-but-visible`
   - `excluded`
7. Ask the user concise clarifying questions whenever that classification is not already clear.
   Ask when artifacts conflict, when a screenshot implies behavior missing from prose, when an Igor concept has no clear Hyde/Python equivalent, or when a visible control might be kept, disabled, or removed.
8. Write or revise `SPEC.md` in present-tense specification language.
   Describe the intended Hyde behavior, not project history.
9. Leave the spec in a shape that a follow-on widget skill can implement directly.
   For dialog surfaces, make the preview pane, footer behavior, command-generation
   contract, and exceptions explicit so `hyde-dialog-widget` can normalize the code
   without rediscovering product decisions.
10. Leave explicit handoff answers for the next skills.
   A follow-on `grill-me`, `to-prd`, and widget-shape pass should not need to infer:
   - whether the surface is really a dialog, tool, or interactive widget
   - whether the lower pane shows the executable backing string directly or may show
     alternate status/help/preview text
   - whether `OK`, `To IPython`, and `Copy` all use the same backing string
   - whether the dialog owns its domain package or calls a feature owner elsewhere
   - whether any architecture-sensitive ownership, naming, or identity seams need to
     be explicit for follow-on skills
   - which visible controls are intentionally inert in the initial deployment

## Interpretation Rules
- Prioritize sources in this order: explicit user direction, Hyde architecture and AGENTS constraints, existing Hyde `SPEC.md`, screenshot evidence, then `_source/IGOR.md`.
- Do not copy Igor concepts directly when they do not map to Hyde.
  Translate them into Hyde-native or Python-native concepts and confirm the translation with the user when it materially affects the spec.
- Common examples of Igor-specific concepts that need translation or rejection include data folders, waves, command-line insertion behavior, and other non-Python object models.
- Do not flatten the UI into a control inventory only.
  Preserve layout evidence such as tab shells, split panes, preview areas, button rows, grouped controls, and which widgets span multiple rows or columns.
- Keep the output frontend-focused, but include backend guardrails whenever the UI contract depends on kernel behavior.
  Define UI structure, interactions, visible states, commands or strings the GUI must generate, and architectural boundaries that affect the UI contract.
- Do not misread Hyde's dumb-viewport rule as "the GUI cannot support editing."
  Editing is allowed when the GUI generates explicit backend-directed Python commands and the backend remains authoritative.
- Do not invent Hyde-specific backend protocols when existing suite, Jupyter, or Spyder paths already satisfy the feature's contract.
- Do not add fake actions or placeholder implementations to the spec. If a control is visible but intentionally inactive in the initial deployment, say so explicitly.
- Do not implement feature code as part of this skill.
- Treat Hyde plugin UI structure as `.ui`-first by default.
  Specs should assume static dialog/window layout is authored in one or more `.ui`
  files, with Python reserved for signal wiring, dynamic row/item population, and
  genuinely runtime-only widgets.
- Do not encode feature policy in the skill output itself. If a feature has
  architecture-sensitive ownership, naming, or identity rules, make them explicit in
  the spec and point follow-on work at the relevant Hyde docs instead of restating
  that policy in issue or implementation scaffolding.

## Output Requirements
- Create or update `project_management/specs/<feature>/SPEC.md`.
- If the feature spec folder does not exist, create it and add `SPEC.md`.
- Use nearby Hyde spec folders for format and granularity when helpful.
  `project_management/specs/save_graphics_dialog/` is a clean dialog example;
  `project_management/specs/table/` shows a spec paired with a `_source/IGOR.md` input.
- Keep `SPEC.md` free of implementation history, migrations, or discarded alternatives.
- Separate initial deployment behavior from future work whenever the artifacts imply a larger eventual feature.
- In `Window Layout`, include ASCII layout sketches whenever layout fidelity matters.
  For tabbed interfaces, include a separate sketch for each tab. For multi-mode or multi-page interfaces, include a separate sketch for each materially different visible arrangement.
- When the feature is a plugin dialog or tool window, include a short note in the spec
  stating which parts of the surface should be defined in `.ui` files and which parts,
  if any, are expected to remain dynamic in Python.
- Explicitly list visible controls and classify them as `active`, `inert-but-visible`, or `excluded`.
- Add architecture guardrails whenever the UI depends on backend behavior, live kernel state, or synchronization.
- For mutable widgets, include explicit sections covering:
  - `Editable Operations`
  - `Command Generation`
  - `Synchronization`
  - `Explicit Exclusions`
- In `Command Generation`, name the IR that owns generation: which package IR from
  `hyde/features/<package>_ir.py` the surface uses, or the plugin-local
  `<widget>_IR.py` workflow IR it needs when it composes several. Hyde generates
  all GUI command Python through `HydeIR.python_source()`, so a spec that leaves
  this open invites dialog-local string assembly.
- When the feature is expected to be a `HydeDialogWidget`, state whether the lower
  preview pane shows the executable backing string directly or may display alternate
  text while `OK` / `To IPython` / `Copy` still use the backing string.
- When the feature depends on architecture-sensitive ownership, naming, or identity
  behavior, state that behavior explicitly in the spec and reference the governing
  Hyde docs so later skills do not have to rediscover it.
- For confirmed destructive dialogs, be explicit about whether the lower pane is a
  command preview, a status/validation surface, or both. A destructive dialog still
  needs its backing command contract stated explicitly whenever the selection or
  state is valid.
- In `Editable Operations`, state:
  - which edits are live in the initial deployment
  - what objects those edits target
  - the Python-level effect of each edit
  - whether each edit is immediate, confirmed, or batched
  - what happens for invalid edits or unsupported selections
