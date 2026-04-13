import __main__

import numpy as np
from labscript_utils.ls_zprocess import ProcessTree


def signal_open_table(names, target, title=None):
    """
    Signal the parent executor (Watchdog) to open or update a table.

    This helper is intended to be called from a Hyde-managed kernel process,
    which is now a direct ProcessTree child of the Watchdog.
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
            },
        ])
    except Exception:
        # Silently fail if running outside a Hyde-managed kernel.
        pass


def push_table_data(names, request_id):
    """
    Fetch structured table data and push it to the parent executor.

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
    for name in names:
        obj = getattr(__main__, name, None)
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
