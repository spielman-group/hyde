# Hyde IPC & Process Protocol Specification

## Process Topology
Hyde runs as two cooperating processes plus one GUI-owned helper thread:

1. **GUI Process**
   Owns the PyQt event loop, the MDI interface, the embedded `qtconsole` Python Terminal, project-selection UI, `FileWatcher`, and the plugin-managed lyse-compatible `ZMQServer`.
2. **Kernel Process**
   The `spyder_kernels` IPython kernel that holds the authoritative Python namespace. It is started in-process by `hyde/execution/kernel_launcher.py`, so the real kernel process is the direct `ProcessTree` child of the GUI.
3. **Runtime Helper Thread**
   A GUI-owned `threading.Thread` fed by `queue.Queue`. It owns the non-UI Jupyter client used for silent/background execution against the same kernel.

## Communication Inventory
Hyde uses three communication paths:

1. **Kernel -> GUI**
   `zprocess.ProcessTree` parent-child messages for Hyde-owned relays.
2. **GUI -> Kernel**
   Standard Jupyter ZeroMQ clients connected through the shared kernel connection file.
3. **External -> GUI**
   A lyse-compatible `labscript_utils.ls_zprocess.ZMQServer` bound to the existing
   `ports.lyse` labconfig entry and owned by a first-party GUI plugin.

The Python Terminal and the runtime helper both connect to the same kernel, but they use separate Jupyter client sessions for different purposes.

External clients that already target lyse's labconfig port may also talk to Hyde
through the plugin-owned GUI listener.

## Hyde Package Surface in the Kernel
The kernel may import the Hyde package directly:

```python
import hyde
```

Anything exposed from `hyde/__init__.py` is part of Hyde's public kernel-facing API.

Public helpers added there must:
- be defined deliberately as part of Hyde's runtime interface
- be documented with docstrings and parameter/behavior descriptions suitable for generated API documentation
- remain separate from the `features/...` translation layer

The `features/...` layer is reserved for:
- GUI representation -> Python strings
- Python strings or metadata -> GUI representation

For command-emitting GUI features, that translation lives in `HydeGuiState` /
`FeatureCodec` pairs. The table feature uses `TableState` + `TableCodec` for table
construction, recreation, layout-bearing background requests, and `MutationState` +
generic `MutationCodec` for live data mutation strings.

The table feature is the first implemented example of a public Hyde helper, with
`hyde.table(...)` serving as the kernel-facing entry point for table creation and
appending. The same public symbol also supports decorator use for saved parameterized
table recreation macros. Project persistence is the second implemented example, with
`hyde.save_project(...)` and `hyde.load_project(...)` serving as the explicit save/load
entry points used by the GUI File menu.

The public `hyde.table(...)` helper also accepts optional recreation-layout kwargs:

- `geometry=(x, y, width, height)`
- `column_widths={"array_name": width, ...}`

## Lane 1: Kernel -> GUI (`zprocess.ProcessTree`)

### Transport
- `HydeApp` spawns `hyde/execution/kernel_launcher.py` with `ProcessTree.subprocess(...)`.
- The kernel child uses `ProcessTree.instance().to_parent` for narrow Hyde-owned relays back to the GUI process.

### GUI-owned queue producers
The GUI process owns one internal queue feeding the runtime-helper thread. Queue producers are:
- `FileWatcher` callbacks
- the lyse-compatible `ZMQServer`
- GUI widgets that need silent background kernel work such as table refreshes

The queue is an in-process detail. It is not a public Hyde protocol.

### Kernel -> GUI Messages

#### `['ENTER_NO_PROJECT_STATE', None]`
Sent when the kernel clears its active project and requires the GUI to return to the explicit no-project state.

GUI behavior:
- clear project-path state
- stop watching project files
- hide project-owned windows
- leave only `New Project`, `Load Project`, `Logging`, and `Quit` active

#### `['QUIT_REQUESTED', None]`
Sent when the kernel has already entered Hyde's inert state and requests that the GUI begin application shutdown.

GUI behavior:
- route into the normal main-window close path
- keep `closeEvent` as the only GUI-side shutdown implementation
- continue shutdown with timer-polled kernel-process exit rather than blocking waits on the GUI thread

#### `['ACTIVATE_PROJECT', payload]`
Sent when the kernel has completed a successful project activation and the GUI may adopt that project.

Payload:
```python
{
    'path': '/abs/path/to/project.hy',
}
```

GUI behavior:
- update current project paths
- root the Procedure Browser at `procedures/`
- restart project file watching
- restore project-capable actions

#### `['PROJECT_STATE_RESULT', payload]`
Forwarded when a kernel-side `hyde.save_project(...)` or `hyde.load_project(...)` call
publishes its completion result over `ProcessTree`.

