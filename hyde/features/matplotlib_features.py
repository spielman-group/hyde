from __future__ import annotations

from . import Feature, Option, FeatureRegistry

LINE_COLORS = [
    Option("black", "Black"),
    Option("red", "Red"),
    Option("blue", "Blue"),
    Option("green", "Green"),
    Option("magenta", "Magenta"),
    Option("", "Default"),
]

LINE_STYLES = [
    Option("-", "Solid"),
    Option("--", "Dashed"),
    Option(":", "Dotted"),
    Option("-.", "Dash-Dot"),
    Option("None", "None"),
]

MARKER_STYLES = [
    Option("", "None"),
    Option("o", "Circle"),
    Option("s", "Square"),
    Option("^", "Triangle"),
    Option("D", "Diamond"),
    Option("+", "Plus"),
    Option("x", "Cross"),
    Option("v", "Triangle Down"),
    Option("<", "Triangle Left"),
    Option(">", "Triangle Right"),
    Option("p", "Pentagon"),
    Option("h", "Hexagon"),
]

SCALES = [
    Option("linear", "Linear"),
    Option("log", "Log"),
    Option("log2", "Log2"),
]

MARKER_FILLS = [
    Option("fill", "Fill"),
    Option("hollow", "Hollow"),
    Option("none", "None"),
]

FILL_STYLES = [
    Option("solid", "Solid"),
    Option("pattern", "Pattern"),
    Option("gradient", "Gradient"),
]

ERROR_STYLES = [
    Option("cap", "Cap"),
    Option("bar", "Bar"),
]

TREND_TYPES = [
    Option("linear", "Linear"),
    Option("polynomial", "Polynomial"),
    Option("exponential", "Exponential"),
    Option("logarithmic", "Logarithmic"),
]

ERROR_LEVELS = [
    Option("0.95", "95%"),
    Option("0.99", "99%"),
]

_WEIGHTING = [
    Option("none", "None"),
    Option("std", "Std Dev"),
    Option("inv_std", "1/Std Dev"),
]


class MatplotlibFeatures(FeatureRegistry):
    @classmethod
    def register_all(cls):
        cls.register(Feature("title", str, "", label="Title", tab="Basic Settings", group="Title"))
        cls.register(Feature("xlabel", str, "", label="X Label", tab="Basic Settings", group="Axis"))
        cls.register(Feature("ylabel", str, "", label="Y Label", tab="Basic Settings", group="Axis"))
        cls.register(Feature("xscale", str, "linear", options=SCALES, label="X Scale", tab="Basic Settings", group="Axis", command_key="xscale"))
        cls.register(Feature("yscale", str, "linear", options=SCALES, label="Y Scale", tab="Basic Settings", group="Axis", command_key="yscale"))
        cls.register(Feature("xgrid", bool, False, label="X Grid", tab="Basic Settings", group="Grid", command_key="xgrid"))
        cls.register(Feature("ygrid", bool, False, label="Y Grid", tab="Basic Settings", group="Grid", command_key="ygrid"))
        cls.register(Feature("xmin", float, None, label="X Min", tab="Basic Settings", group="Range", command_key="xmin"))
        cls.register(Feature("xmax", float, None, label="X Max", tab="Basic Settings", group="Range", command_key="xmax"))
        cls.register(Feature("ymin", float, None, label="Y Min", tab="Basic Settings", group="Range", command_key="ymin"))
        cls.register(Feature("ymax", float, None, label="Y Max", tab="Basic Settings", group="Range", command_key="ymax"))
        
        cls.register(Feature("line_color", str, "", options=LINE_COLORS, label="Color", tab="Graph", group="Line"))
        cls.register(Feature("line_style", str, "-", options=LINE_STYLES, label="Style", tab="Graph", group="Line", command_format="{}"))
        cls.register(Feature("line_width", float, 1.5, range=(0, 20), label="Width", tab="Graph", group="Line"))
        
        cls.register(Feature("marker", str, "", options=MARKER_STYLES, label="Style", tab="Graph", group="Points", command_format="{}"))
        cls.register(Feature("markersize", float, 6.0, range=(0, 100), label="Size", tab="Graph", group="Points"))
        cls.register(Feature("marker_fill", str, "fill", options=MARKER_FILLS, label="Fill", tab="Graph", group="Points"))
        
        cls.register(Feature("visible", bool, True, label="Visible", tab="Graph", group="Trace"))
        cls.register(Feature("label", str, "", label="Label", tab="Graph", group="Trace"))
        cls.register(Feature("gaps", bool, False, label="Gaps", tab="Graph", group="Trace"))
        
        cls.register(Feature("fill_enabled", bool, False, tab="Graph", group="Fill"))
        cls.register(Feature("fill_style", str, "solid", options=FILL_STYLES, tab="Graph", group="Fill"))
        cls.register(Feature("fill_color", str, "", tab="Graph", group="Fill"))
        cls.register(Feature("fill_opacity", int, 50, range=(0, 100), tab="Graph", group="Fill"))
        
        cls.register(Feature("error_bars", bool, False, tab="Graph", group="Error"))
        cls.register(Feature("error_style", str, "cap", options=ERROR_STYLES, tab="Graph", group="Error"))
        cls.register(Feature("error_color", str, "", tab="Graph", group="Error"))
        
        cls.register(Feature("show_trendline", bool, False, tab="Analysis", group="Trendline"))
        cls.register(Feature("trend_type", str, "linear", options=TREND_TYPES, tab="Analysis", group="Trendline"))
        cls.register(Feature("polynomial_order", int, 2, range=(2, 10), tab="Analysis", group="Trendline"))
        cls.register(Feature("show_equation", bool, False, tab="Analysis", group="Trendline"))
        cls.register(Feature("show_r_squared", bool, False, tab="Analysis", group="Trendline"))
        
        cls.register(Feature("show_mean", bool, False, tab="Analysis", group="Statistics"))
        cls.register(Feature("show_std_dev", bool, False, tab="Analysis", group="Statistics"))
        cls.register(Feature("show_min_max", bool, False, tab="Analysis", group="Statistics"))
        cls.register(Feature("show_sum", bool, False, tab="Analysis", group="Statistics"))
        cls.register(Feature("show_n", bool, False, tab="Analysis", group="Statistics"))
        
        cls.register(Feature("show_confidence", bool, False, tab="Analysis", group="Error Analysis"))
        cls.register(Feature("show_prediction", bool, False, tab="Analysis", group="Error Analysis"))
        cls.register(Feature("error_level", str, "0.95", options=ERROR_LEVELS, tab="Analysis", group="Error Analysis"))
        
        cls.register(Feature("sync_with", str, "None", tab="Advanced", group="Sync"))
        cls.register(Feature("sync_axis", str, "X-axis", tab="Advanced", group="Sync"))
        cls.register(Feature("link_x_axis", bool, False, tab="Advanced", group="Linked"))
        cls.register(Feature("link_y_axis", bool, False, tab="Advanced", group="Linked"))
        cls.register(Feature("events_enabled", bool, False, tab="Advanced", group="Events"))


def register_matplotlib_features():
    MatplotlibFeatures.register_all()