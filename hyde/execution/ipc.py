import logging
import sys

import numpy as np


LOGGER = logging.getLogger("hyde")

_ProcessTree = None


def enable_process_tree_ipc():
    global _ProcessTree
    if _ProcessTree is None:
        from labscript_utils.ls_zprocess import ProcessTree

        _ProcessTree = ProcessTree


def _parent_tree():
    """The process tree holding this process's channel to its parent, if any.

    A `ProcessTree` always has a `to_parent` attribute; it stays None until the
    process connects to a parent, which only a Hyde-managed kernel child does.
    So the question "is there a GUI to talk to" is answered by the channel
    itself, not by whether the attribute exists. Asking for the tree at all can
    fail in a process that never connected, because building the top-level one
    reads labconfig; a kernel child cannot reach that path, since its instance
    was built by `connect_to_parent()`. Every one of those means the same thing
    here: no parent channel.
    """
    if _ProcessTree is None:
        return None
    try:
        tree = _ProcessTree.instance()
    except Exception:
        return None
    if getattr(tree, "to_parent", None) is None:
        return None
    return tree


def _report_undelivered_signal(signal):
    """Say that `signal` did not reach the GUI process.

    Call from an exception handler, so the traceback travels with it.

    Silent when there is no parent channel: `hyde` is importable in a plain
    IPython, a script, or a test, where there is no GUI to tell and nothing has
    gone wrong. A channel that is there and would not take the message is a
    fault, and the kernel names the signal it lost -- otherwise the GUI simply
    never hears it and neither process says why.

    The kernel configures `hyde-kernel` rather than `hyde`, so this reaches the
    user as the kernel's stderr, which the GUI redirects into its logging
    window. That is why it is worth an error rather than a debug line.
    """
    if _parent_tree() is None:
        return
    LOGGER.exception(
        "Hyde could not deliver the %s signal to the GUI process.",
        signal,
    )


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
        _report_undelivered_signal("OPEN_TABLE_REQUEST")


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
        _report_undelivered_signal("APPEND_TABLE_REQUEST")


def signal_enter_no_project_state():
    """Ask the GUI to enter its explicit no-project state."""
    try:
        put_parent_message(["ENTER_NO_PROJECT_STATE", None])
    except Exception:
        _report_undelivered_signal("ENTER_NO_PROJECT_STATE")


def signal_activate_project(path):
    """Ask the GUI to activate a project after a successful kernel-side transition."""
    try:
        put_parent_message(["ACTIVATE_PROJECT", {"path": path}])
    except Exception:
        _report_undelivered_signal("ACTIVATE_PROJECT")


def signal_quit_requested():
    """Ask the GUI to perform an orderly Hyde shutdown."""
    try:
        put_parent_message(["QUIT_REQUESTED", None])
    except Exception:
        _report_undelivered_signal("QUIT_REQUESTED")


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
        _report_undelivered_signal("PROJECT_STATE_RESULT")
