# Action Plan

This document is a living checklist tracking the specific steps we will follow (or have followed) to build Hyde, organized by our strategy phases.

## Phase I: Articulate Design Philosophy
- [x] Clear existing prototype code.
- [x] Establish the `project_management/` documentation hierarchy.
- [x] Draft the `STRATEGY.md`.
- [x] Draft this `PLAN.md`.
- [x] Refine `HYDE.md` to cleanly articulate vision and goals.
- [x] Refine `ARCHITECTURE.md` to define design philosophy.
- [ ] Test the documentation by spawining a sub-agent and verifying that it correctly and completly understood the design philosophy.

## Phase II: Minimum Feature Set Prototype
- [x] Spec: Draft `specs/IPC_PROTOCOL.md` defining how the PyQt window interacts with the Jupyter kernel.
- [x] Impl: Scaffold the core PyQt MainWindow shell (the resulting code should run without error, yielding a near-featurless MDI container.)
- [ ] Impl: Implement the `ExecutionController` that spins up `spyder_kernels` in a subprocess.
- [ ] Impl: Create a simple text input widget that sends Python strings to the subprocess and prints the result.
- [ ] Review: Does the separation of concerns feel robust? Adjust `ARCHITECTURE.md` if necessary.

## Phase III: Core System Tests
- [ ] Add tests executing kernel startup/shutdown.
- [ ] Add tests verifying strings are executed in the separated namespace.

## Phase IV: Iterative Feature Deployment
### Feature A: Matplotlib Figure Capture
- [ ] Spec: Draft `specs/GUI_FIGURES.md`.
- [ ] Impl: Allow `plt.plot()` in the execution process to pop open a PyQt MDI sub-window in the GUI process.
- [ ] Test: Figure rendering and closing behavior.

### Feature B: Data Browser
- [ ] Spec: Draft `specs/DATA_TRACKING.md`.
- [ ] Impl: Capture namespace variables (int, float, array) using `spyder` comms.
- [ ] Impl: Show tracked variables in a QTreeView in the GUI.
- [ ] Test: Namespace syncing when changing variables in the python kernel.

*(Further features like Curve Fitting, Tables, Save/Load `.hy` packages will be added here as we iterate)*

## Phase V: Announcement and Release
- [ ] TBD.
