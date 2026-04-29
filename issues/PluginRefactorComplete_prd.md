## Problem Statement

The PluginRefactor unit of work was started, but it stopped at a partial wrapper stage rather than completing the ownership inversion described in the original PRD. Several Hyde UI features now expose plugin entry points, yet the old monolithic ownership model still remains in the application shell and in some feature implementations. As a result, Hyde is currently in an inconsistent middle state:

- some features look like plugins, but the application shell still imports and coordinates them directly;
- some plugins still depend on application internals or on sibling plugins;
- project/session persistence still reflects old host-owned assumptions in parts of the design;
- the documentation overstates completion and no longer matches the agreed architecture.

This leaves Hyde harder to extend, harder to reason about, and vulnerable to regressions because the old and new ownership models are both present at once. The remaining work is not a fresh redesign. It is the completion of the refactor already defined: remove the surviving old-ownership pathways, finish the inversion of control, and align the documentation with the agreed plugin architecture.

## Solution

Complete PluginRefactor by enforcing the agreed architecture everywhere it was only partially applied:

- the plugin framework used by Hyde must be the upstream `labscript_utils.plugins` model, with a few Hyde specific additions already noted in the initial PRD;
- the plugin namespace must contain plugins only, with host-shell code moved out of that namespace;
- the application shell must provide only generic infrastructure, contexts, and lifecycle coordination, while first-party UI features participate through the same plugin mechanism as other built-in features;
- plugins must consume explicit registered services and contexts rather than the raw application object;
- plugins must not import each other directly;
- project save/load must continue to follow Hyde's visible-command kernel flow, while GUI session persistence is centrally collected through `get_save_data()` and restored through plugin-owned logic;
- the remaining work must remove legacy host-owned code paths, not merely bypass them;
- the documentation set must be updated so it describes the actual target architecture and clearly records what remains unfinished.

The end state for this unit of work is a completed refactor, not a complete rewrite. Existing behavior should be preserved where it already matches the agreed design. The required change is architectural cleanup and completion of ownership boundaries.

## User Stories

1. As a Hyde developer, I want the plugin refactor to finish the ownership inversion rather than wrapping legacy code, so that the codebase has one architecture instead of two.
2. As a Hyde developer, I want the plugin namespace to contain only real plugins, so that package boundaries communicate architecture clearly.
3. As a Hyde developer, I want host-shell code to live outside the plugin namespace, so that application infrastructure and feature plugins are not conflated.
4. As a Hyde developer, I want first-party features to register through the same upstream plugin model as all other built-in features, so that no feature receives privileged integration paths.
5. As a Hyde developer, I want the application shell to depend only on generic contexts and registered services, so that adding or revising a feature does not require editing central feature wiring.
6. As a Hyde developer, I want plugins to work without receiving the raw application object, so that plugin code remains decoupled from shell internals.
7. As a Hyde developer, I want plugins to publish explicit services for feature-owned behavior, so that cross-feature dependencies are visible, reviewable, and testable.
8. As a Hyde developer, I want plugins to communicate with one another through services and lifecycle events by default, so that feature boundaries remain intact.
9. As a Hyde developer, I want direct imports from one plugin into another to be forbidden, so that the monolith cannot quietly reform under plugin wrappers.
10. As a Hyde developer, I want the application shell to stop importing concrete feature widgets, dialogs, and state helpers, so that feature ownership actually moves out of the shell.
11. As a Hyde developer, I want menu items, actions, and action enablement to remain owned by their feature plugins, so that the shell does not centrally manage feature-specific UI state.
12. As a Hyde developer, I want semantic state such as active-table ownership to remain with the feature that defines it, so that the shell only tracks generic UI/container state.
13. As a Hyde developer, I want the project save/load flow to preserve Hyde's existing visible-command kernel pathway, so that PluginRefactor does not accidentally rewrite the kernel/GUI contract.
14. As a Hyde developer, I want GUI session persistence to use one serialization channel centered on `get_save_data()`, so that plugin persistence has one clear mechanism.
15. As a Hyde developer, I want save collection to be centralized while each plugin remains responsible for deciding what state matters, so that persistence stays consistent without reintroducing host-owned feature schemas.
16. As a Hyde developer, I want plugin lifetime and contribution lifetime to remain separate, so that singleton plugins can manage zero, one, or many persistent or transient UI resources.
17. As a Hyde developer, I want Hyde to preserve acceptable temporary debt such as view/service coupling where explicitly deferred, so that this unit of work stays a refactor rather than expanding into unrelated rewrites.
18. As a scientist using Hyde, I want project save/load to continue behaving the same way from the user's perspective, so that architectural cleanup does not change the trusted workflow.
19. As a scientist using Hyde, I want window and workspace restoration to remain reliable, so that project sessions reopen correctly even after the architecture is cleaned up.
20. As a Hyde developer, I want legacy ownership code removed even when it is unused, so that future changes are not misled by stale pathways that no longer belong in the architecture.
21. As a Hyde developer, I want the remaining work documented as explicit acceptance criteria, so that PluginRefactor can be declared complete only when the old ownership model is gone.
22. As a Hyde developer, I want the existing documentation set corrected where it is stale, so that future work is guided by the agreed architecture rather than by outdated notes.
23. As a reviewer, I want to be able to tell whether a feature is truly refactored or merely wrapped, so that code review has a concrete standard.
24. As a tester, I want the refactor to expose stable seams such as contexts, services, events, and persistence hooks, so that features can be tested without booting the full application for every case.
25. As a future contributor, I want the architecture docs and feature specs to match the code and the agreed model, so that adding a new feature does not require reverse-engineering branch-era mistakes.

