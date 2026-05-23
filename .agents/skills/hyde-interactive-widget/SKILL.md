---
name: hyde-interactive-widget
description: Create or normalize HydeInteractiveWidget-based plugins around Hyde's standard saveable interactive-window shape. Use when building a new Hyde interactive plugin, converting an existing interactive plugin to the shared HydeInteractiveWidget lifecycle and save/restore contract, or removing interactive-local wrapper structure so stable naming, macro/session restore, and namespace tracking live in the base class by default.
---

# Hyde Interactive Widget

Use this skill when the target UI surface is a `HydeInteractiveWidget`.

This skill covers two jobs:

- creating a new interactive-style plugin from a spec
- normalizing an existing interactive plugin to Hyde's standard saveable window shape

This skill participates in the normal widget workflow:

1. `add-hyde-ui-feature`
2. `grill-me`
3. `to-prd`
4. use `hyde-interactive-widget` and `to-issues` together to produce `issues/...md`
5. `hyde-simplify`
6. implement the resulting issues with `tdd` and `hyde-interactive-widget`

If the feature spec does not exist or is stale, use `add-hyde-ui-feature` first and
then return here.

## Required Context

Read these before changing code:

1. `AGENTS.md`
2. `project_management/ARCHITECTURE.md`
3. `project_management/IR-CONTROL.md`
4. `project_management/STYLE.md`
5. `project_management/PLAN.md`
6. `project_management/STATUS.md`

Then read only the feature spec and code relevant to the interactive widget.

For the standard interactive pattern and a concrete checklist, read
[references/interactive-pattern.md](references/interactive-pattern.md).

If you need a starting skeleton, copy from
`assets/template_plugin/` and then rename the placeholder package/module names.

## Core Contract

Treat `HydeInteractiveWidget` as the owner of the interactive window lifecycle.

Default rule:

- the base owns stable window naming and subwindow binding
- the base owns saveable macro/session-restore integration
- the base owns geometry/window-state capture
- the base owns tracked namespace-state bookkeeping
- the widget emits hidden Python through the normal execution path when it mutates
  kernel-owned state

Do not recreate save/restore or stable-name plumbing locally.

## Workflow

1. Identify the actual widget surface.
   Confirm the target should be a `HydeInteractiveWidget`, not a dialog or plain tool.
2. Inventory existing subclass structure.
   Look for duplicated save/restore code, local stable-name management, or local
   namespace tracking that the base already provides.
3. Remove trivial lifecycle duplication first.
4. Keep static layout in `.ui`.
   Use Python for signal wiring, dynamic rows/items, and runtime-only widgets.
5. Keep command generation and validation in the feature layer when the interactive
   widget emits Python or owns domain lowering.
6. Validate the interactive contract with behavior tests.
   Prefer tests that prove stable naming, save/restore source, and namespace-driven
   refresh behavior.

## Planning Handoff

When this skill is paired with `to-issues`, make sure the implementation plan says:

- what the stable window handle is
- what macro/session-restore source the widget must produce
- whether namespace changes should trigger refresh behavior
- whether the widget owns its domain package or calls a feature owner elsewhere
- which tests must prove stable-name binding, save/restore source, and tracked-state
  behavior

## New Plugin Shape

For a new interactive plugin, prefer this structure:

- plugin package `__init__.py` registers and opens/shows the interactive window
- `window.py` contains the `HydeInteractiveWidget` subclass
- static layout lives in `.ui` files
- domain lowering/validation lives in `hyde/features/..._features.py` when needed
- the base widget owns stable naming and save/restore lifecycle

## Normalization Targets

When normalizing an existing plugin, prefer these end states:

- no duplicated stable-name plumbing when `bind_subwindow(...)` and
  `on_stable_name_bound(...)` are enough
- no duplicated save/restore wrapper layer when the base already owns it
- no local namespace-tracking mirror when `tracked_namespace_names()` and
  `update_tracked_namespace_state(...)` are enough
- no interactive-local hidden-command wrapper when the normal execution path is enough

## Output Rules

- Keep the patch small and local to the interactive/plugin unless the base class
  clearly needs a small shared improvement.
- Update the relevant spec if the interactive contract changes.
- If you change the shared interactive contract, update the base-widget tests too.
