import numpy as np


def resolve_names(args, frame, validate_1d=True):
    """
    Resolves top-level name in the provided frame's namespace by identity (`is`).
    
    Args:
        args: Tuple of live Python objects.
        frame: The execution frame to search (locals then globals).
        validate_1d: If True, validates each object is a 1D array-like.
        
    Returns:
        list: Resolved names for each object.
        
    Raises:
        ValueError: If a unique name cannot be resolved for an object.
        TypeError: If an object fails 1D validation.
    """
    names = []
    locals_dict = frame.f_locals
    globals_dict = frame.f_globals
    
    for obj in args:
        found_names = []
        
        # Search locals then globals by identity
        for d in [locals_dict, globals_dict]:
            for name, value in d.items():
                if value is obj:
                    if not name.startswith('_'):
                        found_names.append(name)
            if found_names:
                break
        
        unique_names = list(set(found_names))
        if len(unique_names) == 1:
            name = unique_names[0]
            if validate_1d:
                validate_1d_arraylike(obj, name)
            names.append(name)
        elif len(unique_names) > 1:
            raise ValueError(
                f"Ambiguous name for object: found multiple matches {unique_names}."
            )
        else:
            raise ValueError(
                "Could not resolve the provided object to a unique top-level name. "
                "Hyde public helpers require named kernel variables."
            )
            
    return names


def validate_1d_arraylike(obj, name):
    """
    Verifies object is a 1D array-like.

    Raises:
        TypeError: If validation fails.
    """
    try:
        arr = np.asanyarray(obj)
        if arr.ndim != 1:
            raise TypeError(f"Object '{name}' must be 1D (has dimension {arr.ndim}).")
    except Exception as e:
        if isinstance(e, TypeError):
            raise
        raise TypeError(f"Object '{name}' is not an array-like 1D type.")