## Implementation Decisions

- **Authoritative plugin model:** Hyde will use the upstream `labscript_utils.plugins` contract as the plugin architecture for this unit of work. Hyde should not introduce a parallel plugin abstraction, naming scheme, or dependency mechanism when the upstream model already defines the surface.
- **Hard namespace boundary:** The plugin namespace remains the discovery root for built-in UI plugins, but it must be plugin-only. Host-shell code must be moved out so the package boundary matches the architectural boundary.
- **No partial-credit wrappers:** A feature is not considered refactored merely because it exposes a plugin class. If old host-owned pathways, direct shell ownership, or inter-plugin imports remain present, that feature is still incomplete.
- **Shell responsibilities:** The application shell remains responsible for bootstrap, context registration, plugin manager integration, lifecycle/event broadcasting, project-session orchestration, and other generic infrastructure. It must not retain feature-specific orchestration.
- **First-party features remain plugins:** Built-in windows and actions remain first-party plugins, but they are integrated through the same plugin mechanism and contexts as any other built-in feature.
- **No raw application injection:** The shell must not inject the raw application object into plugins. Feature code should receive only the generic contexts, infrastructure services, and application-defined data that are actually required by the upstream plugin contract.
- **Service ownership:** Feature-owned behavior must be exposed through explicit named services published by the owning plugin. The shell may expose only generic infrastructure services needed to operate the application.
- **No direct plugin-to-plugin imports:** Dependencies between features must be expressed through services or lifecycle events, not through direct imports of widgets, dialogs, or state helpers from sibling plugins.
- **Action ownership:** Plugins own their own actions, including creation, identity, and enable/disable state. The shell may host menu locations and render contributed actions, but it must not bind aliases by text or centrally manage feature-specific action state.
- **Container versus semantic ownership:** The shell owns generic UI containers and concrete context implementations, including MDI infrastructure. Feature-specific semantic state remains owned by the relevant plugin.
- **Preserve the established save/load flow:** PluginRefactor does not replace Hyde's existing visible-command save/load pipeline. User-facing save actions still generate visible Hyde commands for the kernel; the kernel remains authoritative for scientific object persistence; the GUI remains responsible for GUI session persistence after kernel success.
- **One GUI persistence channel:** GUI/session persistence should use a single serialization path centered on plugin `get_save_data()`. Save collection is centralized, while each plugin determines what to serialize and how to interpret restored state on the appropriate lifecycle event.
- **Plugin lifetime versus contribution lifetime:** A discovered plugin object may outlive the UI contributions it manages. Individual contributions may be singleton, absent, recreated, transient, or restorable according to feature semantics without changing plugin lifetime.
- **Acceptable deferred debt:** Headless separation of services from views remains future work and is not required to close PluginRefactor. The unit of work is complete when the ownership boundaries are correct, even if some currently mandatory built-in features still combine view and service responsibilities internally.
- **Legacy cleanup is mandatory:** Legacy shell-owned code paths from the pre-plugin architecture must be removed, not merely bypassed. Dead code that still expresses the old ownership model should be treated as unfinished refactor work.
- **Documentation is part of the deliverable:** PluginRefactor is not complete until the architecture and feature documentation reflect the final agreed ownership model and call out any consciously deferred follow-on work.
- **Suggested work breakdown:**
  - complete the shell/plugin package split;
  - remove shell imports and direct orchestration of feature plugins;
  - convert surviving feature-to-shell or feature-to-feature dependencies into service/event/context usage;
  - finish persistence cleanup around plugin-owned save data and restore responsibilities;
  - delete dead legacy pathways;
  - update documentation and acceptance criteria.

