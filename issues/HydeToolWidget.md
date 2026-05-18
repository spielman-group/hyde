## Problem Statement

Hyde's persistent tool-window plugins currently repeat the same outer-widget and plugin boilerplate in several places. The repeated work includes UI loading, service storage and lookup, widget-specific `session.toml` save and restore behavior, close-versus-hide behavior for persistent windows, lifecycle shim methods, plugin-side widget factory code, plugin-side MDI contribution dictionaries, plugin-side menu wiring, and plugin-side delegation from plugin hooks into widget methods.

This repetition makes it harder to add new persistent tool windows, especially the planned fitting window, and makes existing windows such as Python Variables, Python Terminal, Logging, and Procedures feel more structurally different than they should. The current pattern also encourages building simple controls directly in Python when they would be better expressed in `.ui` files.

The goal is to introduce a shared `HydeToolWidget` abstraction and matching plugin-side boilerplate reduction so persistent tool windows follow one clear pattern while preserving Hyde's existing plugin-owned session and MDI contracts.

## Solution

Introduce `HydeToolWidget` as the standard base class for persistent tool-window widgets and extend the plugin base so ordinary tool-window plugins can be declared with much less custom code.

`HydeToolWidget` will do meaningful shared work in `super().__init__(...)`: load `self.ui` from a configured `ui_path`, keep the shared `services` mapping, expose a small `service()` helper, store the runtime `session_key`, provide widget-level `session.toml` save and restore hooks, define no-op lifecycle shim methods for plugin-to-widget forwarding, expose a standard `shutdown()` hook, provide the default persistent-tool-window close/hide behavior, and include the helper needed for mounting child widgets into the shared default UI.

There will be one shared default UI file, `hyde_tool_widget.ui`. Subclasses may override `ui_path` when they need a custom outer UI. The design explicitly supports both of these patterns:

- use the shared default UI and mount a child widget into it, such as wrapping a `RichJupyterWidget` for Python Terminal
- override `ui_path` and use a fully custom widget UI, such as Python Variables

The plugin layer will remain responsible for the existing session and MDI contracts, but repeated plugin code for normal tool windows will be centralized. Plugins will own `session_key`, pass it into the widget, and rely on shared plugin behavior for eager creation policy, widget creation, UI contribution generation, menu wiring, and delegation of widget-owned `session.toml` state.

## User Stories

1. As a Hyde developer, I want a standard base class for persistent tool-window widgets, so that new windows start from one consistent structure.
2. As a Hyde developer, I want `super().__init__(...)` in tool-window widgets to perform meaningful shared setup, so that subclasses do not reimplement the same outer initialization.
3. As a Hyde developer, I want a shared default UI file for simple tool windows, so that I can avoid writing trivial layout code in Python.
4. As a Hyde developer, I want tool-window subclasses to be able to override the default UI path, so that richer windows can still provide their own UI files.
5. As a Hyde developer, I want tool windows to support both mounted-child and fully custom UI patterns, so that Python Terminal and Python Variables can both fit the same architectural model.
6. As a Hyde developer, I want widget-owned `session.toml` save and restore hooks, so that plugin hooks can delegate UI state persistence instead of manually reading controls.
7. As a Hyde developer, I want persistent tool windows to share one default close-versus-hide behavior, so that they behave consistently when the user closes them.
8. As a Hyde developer, I want a standard `shutdown()` hook for tool-window widgets, so that cleanup behavior is predictable across destroy and application-shutdown paths.
9. As a Hyde developer, I want plugin boilerplate for tool-window creation and registration to be centralized, so that ordinary plugins do not re-declare the same factory and MDI contribution code.
10. As a Hyde developer, I want eager creation to be declared centrally at the plugin layer, so that plugins can opt into eager widget creation without custom `setup()` conditionals.
11. As a Hyde developer, I want one plugin-owned `session_key` to drive MDI identity and widget-state persistence, so that identity strings do not drift apart.
12. As a Hyde developer, I want plugin restore to apply generic tool-window state before widget-specific UI state, so that widget restore runs in a consistent MDI context.
13. As a Hyde developer, I want Python Terminal to be representable as a `HydeToolWidget` container around a child console widget, so that it participates in the same tool-window pattern as other persistent windows.
14. As a Hyde developer, I want Python Variables to migrate away from Python-built control construction toward a UI-file-driven structure, so that the window becomes easier to read and maintain.
15. As a Hyde developer, I want the future fitting window to reuse the same persistent tool-window pattern from the start, so that it does not introduce another bespoke architecture.
16. As a Hyde maintainer, I want the plugin event system and session capture model to remain intact during this work, so that tool-window cleanup does not reopen larger plugin-system redesign questions.
17. As a Hyde maintainer, I want lifecycle widget methods to be clearly treated as temporary plugin-to-widget shims, so that future plugin-system cleanup remains possible.
18. As a Hyde developer, I want simple persistent tool-window plugins such as Logging and Procedures to move away from ad hoc Python layout code when appropriate, so that UI structure is easier to inspect in designer files.
19. As a Hyde developer, I want repeated menu wiring for ordinary tool windows to be absorbed into shared plugin behavior, so that plugins only state their identity and presentation metadata.
20. As a Hyde maintainer, I want the redesign to avoid pulling in saveable-window behavior from tables and figures, so that `HydeToolWidget` remains narrowly about persistent tool windows.

