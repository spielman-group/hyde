# Hyde IPC & Process Protocol Specification

## Process Topology
Hyde runs as three cooperating processes:

1. **GUI Process**
   Owns the PyQt event loop, the MDI interface, the embedded `qtconsole` command window, and project-selection UI.
2. **Execution Controller / Watchdog**
   Spawned by the GUI through `zprocess.ProcessTree`. Owns kernel lifecycle and procedure-file monitoring.
3. **Kernel Process**
   The `spyder_kernels` IPython kernel that holds the authoritative Python namespace.

## Communication Inventory
Hyde controls three distinct communication paths:

1. **GUI -> Executor**
   `zprocess.ProcessTree` queue messages for Hyde-owned orchestration.
2. **Executor -> GUI**
   `zprocess.ProcessTree` queue messages for watchdog status.
3. **GUI -> Kernel** and **Executor -> Kernel**
   Standard Jupyter ZeroMQ clients connected through the shared kernel connection file.

The executor and the GUI both connect to the same kernel, but they use separate Jupyter client sessions for different purposes.

## Hyde Feature Surface in the Kernel
Supported tools expose their Hyde-facing behavior through the package's `features/` modules. This includes the kernel API made available by:

```python
import hyde
```

That import should be understood as the public Hyde interface to supported tool features. If Hyde provides a helper that is not already part of the underlying third-party library, that helper belongs to this supported feature surface.

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
- establish the kernel namespace in which `import hyde` exposes the supported Hyde feature surface

### Execution String
The executor uses one canonical command string for both initial load and reload:

```python
import os
import sys
import importlib

os.chdir(project_dir)
importlib.invalidate_caches()
for name in list(sys.modules):
    if name == "procedures" or name.startswith("procedures."):
        del sys.modules[name]
import procedures
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

## Not Yet Implemented Here
- Figure metadata mirroring over Jupyter `comm` channels is planned but not yet implemented.
- Namespace/data-browser comm traffic is planned but not yet implemented.
- External suite messages such as runmanager/BLACS notifications are not yet part of the implemented Hyde IPC path.
