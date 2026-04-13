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

*(Further features like Curve Fitting, Tables, Save/Load `.hy` packages will be added here as we iterate)*

### Feature D: Table Editor
- [ ] Spec: Refine `specs/table/SPEC.md`.
- [ ] Impl: Create the table editor MDI window and data model integration.
- [ ] Test: Verify table editing, sorting, and persistence behavior.

## Phase V: Announcement and Release
- [ ] TBD.
