from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class HydeInbox:
    shots: list[dict] = field(default_factory=list)

    def add_shot(self, filepath):
        path = str(Path(filepath))
        self.shots.append({"filepath": path})
        return path

    def to_dataframe(self):
        return pd.DataFrame(self.shots, columns=["filepath"])


def handle_lyse_request(request_data, inbox: HydeInbox, on_filepath):
    if request_data == "hello":
        return "hello"
    if request_data == "get dataframe":
        return inbox.to_dataframe()
    if (
        isinstance(request_data, tuple)
        and len(request_data) == 3
        and request_data[0] == "get dataframe"
    ):
        _, n_sequences, filter_kwargs = request_data
        dataframe = inbox.to_dataframe()
        if n_sequences is not None:
            dataframe = dataframe.tail(n_sequences)
        if filter_kwargs:
            dataframe = dataframe.filter(**filter_kwargs)
        return dataframe
    if isinstance(request_data, dict) and "filepath" in request_data:
        filepath = inbox.add_shot(request_data["filepath"])
        on_filepath(filepath)
        return "added successfully"
    if isinstance(request_data, str):
        filepath = inbox.add_shot(request_data)
        on_filepath(filepath)
        return "Experiment added successfully\n"
    return (
        "error: operation not supported. Recognised requests are:\n "
        "'get dataframe'\n 'hello'\n {'filepath': <some_h5_filepath>}"
    )

