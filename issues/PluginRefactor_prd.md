## Problem Statement

Hyde's UI architecture is currently monolithic. The main application class (`HydeApp`) contains hardcoded imports, instantiation logic, and signal/slot wiring for every UI component (e.g., Data Browser, Procedure Browser, Command Window). This tight coupling makes it difficult to develop or modify UI elements in isolation, as changes often require editing the main application's initialization code and the central `.ui` file. Furthermore, it hinders the addition of new specialized viewports (like Figures or Fitting tools) by requiring boilerplate integration in the core application.

## Solution

Refactor the Hyde UI to use the plugin architecture provided by `labscript_utils.plugins`. This refactor will transition Hyde from a monolithic UI to a modular system where:
- Each UI component lives in its own subdirectory within `hyde.user_interface`.
- Components are discovered and loaded automatically by a plugin manager.
- Components contribute their own menu items and UI windows through standardized contexts.
- Inter-component communication and application lifecycle management are handled through an event bus and a shared services registry.
- Development of UI features is scoped entirely to their respective directories, requiring no changes to the main application code.

## User Stories

1. As a developer, I want to create a new UI window by adding a directory to `hyde.user_interface`, so that I don't have to modify the main application code.
2. As a developer, I want my UI component to add its own items to the "Window" or "View" menus, so that its functionality is discoverable without central configuration.
3. As a developer, I want to access kernel execution services from my UI component without importing `HydeApp`, so that my component remains decoupled and testable.
4. As a developer, I want my UI component to listen for "project loaded" events, so that it can restore its specific state from the project session.
5. As a developer, I want to provide a service (like a table manager) that other UI components can use, so that we can have clean cross-component dependencies.
6. As a scientist, I want the UI to load reliably without being affected by corrupted configuration files, so that my core analysis tools are always available.
7. As a scientist, I want my window layouts and table states to be saved and restored correctly per-project, so that my workspace remains consistent with my data.

## Implementation Decisions

- **Unconditional Plugin Discovery:** A custom `HydePluginManager` will be implemented to scan `hyde.user_interface` and activate all discovered plugins. It will bypass the standard `labconfig` enabling/disabling mechanism to ensure core scientific tools are never accidentally deactivated.
- **BasePlugin Amendment:** `labscript_utils.plugins.BasePlugin` will be updated to include a `get_services()` method. This allows plugins to explicitly declare the APIs they expose to other parts of the system.
- **Service Aggregation:** The plugin manager will aggregate all services into a master registry before the final setup phase, ensuring that dependency injection is safe and order-independent.
- **Execution Service Injection:** `HydeApp` will register core kernel execution methods (e.g., `execute_command`) into the shared services registry. Plugins will consume these services rather than calling methods on the application object directly.
- **Event-Driven Lifecycle:** Application state changes (Project Load, Project Close, Kernel Crash, Shutdown) will be broadcast as events. This replaces direct method calls from the application to specific widgets.
- **Context-Based UI Homing:** The application will provide an `MDIContext` for mounting persistent tool windows and a `MenuContext` for injecting actions into the main menubar.
- **Session State Delegation:** The responsibility for serializing and deserializing project-specific state (stored in `session.toml`) will shift to the individual plugins via `project_loaded` and `request_project_save` events.
- **Main UI Simplification:** The `main.ui` file will be stripped of specific tool-window actions, leaving only generic top-level menus to be populated by plugins.

## Testing Decisions

- **Service Registry Integrity:** Tests should verify that services registered by one plugin are correctly injected and accessible by another during the setup phase.
- **Event Propagation:** Verify that lifecycle events (like project loading) correctly trigger state restoration in plugins.
- **Discovery Robustness:** Verify that the custom plugin manager correctly identifies and loads all modules in the target package.
- **Isolated Component Testing:** Since components are now plugins, they can be tested by instantiating them with a mock services dictionary and firing events at them, without needing to launch the full Hyde application.

## Out of Scope

- **End-user Plugin Management:** A UI for users to enable/disable plugins is explicitly out of scope; discovery is automatic and activation is mandatory for everything in the `user_interface` package.
- **Third-party Plugin Support:** Loading plugins from arbitrary external paths is not a goal of this refactor.
- **Kernel-side Plugin Logic:** This refactor is strictly limited to the GUI process and its interaction with the execution layer.

## Further Notes

- This refactor is a critical step for Phase IV of the Hyde roadmap, moving towards a more robust and extensible scientific viewport architecture.
- The use of `labscript_utils.plugins` ensures alignment with suite-wide patterns while leveraging new features designed specifically for modern Hyde-style applications.
