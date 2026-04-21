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

## 3. Coding Style and Rules
Before writing code, you must review [STYLE.md](file:///Users/ispielma/Python/Labscript/hyde/project_management/STYLE.md) for project-specific conventions regarding imports, UI framework boundaries, and threading.
When adding or changing command-emitting GUI surfaces or GUI-side state/code generation, you must also review `state-control.md` and follow its ownership and placement rules.

## 4. Work Strategy & Scope
We are aggressively iterating through a phased roadmap defined in `project_management/STRATEGY.md`.
- **Use Feature Branches for Feature Work:** Hyde now has working scaffolding. When adding or changing a specific feature, create a dedicated git feature branch first and do the work on that branch rather than directly on the baseline branch.
- **One Branch Per Feature:** Keep each feature branch scoped to one feature or one tightly related unit of work so review and rollback remain straightforward.
- **Do Not Overbuild:** We are intentionally building minimal viable components to test architectural assumptions (Phase II). Do not build complex feature trees, generic plugin handlers, or edge-case handling prematurely.
- **Use the Frontend Spec Skill:** When creating or revising a frontend feature specification under `project_management/specs/`, use the project-local `$add-hyde-ui-feature` skill from `.codex/skills/add-hyde-ui-feature`.
- **Prefer the Simplest Working Change:** When solving a problem, first look for the smallest clear modification to the existing code path that satisfies the request. Extend an existing function, thread, queue, or process before introducing a new helper, protocol, abstraction, watcher, or subsystem.
- **No Speculative Architecture:** Do not broaden a task into a larger redesign unless the user explicitly asks for that redesign, or the existing architecture makes the narrow solution impossible. If you believe a broader change is necessary, you must first explain why the simpler option fails in this codebase.
- **Smallest-Path First:** If a solution can be implemented in roughly 10-20 lines inside an existing module, do that instead of creating a more general framework. Hyde is early-stage; simple and local is preferred over clever and extensible.
- **Minimize Moving Parts:** Do not add extra threads, processes, IPC messages, background services, or state machines if an existing one can carry the behavior with a small extension.
- **No Compatibility Shims Unless Asked:** Hyde is early-stage. Do not add migration paths, fallback formats, or compatibility layers unless the user explicitly requests them.
- **Check the Plan:** Always look at `project_management/PLAN.md` to determine exactly what Phase the project is currently in. Restrict your work solely to the immediate uncompleted tasks.
- **Review Current Progress:** Refer to `project_management/STATUS.md` for a summary of the current architectural state and recent accomplishments.

## 5. Documentation Boundary
- **Specs Describe the Intended System:** Files such as `project_management/ARCHITECTURE.md`, `project_management/HYDE.md`, and `project_management/specs/**/*.md` must describe Hyde in present-tense architectural or specification terms. Do not insert narrative about previous implementations, discarded approaches, migrations, or what the code "used to" do.
- **No Migration Code by Default:** Hyde is still early-stage. Do not add migration paths, compatibility shims, or fallback behavior for superseded designs unless the user explicitly requests them.
- **History Belongs in History Files:** Material about past implementations, design reversals, resolved problems, evaluations, and why one approach replaced another belongs in history/progress documents such as `project_management/STATUS.md`, `project_management/PLAN.md`, and dated evaluation notes like `2025_04_12_OPUS_EVALUATION.md`.
- **When Adding Historical Context, Put It in the Right Place:** If a change requires recording that an older approach existed, add that note to a history/progress file, not to a spec, architecture, or feature-design document.
- **When Reading Docs, Expect This Split:** Agents should expect present-state requirements in specs and architecture docs, and should expect past-state/project-history material only in the designated history/progress documents.