## Testing Decisions

- **Good tests validate agreed behavior and boundaries:** Tests should focus on externally meaningful behavior: discovery, registration, service availability, contribution routing, lifecycle handling, save/load roundtrips, and preservation of established user workflows. They should avoid binding to incidental implementation details unless the boundary itself is a product requirement.
- **Architecture guard tests are justified here:** For PluginRefactor, some architectural constraints are part of the feature contract. Lightweight guard tests are appropriate where the absence of forbidden shell imports, raw app injection, or inter-plugin imports is itself a requirement of the refactor.
- **Plugin manager integration tests:** Verify that built-in plugins are discovered and instantiated through the upstream plugin manager using the intended discovery package.
- **Service registry tests:** Verify that services exposed by one plugin are available to other plugins in an order-independent way before final setup.
- **Context routing tests:** Verify that menu and MDI contributions are registered through application-owned contexts rather than through shell hardcoding.
- **Lifecycle event tests:** Verify that project lifecycle events reach plugins and that plugins can restore their own relevant state without direct shell feature calls.
- **Persistence roundtrip tests:** Verify that GUI/session state is centrally collected from plugin `get_save_data()` output, written once, and returned to the appropriate plugin-owned restore path on project load.
- **Transient versus persistent contribution tests:** Verify that a long-lived plugin can manage both transient and restorable contributions without the shell owning contribution-specific semantics.
- **Regression tests for preserved workflows:** Verify that visible save/load command generation, kernel-authoritative scientific persistence, and GUI session persistence still behave the same from the user's perspective.
- **Documentation regression checks:** Add a review checklist or automated validation where practical so that the architecture docs, status notes, and feature specs are updated together when ownership rules change.
- **Prior art:** Reuse Hyde's existing integration-test style for end-to-end GUI/kernel behavior where appropriate, and use the upstream `labscript_utils.plugins` examples as the behavioral model for contexts, services, event handlers, and plugin setup ordering.

## Out of Scope

- Replacing Hyde's kernel-side save/load contract or changing the visible-command user workflow.
- Full headless separation of runtime services from windows.
- Third-party plugin loading from arbitrary external paths.
- End-user enable/disable management for built-in UI plugins.
- Redesigning mature feature behavior that already matches the agreed architecture.
- Broad UI redesigns unrelated to PluginRefactor acceptance criteria.
- Rewriting Hyde around a new plugin framework instead of the upstream `labscript_utils.plugins` contract.

## Further Notes

### Documentation currently out of date

The documentation set needs explicit cleanup as part of this unit of work.

- **Architecture document:** The current architecture write-up still describes the plugin discovery namespace as also containing the main application package. That is stale relative to the agreed hard package boundary. The architecture doc should be revised so the discovery namespace is plugin-only and the shell lives outside it.
- **Project Save/Load spec:** The current save/load spec still documents a host-shaped session schema with feature-specific top-level state such as tool-window state, active-table bookkeeping, and other feature details. That is stale relative to the agreed persistence model, where GUI state is centrally collected from plugin `get_save_data()` and feature semantics remain plugin-owned.
- **Status document:** The current status write-up overstates completion for this unit of work. It reports no major runtime/lifecycle bugs in the area and lists the documentation set as updated, but PluginRefactor is still incomplete because the old ownership model remains present in code.
- **Feature specs that describe cross-feature ownership in direct terms:** Any feature spec that currently describes one feature as directly launching or owning another feature's internal dialog/state needs wording cleanup so the behavior is expressed in terms of services, contexts, lifecycle events, and kernel-visible commands rather than direct feature-to-feature control.
- **Plan and completion tracking:** Any planning/status notes that imply PluginRefactor is effectively done should be revised so completion is tied to the removal of old-ownership pathways, not merely to the existence of plugin wrappers.

### Acceptance criteria for closing PluginRefactor

PluginRefactor should be considered complete only when all of the following are true:

- the plugin discovery namespace is plugin-only;
- the shell no longer imports or directly orchestrates concrete feature plugins;
- plugins do not receive the raw application object;
- plugins do not import one another directly;
- feature-owned behavior is exposed through plugin services rather than shell-owned feature callables;
- GUI persistence is collected centrally through plugin save data rather than host-owned feature schemas;
- legacy old-ownership code has been removed, including unused leftovers;
- the documentation set reflects the final agreed architecture and clearly labels deferred follow-on work.

### Practical review standard

When reviewing remaining changes for this unit of work, the decisive question should be: **does this code still express the old ownership model anywhere?** If the answer is yes, the refactor is still incomplete in that area.