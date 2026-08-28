---
name: hyde-interactive-widget
description: Create or normalize HydeInteractiveWidget-based plugins around Hyde's standard saveable interactive-window shape. Use when building a new Hyde interactive plugin, converting an existing interactive plugin to the shared HydeInteractiveWidget lifecycle and save/restore contract, or removing interactive-local wrapper structure so stable naming, macro/session restore, and namespace tracking live in the base class by default.
metadata:
  uuid: "d6f2978a-6474-4984-aa48-43997350290c"
---

# Hyde Interactive Widget

Use this skill when the target UI surface is a `HydeInteractiveWidget`: creating a
new interactive-style plugin from a spec, or normalizing an existing one.

Always read `.agents/protocols/hyde/widget-family.md` first. It carries the shared
workflow, the `widget_ir` / `python_source()` contract, ownership split, override
discipline, and test expectations. This file covers only the saveable interactive
window lifecycle.

If the feature spec does not exist or is stale, use `add-hyde-ui-feature` first.

For the interactive checklist, read
[references/interactive-pattern.md](references/interactive-pattern.md).
For a starting skeleton, copy `assets/template_plugin/` and rename the placeholders.

## Interactive Lifecycle Contract

`HydeInteractiveWidget` owns:

- stable window naming and subwindow binding
- saveable macro/session-restore integration
- geometry and window-state capture
- tracked namespace-state bookkeeping

Here `widget_ir` is the **live current object IR** — not a snapshot. It is the
GUI-side truth for the window's recreatable state, and both live mutation commands
and `session.py` restore source lower from it. `TableWidget.widget_ir` holding
`TableIR` / `TableIRDiff` is the reference implementation.

Interactive windows are created on demand and added to the MDI area directly, so
they keep Qt's normal delete-on-close behavior rather than the persistent
tool-window wrapper that turns close into hide.

Do not recreate save/restore or stable-name plumbing locally.

## Workflow

1. Confirm the surface really is a `HydeInteractiveWidget`, not a dialog or plain
   tool.
2. Inventory the subclass for duplicated save/restore code, local stable-name
   management, or a local namespace-tracking mirror.
3. Remove that lifecycle duplication before adding anything.
4. Route live mutation commands and recreation source through
   `widget_ir.python_source()` and its recreation lowering.
5. Follow documented identity rules. Where the docs separate stable identity from
   visible presentation — as figure windows do for titles — preserve that split
   instead of inventing widget-local policy.
6. Prove the contract with tests on stable naming, save/restore source, and
   namespace-driven refresh.

## Normalization Targets

- no duplicated stable-name plumbing when `bind_subwindow(...)` and
  `on_stable_name_bound(...)` are enough
- no save/restore wrapper layer when the base already owns it
- no local namespace mirror when `tracked_namespace_names()` and
  `update_tracked_namespace_state(...)` are enough
- no interactive-local hidden-command wrapper when the normal execution path works
- no locally assembled command text where `widget_ir.python_source()` belongs
- no widget-local policy duplicating a documented family-level identity rule

## Planning Handoff

When paired with issue work, make the plan state:

- what the stable window handle is
- whether a doc-defined identity/presentation split must be preserved
- what its `widget_ir` is, and what recreation source it must produce
- whether namespace changes should trigger refresh behavior
- which tests prove stable-name binding, save/restore source, and tracked state
