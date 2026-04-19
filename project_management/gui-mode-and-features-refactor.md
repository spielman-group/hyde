# Branch Refactor: GUI Mode and Features Architecture

This document summarizes the changes made in the `feature/gui-mode-and-features-refactor` branch, focusing on enforcing the "Central Dogma" and improving project persistence.

## 1. Summary of Changes

### 1.1 Architectural Enforcements
- **`HYDE_GUI` Flag:** Introduced a global `HYDE_GUI` flag in `hyde/__init__.py`. This flag is explicitly set to `True` only when running within the managed GUI environment.
- **IPC Safety:** Public API helpers (like `hyde.table()`) now check `HYDE_GUI` before attempting to send IPC signals, preventing crashes or unexpected behavior in headless/terminal-only sessions.
- **Kernel-Driven Persistence:** Refactored `save_project` and `load_project` to be kernel-driven. The GUI now purely dispatches execution strings to the kernel, which then signals the GUI back via IPC once state restoration is complete.

### 1.2 Namespace and Module Cleanup
- **Module Renaming:** Removed leading underscores from internal modules. `_project_state.py` was consolidated into `hyde/__init__.py`, and `_table_macros.py` was renamed to `table_macros.py`.
- **Import Standardization:** Standardized on explicit, un-aliased internal imports (e.g., `import hyde.table_macros` instead of `import ... as macros`). This improves code traceability and aligns with the new `STYLE.md` guideline.

### 1.3 Asynchronous Startup Refactor
- **Decoupled Boot:** The GUI startup no longer blocks for project selection before the kernel/watchdog processes are spawned.
- **Zero-State Initialization:** Hyde now boots to a "zero-state" UI with a live kernel, and *then* prompts the user to open or create a project. This allows for a more responsive startup experience and ensures the execution environment is ready before any project logic is loaded.

### 1.4 Feature Logic Consolidation
- **`hyde_features.py`:** Moved all logic for generating Python bootstrap and command strings into `hyde/features/hyde_features.py`. This ensures that the execution controller and GUI code stay lean and focused on orchestration.

## 2. Style Documentation
- Created `project_management/STYLE.md` to house project-specific coding standards, including the prohibition of internal module aliasing and the enforcement of the UI/Kernel boundary.
- Updated `AGENTS.md` to reference the centralized style guide.

## 3. Current State and Hand-off
The core structural refactoring for Phase III is complete. All persistence operations now flow through the kernel asynchronously.

**Where work stopped:**
The current work focused on the underlying architecture and persistence protocols. Higher-level GUI features (like refined Procedure Browser interactions or advanced visualization plugins) are deferred to subsequent Phase IV/V tasks, now that they have a robust kernel-driven foundation to build upon.

**Reason for stopping:**
The objectives of the refactor branch—namely fixing architectural design philosophy violations, centralizing feature command strings, and improving project save/load workflows—have been met and verified.
