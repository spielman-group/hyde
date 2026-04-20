# Hyde Phase II, III, & IV Status

We have successfully built the core architectural skeleton of Hyde, transitioning from design philosophy to a fully functional GUI-plus-kernel infrastructure.

## Key Accomplishments

### 1. The 2-Process Architecture
Successfully isolated the GUI from execution logic using a direct managed hierarchy:
- **Main GUI Process**: A PyQt MDI shell with a `RichJupyterWidget` view, a GUI-owned `FileWatcher`, a lyse-compatible `ZMQServer`, and a lightweight runtime-helper thread for silent kernel work.
- **Jupyter Kernel (`spyder_kernels`)**: The authoritative source of truth, isolated for crash resiliency.

![Hyde Phase II Shell Prototype](snapshots/hyde_phase2_execution_prototype.png)

### 2. The 2-Lane IPC Strategy
Implemented clear separation of communication concerns:
- **Lane 1 (Control)**: `zprocess.ProcessTree` handles orchestration signals such as project-state notifications, table-open requests, and structured table-data responses.
- **Lane 2 (Data/Execution)**: Jupyter ZMQ handles visible execution, silent runtime-helper-owned execution, and Spyder namespace metadata. Hyde-owned structured relays such as table-open intents and table-data payloads travel through `ProcessTree` only where that narrow relay is a better fit than a new comm protocol.

### 3. Automated System Tests (Phase III)
Developed a headless integration suite (`tests/test_watchdog.py`) that:
- Launches the direct managed kernel child.
- Validates absolute path connection file linking.
- Executes isolated code strings via a `BlockingKernelClient`.
- Proves bidirectional ZMQ communication works without a GUI event loop.

### 4. Managed Process Tree & Observability
Established a managed lifecycle and real-time observability:
- **Managed Hierarchy**: Implemented a `GUI -> Kernel` tree using `zprocess` heartbeats to eliminate orphan processes. The `kernel_launcher.py` entrypoint starts Spyder's kernel in-process so the real kernel is the managed `ProcessTree` child rather than a separate `Popen` descendant.
- **Unified Logging**: Integrated `zlog` across all nodes, targeting standard suite `~/labscript_suite/logs/`.
- **Logging Window**: Added a dedicated MDI `OutputBox` for real-time stdout/stderr redirection of background processes.

### 5. Phase IV-A: Procedure Browser & Explicit Initialization
Established the foundation for a transparent, reproducible scientific environment:
- **Project Creation / Loading Flow**: Startup now accepts an existing `.hy` project path from `argv`, or prompts the user to open an existing project or create a new one. New projects are copied from a repo-stored template package.
- **"Explicit is Better than Implicit"**: The execution layer imports `procedures` from `procedures/__init__.py` in the kernel after project configuration, ensuring all imports (numpy, matplotlib) and backends are script-defined.
- **MDI Procedure Browser**: Added a native script browser for managing `.py` files within the project, featuring double-click integration with the system-default editor.
- **GUI-Owned Procedure Reload**: The GUI owns procedure-file monitoring through `labscript_utils.filewatcher.FileWatcher` and re-executes the canonical `procedures/__init__.py` load path through the runtime helper when watched `.py` files change.
- **Masked Background Execution**: Runtime-helper-driven `procedures/__init__.py` execution uses Jupyter `silent=True`, so backend-controlled execution does not emit visible `execute_input` or consume the user's prompt history.
- **Lyse-Compatible Remote Listener**: The GUI now owns a `ZMQServer` bound to the existing `ports.lyse` labconfig entry. Its handler normalizes incoming agnostic-path payloads and queues visible `remote(...)` execution through the runtime helper.
- **Procedure Browser Path Semantics**: The browser is rooted at `procedures/`; displayed entries are relative to that directory, not to the `.hy` project root.

### 6. Phase IV-C: Data Browser Initial Implementation
Established the first Hyde-native namespace browser:
- **Spyder-Based Namespace View**: The Data Browser uses Spyder's namespace-view comm path rather than a Hyde-specific metadata tracker.
- **MDI Data Browser**: Added a dedicated MDI Data Browser window with a left-hand display control column and a main namespace list.
- **Filtering Semantics**: Implemented `Waves`, `Variables`, and `Strings` filters, with `Waves` covering numpy arrays and pandas DataFrames.
- **Info Pane Toggle**: The `Info` checkbox controls the visibility of the metadata pane.
- **Namespace Synchronization**: The browser requests an initial namespace snapshot after its own comm path is ready and refreshes after kernel execution and runtime-helper-owned procedure reload.
- **Supported Actions**: Implemented `Copy Python Expression` and `Delete Object` against the live kernel namespace.
- **Persistent Tool Windows**: MDI tool windows, including the Data Browser, now hide on close rather than destroying their subwindow wrappers.

