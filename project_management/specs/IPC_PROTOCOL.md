# Hyde IPC & Process Protocol Specification

## Process Topology
Hyde runs as three cooperating processes:

1. **GUI Process**
   Owns the PyQt event loop, the MDI interface, the embedded `qtconsole` command window, and project-selection UI.
2. **Execution Controller / Watchdog**
   Spawned by the GUI through `zprocess.ProcessTree`. Owns kernel lifecycle and procedure-file monitoring.
3. **Kernel Process**
   The `spyder_kernels` IPython kernel that holds the authoritative Python namespace. It is started in-process by `hyde/execution/kernel_launcher.py`, so the real kernel process is itself the `ProcessTree` child.

## Communication Inventory
Hyde controls three distinct communication paths:

1. **GUI -> Executor**
   `zprocess.ProcessTree` queue messages for Hyde-owned orchestration.
2. **Executor -> GUI**
   `zprocess.ProcessTree` queue messages for watchdog status.
3. **GUI -> Kernel** and **Executor -> Kernel**
   Standard Jupyter ZeroMQ clients connected through the shared kernel connection file.

The executor and the GUI both connect to the same kernel, but they use separate Jupyter client sessions for different purposes.

## Hyde Package Surface in the Kernel
The kernel may import the Hyde package directly:

```python
import hyde
```

Today, this provides the Hyde Python package namespace itself. Hyde-specific helper functions are not yet a defined public API surface. When such helpers are added, they should be exposed deliberately through the Hyde package and documented alongside the implementation.

## Lane 1: GUI <-> Executor (`zprocess.ProcessTree`)

### Transport
- `HydeApp` spawns `hyde/execution/execution_controller.py` with `ProcessTree.subprocess(...)`.
- The resulting `to_worker` / `from_worker` queues are the authoritative Hyde-owned orchestration channel.

### GUI -> Executor Messages

#### `['WATCH_PROJECT', payload]`
Configures the executor for the selected `.hy` project.

Payload:
```python
{
    'project_dir': '/abs/path/to/project.hy',
    'procedures_dir': '/abs/path/to/project.hy/procedures',
    'procedures_init': '/abs/path/to/project.hy/procedures/__init__.py',
}
```

Behavior:
- update the executor's project paths
- rebuild the `FileWatcher` for `procedures/` plus `procedures/__init__.py`
- request a package initialization execution through the executor's canonical reload path

Send sites:
- initial startup after the watchdog is spawned
- any explicit project load / new project selection
- after creating a default `procedures/__init__.py`

#### `['QUIT', None]`
Requests clean shutdown of the executor.

Behavior:
- set the executor's exit flag
- stop the watchdog main loop
- stop file watching
- stop the executor's kernel client channels
- terminate the kernel subprocess if it is still alive

Send site:
- GUI `aboutToQuit`

### Executor -> GUI Messages

#### `['KERNEL_READY', connection_file]`
Sent when the kernel is running and a valid Jupyter connection file exists.

Payload:
```python
'/abs/path/to/kernel-hyde.json'
```

GUI behavior:
- instantiate the embedded command window
- connect the command window's `QtKernelClient` to the same kernel
- show the main window and dismiss the splash screen

#### `['KERNEL_CRASHED', None]`
Sent when the watchdog detects unexpected kernel death and is about to restart it.

GUI behavior:
- show a warning dialog that the execution kernel died unexpectedly

## Lane 2A: GUI -> Kernel (Visible Command Session)

### Transport
- `hyde/user_interface/command_window/__init__.py`
- `qtconsole.client.QtKernelClient`
- shared connection file: `kernel-hyde.json`

### Purpose
This is the user's visible interactive console session.

### Behavior
- the command window is a minimal `RichJupyterWidget`
- it creates its own `QtKernelClient`
- user-entered Python is sent directly to the kernel over standard Jupyter `execute_request`
- this session owns the visible rich IPython prompt/history behavior seen by the user
- the user may access Hyde's supported feature surface in the kernel via `import hyde`

### Important boundary
- Hyde should not inject watchdog-controlled system execution through this session
- the command window is for visible user interaction, not for replaying `procedures/__init__.py`

## Lane 2B: Executor -> Kernel (Background Control Session)

### Transport
- `hyde/execution/execution_controller.py`
- `jupyter_client.BlockingKernelClient`
- shared connection file: `kernel-hyde.json`

