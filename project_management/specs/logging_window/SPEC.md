# Logging Window Specification

The Logging window provides a centralized view of runtime output (stdout/stderr) from the managed IPython kernel process.

## Features
- **Centralized Output**: Displays captured output from the GUI-managed ProcessTree child kernel.
- **Suite Integration**: Utilizes `labscript_utils.qtwidgets.outputbox.OutputBox` for secure, ZMQ-based log streaming.
- **MDI Compatibility**: Operates as a standard MDI sub-window within the Hyde main workspace.
- **Lifecycle Management**: Persists across kernel crashes/restarts, continuing to capture output from new kernel processes via the `ProcessTree` redirection port.

## Interface
- **Access**: Managed via the **Windows > Logging** menu action.
- **Default State**: Closed/Hidden. It is intended for debugging and monitoring, not as a primary focus for standard experiment analysis.
- **Styling**: Consistent with the `labscript-suite` color coding for stdout (black/grey) and stderr (red).

## Technical Implementation
- The GUI instantiates the `OutputBox` and binds it to a random port.
- This port is passed to the kernel subprocess as the `output_redirection_port`.
- The kernel subprocess stdout/stderr is pushed to this port.
