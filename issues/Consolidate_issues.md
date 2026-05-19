# Consolidation Issues

## Completion Checklist

- [x] `CONS-01` Consolidate shared interactive execution and namespace-tracking helpers
- [x] `CONS-02` Centralize interactive window macro-menu and session boilerplate
- [x] `CONS-03` Standardize persistent tool-window lifecycle and service surfaces
- [x] `CONS-04` Move Procedure Browser onto the shared `HydeToolWidget` path
- [x] `CONS-05` Simplify file-dialog action binding and command dispatch
- [x] `CONS-06` Consolidate shared figure-control dialog draft/update helpers

## `CONS-01` Consolidate shared interactive execution and namespace-tracking helpers

**Type**: AFK

**Blocked by**: None - can start immediately

**User stories covered**:
- Hyde saveable windows should share one interactive-window runtime path.
- Table and figure windows should not maintain parallel hidden-execution helpers.
- Namespace-tracking refresh rules should live on the shared interactive-widget layer.

### What to build

Move the shared hidden-command execution and tracked-namespace snapshot helpers out of table/figure window implementations and into `HydeInteractiveWidget`. Keep the shared logic generic and widget-family-owned, then update table and figure windows to consume that shared contract instead of carrying local copies.

### Acceptance criteria

- [ ] `HydeInteractiveWidget` owns the common hidden-command execution helper used by both table and figure windows.
- [ ] Shared tracked-namespace snapshot logic lives on `HydeInteractiveWidget` instead of parallel table-only wrappers.
- [ ] Table and figure windows no longer keep duplicate implementations of the moved helpers.
- [ ] Tests verify the shared interactive-window behavior through observable table/figure refresh behavior rather than helper wiring.

## `CONS-02` Centralize interactive window macro-menu and session boilerplate

**Type**: AFK

**Blocked by**: `CONS-01`

**User stories covered**:
- Table and figure plugins should not each build the same macro-menu plumbing.
- No-op session overrides and repeated subwindow-destroy glue should not remain plugin-local.
- Interactive window plugins should state product-specific behavior, not repeated plugin scaffolding.

### What to build

Move repeated macro-menu creation and other duplicated plugin boilerplate for interactive windows into `HydePlugin`, then trim the table and figure plugins down to their feature-specific contributions. Remove redundant no-op or near-no-op overrides when the base already provides the behavior.

### Acceptance criteria

- [ ] Macro-menu creation is owned by shared plugin tooling rather than duplicated in both table and figure plugins.
- [ ] Redundant table/figure plugin overrides that only restate base behavior are removed.
- [ ] Table and figure plugins still expose the same user-visible macro menu behavior after the cleanup.
- [ ] Tests cover the shared menu/session contract at the plugin level and keep table/figure tests focused on feature behavior.

## `CONS-03` Standardize persistent tool-window lifecycle and service surfaces

**Type**: AFK

**Blocked by**: None - can start immediately

**User stories covered**:
- Persistent tool-window plugins should use one shared lifecycle policy.
- Plugin services should expose feature-specific behavior, not generic MDI wrappers.
- Shared restore and project-state transitions should not be re-declared per tool window.

### What to build

Pull repeated persistent tool-window lifecycle hooks into shared plugin tooling and trim duplicated service pass-throughs from Logging, Python Terminal, and Python Variables. Keep the resulting service interfaces focused on actual feature contracts while relying on `HydePlugin` and `HydeToolWidget` for generic window management behavior.

### Acceptance criteria

- [ ] Repeated persistent tool-window lifecycle handlers are centralized in shared plugin tooling.
- [ ] Logging, Python Terminal, and Python Variables no longer expose duplicate MDI wrapper methods that add no feature semantics.
- [ ] Existing user-visible tool-window behavior remains intact across project load, project activation, no-project mode, and kernel transitions.
- [ ] Tests verify the shared lifecycle contract and the remaining feature-specific service surface.

## `CONS-04` Move Procedure Browser onto the shared `HydeToolWidget` path

**Type**: AFK

**Blocked by**: `CONS-03`

**User stories covered**:
- Procedure Browser should behave like the other persistent tool windows.
- Persistent tool windows should share one close/hide and subwindow-binding path.
- Hyde should not keep raw ad hoc widgets under the tool-window plugin abstraction.

### What to build

Convert Procedure Browser from a raw `QWidget` implementation to the shared `HydeToolWidget` pattern so it participates in the standard persistent tool-window shell, subwindow binding, and close/hide behavior. Keep its feature-specific behavior local while removing the ad hoc lifecycle path.

### Acceptance criteria

- [ ] Procedure Browser is implemented on top of `HydeToolWidget` rather than a raw `QWidget`.
- [ ] Procedure Browser participates in the standard persistent tool-window subwindow binding and close/hide behavior.
- [ ] Existing Procedure Browser user behavior remains intact, including directory updates and double-click launch behavior.
- [ ] Tests cover Procedure Browser through the shared tool-window contract rather than bespoke widget plumbing.

## `CONS-05` Simplify file-dialog action binding and command dispatch

**Type**: AFK

**Blocked by**: None - can start immediately

**User stories covered**:
- File-dialog plugins should use shared menu-action binding instead of local registries.
- One-off command wrapper classes should not exist when plugin/dialog dispatch already covers the behavior.
- File-dialog behavior should stay easy to reason about and test end to end.

### What to build

Remove the duplicate action-binding layer from the file-dialog plugin and collapse the standalone save/quit command wrappers back into the existing plugin/dialog dispatch path. Keep the end-to-end new/load/save/quit flows unchanged while reducing unnecessary abstraction.

### Acceptance criteria

- [ ] The file-dialog plugin uses shared menu-action binding instead of a duplicate local registry.
- [ ] One-off save/quit command wrapper classes are removed if they only forward existing dialog/plugin dispatch behavior.
- [ ] File-dialog flows still produce the same user-visible project-selection and dispatch behavior.
- [ ] Tests cover the end-to-end file-dialog flows and no longer depend on the removed wrapper shapes.

## `CONS-06` Consolidate shared figure-control dialog draft/update helpers

**Type**: AFK

**Blocked by**: None - can start immediately

**User stories covered**:
- Figure-control dialogs should not each carry parallel draft/apply/revert plumbing.
- Obvious helper duplication inside the figure-control-dialog family should be removed.
- Figure-control dialog code should better match the documented local shared-layer design.

### What to build

Introduce a small figure-control-dialog family shared layer for draft-state and live-update/apply/revert behavior that is currently split between axis and trace dialogs. Remove literal helper duplication, especially where two helpers express the same normalization policy, while keeping the figure-control-dialog logic local to that family rather than pushing it onto widget/plugin bases.

### Acceptance criteria

- [ ] Shared draft/update/revert dialog-family behavior is factored into a local figure-control-dialog layer instead of duplicated across axis and trace dialogs.
- [ ] Literal duplicate helpers are removed or merged.
- [ ] Axis and trace dialogs preserve their current user-visible behavior, including preview/update/cancel flows.
- [ ] Tests validate the dialog-family contract through observable dialog behavior rather than helper implementation details.
