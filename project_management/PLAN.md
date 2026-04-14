# Action Plan

This document is a living checklist tracking the specific steps we will follow (or have followed) to build Hyde, organized by our strategy phases.

## Phase I: Articulate Design Philosophy
- [x] Clear existing prototype code.
- [x] Establish the `project_management/` documentation hierarchy.
- [x] Draft the `STRATEGY.md`.
- [x] Draft this `PLAN.md`.
- [x] Refine `HYDE.md` to cleanly articulate vision and goals.
- [x] Refine `ARCHITECTURE.md` to define design philosophy.
- [x] Test the documentation by spawining a sub-agent and verifying that it correctly and completly understood the design philosophy.

## Phase II: Minimum Feature Set Prototype
- [x] Spec: Draft `specs/IPC_PROTOCOL.md` defining how the PyQt window interacts with the Jupyter kernel.
- [x] Impl: Scaffold the core PyQt MainWindow shell (the resulting code should run without error, yielding a near-featurless MDI container.)
- [x] Impl: Implement the `ExecutionController` that spins up `spyder_kernels` in a subprocess.
- [x] Impl: Create and wire in the command_window widget.
- [x] Impl: Integrate unified `zlog` and managed `ProcessTree` hierarchy.
- [x] Impl: Create the MDI Logging window for process observability.

## Phase III: Core System Tests
- [x] Add tests executing kernel startup/shutdown.
- [x] Add tests verifying strings are executed in the separated namespace.

## Phase IV: Iterative Feature Deployment
### Feature A: Procedure Browser & Kernel Initialization
- [x] Spec: Draft `specs/procedure_browser/SPEC.md`.
- [x] Impl: Implement `procedures/__init__.py` bootstrapping and automated kernel execution.
- [x] Impl: Create the MDI Procedure Browser.
- [x] Test: Verify environment synchronization between script and kernel.
- [x] Refinement: Move procedure-file change tracking and `procedures/__init__.py` re-sync ownership into the execution side using `labscript_utils.filewatcher.FileWatcher` (BLACS connection-table pattern).
- [x] Refinement: Mask executor-owned `procedures/__init__.py` execution input at the kernel protocol level with `silent=True`.
- [ ] Refinement: Define the command-window display policy for output originating from executor-owned silent execution.

### Feature B: Matplotlib Figure Capture
- [ ] Spec: Draft `specs/figure_window/SPEC.md`.
- [ ] Impl: Allow `plt.plot()` in the execution process to pop open a PyQt MDI sub-window in the GUI process via the Metadata Mirror model.
- [ ] Test: Figure rendering and closing behavior.

### Feature C: Data Browser
- [x] Spec: Draft and refine `specs/data_browser/SPEC.md`.
- [x] Impl: Capture namespace variables using Spyder comms.
- [x] Impl: Show tracked variables in a GUI browser with Waves / Variables / Strings filters and an Info pane.
- [x] Test: Verify namespace syncing on startup, after kernel execution, and after `procedures/__init__.py` reload.

### Feature E: Project Save/Load
- [x] Spec: Draft `specs/project_save_load/SPEC.md`.
- [x] Impl: Add public `hyde.save_state(...)` / `hyde.load_state(...)` helpers for explicit kernel-state persistence.
- [x] Impl: Save kernel objects into `manifest.toml` and `data/*` using exclusion-based persistence.
- [x] Refinement: Exclude packages, interactive namespace artifacts, and runtime helper objects from kernel-state persistence.
- [x] Impl: Save GUI session state into `session.toml` and visible command history into `terminal/history.py`.
- [x] Impl: Wire `File -> Save`, `File -> Save As...`, and project load into the explicit save/load flow.
- [x] Refinement: `File -> Save As...` prompts before overwriting an existing non-empty project.
- [x] Refinement: GUI session restore warns on malformed/missing `session.toml` and does not block kernel-state restore.
- [x] Refinement: In-place `File -> Save` overwrites the current saved state instead of preserving an older synchronized copy.
- [x] Refinement: Switching projects resets the kernel namespace before the new project's procedures/state are loaded.
- [x] Test: Add focused save/load integration coverage.

### Feature D: Table Editor
- [x] Spec: Refine `specs/table/SPEC.md` and define the Data Browser table-launch contract.
- [x] Impl: Create the table editor MDI window, New Table dialog, and Data Browser table-launch/appending integration.
- [x] Test: Verify kernel-to-GUI table-open relay and watchdog handling for `hyde.table(...)`.
- [ ] Test: Expand coverage for GUI row rendering, muted cell-edit execution, and broader table interaction behavior.
- [ ] Refinement: Replace the current executor-triggered table-data fetch hop with a cleaner direct kernel-to-watchdog data path now that the real kernel is a managed `ProcessTree` child.

## Phase V: Announcement and Release
- [ ] TBD.
