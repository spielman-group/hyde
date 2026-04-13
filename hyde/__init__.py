"""
Hyde: A modern, Pythonic data analysis and plotting environment.
"""

__version__ = "0.1.0.dev0"

import inspect
import __main__


def table(*args, target=None):
    """
    Open or append to a Hyde table window displaying 1D numeric data.

    This is a public, kernel-facing API. When called, it resolves the names of the
    provided objects in the caller's namespace and notifies the Hyde GUI to
    manifest or update a table viewport.

    Args:
        *args: Live Python objects to include in the table (e.g., numpy arrays).
        target (str, optional): The unique handle of an existing table (e.g., 'Table0')
            to which these objects should be appended. If None, a new table
            window is created.

    Behavior:
        - Resolves each object's top-level name in the caller's namespace by identity (`is`).
        - Searches the caller's locals, then globals.
        - If exactly one name matches the object's identity, that name is used.
        - Dispatches an 'open_table' intent to the GUI over the 'hyde_api' comm channel.

    Name Resolution Failure Modes:
        - Raises ValueError if an object cannot be uniquely resolved to a top-level name
          (e.g., if it is an anonymous result or has multiple aliases).
        - Raises TypeError if a positional argument is not a supported 1D numeric array-like.
    """
    names = []
    
    # Get the caller's frame to perform identity-based name resolution
    frame = inspect.currentframe().f_back
    locals_dict = frame.f_locals
    globals_dict = frame.f_globals
    
    for obj in args:
        found_names = []
        
        # Search locals then globals by identity
        # We priority locals if the same identity exists in both
        for d in [locals_dict, globals_dict]:
            for name, value in d.items():
                if value is obj:
                    if not name.startswith('_'): # Skip private names
                        found_names.append(name)
            if found_names:
                break
        
        # Ensure a unique name is found
        unique_names = list(set(found_names))
        if len(unique_names) == 1:
            names.append(unique_names[0])
        elif len(unique_names) > 1:
            raise ValueError(
                f"Ambiguous name for object: found multiple matches {unique_names}."
            )
        else:
            raise ValueError(
                "Could not resolve the provided object to a unique top-level name. "
                "The table feature requires named kernel variables."
            )

    # Dispatch intent to GUI via narrow comm
    _send_ui_intent('open_table', names=names, target=target)


def _send_ui_intent(action, **kwargs):
    """Internal helper to send a one-way intent message to the Hyde GUI."""
    try:
        from ipykernel.comm import Comm
        comm = Comm(target_name='hyde_api')
        comm.send({'action': action, **kwargs})
        comm.close()
    except Exception:
        # If running outside a Hyde-managed kernel, intents are ignored.
        pass


def _get_table_data(names):
    """
    Internal helper to fetch 1D numeric array data for table display.
    This is the concrete data fetch path used by the TableWidget refresh logic.
    """
    import numpy as np
    
    result = {}
    for name in names:
        obj = getattr(__main__, name, None)
        if obj is None:
            result[name] = []
            continue
            
        try:
            if hasattr(obj, 'tolist'):
                # Handle numpy arrays, pandas series etc.
                arr = np.asanyarray(obj)
                if arr.ndim > 1:
                    arr = arr.flatten() # Support 1D view of multidimensional for now
                result[name] = arr.tolist()
            elif isinstance(obj, (list, tuple)):
                result[name] = list(obj)
            else:
                result[name] = [obj]
        except Exception:
            result[name] = []
            
    return result


def _register_hyde_comm_target():
    """Register the hyde_api comm target for data-fetch requests."""
    try:
        from spyder_kernels.comms.commbase import CommBase
        from IPython import get_ipython

        class HydeBackendComm(CommBase):
            def __init__(self, kernel):
                super().__init__()
                self.kernel = kernel

            def get_table_data(self, names):
                """Remote-callable method to fetch array data."""
                return _get_table_data(names)

        shell = get_ipython()
        if shell is None:
            return

        backend_comm = HydeBackendComm(shell.kernel)
        shell.kernel.comm_manager.register_target(
            'hyde_api', 
            lambda comm, msg: backend_comm._register_comm(comm)
        )
    except Exception:
        pass

# Attempt registration on import
_register_hyde_comm_target()
