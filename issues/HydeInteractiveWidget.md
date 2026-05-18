## Problem Statement

Hyde's table and figure windows share a substantial amount of saveable-window behavior, but that behavior is currently split across parallel implementations. Both windows participate in the same broad product contract: they are widget-backed MDI children, they support stable window identity, they remember normal geometry, they generate recreation source, they can be saved as macros, they restore through the saveable-window path, and they follow a prompt-oriented close policy that interacts with the save-window dialog flow.

At the same time, the shared behavior is mixed together with feature-specific logic for table recreation, figure recreation, table data refresh, figure comm traffic, table cleanup, and figure kernel-close handshakes. That makes it harder to reason about what is generic saveable-window behavior versus what is specific to tables or figures. It also raises the cost of adding any future saveable window because there is no single shared parent that captures the common contract.

The goal is to introduce a shared parent class for table and figure widgets that owns the saveable-window contract and generic MDI-child mechanics while preserving the real semantic differences between table and figure behavior.

## Solution

Introduce `HydeInteractiveWidget` as the shared parent class for saveable widget windows such as tables and figures.

`HydeInteractiveWidget` will either subclass `HydeToolWidget` or share a common abstract parent with it, but in either case it will add saveable-window behavior that ordinary persistent tool windows do not have. It will own the generic saveable-window contract shape, the shared subwindow binding and geometry behavior, and the shared prompt-oriented close flow.

The parent class will own the broad saveable-window interface shape:

- default macro naming support
- macro source generation entrypoints
- session-restore source generation entrypoints
- shared saveable-window state handling
- shared close-policy structure

The parent will also own generic MDI-child mechanics that both table and figure widgets currently implement in parallel:

- `_subwindow` tracking
- stable-name binding
- remembered normal geometry
- event-filter-based geometry tracking
- generic helpers such as activating the MDI subwindow before popup menu actions

The shared close flow will be centralized as well. The parent class will own shift-bypass support, prompting through `save_window_dialog_service`, and the ordinary saveable-window close structure. Subclasses will only implement the final close action that completes the feature-specific shutdown:

- tables clean up and close immediately
- figures queue a kernel close and wait for confirmation

Feature-specific behavior will remain on the subclass side. Recreation-source generation details, kernel/data transport, refresh/update behavior, and final close completion semantics will stay specific to the table or figure implementation.

## User Stories

1. As a Hyde developer, I want a shared parent for saveable widget windows, so that tables and figures follow one clear architectural contract.
2. As a Hyde developer, I want saveable-window behavior separated from ordinary persistent tool-window behavior, so that the two products do not leak into each other.
3. As a Hyde developer, I want tables and figures to share one parent-level saveable-window interface, so that future saveable windows can follow the same pattern.
4. As a Hyde developer, I want stable-name binding and subwindow attachment logic centralized, so that I do not maintain that MDI-child machinery in parallel.
5. As a Hyde developer, I want remembered normal geometry behavior centralized, so that saveable windows preserve their window placement consistently.
6. As a Hyde developer, I want the shared parent to own generic popup-menu activation behavior, so that saveable windows interact with the MDI shell consistently.
7. As a Hyde developer, I want saveable-window macro naming and recreation-source entrypoints defined at the parent level, so that the common save contract is obvious.
8. As a Hyde developer, I want tables and figures to share one prompt-oriented close structure, so that users encounter one consistent saveable-window close policy.
9. As a Hyde developer, I want shift-bypass behavior handled centrally, so that saveable windows do not each implement a slightly different shortcut close path.
10. As a Hyde developer, I want prompting through `save_window_dialog_service` handled by the shared parent, so that the saveable-window contract is implemented once.
11. As a Hyde developer, I want subclasses to provide only their final close action, so that table and figure differences stay focused and local.
12. As a Hyde developer, I want table-specific refresh and mutation behavior to remain outside the shared parent, so that the parent does not become table-shaped.
13. As a Hyde developer, I want figure-specific comm handling and kernel-close confirmation to remain outside the shared parent, so that the parent does not become figure-shaped.
14. As a Hyde maintainer, I want `HydeInteractiveWidget` to reuse as much generic widget/window behavior as possible from the `HydeToolWidget` direction, so that the two window families do not diverge unnecessarily.
15. As a Hyde maintainer, I want saveable-window state handling to stay distinct from ordinary `session.toml` tool-window persistence, so that product behavior remains clear.
16. As a Hyde developer, I want future saveable windows to start from a parent that already knows the MDI and saveable-window rules, so that new windows do not rebuild those rules from scratch.
17. As a Hyde developer, I want saveable-window recreation logic to remain expressible through subclass contracts, so that different scientific products can restore through their own authoritative path.
18. As a Hyde maintainer, I want the shared parent to make testing easier, so that generic saveable-window behavior can be validated once instead of being rediscovered through feature-specific tests.
19. As a Hyde developer, I want the shared parent to preserve the meaningful difference between table close semantics and figure close semantics, so that architectural cleanup does not flatten real runtime differences.
20. As a Hyde maintainer, I want the resulting class name and role to be clearly parallel to `HydeToolWidget`, so that the codebase communicates two distinct window families: persistent tool widgets and saveable widgets.

