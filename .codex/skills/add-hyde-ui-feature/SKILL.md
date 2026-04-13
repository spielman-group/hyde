---
name: add-hyde-ui-feature
description: Create or revise a Hyde frontend feature specification from a feature spec folder containing screenshots, drawings, SPEC.md, or IGOR.md. Use when Codex needs to define a new Hyde UI feature spec under `project_management/specs/`, especially when the available artifacts imply behavior that must be translated from Igor concepts into Hyde and Python concepts.
---

# Add Hyde UI Feature

## Overview
Define a Hyde frontend feature spec from the artifacts in `project_management/specs/<feature>/`.

Treat screenshots and drawings as evidence of visible UI behavior. Treat `SPEC.md` as the existing Hyde draft if present. Treat `IGOR.md` as a non-authoritative source of feature intent that may include concepts that do not fit Hyde.

## Workflow
1. Inspect the feature spec folder first.
   Look for image assets, `SPEC.md`, and `IGOR.md`.
2. Infer the UI behavior shown by the screenshots before relying on prose.
   Note visible controls, panes, menus, selections, states, and user actions.
3. Read `SPEC.md` if present.
   Preserve Hyde-specific decisions already made unless they conflict with project architecture or newer user direction.
4. Read `IGOR.md` critically.
   Extract user intent and useful UX patterns, not literal Igor implementation details.
5. Ask the user concise clarifying questions whenever the artifacts leave important behavior ambiguous.
   Ask when artifacts conflict, when a screenshot implies behavior missing from prose, or when an Igor concept has no clear Hyde/Python equivalent.
6. Write or revise `SPEC.md` in present-tense specification language.
   Describe the intended Hyde behavior, not project history.

## Interpretation Rules
- Prioritize sources in this order: explicit user direction, Hyde architecture and AGENTS constraints, existing Hyde `SPEC.md`, screenshot evidence, then `IGOR.md`.
- Do not copy Igor concepts directly when they do not map to Hyde.
  Translate them into Hyde-native or Python-native concepts and confirm the translation with the user when it materially affects the spec.
- Common examples of Igor-specific concepts that need translation or rejection include data folders, waves, command-line insertion behavior, and other non-Python object models.
- Keep the output frontend-focused.
  Define UI structure, interactions, visible states, commands or strings the GUI must generate, and architectural boundaries that affect the UI contract.
- Do not implement feature code as part of this skill.

## Output Requirements
- Create or update `project_management/specs/<feature>/SPEC.md`.
- If the feature spec folder does not exist, create it and add `SPEC.md`.
- Use nearby Hyde spec folders for format and granularity when helpful, especially `project_management/specs/data_browser/`.
- Keep `SPEC.md` free of implementation history, migrations, or discarded alternatives.
