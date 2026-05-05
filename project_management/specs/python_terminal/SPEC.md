# Python Terminal Specification

## Feature Checklist
- [x] Embed a `qtconsole`/IPython Python Terminal as an MDI subwindow in the main GUI.
- [x] Connect the Python Terminal directly to the running kernel via the shared Jupyter connection file.
- [x] Use standard rich IPython prompt behavior rather than a separate custom entry widget.
- [x] Support normal user-entered execution through the visible Python Terminal session.
- [x] Keep `procedures/__init__.py` startup/reload execution out of the GUI session.
- [x] Mask runtime-helper-driven `procedures/__init__.py` input at the kernel protocol level with `silent=True`.
- [ ] Show runtime-helper-session output in the Python Terminal without echoing runtime-helper input. Note: this is likely a backend requirement presented to the user via the Python Terminal.
- [ ] Verify exact startup appearance is determined from the stdout produced while `procedures/__init__.py` runs, followed by the first visible prompt `In [1]:`.
- [ ] Document and implement the final policy for other non-user kernel output while keeping first-class figure redraw and edit traffic out of the Python Terminal.

## Specification

- The Python Terminal is a plain `RichJupyterWidget` wrapper in `hyde/user_interface/plugins/python_terminal/__init__.py`.
- It creates a `QtKernelClient`, loads `kernel-hyde.json`, starts the normal Jupyter channels, and exposes the standard rich IPython console UI.
- User-entered commands travel directly from the GUI to the kernel over the Python Terminal's own Jupyter client session.
- `procedures/__init__.py` execution is owned by the GUI-owned runtime helper, which uses its own non-UI Jupyter client connected to the same kernel.
- Input masking for runtime-helper-driven `procedures/__init__.py` execution is implemented at the kernel protocol level with `silent=True`.
- The Python Terminal is inaccessible in Hyde's explicit no-project state and becomes available only after a project is activated.
- While `hyde.HYDE_GUI` is true, `quit` / `quit()` / `exit` / `exit()` are rebound in the kernel namespace to `hyde.quit()` so terminal-driven quit follows Hyde's orderly shutdown path.
- First-class figure-window render, metadata, and semantic edit traffic does not route
  through the runtime helper and does not appear in the Python Terminal as synthetic
  input. That traffic uses the dedicated figure `comm` path defined by the figure
  feature.

## 22_python_terminal.png
![Python Terminal](22_python_terminal.png)
- What it shows: Python Terminal with IPython prompt, command history dropdown, and clear button.
- **Divergence from Igor Pro Image**:
  - There should NOT be a separate text-entry widget at the bottom. The behavior must emulate standard rich IPython (just like the Spyder IDE).
  - IPython syntax highlighting is strictly expected.
  - Standard IPython prompt structures (`In`/`Out`) are expected instead of Igor Pro log numbering:
    ```
    # Out [0]: Any output from startup would go here.
    In [1]: 1+1
    Out[1]: 2

    In [2]:
    ```

## Architecture

### User-Typed Commands
- The user types directly into the embedded rich IPython console.
- The Python Terminal sends those commands to the kernel through its `QtKernelClient`.
- These commands are visible in the Python Terminal and participate in normal IPython history/prompt numbering.

### Package Startup and Reload
- Initial loading and reload of `procedures/__init__.py` are owned by the GUI-owned runtime helper, not the Python Terminal.
- The runtime helper uses a separate non-UI Jupyter client connected to the same kernel.
- The runtime helper executes the canonical package initialization string with `silent=True`, so the kernel does not emit `execute_input` for that request and does not consume the visible prompt history.
- File changes under `procedures/` trigger the same runtime-helper execution path as initial load.

### Figure Traffic
- Opening, redrawing, and editing first-class `@hyde.figure` figures is not a
  runtime-helper workflow.
- Once a first-class figure exists, routine GUI edits are private semantic `comm`
  actions against the figure feature's IR rather than visible terminal commands. For
  this feature, the PRD makes that IR kernel-owned and attached to the live figure.
- Figure redraw payloads and edit acknowledgments therefore do not echo as terminal
  input or consume prompt numbers.

## Output Policy
- A separate Jupyter client session can execute silently without producing `execute_input`.
- Whether output from that session should appear in the visible Python Terminal is a frontend display-policy decision.
- Figure-window traffic is not part of that display-policy question. Figure updates are
  delivered to figure windows over the dedicated figure `comm` path rather than through
  terminal echo.
