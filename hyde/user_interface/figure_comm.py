from __future__ import annotations

import logging


COMM_TARGET = "hyde_figure"
LOGGER = logging.getLogger("hyde")


def register_auxiliary_figure_comm_sink(kernel_client, label):
    comm_manager = getattr(kernel_client, "comm_manager", None)
    if comm_manager is None:
        return False

    def _on_open(comm, msg):
        payload = msg.get("content", {}).get("data", {})
        LOGGER.debug(
            "Auxiliary kernel client %s absorbed figure comm %s for figure %s.",
            label,
            getattr(comm, "comm_id", None),
            payload.get("figure_number"),
        )
        comm.on_msg(lambda _message: None)
        comm.on_close(
            lambda _message, current_comm=comm: LOGGER.debug(
                "Auxiliary kernel client %s observed figure comm %s close.",
                label,
                getattr(current_comm, "comm_id", None),
            )
        )

    comm_manager.register_target(COMM_TARGET, _on_open)
    return True
