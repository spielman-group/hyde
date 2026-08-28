---
name: hyde-tool-widget
description: Create or normalize HydeToolWidget-based plugins around Hyde's standard persistent tool-window shape. Use when building a new Hyde tool plugin, converting an existing tool plugin to the shared HydeToolWidget shell and mounting contract, or removing tool-local wrapper structure so window identity, close policy, and mounted-child ownership live in the base class by default.
metadata:
  uuid: "6d1dda7e-4132-431e-91f2-35b0600d57e8"
---

# Hyde Tool Widget

Use this skill when the target UI surface is a `HydeToolWidget`: creating a new
tool-style plugin from a spec, or normalizing an existing one.

Always read `.agents/protocols/hyde/widget-family.md` first. It carries the shared
workflow, the `widget_ir` / `python_source()` contract, ownership split, override
discipline, and test expectations. This file covers only what is specific to the
persistent tool shell.

If the feature spec does not exist or is stale, use `add-hyde-ui-feature` first.

For the tool checklist, read [references/tool-pattern.md](references/tool-pattern.md).
For a starting skeleton, copy `assets/template_plugin/` and rename the placeholders.

## Tool Shell Contract

`HydeToolWidget` owns the outer persistent shell:

- the outer `hyde_window_widget.ui` shell
- mounted-child plumbing through `mount_child_widget(...)`
- subwindow binding and stable window identity
- hide-vs-close policy declared through `close_policy()`

The plugin owns the content widget, its signal wiring, and domain behavior.

Do not hand-build a second outer shell in plugin code, and do not bypass
`close_policy()` with ad hoc close handling.

Most persistent tools should subclass `HydeToolWindowPlugin`, which already
contributes the Window-menu action, the MDI descriptor, and the show/hide
lifecycle from class attributes plus `create_tool_window_widget(...)`. Do not
re-register that menu action manually.

## Workflow

1. Confirm the surface really is a `HydeToolWidget`, not a dialog or interactive
   widget.
2. Inventory the subclass for duplicated shell layout, manual subwindow binding,
   local close-policy logic, or wrappers around `mount_child_widget(...)`.
3. Remove that shell duplication before adding anything.
4. Keep the tool's own state as UI state. If the tool emits Python, that Python
   comes from `widget_ir.python_source()`.
5. Prove the contract with tests on mounted-child behavior, subwindow identity,
   and close policy.

## Normalization Targets

- no duplicated outer shell layout in Python when the base already owns it
- no local subwindow identifier plumbing when `bind_subwindow(...)` is enough
- no mounted-child wrapper when `mount_child_widget(...)` is enough
- no tool-local hide/close behavior that bypasses `close_policy()`
- no menu/descriptor registration that `HydeToolWindowPlugin` already provides

## Planning Handoff

When paired with issue work, make the plan state:

- whether the plugin is a standard persistent tool or a close-on-dismiss exception
- whether it mounts one main child widget or owns its layout directly
- what its `widget_ir` is, if it emits Python at all
- whether the launcher only opens/shows the tool or duplicates tool-owned behavior
- which tests prove subwindow identity, mounted-child behavior, and close policy
