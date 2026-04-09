from __future__ import annotations

import sys
import traceback

from labscript_utils.ls_zprocess import ProcessTree


def main():
    process_tree = ProcessTree.connect_to_parent()
    process_tree.zlock_client.set_process_name("hyde.execution")
    to_parent = process_tree.to_parent
    from_parent = process_tree.from_parent
    from hyde.runtime import ExecutionRuntime

    runtime = ExecutionRuntime()
    while True:
        request_id, command, payload = from_parent.get()
        try:
            if command == "execute":
                if isinstance(payload, dict):
                    response = runtime.execute(
                        payload["code"],
                        echo=payload.get("echo", True),
                        record_history=payload.get("record_history", True),
                        silent=payload.get("silent", False),
                    )
                else:
                    response = runtime.execute(payload)
            elif command == "snapshot":
                response = {"success": True, "snapshot": runtime.snapshot()}
            elif command == "complete":
                response = {
                    "success": True,
                    **runtime.complete(payload["code"], payload.get("cursor_pos")),
                    "snapshot": runtime.snapshot(),
                }
            elif command == "restore":
                runtime.restore(payload)
                response = {"success": True, "snapshot": runtime.snapshot()}
            elif command == "set_project_root":
                runtime.set_project_root(payload)
                response = {"success": True, "snapshot": runtime.snapshot()}
            elif command == "get_figure_script":
                figure_id = payload["figure_id"]
                function_name = payload["function_name"]
                response = {
                    "success": True,
                    "script_source": runtime.figure_replay_source(figure_id, function_name),
                    "snapshot": runtime.snapshot(),
                }
            elif command == "get_table_script":
                table_id = payload["table_id"]
                function_name = payload["function_name"]
                response = {
                    "success": True,
                    "script_source": runtime.table_replay_source(table_id, function_name),
                    "snapshot": runtime.snapshot(),
                }
            elif command == "quit":
                to_parent.put({"request_id": request_id, "success": True})
                break
            else:
                raise ValueError(f"Unknown Hyde execution command: {command}")
        except Exception:
            response = {
                "success": False,
                "error": traceback.format_exc(),
                "snapshot": runtime.snapshot(),
            }
        response["request_id"] = request_id
        to_parent.put(response)


if __name__ == "__main__":
    main()
