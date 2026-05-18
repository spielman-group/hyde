# New Classes Issue Breakdown

Draft issue breakdown for:
- `issues/HydeToolWidget.md`
- `issues/HydeInteractiveWidget.md`

## Checklist

- [x] `HTW-01` Create `HydeToolWidget` and move Logging onto the default persistent-tool-window shell
- [x] `HTW-02` Introduce shared ordinary tool-window plugin plumbing and migrate Procedure Browser
- [x] `HTW-03` Wrap Python Terminal in a mounted-child `HydeToolWidget`
- [x] `HTW-04` Move Python Variables to a custom-UI `HydeToolWidget` with delegated widget session state
- [x] `HIW-01` Introduce `HydeInteractiveWidget` and migrate table windows onto the shared saveable-window contract
- [x] `HIW-02` Migrate figure windows to `HydeInteractiveWidget` without flattening kernel-close semantics
- [x] `HIW-03` Finalize the shared saveable-window contract across tables and figures
- [x] `HWR-01` Generalize `HydeToolWidget` into the shared Hyde window shell
- [x] `HWR-02` Rebase `HydeInteractiveWidget` onto `HydeToolWidget` and collapse duplicate widget mechanics

## Issues From `HydeToolWidget.md`

### `HTW-01` Create `HydeToolWidget` and Move Logging Onto the Default Persistent-Tool-Window Shell

**Type**: AFK  
**Blocked by**: None  
**User stories covered**: 1, 2, 3, 7, 8, 18, 19

#### What to build

Introduce `HydeToolWidget` as the shared base for persistent tool windows, including the shared default outer UI, service storage/lookup, `session_key` handling, mounted-child support, default hide-on-close behavior, and a standard `shutdown()` hook. Prove the base with the smallest current tool window by moving Logging onto it without changing its runtime-output service contract.

#### Acceptance criteria

- [ ] Logging still opens as an MDI tool window from the Window menu and still exposes the same runtime output service behavior.
- [ ] The outer widget shell comes from `HydeToolWidget` and the shared default UI rather than ad hoc Python layout code in the Logging plugin.
- [ ] Closing the Logging window hides the persistent tool window instead of destroying it, while explicit shutdown remains available for teardown paths.
- [ ] Contract tests cover base UI loading, service lookup, mounted-child support, and the default close/hide semantics.

### `HTW-02` Introduce Shared Ordinary Tool-Window Plugin Plumbing and Migrate Procedure Browser

**Type**: AFK  
**Blocked by**: `HTW-01`  
**User stories covered**: 9, 10, 11, 12, 16, 17, 19

#### What to build

Add shared plugin-side behavior for ordinary persistent tool windows so a plugin can declare its identity, menu presentation, MDI contribution, creation policy, and widget/session delegation without repeating bespoke boilerplate. Migrate Procedure Browser onto that shared plugin path while preserving its project-activation and no-project behavior.

#### Acceptance criteria

- [ ] Procedure Browser declares its normal tool-window metadata through shared plugin behavior rather than repeating local factory/menu/session boilerplate.
- [ ] Plugin-owned `session_key` continues to drive both MDI identity and tool-window persistence state.
- [ ] Generic tool-window restore still happens through the existing plugin-owned session/MDI path, with the shared flow ready to delegate widget-specific restore after generic restore.
- [ ] Procedure Browser still enables, disables, shows, hides, and updates its procedures directory correctly across project activation and no-project transitions.
- [ ] Tests cover shared widget construction, menu wiring, eager-versus-lazy creation policy, and restore delegation order.

### `HTW-03` Wrap Python Terminal in a Mounted-Child `HydeToolWidget`

**Type**: AFK  
**Blocked by**: `HTW-02`  
**User stories covered**: 5, 10, 11, 13, 16, 17

#### What to build