## Implementation Decisions

- The parent class will be named `HydeInteractiveWidget`.
- `HydeInteractiveWidget` will either subclass `HydeToolWidget` or share a common abstract parent with it. Either shape is acceptable as long as the overlap is factored cleanly.
- `HydeInteractiveWidget` is specifically for saveable widget windows such as tables and figures and is not a generic replacement for `HydeToolWidget`.
- `HydeInteractiveWidget` will own the saveable-window contract shape, including parent-level entrypoints for default macro naming, macro source generation, session-restore source generation, shared saveable-window state handling, and shared close-policy structure.
- `HydeInteractiveWidget` will own the shared MDI-child mechanics currently duplicated between tables and figures: subwindow tracking, stable-name binding, remembered normal geometry, event-filter-driven geometry updates, and generic activation helpers for popup-menu interactions.
- `HydeInteractiveWidget` will own the shared prompt-oriented close flow: shift-bypass handling, use of `save_window_dialog_service`, and the ordinary saveable-window close structure.
- Subclasses will provide the final close action that completes feature-specific shutdown.
- Table-specific and figure-specific runtime semantics will remain in subclasses, including recreation-source details, kernel/data transport, refresh/update logic, and feature-specific close completion.
- Saveable-window semantics remain distinct from ordinary persistent tool-window `session.toml` persistence.
- This work does not force a decision to merge all widget families into one class; it only requires that overlap between the families be factored cleanly.
- The new abstraction should favor the smallest clear parent that captures real shared behavior without absorbing table-specific or figure-specific transport logic.

## Testing Decisions

- Good tests should verify external saveable-window behavior and explicit architectural contracts, not helper wiring or incidental method call sequences.
- Shared tests should validate the generic behaviors promised by `HydeInteractiveWidget`: subwindow binding, remembered geometry behavior, popup-menu activation behavior, close policy, shift-bypass semantics, and save dialog integration where externally visible.
- Table and figure tests should continue to validate their product-specific observable behavior rather than re-testing all generic saveable-window behavior through duplicate assertions.
- The feature-specific tests should focus on the parts that remain subclass-owned: recreation-source behavior, runtime refresh/update behavior, and final close completion semantics.
- Tests should avoid over-coupling to whether the common parent subclasses `HydeToolWidget` directly or shares a thinner abstract ancestor with it.

## Out of Scope

- Refactoring ordinary persistent tool windows into `HydeInteractiveWidget`.
- Unifying saveable-window `session.py` behavior with ordinary tool-window `session.toml` persistence.
- Flattening the real semantic difference between table and figure shutdown behavior.
- Moving table data transport, mutation logic, or recreation lowering into the shared parent.
- Moving figure comm handling, payload routing, or kernel-close confirmation logic into the shared parent.
- Introducing a generic service abstraction as part of this change.
- Broad plugin-system redesign beyond what is needed to support the shared parent cleanly.

## Further Notes

- `HydeInteractiveWidget` is the chosen parallel name to `HydeToolWidget`.
- The design intentionally preserves a distinction between two window families:
  - persistent tool widgets
  - saveable widgets
- The common parent should deepen the saveable-window module without obscuring the fact that tables and figures still restore and shut down through different authoritative paths.
