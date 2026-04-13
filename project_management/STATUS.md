# Hyde Phase II, III, & IV Feature A Status

We have successfully built the core architectural skeleton of Hyde, transitioning from design philosophy to a fully functional multi-process infrastructure.

## Key Accomplishments

### 1. The 3-Process Architecture
Successfully isolated the GUI from execution logic using a robust three-tier hierarchy:
- **Main GUI Process**: A PyQt MDI shell with a `RichJupyterWidget` view.
- **Execution Controller (Watchdog)**: Manages lifecycle, crash recovery, and `KERNEL_READY` heartbeats.
- **Jupyter Kernel (`spyder_kernels`)**: The authoritative source of truth, isolated for crash resiliency.

![Hyde Phase II Shell Prototype](snapshots/hyde_phase2_execution_prototype.png)

### 2. The 2-Lane IPC Strategy
Implemented clear separation of communication concerns:
- **Lane 1 (Control)**: `zprocess.ProcessTree` handles orchestration signals like `QUIT`, `KERNEL_READY`, and `KERNEL_CRASHED`.
- **Lane 2 (Data/Execution)**: Pure Jupyter ZMQ pipeline for real-time string execution and future state tracking via `comm` channels.

### 3. Automated System Tests (Phase III)
Developed a headless integration suite (`tests/test_watchdog.py`) that:
- Spawns the Watchdog.
- Validates absolute path connection file linking.
- Executes isolated code strings via a `BlockingKernelClient`.
- Proves bidirectional ZMQ communication works without a GUI event loop.

### 4. Managed Process Tree & Observability
Established a hierarchical managed lifecycle and real-time observability:
- **Managed Hierarchy**: Implemented a `GUI -> Watchdog -> Launcher -> Kernel` tree using `zprocess` heartbeats to eliminate orphan processes.
- **Unified Logging**: Integrated `zlog` across all nodes, targeting standard suite `~/labscript_suite/logs/`.
- **Logging Window**: Added a dedicated MDI `OutputBox` for real-time stdout/stderr redirection of background processes.

### 5. Phase IV-A: Procedure Browser & Explicit Initialization
Established the foundation for a transparent, reproducible scientific environment:
- **Project Creation / Loading Flow**: Startup now accepts an existing `.hy` project path from `argv`, or prompts the user to open an existing project or create a new one. New projects are copied from a repo-stored template package.
- **"Explicit is Better than Implicit"**: The execution layer imports `procedures` from `procedures/__init__.py` in the kernel after project configuration, ensuring all imports (numpy, matplotlib) and backends are script-defined.
- **MDI Procedure Browser**: Added a native script browser for managing `.py` files within the project, featuring double-click integration with the system-default editor.
- **Execution-Owned Procedure Reload**: The Watchdog owns procedure-file monitoring through `labscript_utils.filewatcher.FileWatcher` and re-executes the canonical `procedures/__init__.py` load path when watched `.py` files change.
- **Masked Background Execution**: Watchdog-driven `procedures/__init__.py` execution uses Jupyter `silent=True`, so backend-controlled execution does not emit visible `execute_input` or consume the user's prompt history.
- **Procedure Browser Path Semantics**: The browser is rooted at `procedures/`; displayed entries are relative to that directory, not to the `.hy` project root.


## Refinements & Bug Fixes
- **Path Derivation**: Implemented absolute module-based path derivation to prevent CWD-drift issues between the GUI and child processes.
- **Initialization Safeties**: Added a polling loop to the Watchdog to ensure the Jupyter connection file exists and is ready before the GUI attempts to connect.
- **UI UX**: Standardized the Logging window size (80x40 equivalent) and ensured it behaves correctly within the MDI container.

## Documentation Updated
- `project_management/PLAN.md`: Marked Phase II architectural refinements as complete.
- `project_management/ARCHITECTURE.md`: Codified the finalized IPC and package structure models.
- `project_management/specs/logging_window/SPEC.md`: Added formal specifications for the new observability window.
- `2025_04_12_OPUS_EVALUATION.md`: Noted the transition toward `zprocess.Event` for future state notifications.