Keep the terminal's `RichJupyterWidget` behavior intact, but host it inside a `HydeToolWidget` container that uses the shared default UI and child-mounting path. Move the plugin onto the shared ordinary tool-window plumbing while preserving eager creation on kernel readiness, visible history behavior, and crash teardown.

#### Acceptance criteria

- [ ] Python Terminal still behaves as the visible console, including visible execution and history capture/restore.
- [ ] The outer persistent tool-window shell is a `HydeToolWidget` that hosts the console widget through the mounted-child path.
- [ ] Kernel-ready eager creation, menu presentation, and kernel-crash teardown continue to work through the shared plugin flow.
- [ ] Tests cover mounted-child tool-window behavior and preserved terminal history/session contracts.

### `HTW-04` Move Python Variables to a Custom-UI `HydeToolWidget` With Delegated Widget Session State

**Type**: AFK  
**Blocked by**: `HTW-02`  
**User stories covered**: 4, 5, 6, 11, 12, 14, 18

#### What to build

Convert Python Variables into a `HydeToolWidget` subclass that keeps its own UI file and existing kernel-runtime/Spyder-comm behavior, while moving filter/info-pane persistence into widget-owned session hooks delegated by the shared plugin flow. Preserve the current service shape instead of broadening this work into a generic service redesign.

#### Acceptance criteria

- [ ] Python Variables still refreshes namespace metadata, supports selection/context actions, and preserves its current service-facing behavior.
- [ ] Widget-specific state such as filter toggles and info-pane visibility is saved and restored through widget-owned `session.toml` hooks rather than plugin-side control scraping.
- [ ] Generic tool-window restore runs before widget-specific restore so the widget restores in a valid MDI context.
- [ ] Tests cover persistence of Python Variables view-state across project save/load and verify the custom-UI `HydeToolWidget` path.

## Issues From `HydeInteractiveWidget.md`

### `HIW-01` Introduce `HydeInteractiveWidget` and Migrate Table Windows Onto the Shared Saveable-Window Contract

**Type**: AFK  
**Blocked by**: `HTW-01`  
**User stories covered**: 1, 2, 4, 5, 6, 8, 9, 10, 11, 12, 16, 18

#### What to build

Introduce `HydeInteractiveWidget` as the saveable-window parent for interactive MDI children and use table windows as the first end-to-end migration. The parent should own shared subwindow binding, stable-name handling, remembered normal geometry, popup-activation helpers, shared close-policy structure, and the saveable-window interface surface, while the table subclass keeps table-specific recreation, mutation, refresh, and immediate-close behavior.

#### Acceptance criteria

- [ ] Table windows preserve stable handle binding, remembered normal geometry, and popup-menu activation through shared parent behavior.
- [ ] The save dialog flow and shift-bypass behavior still work for tables, while the final close action remains the table-specific immediate cleanup path.
- [ ] Table macro generation and session-restore generation still lower through the existing table-authoritative recreation path.
- [ ] Shared tests cover parent-level geometry, activation, and close-policy behavior through the table-backed migration.

### `HIW-02` Migrate Figure Windows to `HydeInteractiveWidget` Without Flattening Kernel-Close Semantics

**Type**: AFK  
**Blocked by**: `HIW-01`  
**User stories covered**: 3, 7, 8, 9, 10, 11, 13, 17, 19

#### What to build

Move figure windows onto `HydeInteractiveWidget` so they share the same saveable-window shell as tables, but keep the figure-specific runtime semantics local to the figure subclass. The shared parent should supply the generic prompt and MDI behavior, while the figure subclass remains responsible for figure IR recreation, comm traffic, kernel-close queuing, duplicate-close protection, and timeout handling.

#### Acceptance criteria

- [ ] Figure windows preserve stable identity, remembered geometry, and popup-menu activation while inheriting the shared saveable-window shell.
- [ ] Closing a figure still uses the shared prompt flow, then queues a kernel close and waits for confirmation instead of taking the table immediate-close path.
- [ ] Figure macro generation and session-restore generation still lower through the figure-authoritative recreation path.
- [ ] Tests prove that figure-specific close completion remains distinct from the table close contract.