### 7. Phase IV-D: Table Initial Implementation
Established Hyde's first editable kernel-backed table workflow:
- **Public Table API**: `hyde.table(...)` now serves as a documented public Hyde helper for opening a table from live kernel objects.
- **MDI Table Window**: Added a table subwindow with a point column, one column per selected object, and a current-cell value strip.
- **New Table Dialog**: Added a `Windows -> New Table...` entry and a dialog that generates visible `hyde.table(...)` commands.
- **Data Browser Integration**: The Data Browser's `Edit` and `Append to Table` actions now route table creation/appending through the same visible command path.
- **Kernel Relay Path**: Table-open requests and structured table-data payloads travel through the direct `ProcessTree` relay between the kernel and GUI.
- **Muted Cell Edits**: Table cell edits execute through the same command machinery as other Hyde commands, but are hidden from the visible command history to avoid console clutter.
- **Current Scope**: The implemented table path is limited to 1D numeric arrays; DataFrame tables, sorting, and persistence remain future work.
- **Recreation Macros**: Table close now offers to save a parameterized `@hyde.table` recreation macro into `procedures/__init__.py`, and `Windows -> Table Macros` is populated from the decorated registry after procedures reload.

### 8. Phase IV-E: Project Save/Load Initial Implementation
Established the first end-to-end `.hy` package persistence flow:
- **Explicit Hyde Commands**: Project persistence now uses public `hyde.save_project(...)` and `hyde.load_project(...)` helpers executed through visible command strings.
- **Kernel-State Persistence**: Saved kernel objects are written under `data/`, with `numpy.ndarray` using `.npy` and other saveable objects using pickle fallback.
- **Exclusion-Based Save Rules**: Saveable objects are selected by exclusion, including modules, packages, routines, classes/types, and interactive artifacts such as `In` / `Out`.
- **Manifest Tracking**: `manifest.toml` now records the saved-object registry, serializer, relative data path, and Python type name.
- **GUI Session Persistence**: `session.toml` stores main-window state, tool-window visibility/geometry, Data Browser filter state, and open table descriptors.
- **Visible History Persistence**: `terminal/history.py` stores visible command history only; muted GUI micro-mutations are excluded.
- **File Menu Wiring**: `File -> Save` saves in place, `File -> Save As...` confirms before overwriting an existing non-empty project, writes a new `.hy` package, and switches Hyde to it, and project load restores kernel state after `procedures/__init__.py` runs.
- **Session Restore Policy**: GUI session restore reports malformed or missing `session.toml` files and continues with kernel-state restore already complete.
- **Save Semantics**: In-place project saves rewrite the current saved state rather than preserving an older synchronized copy.
- **Project Switch Isolation**: Switching to a different `.hy` project resets the kernel namespace back to Hyde's clean baseline before the new project's procedures and saved state are loaded, so stale objects do not leak across projects.


## Refinements & Bug Fixes
- **Path Derivation**: Implemented absolute module-based path derivation to prevent CWD-drift issues between the GUI and child processes.
- **Initialization Safeties**: Added a polling loop to ensure the Jupyter connection file exists and is ready before the GUI attempts to connect.
- **UI UX**: Standardized the Logging window size (80x40 equivalent) and ensured it behaves correctly within the MDI container.

## Active Major Bugs
- **`exit()` in Command Window**: Typing `exit()` in the embedded IPython command window kills the kernel and produces repeated `Kernel died, restarting` output along with repeated crash alerts. This is a major UX bug. Hyde needs a defined policy for terminal-driven kernel exit so that it is either intercepted, converted into an orderly application quit, or handled as a single controlled kernel restart event rather than a visible crash loop.

## Documentation Updated
- `project_management/PLAN.md`: Marked Phase II architectural refinements as complete.
- `project_management/ARCHITECTURE.md`: Codified the finalized IPC and package structure models.
- `project_management/specs/logging_window/SPEC.md`: Added formal specifications for the new observability window.
- `project_management/specs/data_browser/SPEC.md`: Updated to match the implemented Hyde-native browser layout and supported action set.
- `project_management/specs/IPC_PROTOCOL.md`: Updated to document the actual `spyder_api` namespace-view comm path.
- `project_management/specs/table/SPEC.md` and `project_management/specs/new_table_dialog/SPEC.md`: Updated to match the implemented table workflow.
- `project_management/specs/project_save_load/SPEC.md`: Added the initial `.hy` package save/load contract and the overwrite-confirmation rule for `Save As...`.
- `2025_04_12_OPUS_EVALUATION.md`: Noted the transition toward `zprocess.Event` for future state notifications.
