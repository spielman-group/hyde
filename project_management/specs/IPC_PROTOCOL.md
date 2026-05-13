# Hyde IPC & Process Protocol Specification

## Process Topology
Hyde runs as two cooperating processes plus one GUI-owned helper thread:

1. **GUI Process**
   Owns the PyQt event loop, the MDI interface, the embedded `qtconsole` Python Terminal, project-selection UI, `FileWatcher`, and the plugin-managed lyse-compatible `ZMQServer`.
2. **Kernel Process**
   The `spyder_kernels` IPython kernel that holds the authoritative Python namespace. It is started in-process by `hyde/execution/kernel_launcher.py`, so the real kernel process is the direct `ProcessTree` child of the GUI.
3. **Runtime Helper Thread**
   A GUI-owned `threading.Thread` that watches the kernel process and relays Lane 1
   control messages into the shell. It does not own a second frontend kernel session
   and it does not own silent/background execution.

## Communication Inventory
Hyde uses three communication paths:

1. **Kernel -> GUI**
   `zprocess.ProcessTree` parent-child messages for Hyde-owned relays.
2. **GUI -> Kernel**
   Standard Jupyter ZeroMQ clients and Jupyter `comm` channels connected through the shared kernel connection file.
3. **External -> GUI**
   A lyse-compatible `labscript_utils.ls_zprocess.ZMQServer` bound to the existing
   `ports.lyse` labconfig entry and owned by a first-party GUI plugin.

The Python Terminal and the kernel-runtime plugin both use one shared GUI-owned
frontend `QtKernelClient` session. The Python Terminal presents the visible rich-console
UI on top of that shared client, while the kernel-runtime plugin reuses the same client
for silent background execution.

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

Across Hyde, "IR" means internal representation/internal state in the same sense as the
existing state-to-Python path used by `features/...`: structured Hyde state that can
lower back to standard Python source. It is not globally synonymous with kernel-owned
state. The difference is feature-specific ownership. Table state currently lives in the
GUI long enough to emit commands, while Hyde keeps figure IR kernel-owned and attached
directly to the live matplotlib `Figure` so figure runtime truth and
recreation/editability truth stay aligned.

The table feature is the first implemented example of a public Hyde helper, with
`hyde.create_table(...)` serving as the imperative kernel-facing entry point for table
creation and reopen, `hyde.append_table(...)` serving as the explicit append-to-
existing entry point, and `@hyde.table` serving as the recreation decorator used for
saved parameterized table macros and non-registering session restore. Project
persistence is the second implemented example, with `hyde.save_project(...)` and
`hyde.load_project(...)` serving as the explicit save/load entry points used by the GUI
File menu.

The figure feature adds a distinct private kernel service rather than a broad new public
helper API. First-class figures are created through `@hyde.figure`. Those figures carry:

- a live kernel `Figure` as runtime truth
- a kernel-owned figure IR as recreation/editability truth
- a parallel figure-local command log and optional source/AST artifacts for diagnostics

Non-decorated figures remain ordinary kernel-side matplotlib figures in this
deployment. They do not open Hyde GUI figure windows and do not participate in the
private figure-window `comm` service unless a future explicit promotion path is
defined.

The public `hyde.create_table(...)` helper also accepts optional recreation-layout
kwargs:

- `geometry=(x, y, width, height)`
- `column_widths={"array_name": width, ...}`

## Lane 1: Kernel -> GUI (`zprocess.ProcessTree`)

### Transport
- `HydeApp` spawns `hyde/execution/kernel_launcher.py` with `ProcessTree.subprocess(...)`.
- The kernel child uses `ProcessTree.instance().to_parent` for narrow Hyde-owned relays back to the GUI process.

### GUI-owned hidden execution producers
Silent/background execution requests originate in GUI-owned producers such as:
- `FileWatcher` callbacks
- the lyse-compatible `ZMQServer`
- GUI widgets that need background kernel work such as table refreshes

Those requests are routed through the kernel-runtime plugin's shared frontend client.
That routing is an in-process detail, not a public Hyde protocol.

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
Sent when the kernel requests that the GUI open a table.

Payload:
```python
{
    'names': ['x', 'y'],
    'name': 'Table0',
    'geometry': (5, 42, 510, 242),
    'column_widths': {'y': 262},
    'window_state': 'minimized',
}
```

GUI behavior:
- create a new table window when `name` is free
- otherwise fall forward to the next available stable `TableN` name
- restore saved `geometry`, `column_widths`, and `window_state` when provided

#### `['APPEND_TABLE_REQUEST', payload]`
Sent when the kernel requests that the GUI append columns to an existing table.

Payload:
```python
{
    'names': ['x', 'y'],
    'name': 'Table0',
}
```

GUI behavior:
- append columns to the existing open table whose `QMdiSubWindow.objectName()` is
  `name`
- ignore the request if no such open table exists

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

#### `['TASK_COMPLETE', payload]`
Sent when kernel-side Hyde code reports completion of a named background task through
the public `hyde.task_complete(...)` API.

Payload:
```python
{
    'name': 'session_restore',
    'success': True,
}
```

GUI behavior:
- for `session_restore`, finalize deferred project-restore presentation work only on
  success
- on failure, keep the existing error/reporting path and skip deferred restore
  ordering/state application

#### `['WINDOW_MACROS_RESPONSE', payload]`
Sent when the kernel publishes a serialized window-macro registry snapshot.

Payload:
```python
{
    'kind': 'table' or 'figure',
    'macros': [
        {'name': 'Table0', 'args': ['c', 'd']},
        {'name': 'Table1', 'args': ['array0']},
    ],
}
```

