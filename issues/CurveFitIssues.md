# Plugin Boundary Follow-Up Issues

## Checklist

- [X] Issue 1: Make `save_window_dialog` a self-contained service
- [X] Issue 2: Replace `logging_window` widget reach-through with a logging sink service
- [X] Issue 3: Add a figure-facing plugin boundary and move `figure_control_dialogs` onto it
- [X] Issue 4: Move Curve Fit onto the figure-facing plugin boundary

## Issue 1: Make `save_window_dialog` a self-contained service

- **Title**: Make save-window prompting work through one complete service boundary
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: None directly - architectural boundary cleanup

### What to build

Make `save_window_dialog` usable entirely through its registered service surface.
Callers should not need to supply shell/project plumbing like `parent`,
`procedures_init`, or `reload_procedures` just to ask the plugin to handle the
"save / no save / cancel" flow for a saveable window.

This slice should leave the current close-time user experience intact while moving
the missing runtime authority behind the plugin's own declared boundary.

### Acceptance criteria

- [ ] `save_window_dialog` exposes one self-contained service call for prompting about window macro save-on-close.
- [ ] Generic saveable-window close paths use only that declared service boundary.
- [ ] Shell/project details needed by the prompt flow are obtained inside the service through registered services rather than supplied ad hoc by callers.
- [ ] Existing save / no save / cancel behavior still works for saveable windows.
- [ ] Behavior tests prove the close-time contract through observable outcomes rather than helper wiring.

### TDD focus

- First failing behavior: a generic saveable window can ask the service to prompt on close without supplying shell/project callbacks.
- Follow-up behavior: save and no-save still close, cancel still leaves the window open.
- Final behavior in this slice: the service boundary is complete and callers no longer pass leaked runtime plumbing.

## Issue 2: Replace `logging_window` widget reach-through with a logging sink service

- **Title**: Stop exporting `logging_window` internals through the runtime output service
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: None directly - architectural boundary cleanup

### What to build

Replace the current `logging_window` service contract that exposes the internal
`OutputBox` child widget to outside consumers. The runtime output surface should be
a narrow sink-style service boundary rather than a widget-internals escape hatch.

This slice should preserve the current visible logging behavior while removing the
direct shell-to-child-widget reach-through.

### Acceptance criteria

- [ ] The logging plugin exports a narrow runtime output service boundary rather than its internal `OutputBox` child widget.
- [ ] The shell writes Hyde log output through that service boundary.
- [ ] The logging window still shows the same runtime output to the user.
- [ ] No caller outside the logging plugin needs the logging widget's internal child object.
- [ ] Behavior tests prove output still appears in the logging window through the new service contract.

### TDD focus

- First failing behavior: runtime log output still appears in the logging window when routed through the new service boundary.
- Follow-up behavior: callers no longer receive the internal `OutputBox` widget object.
- Final behavior in this slice: the shell talks only to a logging sink service, not widget internals.

## Issue 3: Add a figure-facing plugin boundary and move `figure_control_dialogs` onto it

- **Title**: Replace `figure_control_dialogs` reach-through with a declared figure-facing boundary
- **Type**: AFK
- **Blocked by**: None - can start immediately
- **User stories covered**: None directly - architectural boundary cleanup

### What to build

Introduce the smallest clear figure-facing boundary that other plugins can use for
"active editable first-class figure" discovery plus the metadata needed by figure
control dialogs. Then move `figure_control_dialogs` onto that boundary so it no
longer imports `FigureWindow`, copies `figure_window.services`, or depends on the
figure plugin's widget-only API as its runtime integration surface.

This slice should keep the current dialog behavior intact while moving that behavior
behind a declared plugin boundary.

### Acceptance criteria

- [ ] There is one declared figure-facing boundary for active editable figure discovery and the metadata needed by figure-control dialogs.
- [ ] `figure_control_dialogs` no longer imports the concrete `FigureWindow` class as its integration boundary.
- [ ] `figure_control_dialogs` no longer bootstraps from `figure_window.services`.
- [ ] Trace and axis edit dialogs still open and behave the same from the user's perspective.
- [ ] Behavior tests prove the same user-visible dialog behavior through the new boundary.

### TDD focus

- First failing behavior: the figure-control plugin can still open the right dialog for the active editable figure through the new boundary.
- Follow-up behavior: trace and axis editing still apply the same semantic figure actions.
- Final behavior in this slice: figure-control dialogs no longer depend on figure widget internals as their runtime boundary.

## Issue 4: Move Curve Fit onto the figure-facing plugin boundary

- **Title**: Replace Curve Fit reach-through with the declared figure-facing boundary
- **Type**: AFK
- **Blocked by**: Issue 3
- **User stories covered**: None directly - architectural boundary cleanup

### What to build

Move Curve Fit off the `figure` plugin's concrete widget API and onto the same
declared figure-facing boundary introduced in Issue 3. Curve Fit should no longer
discover targets by concrete `FigureWindow` type, merge `figure_window.services`, or
read figure widget internals as its runtime integration seam.

This slice should preserve the existing Curve Fit user behavior while removing the
remaining runtime and code-boundary leak into the `figure` plugin.

### Acceptance criteria

- [ ] Curve Fit no longer imports the concrete `FigureWindow` class as its integration boundary.
- [ ] Curve Fit no longer merges `figure_window.services` into dialog services.
- [ ] Curve Fit uses the declared figure-facing boundary for active attached-figure context and figure metadata.
- [ ] Attached Curve Fit behavior remains unchanged from the user's perspective.
- [ ] Behavior tests prove the same attached and unattached dialog behavior through the new boundary.

### TDD focus

- First failing behavior: Curve Fit still opens attached when the active figure context is valid and unattached otherwise.
- Follow-up behavior: attached preview and semantic figure-action behavior still work through the new figure-facing boundary.
- Final behavior in this slice: Curve Fit no longer depends on figure widget internals as its plugin boundary.
