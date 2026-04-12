# Critical Evaluation: Hyde Project

Notable architectural decisions have been made to resolve several Phase II tactical risks. This document tracks remaining strategic risks and provides a record of resolved items.

> [!NOTE]
> **Strategic Direction (Phase III/IV)**: While current internal notifications (e.g., `KERNEL_READY`) utilize 1-to-1 ProcessTree queues, future development of multi-component features (like a Data Browser or Status Bar) should migrate to `zprocess.Event`. This will allow multiple GUI subscribers to independently monitor kernel lifecycle events without complex message routing.

## Outstanding Risk

### 🔴 Risk 1: Deep coupling to `spyder-kernels` internal APIs

This is the biggest strategic risk in the project.

**The problem:** The architecture documents repeatedly say "reference Spyder's implementation" and "copy existing solutions" for namespace tracking, comm-based change notifications, and figure routing. Having now read the `spyder-kernels` `CommBase` source, I can tell you: **this is not a public API.** It's a ~600-line internal RPC framework with:

- A custom message protocol (`spyder_msg_type`, `remote_call`, `remote_call_reply`)
- Blocking/async reply semantics with UUID-correlated call IDs
- Its own error wrapping and propagation system
- A `RemoteCallFactory` that uses `__getattr__` magic to dispatch calls

Spyder's Variable Explorer works by both sides (kernel + frontend) instantiating matching `CommBase` subclasses that speak this private protocol. If you build Hyde's namespace tracking on top of this:

- **You inherit Spyder's internal breaking changes.** `spyder-kernels` has no stability guarantees for these APIs. Major refactors happen between Spyder versions (the Spyder 4 → 5 transition rewrote major parts of the comm system).
- **You create a hard dependency on Spyder's specific comm protocol,** not on Jupyter's generic `comm` spec. These are different things.
- **Your `pyproject.toml` pins `spyder-kernels>=2.0`** — that's an enormous version range covering multiple incompatible API surfaces.

**Recommendation:** Before building Feature B (Data Browser), explicitly decide:
1. **Option A:** Depend on Spyder's comm framework directly (fastest to prototype, highest maintenance burden, most fragile).
2. **Option B:** Use Jupyter's *standard* `comm` protocol (`ipykernel.comm.Comm`) to build your own lightweight namespace-change notification system. A `post_execute` hook in the kernel that diffs `user_ns` and sends a JSON payload over a standard `comm` channel is ~50 lines of code and has zero dependency on `spyder-kernels`' internal RPC framework.
3. **Option C:** Hybrid — use `spyder-kernels` only as the kernel launcher (you already do this), but build all custom comm logic on the Jupyter standard.

> [!IMPORTANT]
> I strongly recommend **Option C**. You're already using `spyder_kernels.console` as the kernel entry point, which is fine. But building your own comm handlers on `ipykernel.comm.Comm` gives you control over your protocol without inheriting Spyder's maintenance burden.

---

## Resolved Issues

### Resolved Risks & Concerns

| Risk ID | Description | Resolution Strategy | Status |
| :--- | :--- | :--- | :--- |
| **Risk 3** | Connection File Fragility | Switched to per-session `tempfile` and passed path via native `ProcessTree` args. | **Resolved** |
| **Risk 4** | UI Scaffolding Clutter | Removed 12 empty placeholder directories; consolidated on `main` and `command_window`. | **Resolved** |
| **Risk 5** | Dynamic Versioning | Added `__version__` to `__init__.py` to satisfy `pyproject.toml` dynamic lookup. | **Resolved** |
| **Risk 7** | Package Data Exclusions | Corrected UI file glob to `**/*.ui` for recursive inclusion. | **Resolved** |
| **Risk 8** | Lifecycle & Observability | Implemented `GUI -> Watchdog -> Kernel` managed tree; added `zlog` and `OutputBox` monitoring. | **Resolved** |

The following issues from the original evaluation have been addressed:

| # | Issue | Resolution |
|---|-------|------------|
| 2 | Custom matplotlib backend complexity | Documented the implementation approach in `ARCHITECTURE.md`: subclass `backend_qtagg` (`FigureCanvasQTAgg` / `FigureManagerQT`), override `show()` to route into MDI. |
| 3 | Hardcoded connection file path | Connection file now generated per-session in `tempfile.mkdtemp()`. Path is passed to the Watchdog via `sys.argv[1]`. Defined centrally in `hyde/paths.py`. |
| 4 | Empty spec/UI scaffolding | Removed all 12 empty `user_interface/` subdirectories. Spec directories already contained content (SPEC.md + screenshots) and were retained. |
| 5 | Missing `__version__` | Added `__version__ = "0.1.0.dev0"` to `hyde/__init__.py`. |
| 6 | Path construction inconsistency | Created `hyde/paths.py` as the single source of truth for `HYDE_PKG_DIR`, `CONNECTION_FILE`, `SPLASH_SVG`, and `EXECUTION_CONTROLLER`. Updated all consumers. |
| 7 | `.ui` glob mismatch in pyproject.toml | Changed glob from `user_interface/*.ui` to `user_interface/**/*.ui`. |
