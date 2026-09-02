import sys

import numpy as np


_ProcessTree = None


def enable_process_tree_ipc():
    global _ProcessTree
    if _ProcessTree is None:
        from labscript_utils.ls_zprocess import ProcessTree

        _ProcessTree = ProcessTree


def _parent_tree():
    if _ProcessTree is None:
        return None
    tree = _ProcessTree.instance()
    if tree is None or not hasattr(tree, "to_parent"):
        return None
    return tree


def put_parent_message(message):
    tree = _parent_tree()
    if tree is not None:
        tree.to_parent.put(message)


def _executing_request_id():
    """The `msg_id` of the kernel request currently executing, if any.

    The parent-message channel carries no Jupyter header, so a payload sent
    down it cannot be matched to the request that produced it unless it says
    so itself. Returns an empty string outside a kernel, which the GUI reads
    as "cannot tell" rather than as evidence against any request.
    """
    try:
        from IPython import get_ipython

        shell = get_ipython()
        if shell is None:
            return ""
        parent = shell.get_parent()
        return str((parent or {}).get("header", {}).get("msg_id") or "")
    except Exception:
        return ""


def signal_copy_to_clipboard(representations):
    """Hand rendered figure representations to the parent GUI process.

    The clipboard belongs to the GUI process, so the kernel renders and hands
    the result over rather than writing it itself. Each representation names
    the matplotlib format it was rendered in; which MIME type that becomes is
    the GUI's business.

    This helper is intended to be called from a Hyde-managed kernel process,
    which is a direct ProcessTree child of the GUI process.
    """
    try:
        put_parent_message([
            "COPY_TO_CLIPBOARD_REQUEST",
            {
                "representations": [
                    {
                        "output_format": str(item["output_format"]),
                        "payload_base64": str(item["payload_base64"]),
                    }
                    for item in representations
                ],
                "request_msg_id": _executing_request_id(),
            },
        ])
    except Exception:
        # Silently fail if running outside a Hyde-managed kernel.
        pass


def signal_open_table(
    names,
    name=None,
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
        put_parent_message([
            "OPEN_TABLE_REQUEST",
            {
                "names": list(names),
                "name": name,
                "geometry": geometry,
                "column_widths": dict(column_widths or {}),
                "window_state": window_state,
            },
        ])
    except Exception:
        # Silently fail if running outside a Hyde-managed kernel.
        pass


def signal_append_table(names, *, name):
    try:
        put_parent_message([
            "APPEND_TABLE_REQUEST",
            {
                "names": list(names),
                "name": str(name),
            },
        ])
    except Exception:
        pass


def signal_enter_no_project_state():
    """Ask the GUI to enter its explicit no-project state."""
    try:
        put_parent_message(["ENTER_NO_PROJECT_STATE", None])
    except Exception:
        return


def signal_activate_project(path):
    """Ask the GUI to activate a project after a successful kernel-side transition."""
    try:
        put_parent_message(["ACTIVATE_PROJECT", {"path": path}])
    except Exception:
        return


def signal_quit_requested():
    """Ask the GUI to perform an orderly Hyde shutdown."""
    try:
        put_parent_message(["QUIT_REQUESTED", None])
    except Exception:
        return


def push_table_data(names, request_id):
    """
    Fetch structured table data and push it to the parent GUI process.

    Raises:
        RuntimeError: If called outside a Hyde-managed ProcessTree.
    """
    tree = _parent_tree()
    if tree is None:
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
        put_parent_message([
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
