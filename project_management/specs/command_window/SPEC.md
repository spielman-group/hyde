# Command Window Specification

## Feature Checklist
- [x] Embed a `qtconsole`/IPython command window as an MDI subwindow in the main GUI.
- [x] Connect the command window directly to the running kernel via the shared Jupyter connection file.
- [x] Use standard rich IPython prompt behavior rather than a separate custom entry widget.
- [x] Support normal user-entered execution through the visible command window session.
- [x] Keep `procedures/__init__.py` startup/reload execution out of the GUI session.
- [x] Mask watchdog-driven `procedures/__init__.py` input at the kernel protocol level with `silent=True`.
- [ ] Show watchdog-session output in the command window without echoing watchdog input.  Note: this is likely a back-end requirement that is presented to the user via the command window.
- [ ] Verify exact startup appearance is determined from the stdout produced while `procedures/__init__.py` runs, followed by the first visible prompt `In [1]:`.
- [ ] Document and implement the final policy for other non-user executor traffic, such as figure-preview updates.

## Specification

- The command window is a plain `RichJupyterWidget` wrapper in `hyde/user_interface/command_window/__init__.py`.
- It creates a `QtKernelClient`, loads `kernel-hyde.json`, starts the normal Jupyter channels, and exposes the standard rich IPython console UI.
- User-entered commands travel directly from the GUI to the kernel over the command window's own Jupyter client session.
- `procedures/__init__.py` execution is owned by the execution watchdog, which uses its own `BlockingKernelClient`.
- Input masking for watchdog-driven `procedures/__init__.py` execution is implemented at the kernel protocol level with `silent=True`.

## 22_command_window.png
![Command Window](22_command_window.png)
- What it shows: Command window/terminal with IPython prompt, command history dropdown, and clear button.
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
- The command window sends those commands to the kernel through its `QtKernelClient`.
- These commands are visible in the command window and participate in normal IPython history/prompt numbering.

### Package Startup and Reload
- Initial loading and reload of `procedures/__init__.py` are owned by the execution watchdog, not the command window.
- The watchdog uses a separate `BlockingKernelClient` connected to the same kernel.
- The watchdog executes the canonical package initialization string with `silent=True`, so the kernel does not emit `execute_input` for that request and does not consume the visible prompt history.
- File changes under `procedures/` trigger the same watchdog-side execution path as initial load.

## Output Policy
- A separate Jupyter client session can execute silently without producing `execute_input`.
- Whether output from that session should appear in the visible command window is a frontend display-policy decision.
