# Plan: Complete Reimplementation of Command Window

## Overview

Replace the existing `CommandInputHandler` + `QLineEdit` terminal with a proper IPython terminal using `spyder_kernels` kernel and qtconsole's `RichJupyterWidget`.

## Phase 1: Remove Existing Code

| File | Remove |
|------|--------|
| `main_window.py` | Delete `CommandInputHandler` class (lines 38-140) |
| `main_window.py` | Remove `OutputBox` import and usage |
| `main_window.py` | Remove terminal panel setup in `HydeMainWindow.__init__()` |
| `user_interface/` | Delete `terminal_panel.ui` |
| `main_window.py` | Remove command input frame from `HydeMainWindow` |

## Phase 2: Create New Terminal Implementation

### 2.1 Create terminal package

Create `user_interface/terminal/` package:

```
user_interface/terminal/
├── __init__.py
├── terminal.py
└── terminal.ui (optional - may not need .ui file)
```

### 2.2 Implement HydeTerminalWidget

Subclass `RichJupyterWidget` to create `HydeTerminalWidget`:

```python
class HydeTerminalWidget(RichJupyterWidget):
    """RichJupyterWidget with Hyde-specific integration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Add Hyde-specific handlers
```

Key responsibilities:
- Connect to kernel via QtKernelManager
- Handle comm-based namespace change notifications
- Handle matplotlib figure output
- Provide completion handling

### 2.3 Modify execution subprocess

In `execution/execution_subprocess.py`:

```python
# Replace ExecutionRuntime with spyder_kernels kernel
from spyder_kernels.console import main as kernel_main
# Or use IPython kernel directly
from ipykernel import IPythonKernel

# Start kernel and write connection file
# Connection file path passed to parent process
```

The kernel is started via ProcessTree but communicates via ZMQ.

### 2.4 Inject minimal helpers

At kernel startup, inject only functions not in supported libraries:

```python
def kernel_startup_hook(kernel):
    """Inject minimal helpers into kernel namespace."""
    kernel.shell.push({
        'open_table': open_table_function,
        # Only what matplotlib/lmfit don't provide
    })
```

## Phase 3: Integration

### 3.1 Update HydeMainWindow

Replace terminal panel with `HydeTerminalWidget` in MDI:

```python
# In HydeMainWindow.__init__
self.terminal = HydeTerminalWidget()
self.mdi.addSubWindow(self.terminal)
```

### 3.2 Update app.py

Replace `ExecutionController` with kernel connection:

```python
# Remove old execution controller
from qtconsole.rich_jupyter_widget import RichJupyterWidget
from qtconsole.manager import QtKernelManager

class HydeApplication:
    def __init__(self):
        self.kernel_manager = None
        self.terminal = None
```

### 3.3 IPC mechanism

Use connection file approach (like Spyder):

1. Execution subprocess starts kernel, writes `kernel-{uuid}.json`
2. GUI reads connection file path from subprocess
3. `QtKernelManager` loads connection file
4. `RichJupyterWidget` connects via ZMQ

## Key Design Decisions

1. **Kernel runs in subprocess** via ProcessTree - maintains Hyde's architecture
2. **Frontend connects via ZMQ** using QtKernelManager - standard qtconsole approach
3. **Namespace helpers injected** at kernel startup - minimal, only `open_table` etc.
4. **Figure handling** via spyder_kernels comm system - better than TrackedArray

## Architecture Diagram

```
GUI Process (PyQt)                           Execution Subprocess
┌─────────────────────────────────────┐      ┌─────────────────────────┐
│ HydeMainWindow (MDI)                 │      │ spyder_kernels kernel  │
│  ┌─────────────────────────────┐    │      │                         │
│  │ HydeTerminalWidget          │◄───┼─────►│ ZMQ channels            │
│  │ (RichJupyterWidget subclass)│    │      │                         │
│  └─────────────────────────────┘    │      │ + minimal helpers       │
│  ┌─────────────────────────────┐    │      │   (open_table, etc.)    │
│  │ Figure windows              │    │      └─────────────────────────┘
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
       │
       │ QtKernelManager connects via connection file
       ▼
  kernel-{uuid}.json
```

## Files to Create/Modify

### New Files
- `user_interface/terminal/__init__.py`
- `user_interface/terminal/terminal.py`

### Delete
- `user_interface/terminal_panel.ui`
- `CommandInputHandler` class in `main_window.py`

### Modify
- `execution/execution_subprocess.py` - use spyder_kernels kernel
- `app.py` - kernel manager instead of ExecutionController
- `main_window.py` - remove old terminal code, add new terminal widget