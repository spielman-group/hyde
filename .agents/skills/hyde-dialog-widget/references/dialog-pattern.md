# HydeDialogWidget Pattern

Use this as the default target shape for Hyde dialog plugins.

This reference is used in two modes:

- implementation mode: build or normalize the dialog code
- planning mode: help `to-issues` capture the intended standard shape before code
  exists

## Ownership Split

`HydeDialogWidget` should own:

- footer button wiring
- backing preview string storage
- default `Do It` enablement from whether the backing preview string is non-empty
- default `Do It` dispatch
- default `To Cmd Line`
- default `To Clip`
- file-backed help through `help_filename`

The subclass should own:

- loading the `.ui`
- reading widget state
- populating dynamic rows/items
- validation messages
- cancel/revert behavior
- meaningful `Do It` policy that wraps the shared dispatch path

## Preview Contract

Default contract:

```python
self.set_preview_string(command_source)
self.refresh_shell()
```

If the dialog needs different displayed text:

```python
self.set_preview_string(command_source, display_text=display_preview)
self.refresh_shell()
```

Interpretation:

- backing string: what executes, copies, and usually what the user sees
- display text: optional alternate lower-pane text only when product behavior needs it

## Good Override Reasons

Keep a subclass override only when it adds real local policy.

Examples:

- `can_do_it()` depends on local validation state beyond whether a backing payload
  exists
- `do_it_dispatch_mode()` must be visible instead of hidden
- `handle_do_it()` must perform validation, logging, rollback capture, or state
  bookkeeping before or after shared dispatch
- `can_send_to_cmd_line()` must intentionally disable visible command emission in one
  preview mode

## Bad Override Reasons

Delete overrides that only:

- return preview text already stored in the dialog
- forward directly to the base dispatch path without extra policy
- restate base help behavior
- maintain a second preview string that only mirrors the lower text widget

## Feature Ownership

Use `hyde/features/..._features.py` for:

- validation
- normalization
- preview/source lowering
- package-specific command generation

Two common cases:

1. Plugin owns the domain package or surface.
   Example: a fitting dialog that owns `lmfit` interaction.
2. Plugin uses a package/domain owned elsewhere.
   Example: a dialog that edits figures but should call figure-lowering helpers rather
   than recreate them locally.

In both cases, keep the dialog as a UI state holder and string factory, not the
authority on backend semantics.

## New Plugin Checklist

- plugin package name follows Hyde suffix taxonomy
- static layout is in `.ui`
- dialog subclass extends `HydeDialogWidget`
- dialog updates `set_preview_string(...)` from one real refresh path
- footer actions use the base class wherever possible
- launcher passes `services=` into the dialog
- no second dispatch path after dialog acceptance
- behavior tests prove execute/copy/send behavior

If this checklist cannot be satisfied, make the exception explicit in the spec, PRD,
and issue file rather than burying it in implementation.

## Existing Plugin Normalization Checklist

- remove trivial payload-getter wrappers and use `preview_string()` as the real
  backing command interface
- remove trivial `To Cmd Line` / `To Clip` implementations
- collapse duplicate preview state into the base backing string
- push command generation into the feature layer if duplicated in the dialog
- verify `Do It`, `To Cmd Line`, and `To Clip` all use the same backing command
  string unless the spec explicitly says otherwise

## Feature-Specific Policy

Do not copy feature-specific dialog contracts into this reference. When a dialog has
feature-specific ownership, preview, identity, or dispatch rules, read the active
spec, PRD, issue file, and Hyde docs directly and apply this pattern around those
sources.
