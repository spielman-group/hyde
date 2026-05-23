---
name: hyde-tool-widget
description: Create or normalize HydeToolWidget-based plugins around Hyde's standard persistent tool-window shape. Use when building a new Hyde tool plugin, converting an existing tool plugin to the shared HydeToolWidget shell and mounting contract, or removing tool-local wrapper structure so window identity, close policy, and mounted-child ownership live in the base class by default.
---

# Hyde Tool Widget

Use this skill when the target UI surface is a `HydeToolWidget`.

This skill covers two jobs:

- creating a new tool-style plugin from a spec
- normalizing an existing tool-style plugin to Hyde's standard persistent tool shape

This skill participates in the normal widget workflow:

1. `add-hyde-ui-feature`
2. `grill-me`
3. `to-prd`
4. use `hyde-tool-widget` and `to-issues` together to produce `issues/...md`
5. `hyde-simplify`
6. implement the resulting issues with `tdd` and `hyde-tool-widget`

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

Then read only the feature spec and code relevant to the tool.

For the standard tool pattern and a concrete checklist, read
[references/tool-pattern.md](references/tool-pattern.md).

If you need a starting skeleton, copy from
`assets/template_plugin/` and then rename the placeholder package/module names.

## Core Contract

Treat `HydeToolWidget` as the owner of the outer persistent tool shell.

Default rule:

- the base owns the outer `hyde_window_widget.ui` shell
- the plugin mounts one child/content widget through `mount_child_widget(...)`
- subwindow binding and stable window identity are base-owned
- hide-vs-close policy is declared through `close_policy()`, not ad hoc close wiring

Do not hand-build a second outer shell in plugin code.

## Workflow

1. Identify the actual widget surface.
   Confirm the target should be a `HydeToolWidget`, not a dialog or interactive
   widget.
2. Inventory existing subclass structure.
   Look for duplicated shell layout, manual subwindow binding, local close-policy
   logic, or pass-through wrappers around `mount_child_widget(...)`.
3. Remove trivial shell duplication first.
   Keep plugin code focused on the content widget and domain behavior.
4. Keep static layout in `.ui`.
   Use Python for signal wiring, dynamic population, and service integration.
5. Keep command generation and validation in the feature layer when the tool emits
   Python or owns domain lowering.
6. Validate the tool contract with behavior tests.
   Prefer tests that prove mounted-child behavior, subwindow identity, and close
   policy over helper wiring.

## Planning Handoff

When this skill is paired with `to-issues`, make sure the implementation plan says:

- whether the plugin is a standard persistent tool or a close-on-dismiss exception
- whether the tool mounts one main child widget or owns its layout directly
- whether the plugin owns its domain package or calls a feature owner elsewhere
- whether the launcher only opens/shows the tool or duplicates tool-owned behavior
- which tests must prove subwindow identity, mounted-child behavior, and close policy

## New Plugin Shape

For a new tool plugin, prefer this structure:

- plugin package `__init__.py` registers and opens/shows the tool
- `window.py` contains the `HydeToolWidget` subclass or its mounted child widget
- static layout lives in `.ui` files
- domain lowering/validation lives in `hyde/features/..._features.py` when needed
- the base shell owns persistence and mounted-child plumbing

## Normalization Targets

When normalizing an existing plugin, prefer these end states:

- no duplicated outer shell layout in Python when the base already owns it
- no local subwindow identifier plumbing when `bind_subwindow(...)` is enough
- no duplicate mounted-child wrapper when `mount_child_widget(...)` is enough
- no tool-local hide/close behavior that bypasses `close_policy()`

## Output Rules

- Keep the patch small and local to the tool/plugin unless the base class clearly
  needs a small shared improvement.
- Update the relevant spec if the tool contract changes.
- If you change the shared tool-shell contract, update the base-widget tests too.
