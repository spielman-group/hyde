import unittest

from hyde.user_interface.shared.figure import FigureDisplayHelper, FigureEditSession


class TestFigureDisplayHelper(unittest.TestCase):
    def _figure_ir(self):
        return {
            "layout": {
                "subplots": [
                    {
                        "id": "subplot0",
                        "traces": [
                            {
                                "id": "trace_label_x",
                                "kind": "line",
                                "kwargs": {"label": "Amplitude"},
                                "x_source": {"kind": "name", "value": "time"},
                                "y_source": {"kind": "name", "value": "signal"},
                            },
                            {
                                "id": "trace_label_only",
                                "kind": "line",
                                "kwargs": {"label": "Offset"},
                                "y_source": {"kind": "name", "value": "baseline"},
                            },
                            {
                                "id": "trace_x_only",
                                "kind": "line",
                                "kwargs": {},
                                "x_source": {"kind": "name", "value": "time"},
                                "y_source": {"kind": "name", "value": "residual"},
                            },
                            {
                                "id": "trace_y_only",
                                "kind": "line",
                                "kwargs": {},
                                "y_source": {"kind": "name", "value": "counts"},
                            },
                        ],
                    }
                ]
            }
        }

    def test_supported_trace_records_preserve_raw_label_and_display_name(self):
        records = FigureDisplayHelper().supported_trace_records(self._figure_ir())

        self.assertEqual(
            [
                (
                    record["trace_id"],
                    record["label"],
                    record["display_name"],
                    record["y_name"],
                    record["x_name"],
                )
                for record in records
            ],
            [
                (
                    "trace_label_x",
                    "Amplitude",
                    "Amplitude: signal vs time",
                    "signal",
                    "time",
                ),
                (
                    "trace_label_only",
                    "Offset",
                    "Offset: baseline",
                    "baseline",
                    None,
                ),
                (
                    "trace_x_only",
                    None,
                    "residual vs time",
                    "residual",
                    "time",
                ),
                (
                    "trace_y_only",
                    None,
                    "counts",
                    "counts",
                    None,
                ),
            ],
        )

    def test_figure_edit_session_uses_shared_trace_display_contract(self):
        session = FigureEditSession(figure_number=1, figure_ir=self._figure_ir())

        self.assertEqual(
            [
                (record["trace_id"], record["label"], record["display_name"])
                for record in session.supported_trace_records()
            ],
            [
                ("trace_label_x", "Amplitude", "Amplitude: signal vs time"),
                ("trace_label_only", "Offset", "Offset: baseline"),
                ("trace_x_only", None, "residual vs time"),
                ("trace_y_only", None, "counts"),
            ],
        )
