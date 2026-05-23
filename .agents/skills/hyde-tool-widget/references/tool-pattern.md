# HydeToolWidget Pattern

Use this as the default target shape for Hyde tool plugins.

This reference is used in two modes:

- implementation mode: build or normalize the tool code
- planning mode: help `to-issues` capture the intended standard shape before code
  exists

## Ownership Split

`HydeToolWidget` should own:

- the outer persistent shell
- mounted-child plumbing
- subwindow binding and window identity
- default hide-vs-close behavior through `close_policy()`

The subclass or mounted child should own:

- the actual content UI
- signal wiring
- dynamic rows/items
- domain behavior

## Good Override Reasons

Keep a subclass override only when it adds real local policy.

Examples:

- `close_policy()` must be `"close"` instead of the default persistent hide behavior
- the tool must perform extra shutdown cleanup in `shutdown()`
- a mounted child widget is not enough because the tool truly owns multiple runtime
  child surfaces

## Bad Override Reasons

Delete structure that only:

- recreates the base shell in plugin code
- wraps `mount_child_widget(...)` without adding policy
- duplicates subwindow binding or identifier storage
- bypasses `close_policy()` with ad hoc close handling

## Feature Ownership

Use `hyde/features/..._features.py` for:

- validation
- command lowering
- package-specific logic

Two common cases:

1. The tool owns the domain package or surface.
2. The tool uses a package/domain owned elsewhere and should call that feature owner.

## New Plugin Checklist

- plugin package name follows Hyde suffix taxonomy
- static layout is in `.ui`
- tool subclass extends `HydeToolWidget`
- tool mounts one main child widget unless there is a real reason not to
- launcher only opens/shows the tool
- behavior tests prove mounted-child and close-policy behavior

## Existing Plugin Normalization Checklist

- remove duplicated outer shell layout
- collapse mounted-child wrappers into `mount_child_widget(...)`
- remove duplicated subwindow-identifier plumbing
- move domain lowering into the feature layer if duplicated in the tool
