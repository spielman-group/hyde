# HydeInteractiveWidget Pattern

Use this as the default target shape for Hyde interactive plugins.

This reference is used in two modes:

- implementation mode: build or normalize the interactive code
- planning mode: help `to-issues` capture the intended standard shape before code
  exists

## Ownership Split

`HydeInteractiveWidget` should own:

- stable window naming
- subwindow binding
- geometry/window-state capture
- macro/session-restore scaffolding
- tracked namespace-state bookkeeping

The subclass should own:

- the actual interactive content
- domain refresh behavior
- explicit saveable source methods
- domain behavior and command generation

## Good Override Reasons

Keep a subclass override only when it adds real local policy.

Examples:

- `tracked_namespace_names()` declares which namespace objects drive refreshes
- `on_stable_name_bound(...)` must update domain state from the final stable name
- saveable source methods must emit domain-specific Python

## Bad Override Reasons

Delete structure that only:

- reimplements stable-name plumbing
- duplicates window-state capture
- wraps existing save/restore helpers without adding policy
- mirrors tracked namespace state locally without a real need

## Feature Ownership

Use `hyde/features/..._features.py` for:

- validation
- command lowering
- package-specific logic

Two common cases:

1. The interactive widget owns the domain package or surface.
2. The interactive widget uses a package/domain owned elsewhere and should call that
   feature owner.

## New Plugin Checklist

- plugin package name follows Hyde suffix taxonomy
- static layout is in `.ui`
- interactive subclass extends `HydeInteractiveWidget`
- stable window naming is base-owned
- save/restore source is explicit and tested
- namespace-driven refresh behavior is explicit and tested

## Existing Plugin Normalization Checklist

- remove duplicated stable-name plumbing
- remove duplicated save/restore wrapper layers
- collapse namespace tracking onto the base contract
- move domain lowering into the feature layer if duplicated in the widget