GUI behavior:
- rebuild the corresponding Windows submenu
- selecting a macro generates a visible call such as `Table0(c, d)` or `Graph0(x, y)`
- disable that submenu when `macros` is empty

## Lane 2A: GUI -> Kernel (Visible Command Session)

### Transport
- `hyde/user_interface/main/frontend_kernel.py`
- `hyde/user_interface/plugins/python_terminal/__init__.py`
- `qtconsole.client.QtKernelClient`
- shared connection file: `kernel-hyde.json`

### Purpose
This is the user's visible interactive console session.

### Behavior
- the Python Terminal is a minimal `RichJupyterWidget`
- it attaches to the GUI-owned shared frontend `QtKernelClient`
- user-entered Python is sent directly to the kernel over standard Jupyter `execute_request`
- this session owns the visible rich IPython prompt/history behavior seen by the user
- the user may access Hyde's supported feature surface in the kernel via `import hyde`
- saved window-macro menu actions also use this visible session by generating explicit
  macro calls after the relevant registry snapshot has been published to the GUI

### Important boundary
- Hyde should not inject kernel-runtime-controlled background execution through this session
- the Python Terminal is for visible user interaction, not for replaying `procedures/__init__.py`
- routine figure GUI edits do not travel through this session; they use semantic Jupyter
  `comm` actions against kernel-owned figure state

## Lane 2B: Kernel Runtime -> Kernel (Background Control Session)

### Transport
- `hyde/user_interface/plugins/kernel_runtime/__init__.py`
- `hyde/user_interface/main/frontend_kernel.py`
- shared connection file: `kernel-hyde.json`

### Purpose
This is the GUI-owned background control session.

### Responsibilities
- dispatch GUI-owned hidden project commands such as `hyde.load_project(...)`,
  `hyde.save_project(...)`, and `hyde.quit()`
- reload `procedures/__init__.py` when watched procedure files change
- trigger silent helper calls generated by `TableState` / `TableCodec` that cause the kernel to push structured table data back over `ProcessTree`
- relay project-state completion messages emitted by kernel-side save/load helpers
- trigger silent helper calls generated by `TableState` / `TableCodec` that publish the current table-macro registry after procedures reload
- execute remote requests forwarded from the GUI-owned lyse-compatible listener

This lane reuses the shared frontend `QtKernelClient` through the kernel-runtime
plugin's `python_execution_service` / `FrontendKernelService.execute(..., silent=True)`.
It does not own a second frontend execution session.

Lane 2B owns dispatch of GUI-triggered hidden project commands, but the authoritative
bootstrap and restore still happen inside the kernel-side `hyde.load_project(...)`
and `hyde.save_project(...)` command paths. `hyde.load_project(...)` emits
`ENTER_NO_PROJECT_STATE`, `ACTIVATE_PROJECT`, and `PROJECT_STATE_RESULT` messages as
needed.

## Lane 2C: GUI Figure Windows <-> Kernel (Semantic Figure `comm` Session)

### Purpose
This lane carries figure metadata publication and semantic figure edit actions for Hyde
figure windows. Only first-class `@hyde.figure` figures participate in this lane.

### Authority model
- the live kernel matplotlib `Figure` is the runtime truth
- the authoritative recreation/editability state for a first-class figure is the
  kernel-owned figure IR attached directly to that figure
- the GUI figure window is a viewport and event source only

### First-class figure window boundary
- first-class figures are created through `@hyde.figure`
- a first-class figure is guaranteed to have a kernel-owned figure IR and associated
  figure-local artifacts
- non-decorated figures do not open Hyde GUI figure windows in this deployment
- non-decorated figures therefore do not participate in semantic figure editing or
  IR-driven graph-macro generation through the GUI figure-window path

### Figure-local kernel artifacts
First-class figures may carry artifacts such as:
- `fig._hyde_ir`
- `fig._hyde_command_log`
- `fig._hyde_source_artifact`
- `fig._hyde_ast_artifact`

The figure IR is authoritative for recreation and editability. The command log and
captured artifacts are auxiliary and do not outrank the IR once the figure exists.

### Responsibilities
- publish figure metadata and rendered-image updates from the kernel to the GUI
- accept semantic figure edit actions from the GUI over Jupyter `comm`
- resolve target figures through the matplotlib global registry identity
- mutate the authoritative figure IR and the live figure transactionally
- redraw the live figure after accepted edits
- support explicit regenerate-from-IR requests as a debug path

### Semantic action examples
Routine GUI figure edits are semantic actions rather than ad hoc Python snippets. The
action vocabulary includes operations such as:
- set axis limits
- set axis labels
- set figure or subplot title
- mutate trace styling
- toggle legend
- request explicit regenerate-from-IR

### Important boundary
- figure edit actions are a private Hyde protocol in this deployment, not a public
  user-facing kernel API
- routine figure editing does not use `ProcessTree`
- routine figure editing does not depend on the GUI owning canonical plot state
- saved graph macros are generated from the authoritative figure IR and exposed back to
  the GUI through the existing window-macro registry path

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
  - the listener dispatches the normalized payload through the kernel-runtime hidden-execution path
  - the kernel-runtime plugin issues kernel code `remote(<local_path>)`
  - returns `'added successfully'`
- `<agnostic_path>` as a plain string
  - the listener dispatches the payload through the kernel-runtime hidden-execution path
  - the kernel-runtime plugin issues kernel code `remote(<agnostic_path>)`
  - returns `'added successfully'`

### Important boundary
- the GUI owns this listener
- no Hyde-specific labconfig port is introduced
- it is the user's responsibility to define `remote()` in `procedures/__init__.py`
- the listener does not touch the kernel client directly; it only normalizes and queues requests
