# Python Terminal Specification

## Feature Checklist

- [x] Embed a `qtconsole`/IPython Python Terminal as an MDI subwindow in the main GUI.
- [x] Host the Python Terminal tool window in a `HydeToolWidget` container and mount
  the console widget as its child.
- [x] Connect the Python Terminal directly to the running kernel via the shared Jupyter
  connection file.
- [x] Use standard rich IPython prompt behavior rather than a separate custom entry
  widget.
- [x] Support normal user-entered execution through the visible Python Terminal
  session.
- [x] Keep `procedures/__init__.py` startup/reload execution out of the GUI session.
- [x] Mask kernel-runtime-owned `procedures/__init__.py` input at the kernel protocol
  level with `silent=True`.
- [ ] Show kernel-runtime-session output in the Python Terminal without echoing
  kernel-runtime input. Note: this is likely a backend requirement presented to the
  user via the Python Terminal.
- [ ] Verify exact startup appearance is determined from the stdout produced while
  `procedures/__init__.py` runs, followed by the first visible prompt `In [1]:`.
- [ ] Document and implement the final policy for other non-user kernel output while
  keeping first-class figure redraw and edit traffic out of the Python Terminal.

## Specification

- The Python Terminal plugin uses `HydeToolWindowPlugin` for ordinary persistent
  tool-window plumbing.
- `create_tool_window_widget()` creates a `HydeToolWidget` container in
  `hyde/user_interface/plugins/python_terminal_tool/__init__.py`.
- That container mounts `PythonTerminal`, a small `RichJupyterWidget` subclass, into
  the shared `content_layout`.
- The `HydeToolWidget` shell is structural only. It provides the shared zero-margin
  tool-window container, mounted-child support, and persistent hide-on-close behavior.
  It does not add a separate terminal-specific entry field, toolbar, clear button, or
  history dropdown around the console.
- The GUI owns one shared frontend `QtKernelClient` in `frontend_kernel.py`, loads
  `kernel-hyde.json`, starts the normal Jupyter channels, and exposes that client to
  the Python Terminal and other frontend services.
- User-entered commands travel directly from the mounted rich IPython console to the
  kernel over that shared frontend client session.
- `procedures/__init__.py` execution is owned by the kernel-runtime plugin, which
  reuses the shared frontend client for silent execution instead of opening a second
  frontend execution session.
- Input masking for kernel-runtime-driven `procedures/__init__.py` execution is
  implemented at the kernel protocol level with `silent=True`.
- The Python Terminal is inaccessible in Hyde's explicit no-project state and becomes
  available only after a project is activated.
- While `hyde.HYDE_GUI` is true, `quit` / `quit()` / `exit` / `exit()` are rebound in
  the kernel namespace to `hyde.quit()` so terminal-driven quit follows Hyde's orderly
  shutdown path.
- First-class figure-window render, metadata, and semantic edit traffic does not route
  through the kernel-runtime hidden execution path and does not appear in the Python
  Terminal as synthetic input. That traffic uses the dedicated figure `comm` path
  defined by the figure feature.

## Reference Image

![Python Terminal](22_python_terminal.png)

The image is a behavior reference for the embedded rich IPython console, not a literal
widget-tree contract. The shipped Hyde structure is a `HydeToolWidget` container with
one mounted `RichJupyterWidget` child.

- Hyde does not add a separate text-entry widget below the console.
- Hyde does not add a terminal-specific history dropdown or clear-button strip around
  the console.
- Standard IPython prompt structure (`In` / `Out`) is expected:

```text
# Out [0]: Any output from startup would go here.
In [1]: 1+1
Out[1]: 2

In [2]:
```

## Architecture

### User-Typed Commands

- The user types directly into the mounted rich IPython console.
- The Python Terminal sends those commands to the kernel through the shared frontend
  `QtKernelClient`.
- These commands are visible in the Python Terminal and participate in normal IPython
  history/prompt numbering.

### Package Startup And Reload

- Initial loading and reload of `procedures/__init__.py` are owned by the
  kernel-runtime plugin, not the Python Terminal.
- The kernel-runtime plugin reuses the shared frontend client through
  `FrontendKernelService`.
- The kernel-runtime plugin executes the canonical package initialization string with
  `silent=True`, so the kernel does not emit `execute_input` for that request and does
  not consume the visible prompt history.
- File changes under `procedures/` trigger the same kernel-runtime execution path as
  initial load.

### Figure Traffic

- Opening, redrawing, and editing first-class `@hyde.figure` figures is not a
  kernel-runtime background-execution workflow.
- Once a first-class figure exists, routine GUI edits are private semantic `comm`
  actions against the figure feature's IR rather than visible terminal commands. For
  this feature, Hyde keeps that IR kernel-owned and attached to the live figure.
- Figure redraw payloads and edit acknowledgments therefore do not echo as terminal
  input or consume prompt numbers.

## Output Policy

- Silent execution requests on the shared frontend client can execute without
  producing `execute_input`.
- Whether output from those silent requests should appear in the visible Python
  Terminal is a frontend display-policy decision.
- Figure-window traffic is not part of that display-policy question. Figure updates
  are delivered to figure windows over the dedicated figure `comm` path rather than
  through terminal echo.
