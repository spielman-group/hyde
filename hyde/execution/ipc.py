import sys

import numpy as np
from labscript_utils.ls_zprocess import ProcessTree


def signal_open_table(
    names,
    target,
    title=None,
    geometry=None,
    column_widths=None,
    window_state=None,
):
    """
    Signal the parent GUI process to open or update a table.

    This helper is intended to be called from a Hyde-managed kernel process,
    which is a direct ProcessTree child of the GUI process.
    """
    try:
        tree = ProcessTree.instance()
        if tree is None or not hasattr(tree, "to_parent"):
            return

        tree.to_parent.put([
            "OPEN_TABLE_REQUEST",
            {
                "names": list(names),
                "target": target,
                "title": title,
                "geometry": geometry,
                "column_widths": dict(column_widths or {}),
                "window_state": window_state,
            },
        ])
    except Exception:
        # Silently fail if running outside a Hyde-managed kernel.
        pass


def signal_enter_no_project_state():
    """Ask the GUI to enter its explicit no-project state."""
    try:
        tree = ProcessTree.instance()
        if tree is None or not hasattr(tree, "to_parent"):
            return
        tree.to_parent.put(["ENTER_NO_PROJECT_STATE", None])
    except Exception:
        return


def signal_activate_project(path):
    """Ask the GUI to activate a project after a successful kernel-side transition."""
    try:
        tree = ProcessTree.instance()
        if tree is None or not hasattr(tree, "to_parent"):
            return
        tree.to_parent.put(["ACTIVATE_PROJECT", {"path": path}])
    except Exception:
        return


def signal_quit_requested():
    """Ask the GUI to perform an orderly Hyde shutdown."""
    try:
        tree = ProcessTree.instance()
        if tree is None or not hasattr(tree, "to_parent"):
            return
        tree.to_parent.put(["QUIT_REQUESTED", None])
    except Exception:
        return


def push_table_data(names, request_id):
    """
    Fetch structured table data and push it to the parent GUI process.

    Raises:
        RuntimeError: If called outside a Hyde-managed ProcessTree.
    """
    tree = ProcessTree.instance()
    if tree is None or not hasattr(tree, "to_parent"):
        raise RuntimeError(
            "Hyde data push failed: No managed parent process available. "
            "Are you running in a Hyde-managed IPython session?"
        )

    data = {}
    main_module = sys.modules["__main__"]
    for name in names:
        obj = getattr(main_module, name, None)
        if obj is None:
            data[name] = []
            continue

        try:
            data[name] = np.asanyarray(obj).tolist()
        except Exception:
            data[name] = []

    tree.to_parent.put([
        "TABLE_DATA_RESPONSE",
        {
            "data": data,
            "request_id": request_id,
        },
    ])


def publish_project_state_result(operation, path, success=True, errors=None, object_count=0, mode="save"):
    """Publish kernel-side project save/load completion back to the GUI."""
    try:
        tree = ProcessTree.instance()
        if tree is None or not hasattr(tree, "to_parent"):
            return
        tree.to_parent.put([
            "PROJECT_STATE_RESULT",
            {
                "operation": operation,
                "path": path,
                "success": bool(success),
                "errors": list(errors or []),
                "object_count": int(object_count),
                "mode": mode,
            },
        ])
    except Exception:
        pass
