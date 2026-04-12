# Hyde Agent Instructions

Welcome to the Hyde project workspace. Hyde is a modern, Pythonic data analysis and plotting environment for the labscript-suite, featuring a rigorous separation between the GUI and an active IPython execution kernel.

This file provides specific, Hyde-scoped rules for autonomous agents. **Before making any codebase changes, you must read this document.**

## 1. Project Context & Ecosystem
Hyde is part of the overarching labscript-suite. You should generally be familiar with `../AGENTS.md` for suite-wide patterns (such as standard library reuse). However, because Hyde is a greenfield v1 application, **several suite-wide rules do not apply here:**
- **Forget the "Patch" Skill:** Do not use the `labscript-narrow-patch` skill. We are building a new application architecture from scratch, not patching legacy suite code.
- **No Hardware/Queue Logic:** Hyde does not own the runmanager queue, process labscript sequence paths, or control instruments. Do not attempt to refactor the broader suite's HDF5 lifecycle. 

## 2. Core Architectural Mandates
You must thoroughly review the files in `project_management/` before writing any code. The overarching constraint is the "Central Dogma" defined in `project_management/ARCHITECTURE.md`. You must conform precisely to these three rules:
1. **The GUI is a Dumb Viewport:** Never hold array data or analytical state in the PyQt process. 
2. **The GUI is a String Factory:** If you build a UI interaction (like a button click, a slider move, or menu action), it must construct a human-readable Python string and dispatch it to the execution kernel. **Do not** write imperative backend calculation methods that are called directly from PyQt buttons. Every action must be 100% reproducible via terminal text.
3. **The Backend is Authoritative:** The actual state lives in an isolated `spyder_kernels` IPython subprocess. The GUI reacts to state changes via metadata notifications over `comm` channels. Do not reinvent Python namespace tracking; you must reference the [Spyder IDE](https://github.com/spyder-ide/spyder) implementations for variable tracking.

## 3. Strict Coding Rules
- **UI Framework Boundary:** Do not ever import `PyQt5`, `PyQt6`, `PySide2`, or `PySide6` natively. You must route all imports through the labscript-suite's `qtutils` compatibility layer (e.g., `from qtutils.qt.QtWidgets import QMainWindow`).
- **Threading:** If an IPython response out of the `quconsole` or a zero-MQ callback touches the UI, you MUST route it to the main GUI thread using `qtutils.inmain_decorator` or similar helpers. 
- **Communication:** Use `zprocess.ProcessTree` for general subprocess spawning and suite-level IPC (like listening for `lyse` equivalent messages), but rely entirely on standard Jupyter zero-MQ messaging (`spyder_kernels` / `qtconsole`) to interact with the Python execution kernel.

## 4. Work Strategy & Scope
We are aggressively iterating through a phased roadmap defined in `project_management/STRATEGY.md`.
- **Do Not Overbuild:** We are intentionally building minimal viable components to test architectural assumptions (Phase II). Do not build complex feature trees, generic plugin handlers, or edge-case handling prematurely.
- **Check the Plan:** Always look at `project_management/PLAN.md` to determine exactly what Phase the project is currently in. Restrict your work solely to the immediate uncompleted tasks.
- **Review Current Progress:** Refer to `project_management/STATUS.md` for a summary of the current architectural state and recent accomplishments.
