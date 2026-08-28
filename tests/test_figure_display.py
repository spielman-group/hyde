import unittest

from hyde.features.matplotlib_figure_records import supported_trace_records
from hyde.features.matplotlib_ir import FigureIR


class TestFigureDisplayRecords(unittest.TestCase):
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
                            {
                                "id": "trace_label_fallback",
                                "kind": "line",
                                "kwargs": {"label": "Manual"},
                                "y_source": {"kind": "literal", "value": [1, 2]},
                            },
                            {
                                "id": "trace_id_fallback",
                                "kind": "line",
                                "kwargs": {},
                                "y_source": {"kind": "literal", "value": [3, 4]},
                            },
                        ],
                    }
                ]
            }
        }

    def test_supported_trace_records_preserve_raw_label_and_display_name(self):
        records = supported_trace_records(self._figure_ir())

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
                (
                    "trace_label_fallback",
                    "Manual",
                    "Manual",
                    None,
                    None,
                ),
                (
                    "trace_id_fallback",
                    None,
                    "trace_id_fallback",
                    None,
                    None,
                ),
            ],
        )

    def test_figure_ir_uses_shared_trace_display_contract(self):
        figure_ir = FigureIR(figure_state=self._figure_ir())

        self.assertEqual(
            [
                (record["trace_id"], record["label"], record["display_name"])
                for record in figure_ir.supported_trace_records()
            ],
            [
                ("trace_label_x", "Amplitude", "Amplitude: signal vs time"),
                ("trace_label_only", "Offset", "Offset: baseline"),
                ("trace_x_only", None, "residual vs time"),
                ("trace_y_only", None, "counts"),
                ("trace_label_fallback", "Manual", "Manual"),
                ("trace_id_fallback", None, "trace_id_fallback"),
            ],
        )

    def test_figure_ir_supports_direct_editing_and_lowering_on_its_own(self):
        figure_ir = FigureIR(figure_state=self._figure_ir())

        updated_ir = figure_ir.set_axis_label("x", "Time (s)")

        self.assertEqual(updated_ir.axis_label("x"), "Time (s)")
        self.assertIn("ax.set_xlabel('Time (s)')", updated_ir.preview_source())