Payload:
```python
{
    'operation': 'save' or 'load',
    'path': '/abs/path/to/project.hy',
    'success': True,
    'errors': ['optional warning/error strings'],
    'object_count': 3,
}
```

GUI behavior:
- warn if `errors` is non-empty
- complete Save As project switching after a successful save result
- restore `session.toml` after a successful load result for the active project

#### `['OPEN_TABLE_REQUEST', payload]`
Sent when the kernel requests that the GUI open or update a table.

Payload:
```python
{
    'names': ['x', 'y'],
    'target': None,
    'title': 'My Table',
    'geometry': (5, 42, 510, 242),
    'column_widths': {'y': 262},
}
```

GUI behavior:
- create a new table window when `target` is `None`
- append columns to an existing table when `target` matches an open table handle
- ignore `geometry` and `column_widths` for append-to-target requests

#### `['TABLE_DATA_RESPONSE', payload]`
Sent when the kernel pushes structured table data back to the GUI.

Payload:
```python
{
    'request_id': 'uuid-or-token',
    'data': {
        'x': [1, 2, 3],
        'y': [4, 5, 6],
    },
}
```

GUI behavior:
- deliver the payload to open tables
- each table ignores responses whose `request_id` does not match its outstanding fetch

#### `['WINDOW_MACROS_RESPONSE', payload]`
Sent when the kernel publishes a serialized window-macro registry snapshot.

Payload:
```python
{
    'kind': 'table',
    'macros': [
        {'name': 'Table0', 'args': ['c', 'd']},
        {'name': 'Table1', 'args': ['array0']},
    ],
}
```

GUI behavior:
- rebuild the corresponding Windows submenu
- selecting a table macro generates a visible call such as `Table0(c, d)`
- disable that submenu when `macros` is empty

## Lane 2A: GUI -> Kernel (Visible Command Session)

### Transport
- `hyde/user_interface/plugins/python_terminal/__init__.py`
- `qtconsole.client.QtKernelClient`
- shared connection file: `kernel-hyde.json`

### Purpose
This is the user's visible interactive console session.

### Behavior
- the Python Terminal is a minimal `RichJupyterWidget`
- it creates its own `QtKernelClient`
- user-entered Python is sent directly to the kernel over standard Jupyter `execute_request`
- this session owns the visible rich IPython prompt/history behavior seen by the user
- the user may access Hyde's supported feature surface in the kernel via `import hyde`
- GUI-owned save/load actions also use this visible session by generating explicit
  `hyde.save_project(...)` and `hyde.load_project(...)` commands

### Important boundary
- Hyde should not inject runtime-helper-controlled background execution through this session
- the Python Terminal is for visible user interaction, not for replaying `procedures/__init__.py`

## Lane 2B: Runtime Helper -> Kernel (Background Control Session)

### Transport
- `hyde/user_interface/main/runtime_helper.py`
- `jupyter_client.BlockingKernelClient`
- shared connection file: `kernel-hyde.json`

### Purpose
This is the GUI-owned background control session.

### Responsibilities
- reload `procedures/__init__.py` when watched procedure files change
- trigger silent helper calls generated by `TableState` / `TableCodec` that cause the kernel to push structured table data back over `ProcessTree`
- relay project-state completion messages emitted by kernel-side save/load helpers
- trigger silent helper calls generated by `TableState` / `TableCodec` that publish the current table-macro registry after procedures reload
- execute remote requests forwarded from the GUI-owned lyse-compatible listener

Project load itself is not owned by the runtime helper. The authoritative visible
`hyde.load_project(...)` command performs the project bootstrap and saved-object restore
inside the kernel, then emits `ENTER_NO_PROJECT_STATE`, `ACTIVATE_PROJECT`, and
`PROJECT_STATE_RESULT` messages as needed.

## External Lyse-Compatible Listener

### Transport
- `hyde/user_interface/main/runtime_helper.py`
- `labscript_utils.ls_zprocess.ZMQServer`
- port source: `LabConfig().get('ports', 'lyse')`, with fallback `42519`

### Supported requests
- `'hello'`
  - returns `'hello'`
- `{'filepath': <agnostic_path>}`
  - the GUI converts the agnostic/shared-drive path to a local path
  - the listener enqueues the normalized payload into the runtime-helper queue
  - the runtime helper issues kernel code `remote(<local_path>)`
  - returns `'added successfully'`
- `<agnostic_path>` as a plain string
  - the listener enqueues the payload into the runtime-helper queue
  - the runtime helper issues kernel code `remote(<agnostic_path>)`
  - returns `'added successfully'`

### Important boundary
- the GUI owns this listener
- no Hyde-specific labconfig port is introduced
- it is the user's responsibility to define `remote()` in `procedures/__init__.py`
- the listener does not touch the kernel client directly; it only normalizes and queues requests
