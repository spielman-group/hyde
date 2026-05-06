# Figure/Table Context Menu TRD

## Problem Statement

Hyde currently has only static top-level `File` and `Windows` menus. First-class
figure windows and table windows do not have a shared contextual top-level menu that
appears when one of those windows is active. Figure right-click behavior is also
hardcoded locally rather than reusing the same menu surface as the main menu bar.

The intended Hyde behavior is:

- when a figure window is active, a top-level `Figure` menu appears in the menu bar
- when a table window is active, a top-level `Table` menu appears in the menu bar
- those menus are hidden by default
- right-clicking the active figure or table uses the same menu content as the
  corresponding top-level menu
- plugins contribute actions to those menus through the normal Hyde menu system rather
  than through figure-specific or table-specific side registries

This TRD defines only the shared menu-host behavior. It does not define the concrete
dialog or editing features that later plugins will add to those menus.

## Solution

Extend Hyde's existing menu system with two new first-class menu locations:

- `figure`
- `table`

The main UI creates `menuFigure` and `menuTable` at startup, after `Windows`, and keeps
them hidden by default. They are populated once through the normal Hyde menu
contribution path, just like `file` and `window`.

Visibility is controlled through new Hyde-standard main-UI menu methods:

- `show_menu(name)`
- `hide_menu(name)`
- `popup_menu(name, global_pos)`

Figure and table windows use the smallest-code activation wiring available in Qt to
show or hide their corresponding contextual menu through that standard main-UI API.
The same `QMenu` instance is used both as the top-level menu-bar menu and as the
right-click popup menu.

The same behavior applies to figures and tables in parallel:

- active `FigureWindow` -> show `Figure`, hide `Table`
- active `TableWidget`/table window -> show `Table`, hide `Figure`
- non-figure, non-table active window -> hide both contextual menus

## Technical Requirements

### Main UI

- Hyde main UI must create `menuFigure` and `menuTable` during startup.
- Both menus must be registered as standard menu locations named `figure` and `table`.
- Both menus must be hidden by default.
- Both menus must appear after `Windows` in the menu bar order.
- Hyde main UI must expose a standard interface for contextual menu visibility and
  popup:
  - `show_menu(name)`
  - `hide_menu(name)`
  - `popup_menu(name, global_pos)`
- The main UI must not need to know Hyde feature semantics beyond menu names. It owns
  generic menu creation and visibility/popup operations only.

### Menu Registration

- Plugins must register `figure` and `table` actions through the existing Hyde menu
  contribution system.
- Registration behavior for `figure` and `table` must match existing menu locations.
- Grouping and ordering must be supported from the start through the same contribution
  fields already used for other menus.
- No separate figure-only or table-only action registry may be introduced.
- Menu callbacks remain ordinary Hyde menu callbacks. The menu framework does not pass
  figure-specific or table-specific context objects into callbacks.

### Figure Menu Behavior

- When a figure window is active, the `Figure` menu must be shown.
- When that figure window becomes inactive, the `Figure` menu may be hidden using the
  smallest-code implementation path, even if this produces simple visual transitions.
- If a figure is active and no actions are registered yet, the empty `Figure` menu must
  still be shown.
- Every action registered to the `figure` menu must appear both in the top-level
  `Figure` menu and in the figure right-click menu.
- The right-click surface must use the same `QMenu` instance as the top-level `Figure`
  menu rather than a separately rendered copy.
- If the user right-clicks a figure that is not currently the active MDI window, Hyde
  must first activate that figure window and then open the `Figure` menu for it.
- `figure` menu actions are always interpreted relative to the active figure window.
- For this first version, if a figure is active then every registered `figure` action
  is enabled.
- A figure action handler must defensively verify that the active MDI window is still a
  figure window before doing any work.

### Table Menu Behavior

- Table behavior must be exactly parallel to figure behavior, with naming and window
  types substituted appropriately.
- When a table window is active, the `Table` menu must be shown.
- When that table window becomes inactive, the `Table` menu may be hidden using the
  smallest-code implementation path.
- If a table is active and no actions are registered yet, the empty `Table` menu must
  still be shown.
- Every action registered to the `table` menu must appear both in the top-level
  `Table` menu and in the table right-click menu.
- The right-click surface must use the same `QMenu` instance as the top-level `Table`
  menu.
- If the user right-clicks a table that is not currently the active MDI window, Hyde
  must first activate that table window and then open the `Table` menu for it.
