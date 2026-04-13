def format_table_command(names, target=None, title=None):
    """
    Formulates a hyde.table(...) command string.
    
    Args:
        names: List of variable names.
        target: Optional internal handle of the target table.
        title: Optional visible window title for a new table.
        
    Returns:
        str: The Python command string.
    """
    args_str = ", ".join(names)
    kwargs = []
    if target:
        kwargs.append(f"target={target!r}")
    if title:
        kwargs.append(f"title={title!r}")

    if kwargs:
        return f"hyde.table({args_str}, {', '.join(kwargs)})"
    return f"hyde.table({args_str})"


def format_cell_edit_command(var_name, index, value):
    """
    Formulates a muted mutation command for table cell editing.
    """
    return f"{var_name}[{index}] = {value}"


def is_eligible_for_table(metadata):
    """
    Determines if a variable (from Data Browser metadata) is eligible for table display.
    Scoped to 1D numeric waves initially.
    """
    python_type = metadata.get("python_type", "").lower()
    numpy_type = metadata.get("numpy_type", "")
    ndim = metadata.get("ndim", 1)
    kind = metadata.get("numpy_kind", "f") # Default to float if kind metadata is missing

    # Scoped to 1D numeric (numpy ndarray, pandas Series, etc.)
    is_array = python_type in ("ndarray", "series") or numpy_type == "Array"
    is_numeric = kind in 'biuf'
    
    return is_array and is_numeric and ndim == 1
