# HydeToolWidget Pattern

Default target shape for Hyde tool plugins. Shared ownership, IR, and override
rules live in `.agents/protocols/hyde/widget-family.md`; this file is the
tool-specific checklist.

## What The Base Owns

- the outer persistent shell (`hyde_window_widget.ui`)
- mounted-child plumbing (`mount_child_widget(...)`)
- subwindow binding and window identity
- hide-vs-close behavior through `close_policy()`

`HydeToolWindowPlugin` additionally owns the Window-menu action, the MDI window
descriptor, and the show/hide lifecycle, driven by class attributes
(`session_key`, `window_title`, `menu_name`, `window_size`, `menu_order`,
`creation_policy`) plus `create_tool_window_widget(...)`.

## Good Override Reasons

- `close_policy()` must be `"close"` instead of the default persistent hide
- `shutdown()` must perform extra cleanup
- the tool genuinely owns multiple runtime child surfaces, so one mounted child is
  not enough

## Bad Override Reasons

- recreating the base shell in plugin code
- wrapping `mount_child_widget(...)` without adding policy
- duplicating subwindow binding or identifier storage
- bypassing `close_policy()` with ad hoc close handling
- re-registering a menu action `HydeToolWindowPlugin` already contributes

## New Plugin Checklist

- package name ends in `_tool`
- static layout is in `.ui`
- the tool subclasses `HydeToolWidget`; the plugin subclasses
  `HydeToolWindowPlugin` unless it is a real exception
- the tool mounts one main child widget unless there is a concrete reason not to
- the launcher only opens/shows the tool
- if the tool emits Python, it comes from `widget_ir.python_source()`
- tests prove mounted-child behavior, subwindow identity, and close policy

## Normalization Checklist

- remove duplicated outer shell layout
- collapse mounted-child wrappers into `mount_child_widget(...)`
- remove duplicated subwindow-identifier plumbing
- move any locally assembled command text onto the tool's `widget_ir`
- move package-local string lowering into `hyde/features/<package>_features.py`,
  keeping validation and state normalization on the IR class
