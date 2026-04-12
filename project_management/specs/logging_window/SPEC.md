# Logging Window Specification

The Logging window provides a centralized view of all background process output (stdout/stderr) from the Execution Watchdog and the IPython Kernel.

## Features
- **Centralized Output**: Displays captured output from the `GUI -> Watchdog -> Kernel` process tree.
- **Suite Integration**: Utilizes `labscript_utils.qtwidgets.outputbox.OutputBox` for secure, ZMQ-based log streaming.
- **MDI Compatibility**: Operates as a standard MDI sub-window within the Hyde main workspace.
- **Lifecycle Management**: Persists across kernel crashes/restarts, continuing to capture output from the new processes automatically via the `ProcessTree` redirection port.

## Interface
- **Access**: Managed via the **Windows > Logging** menu action.
- **Default State**: Closed/Hidden. It is intended for debugging and monitoring, not as a primary focus for standard experiment analysis.
- **Styling**: Consistent with the `labscript-suite` color coding for stdout (black/grey) and stderr (red).

## Technical Implementation
- The GUI instantiates the `OutputBox` and binds it to a random port.
- This port is passed to the Watchdog as the `output_redirection_port`.
- The Watchdog's own stdout/stderr, and those inherited by the Kernel, are pushed to this port.