- `table` menu actions are always interpreted relative to the active table window.
- For this first version, if a table is active then every registered `table` action is
  enabled.
- A table action handler must defensively verify that the active MDI window is still a
  table window before doing any work.

## User Stories

1. As a Hyde user, I want a `Figure` menu to appear when a figure window is active, so
   that figure-specific commands are easy to discover.
2. As a Hyde user, I want a `Table` menu to appear when a table window is active, so
   that table-specific commands are easy to discover.
3. As a Hyde user, I want contextual menus to stay out of the menu bar when they are
   irrelevant, so that the shell stays uncluttered.
4. As a Hyde developer, I want `figure` and `table` to be ordinary Hyde menu
   locations, so that plugin code stays consistent with the existing menu system.
5. As a Hyde plugin author, I want to register a `figure` or `table` action the same
   way I register `file` or `window` actions, so that I do not need a second menu API.
6. As a Hyde plugin author, I want grouped menu rendering from the start, so that
   larger contextual menus remain organized as more features are added.
7. As a Hyde user, I want the same figure actions available from the menu bar and from
   right-clicking a figure, so that both access paths behave identically.
8. As a Hyde user, I want the same table actions available from the menu bar and from
   right-clicking a table, so that both access paths behave identically.
9. As a Hyde developer, I want the main UI to own menu hiding, showing, and popup
   behavior generically, so that feature plugins do not manipulate menu-bar internals.
10. As a Hyde developer, I want contextual menu visibility to be debuggable even before
    any feature actions are implemented, so that empty contextual menus can still be
    shown while the shell contract is being built.
11. As a Hyde plugin author, I want menu callbacks to stay ordinary callbacks, so that
    contextual menus do not require menu-framework-specific context plumbing.
12. As a Hyde developer, I want figure and table actions to resolve against the active
    window at invocation time, so that the shell keeps one simple targeting rule.

## Implementation Decisions

- Hyde will add two new standard menu locations: `figure` and `table`.
- Hyde main UI will create `menuFigure` and `menuTable` at startup and register them in
  the existing menu context.
- `menuFigure` and `menuTable` will be hidden by default and shown only through the new
  standard menu visibility API.
- Hyde main UI will provide `show_menu(name)`, `hide_menu(name)`, and
  `popup_menu(name, global_pos)` as generic shell services.
- Figure and table windows will use simple Qt activation/deactivation wiring to drive
  their corresponding contextual menu visibility through those main-UI services.
- The first implementation will prefer the smallest clear code path over extra logic
  for focus edge cases or visual polish.
- The same `QMenu` instance will serve both as the menu-bar menu and as the popup menu
  for the matching contextual window type.
- No special context object will be passed through the menu framework for contextual
  menus.
- Plugins that contribute contextual actions remain responsible for validating that the
  current active MDI window is of the expected type before acting.

## Testing Decisions

- Tests should focus on observable shell behavior rather than internal signal ordering.
- Good tests should verify:
  - `figure` and `table` are valid menu locations
  - `menuFigure` and `menuTable` exist, are created at startup, and start hidden
  - actions registered to `figure` and `table` populate the expected menus
  - showing, hiding, and popup operations route through the standard main-UI menu API
  - activating a figure shows `Figure`
  - activating a table shows `Table`
  - activating a non-contextual window hides both contextual menus
  - right-click on a figure or table uses the matching shared `QMenu`
- Tests should not depend on incidental Qt implementation details beyond what is needed
  to prove the shell contract.
- Prior art exists in Hyde's current menu and plugin tests, especially the plugin tools
  coverage around menu registration and rendered actions.

## Out Of Scope

- Any concrete figure-editing actions such as append trace, remove trace, modify trace,
  modify axis, text insertion, or fitting
- Any concrete table-editing or formatting actions
- Per-action enable/disable predicates
- Special logic for preserving contextual-menu visibility across modal dialogs or other
  focus edge cases
- New figure or table runtime services beyond what is required for the shell/menu
  contract
- Changes to figure IR, table IR, or kernel-side editing behavior

## Further Notes

- This document intentionally defines figure and table contextual menus together so the
  shell behavior stays identical across both window families.
- The menu-host contract should be implemented first and be debuggable even when the
  menus are empty.
- Later feature plugins can build on this shell contract without adding new top-level
  menu infrastructure.
