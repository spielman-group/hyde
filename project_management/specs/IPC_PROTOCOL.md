# Hyde IPC & Process Protocol Specification

## The Three-Process Architecture
To isolate the GUI from scientific execution and assure crash-resiliency, Hyde enforces a strict three-process hierarchy:

1. **Main Process (GUI):** Runs the PyQt event loop, the MDI window, and the `RichJupyterWidget`. It owns no scientific state and acts purely as a "string factory" and viewport.
2. **Execution Controller (Watchdog):** A subprocess launched by the GUI via `zprocess.ProcessTree`. Its sole responsibility is to spawn, monitor, and recover the underlying IPython kernel.
3. **The Kernel (`spyder_kernels`):** The isolated Jupyter/IPython process evaluating all scientific execution.

---

## 2-Lane Communication Layer
Hyde explicitly eschews constructing bespoke third-party channels (e.g. raw sockets for figures). Instead, network traffic flows exclusively over two highly robust, specialized lanes:

### Lane 1: Application-Level Orchestration (`zprocess.ProcessTree`)
The PyQt GUI process communicates with the Execution Controller Watchdog over standard `labscript-suite` `ProcessTree` queues (`from_parent` / `to_parent`).
- This channel is used ONLY for Hyde-native overarching state control (e.g., exiting the application, alerting the GUI that a kernel crashed).
- Python analytical commands do **not** traverse this tree.

### Lane 2: The Execution Lane (Spyder / Jupyter ZMQ)
The Python REPL and all visual execution state travels over standard Jupyter ZMQ protocols established by the kernel's connection file (`kernel-hyde.json`). The GUI's `JupyterClient` connects directly to the kernel process (bypassing the Watchdog).
- **String Passing:** User interactions (like "New Figure") generate strings of Python code, which are passed directly to the `JupyterClient` for execution.
- **Figure Routing:** Rather than opening raw ZMQ sockets, the custom `matplotlib` backend will inherit `backend_bases` and transmit its rich drawing instructions to the GUI strictly by multiplexing over standard Jupyter **`comm` channels** on the `IOPub` socket.
- **Namespace Tracking:** State changes of Python objects inherently emit metadata tracking updates over the Spyder `comm` channel (via `post_execute` hooks), triggering the GUI data components to refresh.

---

## Kernel Crash Recovery Protocol
If the `spyder_kernels` instance segfaults or receives an `exit()` command:
1. **Detection:** The Execution Controller detects the sub-process death, restarts a pristine kernel, and pushes a `["KERNEL_RESTARTED"]` alert to the GUI via the `ProcessTree` queue.
2. **Orphaning:** Since the backend namespace is wiped, the GUI will apply a visual "Disconnected/Stale" overlay to all linked Figures and Tables. It does **not** hard crash.
3. **Recovery:** Because the GUI remembers the Application State (which `.hy` package was active), recovery handles reloading natively by triggering the exact same code path as if the user had clicked the `File -> Load` menu item to replay the state script against the fresh kernel.
4. **Re-binding:** As the data loads into the new kernel, the `comm` channels emit namespace tracking updates, and the orphaned UI widgets dynamically reconnect and refresh.
