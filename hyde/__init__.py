"""
Hyde: A modern, Pythonic data analysis and plotting environment for the labscript-suite.
"""

__version__ = "0.1.0.dev0"

import inspect


def table(*args, target=None, title=None):
    """
    Open or append to a Hyde table window displaying 1D numeric data.

    This is a public, kernel-facing API. It resolves object names in the 
    caller's namespace and notifies the Hyde GUI to manifest or update 
    a table viewport.

    Args:
        *args: Live Python objects to include in the table (e.g., numpy arrays).
        target (str, optional): The unique handle of an existing table (e.g., 'Table0')
            to which these objects should be appended. If None, a new table
            window is created.
        title (str, optional): A user-friendly visible title for a new table. 
            If provided, this label is used in the window title bar.

    Behavior:
        - Resolves each object's top-level name in the caller's namespace by identity (`is`).
        - Searches the caller's locals, then globals.
        - Validates that each object is a supported 1D numeric array-like.
        - Signals the Hyde executor to open or update a table via the ProcessTree.

    Failure Modes:
        - Raises TypeError if a positional argument is not a 1D numeric array-like.
        - Raises ValueError if an object cannot be uniquely resolved to a top-level name.
    """
    from .execution.helpers import resolve_names
    from .execution.ipc import signal_open_table
    
    # Capture the caller's frame for name resolution
    frame = inspect.currentframe().f_back
    
    # Resolve names and perform 1D numeric validation
    names = resolve_names(args, frame, validate_1d=True)
    
    # Signal the parent executor (Watchdog) to relay the open intent to the GUI
    signal_open_table(names, target, title=title)
