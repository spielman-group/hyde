import ast


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


def format_table_macro_source(macro_name, names, title=None):
    """
    Build a parameterized decorated table recreation macro definition.
    """
    parameters = ", ".join(names)
    kwargs = []
    if title:
        kwargs.append(f"title={title!r}")
    arguments = parameters
    if kwargs:
        arguments = f"{arguments}, {', '.join(kwargs)}"
    return (
        "@hyde.table\n"
        f"def {macro_name}({parameters}):\n"
        f"    hyde.table({arguments})\n"
    )


def format_cell_edit_command(var_name, index, value):
    """
    Formulates a muted mutation command for table cell editing.
    """
    return f"{var_name}[{index}] = {format_entry_literal(value)}"


def format_cell_append_command(var_name, value):
    """
    Formulates a muted append command for table row extension.

    The appended value is explicitly converted through the existing array dtype so
    incompatible entries fail in the kernel instead of silently widening dtype.
    """
    literal = format_entry_literal(value)
    return (
        f"{var_name} = np.concatenate(("
        f"{var_name}, np.array([{literal}], dtype={var_name}.dtype)"
        f"))"
    )


def format_new_array_command(var_name, value):
    """Formulates a muted command creating a new 1D array from one entered value."""
    return f"{var_name} = np.array([{format_entry_literal(value)}])"


def format_delete_indices_command(var_name, indices):
    """Formulates a muted delete command for one array column."""
    index_list = sorted(set(indices))
    return f"{var_name} = np.delete({var_name}, {index_list!r})"


def format_entry_literal(value_text):
    """
    Convert user-entered cell text into a Python literal expression.

    Bare text is treated as a string literal, while valid Python literals
    such as numbers, quoted strings, booleans, and None are preserved.
    """
    text = value_text.strip()
    if not text:
        raise ValueError("Empty cell edits are not supported.")
    try:
        value = ast.literal_eval(text)
    except Exception:
        value = text
    return repr(value)


def suggest_new_array_name(existing_names, value_text):
    """
    Suggest a deterministic kernel variable name for a newly created table column.

    String-like entries use an Igor-style `textWaveN` prefix to match user
    expectation from the reference UI. All other entries use `waveN`.
    """
    existing = set(existing_names)
    try:
        value = ast.literal_eval(value_text.strip())
    except Exception:
        value = value_text

    prefix = "textWave" if isinstance(value, str) else "wave"

    index = 0
    while f"{prefix}{index}" in existing:
        index += 1
    return f"{prefix}{index}"


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


def execute_procedures_bootstrap(project_dir, hyde_source_root, reset_namespace=False):
    import os
    import sys
    import importlib
    import __main__
    
    os.chdir(project_dir)
    project_root = os.getcwd()
    
    while project_root in sys.path:
        sys.path.remove(project_root)
    sys.path.insert(0, project_root)
    
    while hyde_source_root in sys.path:
        sys.path.remove(hyde_source_root)
    sys.path.insert(1, hyde_source_root)
    
    if '__hyde_clean_dict__' not in __main__.__dict__:
        __main__.__dict__['__hyde_clean_dict__'] = __main__.__dict__.copy()
        
    if reset_namespace:
        _hyde_clean_dict = __main__.__dict__.get('__hyde_clean_dict__')
        if _hyde_clean_dict is None:
            _hyde_clean_dict = __main__.__dict__.copy()
        __main__.__dict__.clear()
        __main__.__dict__.update(_hyde_clean_dict)
        __main__.__dict__['__hyde_clean_dict__'] = _hyde_clean_dict
        
    importlib.invalidate_caches()
    for name in list(sys.modules):
        if name == 'procedures' or name.startswith('procedures.') or name == 'hyde' or name.startswith('hyde.'):
            del sys.modules[name]
            
    import hyde
    hyde.gui_mode(True)
    import hyde.table_macros as _hyde_table_macros
    _hyde_table_macros.clear_table_macros()
    
    import procedures
    __hyde_exports = {
        name: value
        for name, value in procedures.__dict__.items()
        if not name.startswith('_')
    }
    __main__.__dict__.update(__hyde_exports)
    __main__.__hyde_procedures_exports__ = set(__hyde_exports)
    _hyde_table_macros.publish_table_macro_registry()


def format_procedures_bootstrap_code(project_dir, hyde_source_root, reset_namespace=False):
    """
    Formulates the canonical procedure environment bootstrap string by
    invoking the real execution logic.
    """
    return (
        "import sys\n"
        f"if {hyde_source_root!r} not in sys.path:\n"
        f"    sys.path.insert(0, {hyde_source_root!r})\n"
        "from hyde.features.hyde_features import execute_procedures_bootstrap\n"
        f"execute_procedures_bootstrap({project_dir!r}, {hyde_source_root!r}, reset_namespace={reset_namespace})\n"
    )


def format_remote_command(request_filepath):
    """
    Formulates a muted command to trigger remote execution for a file payload.
    """
    return f"remote({request_filepath!r})"
