# HydeInteractiveWidget Pattern

Default target shape for Hyde interactive plugins. Shared ownership, IR, and
override rules live in `.agents/protocols/hyde/widget-family.md`; this file is the
interactive-specific checklist.

## What The Base Owns

- stable window naming
- subwindow binding
- geometry and window-state capture
- macro/session-restore scaffolding
- tracked namespace-state bookkeeping

## Good Override Reasons

- `tracked_namespace_names()` declares which namespace objects drive refreshes
- `on_stable_name_bound(...)` must update domain state from the final stable name
- saveable source methods must emit domain-specific Python

## Bad Override Reasons

- reimplementing stable-name plumbing
- duplicating window-state capture
- wrapping existing save/restore helpers without adding policy
- mirroring tracked namespace state locally without a real need

## New Plugin Checklist

- package name ends in `_interactive`
- static layout is in `.ui`
- the widget subclasses `HydeInteractiveWidget`
- `widget_ir` holds the live current object IR for the window
- stable window naming is base-owned
- creation adds the window to the MDI area with delete-on-close, binds the
  subwindow, and registers it with the plugin's workspace service
- save/restore source lowers from `widget_ir` and is tested
- namespace-driven refresh behavior is explicit and tested

## Normalization Checklist

- remove duplicated stable-name plumbing
- remove duplicated save/restore wrapper layers
- collapse namespace tracking onto the base contract
- move any locally assembled command text onto `widget_ir`
- move package-local string lowering into `hyde/features/<package>_features.py`,
  keeping validation and state normalization on the IR class
