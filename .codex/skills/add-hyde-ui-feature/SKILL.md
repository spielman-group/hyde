---
name: add-hyde-ui-feature
description: Create or revise a Hyde frontend feature specification from a feature spec folder containing screenshots, drawings, SPEC.md, or IGOR.md. Use when Codex needs to translate ambiguous screenshot or Igor-style behavior into Hyde-native UI requirements, especially for features under `project_management/specs/` that involve live kernel state, explicit exclusions, or editable widget behavior.
---

# Add Hyde UI Feature

## Overview
Define a Hyde frontend feature spec from the artifacts in `project_management/specs/<feature>/`.

Treat screenshots and drawings as evidence of visible UI behavior. Treat `SPEC.md` as the existing Hyde draft if present. Treat `IGOR.md` as a non-authoritative source of feature intent that may include concepts that do not fit Hyde.

For repeatable Hyde-specific patterns, read [references/hyde-ui-spec-patterns.md](references/hyde-ui-spec-patterns.md) before drafting or revising the final spec.

## Workflow
1. Inspect the feature spec folder first.
   Look for image assets, `SPEC.md`, and `IGOR.md`.
2. Infer the UI behavior shown by the screenshots before relying on prose.
   Note visible controls, panes, menus, selections, states, and user actions.
3. Read `SPEC.md` if present.
   Preserve Hyde-specific decisions already made unless they conflict with project architecture or newer user direction.
4. Read `IGOR.md` critically.
   Extract user intent and useful UX patterns, not literal Igor implementation details.
5. Classify every meaningful visible control as one of:
   - `active`
   - `inert-but-visible`
   - `excluded`
6. Ask the user concise clarifying questions whenever that classification is not already clear.
   Ask when artifacts conflict, when a screenshot implies behavior missing from prose, when an Igor concept has no clear Hyde/Python equivalent, or when a visible control might be kept, disabled, or removed.
7. Write or revise `SPEC.md` in present-tense specification language.
   Describe the intended Hyde behavior, not project history.

## Interpretation Rules
- Prioritize sources in this order: explicit user direction, Hyde architecture and AGENTS constraints, existing Hyde `SPEC.md`, screenshot evidence, then `IGOR.md`.
- Do not copy Igor concepts directly when they do not map to Hyde.
  Translate them into Hyde-native or Python-native concepts and confirm the translation with the user when it materially affects the spec.
- Common examples of Igor-specific concepts that need translation or rejection include data folders, waves, command-line insertion behavior, and other non-Python object models.
- Keep the output frontend-focused, but include backend guardrails whenever the UI contract depends on kernel behavior.
  Define UI structure, interactions, visible states, commands or strings the GUI must generate, and architectural boundaries that affect the UI contract.
- Do not misread Hyde's dumb-viewport rule as "the GUI cannot support editing."
  Editing is allowed when the GUI generates explicit backend-directed Python commands and the backend remains authoritative.
- Do not invent Hyde-specific backend protocols when existing suite, Jupyter, or Spyder paths already satisfy the feature's contract.
- Do not add fake actions or placeholder implementations to the spec. If a control is visible but intentionally inactive in the initial deployment, say so explicitly.
- Do not implement feature code as part of this skill.

## Output Requirements
- Create or update `project_management/specs/<feature>/SPEC.md`.
- If the feature spec folder does not exist, create it and add `SPEC.md`.
- Use nearby Hyde spec folders for format and granularity when helpful, especially `project_management/specs/data_browser/`.
- Keep `SPEC.md` free of implementation history, migrations, or discarded alternatives.
- Separate initial deployment behavior from future work whenever the artifacts imply a larger eventual feature.
- Explicitly list visible controls and classify them as `active`, `inert-but-visible`, or `excluded`.
- Add architecture guardrails whenever the UI depends on backend behavior, live kernel state, or synchronization.
- For mutable widgets, include explicit sections covering:
  - `Editable Operations`
  - `Command Generation`
  - `Synchronization`
  - `Explicit Exclusions`
- In `Editable Operations`, state:
  - which edits are live in the initial deployment
  - what objects those edits target
  - the Python-level effect of each edit
  - whether each edit is immediate, confirmed, or batched
  - what happens for invalid edits or unsupported selections
