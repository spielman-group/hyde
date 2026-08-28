def trace_source_name(source):
    if not isinstance(source, dict):
        return None
    if source.get("kind") != "name":
        return None
    value = str(source.get("value") or "").strip()
    return value or None


def trace_label(trace):
    label = dict(trace or {}).get("kwargs", {}).get("label")
    if label in (None, "", "_nolegend_"):
        return None
    return str(label)


def trace_display_name(trace):
    trace = dict(trace or {})
    label = trace_label(trace)
    x_name = trace_source_name(trace.get("x_source"))
    y_name = trace_source_name(trace.get("y_source"))
    if label and y_name and x_name:
        return f"{label}: {y_name} vs {x_name}"
    if label and y_name:
        return f"{label}: {y_name}"
    if y_name and x_name:
        return f"{y_name} vs {x_name}"
    if y_name:
        return y_name
    if label:
        return label
    return str(trace.get("id", "trace"))


def supported_trace_records(figure_ir):
    figure_ir = dict(figure_ir or {})
    subplots = figure_ir.get("layout", {}).get("subplots", [])
    if not subplots:
        return ()
    subplot = subplots[0]
    records = []
    for trace in subplot.get("traces", []):
        if trace.get("kind") != "line":
            continue
        records.append(
            {
                "subplot_id": str(subplot.get("id")),
                "trace_id": str(trace.get("id")),
                "label": trace_label(trace),
                "display_name": trace_display_name(trace),
                "x_name": trace_source_name(trace.get("x_source")),
                "y_name": trace_source_name(trace.get("y_source")),
                "trace": dict(trace),
            }
        )
    return tuple(records)