### Purpose
This is the executor-owned background control session.

### Responsibilities
- execute `procedures/__init__.py` after project configuration
- reload `procedures/__init__.py` when watched procedure files change
- establish the kernel namespace in which project procedures run

### Execution String
The executor uses one canonical command string for both initial load and reload:

```python
import os
import sys
import importlib
import __main__

os.chdir(project_dir)
project_root = os.getcwd()
if sys.path[:1] != [project_root]:
    while project_root in sys.path:
        sys.path.remove(project_root)
    sys.path.insert(0, project_root)
for name in list(getattr(__main__, "__hyde_procedures_exports__", set())):
    __main__.__dict__.pop(name, None)
importlib.invalidate_caches()
for name in list(sys.modules):
    if name == "procedures" or name.startswith("procedures."):
        del sys.modules[name]
import procedures
__hyde_exports = {
    name: value
    for name, value in procedures.__dict__.items()
    if not name.startswith("_")
}
__main__.__dict__.update(__hyde_exports)
__main__.__hyde_procedures_exports__ = set(__hyde_exports)
```

### Execution Policy
- this command is sent with `silent=True`
- this masks the corresponding `execute_input` at the Jupyter protocol level
- it also avoids consuming the visible IPython prompt/history count for the user's command session

### Trigger Source
- `WATCH_PROJECT` requests initial execution
- `labscript_utils.filewatcher.FileWatcher` watches `procedures/` and `procedures/__init__.py`
- any relevant `.py` change sets the executor's reload flag
- the watchdog main loop consumes that flag and re-runs the same canonical command string

## Lane 2C: Data Browser Namespace View (Target: `spyder_api`)

### Transport
- Jupyter `comm` channel.
- Kernel-side: `spyder_kernels` registers the `spyder_api` comm target natively.
- GUI-side: the Data Browser maintains its own `QtKernelClient`.
- Frontend comm opening is performed through `qtconsole`'s `kernel_client.comm_manager`, not by calling comm methods on `QtKernelClient` directly.

### Purpose
- provide a live namespace view for the Data Browser
- reuse Spyder's existing namespace metadata machinery instead of inventing a Hyde-specific tracker

### Session Ownership
- the command window keeps its own visible user-facing Jupyter client session
- the Data Browser keeps a separate GUI-side metadata session
- the executor keeps its own background control session

### Setup Sequence
The Data Browser performs the following sequence after its own client channels are ready:

1. open a `spyder_api` comm through `kernel_client.comm_manager.new_comm(...)`
2. wait for the comm-ready callback from Spyder
3. send a Spyder `remote_call` to:
   - `set_configuration({"namespace_view_settings": ...})`
4. send a Spyder `remote_call` to:
   - `get_namespace_view()`

### Data Returned
The namespace view comes from Spyder's existing `get_namespace_view()` handler.
It is a dictionary keyed by variable name.

Representative payload shape:
```python
{
    'x': {
        'type': 'int',
        'size': 1,
        'view': '1',
        'python_type': 'int',
        'numpy_type': 'Unknown'
    },
    'arr': {
        'type': 'Array of int64',
        'size': (100,),
        'view': 'Column vector containing 100 elements',
        'python_type': 'ndarray',
        'numpy_type': 'Array'
    },
}
```

### Triggering Policy
- **On Initialization**: Viewports request an initial snapshot immediately upon comm establishment.
- **On Execution**: The Data Browser monitors kernel `status` messages. When externally generated kernel work transitions `busy -> idle`, it requests a new namespace snapshot.
- **On Reload**: Executor-driven `procedures/__init__.py` reloads also trigger the same `busy -> idle` path, ensuring the Data Browser reflects script-defined changes.
- **Scope**: The Data Browser only consumes messages associated with its own Spyder comm. Unrelated comm traffic must be ignored.

## Kernel-Side Consequences

### For GUI Session Commands
- normal `execute_request`
- normal prompt/history behavior
- visible `execute_input`, `execute_result`, `stream`, and error messages as handled by the frontend

### For Executor Session Commands
- separate Jupyter client session
- `silent=True` background execution for `procedures/__init__.py`
- no `execute_input` for those requests
- no prompt/history consumption for that background execution

---

## Not Yet Implemented Here
- Figure metadata mirroring over Jupyter `comm` channels is planned but not yet implemented.
- External suite messages such as runmanager/BLACS notifications are not yet part of the implemented Hyde IPC path.