## Implementation Decisions

- `HydeToolWidget` will be the standard base class for persistent tool-window widgets.
- `HydeToolWidget` will load `self.ui` during base initialization using `ui_path`.
- `HydeToolWidget` will define one shared default UI file name, `hyde_tool_widget.ui`.
- Subclasses may override `ui_path` when they need a custom UI file.
- No structural restrictions will be imposed on subclass UI files beyond what `HydeToolWidget` itself needs.
- `HydeToolWidget` will support both default-UI-plus-mounted-child usage and fully custom UI usage.
- `HydeToolWidget` will own shared widget concerns only: services storage and lookup, runtime `session_key`, widget-level `session.toml` persistence hooks, lifecycle shim methods, default close/hide behavior for persistent tool windows, `shutdown()`, and the child-mounting helper for the default UI.
- The plugin will own `session_key` and pass it into the widget at runtime. The same key will be used for the MDI widget key and the widget-owned `session.toml` namespace.
- Plugin hooks will continue to be the entrypoint for session capture and restore. Widget hooks will sit under them as delegated behavior.
- Generic tool-window restore will happen before widget-specific `session.toml` restore.
- Plugin-side repeated code for ordinary tool windows will be centralized in the shared plugin base: eager creation policy, default widget factory, default MDI contribution generation, default window-menu contribution and show behavior, shared widget-session capture and restore delegation, and a small kwargs-building escape hatch for special constructor inputs.
- Eager versus lazy creation remains plugin policy, not widget policy. The policy will be declarative and handled centrally in the plugin base.
- Python Variables will remain one combined widget-plus-service module for now.
- No generic tool-window service abstraction is part of this work. PythonVariablesService is intentionally left alone because it is not UI code and may move closer to the kernel/runtime side later.
- Lifecycle methods on `HydeToolWidget` are acknowledged as temporary plugin-to-widget shims and not the final desired plugin-system design.
- Tables and figures are explicitly not part of the `HydeToolWidget` abstraction, other than possible later reuse of tiny generic MDI-child helpers.
- Saveable-window reopen logic, macro generation, save-on-close prompts, kernel close handshakes, and `session.py` reopening behavior remain outside this work.

## Testing Decisions

- Good tests should verify external behavior and architectural contracts, not incidental implementation details such as helper wiring or exact internal call order.
- Tests should focus on what a persistent tool window does from Hyde's point of view: UI loading through the base class, widget-owned session state save and restore, close-versus-hide behavior, eager creation policy at the plugin layer, and plugin-to-widget lifecycle delegation where behavior is externally meaningful.
- The shared widget base should be tested for the default behaviors it promises: UI loading, service access, session hook delegation surface, and shutdown/close semantics.
- The shared plugin behavior for ordinary tool windows should be tested for the standard contracts it promises: widget construction, MDI contribution generation, eager creation handling, session capture delegation, and restore ordering.
- Converted plugins should be tested through observable behavior, such as the persistence of Python Variables filter state and the ability of Python Terminal to work as a mounted-child tool window.
- Tests should avoid asserting implementation details that would prevent later cleanup of lifecycle shims or internal helper structure.

## Out of Scope

- Redesigning Hyde's plugin event architecture beyond the acknowledged temporary lifecycle shims.
- Introducing a generic tool-window service abstraction.
- Splitting Python Variables service behavior away from the widget as part of this change.
- Refactoring non-tool-window infrastructure plugins into the same abstraction.
- Bringing tables or figures into `HydeToolWidget`.
- Changing the `session.py` reopen path, macro generation, or saveable-window close contracts.
- Generalizing saveable-window behavior from tables and figures into the persistent tool-window abstraction.
- Larger kernel-runtime or plugin-manager redesign work.

## Further Notes

- Python Terminal is explicitly in scope for conversion to a `HydeToolWidget` container that hosts a child `RichJupyterWidget`.
- Python Variables is expected to move toward a stronger UI-file-driven structure and away from Python-built control construction where practical.
- The planned fitting window is a primary motivation for establishing this pattern now.
- The design intentionally standardizes widget and plugin boilerplate while preserving Hyde's existing plugin-owned session and MDI contracts.
