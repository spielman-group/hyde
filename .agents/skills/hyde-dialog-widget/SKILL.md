---
name: hyde-dialog-widget
description: Create or normalize HydeDialogWidget-based plugins around Hyde's standard dialog shape. Use when building a new Hyde dialog plugin, converting an existing dialog plugin to the shared HydeDialogWidget footer contract, or removing dialog-local shims so preview-backed Do It, To Cmd Line, To Clip, and Help behavior live in the base class by default.
---

# Hyde Dialog Widget

Use this skill when the target UI surface is a `HydeDialogWidget`.

This skill covers two jobs:

- creating a new dialog-style plugin from a spec
- normalizing an existing dialog-style plugin to Hyde's standard shape

This skill participates in the normal dialog workflow:

1. `add-hyde-ui-feature`
2. `grill-me`
3. `to-prd`
4. use `hyde-dialog-widget` and `to-issues` together to produce `issues/...md`
5. `hyde-simplify`
6. implement the resulting issues with `tdd` and `hyde-dialog-widget`

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

Then read only the feature spec and code relevant to the dialog.

For the standard dialog pattern and a concrete checklist, read
[references/dialog-pattern.md](references/dialog-pattern.md).

If you need a starting skeleton, copy from
`assets/template_plugin/` and then rename the placeholder package/module names.

## Core Contract

Treat `HydeDialogWidget` as the owner of the common footer behavior.

Default rule:

- the dialog maintains one backing preview string via `set_preview_string(...)`
- base `can_do_it()` follows whether that backing string is non-empty
- `Do It`, `To Cmd Line`, and `To Clip` use that backing string by default
- the lower preview pane may display different text only when the product truly
  needs it
- `Help` is file-backed through `help_filename`
- `Cancel` stays local unless the plugin has no special cancel behavior

Do not keep subclass shims that only restate base behavior.

When this skill is used before code exists, its job is to make the dialog shape
explicit enough that `to-issues` can slice the work without rediscovering the footer
contract, preview contract, package ownership, or legitimate exceptions.

## Workflow

1. Identify the actual widget surface.
   Confirm the target should be a `HydeDialogWidget`, not a tool or interactive
   widget.
2. Inventory existing subclass overrides.
   Look for `handle_do_it()`, `can_do_it()`, `can_send_to_cmd_line()`,
   `do_it_dispatch_mode()`, and `handle_help()`.
3. Remove trivial shims first.
   If the subclass method only returns preview text or forwards to shared dispatch,
   delete it and move state updates into the dialog's existing refresh path.
4. Move the preview contract onto the backing string.
   The dialog should update `set_preview_string(payload, display_text=...)` from its
   real state-refresh path.
5. Keep only meaningful overrides.
   Valid reasons include dialog-local validation beyond payload presence,
   visible-vs-hidden dispatch policy, or a real difference between displayed preview
   text and executable payload.
6. Keep command generation in the feature layer.
   If the dialog owns a Python package or domain, lowering/validation belongs in the
   matching `hyde/features/..._features.py` module. If it uses a package owned
   elsewhere, call that existing feature module instead of duplicating logic.
7. Reuse any documented family-specific ownership seam.
   If the dialog belongs to an existing widget family with shared ownership or
   lifecycle rules, follow the docs and spec rather than inventing dialog-local
   policy or a new abstraction inside the plugin.
8. Validate the footer contract with behavior tests.
   Prefer tests that prove what the user sees and what gets executed or copied, not
   helper wiring.

## Planning Handoff

When this skill is paired with `to-issues`, make sure the implementation plan says:

- whether the dialog is a standard preview-backed dialog or a real display-text
  exception
- whether `Do It`, `To Cmd Line`, and `To Clip` all use the same backing string
- whether `Help` should be base-owned through `help_filename`
- whether the plugin owns its domain package or calls a feature owner elsewhere
- whether any family-specific ownership or lifecycle rule from the docs/spec must be
  reused
- whether launcher code only opens the dialog or still has a second dispatch path
- which tests must prove the shared footer contract

## New Plugin Shape

For a new dialog plugin, prefer this structure:

- plugin package `__init__.py` registers the plugin and opens the dialog
- `dialogs.py` contains the `HydeDialogWidget` subclass
- static layout lives in `.ui` files
- domain lowering/validation lives in `hyde/features/..._features.py`
- dialog-local state only tracks UI draft state and preview state

Do not add a second launcher-side dispatch path after `exec_()`. If `Do It` exists,
the dialog should own that dispatch through the shared base behavior unless there is
clear local policy that must wrap it.

## Normalization Targets

When normalizing an existing plugin, prefer these end states:

- no subclass `To Cmd Line` / `To Clip` implementation when base behavior is enough
- no launcher-side post-accept dispatch duplicating dialog `Do It`
- no dialog-local help implementation when `help_filename` is enough
- no duplicated preview string and lower-text-edit state
- no separate payload getter when `preview_string()` already is the real backing
  command contract
- no dialog-local policy that duplicates a documented family-level ownership or
  lifecycle rule

## Output Rules

- Keep the patch small and local to the dialog/plugin unless the base class clearly
  needs a small shared improvement.
- Update the relevant spec if the dialog contract changes.
- If you change the shared footer contract, update the base-widget tests too.
- If you are helping shape issues before implementation, prefer issue slices that:
  - establish or preserve the base footer contract first
  - keep command generation in the feature layer
  - remove trivial dialog shims instead of encoding them as permanent structure
