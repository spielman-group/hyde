"""
Hyde: A modern, Pythonic data analysis and plotting environment for the labscript-suite.
"""

__version__ = "0.1.0.dev0"

import inspect

from ._table_macros import publish_table_macro_registry, register_table_macro


def table(*args, target=None, title=None):
    """
    Open or append to a Hyde table window, or register a recreation macro.

    This public Hyde API supports two forms:

    1. Direct call form:
       ``hyde.table(a, b, target=..., title=...)``
       Opens a new table or appends to an existing one.
    2. Decorator form:
       ``@hyde.table``
       Registers a parameterized table recreation macro.

    Args:
        *args: Live Python objects to include in the table, or one function in
            decorator form.
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
        - Registers decorated functions as table recreation macros whose
          parameters name the live kernel objects needed to recreate the table.

    Failure Modes:
        - Raises TypeError if a positional argument is not a 1D numeric array-like.
        - Raises TypeError if decorator form uses unsupported non-positional parameters.
        - Raises ValueError if an object cannot be uniquely resolved to a top-level name.
    """
    if not args and target is None and title is None:
        def decorator(func):
            register_table_macro(func)
            publish_table_macro_registry()
            return func

        return decorator

    if (
        len(args) == 1
        and callable(args[0])
        and target is None
        and title is None
    ):
        register_table_macro(args[0])
        publish_table_macro_registry()
        return args[0]

    from .execution.helpers import resolve_names
    from .execution.ipc import signal_open_table
    
    # Capture the caller's frame for name resolution
    frame = inspect.currentframe().f_back
    
    names = resolve_names(args, frame, validate_1d=True)
    
    # Signal the parent executor (Watchdog) to relay the open intent to the GUI
    signal_open_table(names, target, title=title)