### `HIW-03` Finalize the Shared Saveable-Window Contract Across Tables and Figures

**Type**: AFK  
**Blocked by**: `HIW-02`  
**User stories covered**: 14, 15, 18, 20

#### What to build

After both tables and figures sit on the new parent, remove the remaining parallel saveable-window scaffolding so `HydeInteractiveWidget` becomes the single home for the generic contract. Make the parent-level interface for macro naming, saveable state handling, session-restore entrypoints, shift-bypass behavior, and save-dialog structure explicit, while keeping table/figure transport and authoritative recreation details out of the parent.

#### Acceptance criteria

- [ ] Generic saveable-window scaffolding is no longer duplicated across table and figure widgets beyond subclass-owned recreation and final-close behavior.
- [ ] Both tables and figures consume one explicit parent-level interface for default macro naming, saveable-window state handling, and restore/macro entrypoints.
- [ ] Shared tests validate the generic saveable-window contract once, while table and figure tests focus on subclass-specific behavior.
- [ ] The resulting code and docs make the two Hyde window families explicit: `HydeToolWidget` for persistent tool windows and `HydeInteractiveWidget` for saveable windows.

## Follow-On Revision Issues

### `HWR-01` Generalize `HydeToolWidget` Into the Shared Hyde Window Shell

**Type**: AFK  
**Blocked by**: `HTW-04`, `HIW-03`  
**User stories covered**: HydeToolWidget 1, 2, 3, 5, 7, 8; HydeInteractiveWidget 14, 16, 18, 20

#### What to build

Refactor `HydeToolWidget` so it becomes the common Hyde MDI widget shell rather than a tool-window-only base. Move the truly shared widget mechanics into that class: the default shared `.ui` shell, service storage and lookup, the common window identifier, mounted-child support, subwindow binding, and base shutdown/close-policy hooks. Keep ordinary tool-window behavior intact by expressing tool-specific close behavior as policy instead of structure.

#### Acceptance criteria

- [ ] `HydeToolWidget` can serve as the shared shell for both persistent tool windows and saveable interactive windows without duplicating base widget mechanics elsewhere.
- [ ] The shared default `.ui` shell has neutral naming and continues to load correctly for existing tool-window consumers.
- [ ] Ordinary tool-window behavior remains intact for Logging, Procedure Browser, Python Terminal, and Python Variables, including hide-on-close and explicit teardown behavior.
- [ ] Tests cover the shared shell contract through public behavior rather than wrapper internals.

### `HWR-02` Rebase `HydeInteractiveWidget` Onto `HydeToolWidget` and Collapse Duplicate Widget Mechanics

**Type**: AFK  
**Blocked by**: `HWR-01`  
**User stories covered**: HydeInteractiveWidget 1, 3, 4, 5, 6, 7, 8, 10, 11, 14, 16, 18, 20

#### What to build

Make `HydeInteractiveWidget` a `HydeToolWidget` subclass and remove the duplicate widget shell mechanics that have drifted apart. Adopt one common window-identity concept across tool and interactive windows, keep shared `.ui` shell behavior aligned, and leave only saveable-window behavior on the interactive subclass: stable-name handling, remembered geometry, macro/session-restore generation, and prompt-oriented close flow.

#### Acceptance criteria

- [ ] `HydeInteractiveWidget` subclasses `HydeToolWidget` and no longer reimplements shared service, shell, mounted-child, or subwindow plumbing.
- [ ] Table and figure windows preserve their current saveable behavior, including stable naming, geometry capture, macro/session-restore generation, and their distinct close semantics.
- [ ] Shared identity naming is unified across the common base and interactive subclass instead of splitting `session_key` versus window-handle concepts unnecessarily.
- [ ] Tests prove the shared-shell/subclass contract through observable behavior while keeping tool-window and saveable-window policy differences explicit.
