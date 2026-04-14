"""GUI-owned project session and history persistence helpers."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import tomllib
from qtutils.qt import QtCore


def _encode_qbytearray(value):
    return bytes(value.toBase64()).decode("ascii")


def _decode_qbytearray(value):
    return QtCore.QByteArray.fromBase64(value.encode("ascii"))


def _rect_to_list(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def _list_to_rect(values):
    return QtCore.QRect(*values)


def _write_toml(path: Path, session):
    lines = [
        f"format_version = {int(session['format_version'])}",
        f"active_table_handle = {session['active_table_handle']!r}",
        f"table_counter = {int(session['table_counter'])}",
        "",
    ]
    lines.extend(
        [
            "[main_window]",
            f'geometry = "{session["main_window"]["geometry"]}"',
            f'state = "{session["main_window"]["state"]}"',
            "",
            "[data_browser]",
            f"waves = {str(session['data_browser']['waves']).lower()}",
            f"variables = {str(session['data_browser']['variables']).lower()}",
            f"strings = {str(session['data_browser']['strings']).lower()}",
            f"info = {str(session['data_browser']['info']).lower()}",
            "",
            "[tool_windows]",
        ]
    )
    for key in ("command", "logging", "procedures", "data_browser"):
        info = session["tool_windows"][key]
        lines.extend(
            [
                f"{key}_visible = {str(info['visible']).lower()}",
                f"{key}_geometry = {info['geometry']!r}",
            ]
        )
    lines.append("")
    for table in session["tables"]:
        lines.extend(
            [
                "[[tables]]",
                f'handle = "{table["handle"]}"',
                f'title = "{table["title"]}"',
                f"names = {table['names']!r}",
                f"hidden = {str(table['hidden']).lower()}",
                f"geometry = {table['geometry']!r}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _session_path(project_dir):
    return Path(project_dir) / "session.toml"


def _history_path(project_dir):
    return Path(project_dir) / "terminal" / "history.py"


def _subwindow_state(subwindow):
    return {
        "visible": bool(subwindow.isVisible()),
        "geometry": _rect_to_list(subwindow.geometry()),
    }


def capture_session(app):
    tables = []
    for handle, table in sorted(app.tables.items()):
        subwindow = table.parentWidget()
        tables.append(
            {
                "handle": handle,
                "title": subwindow.windowTitle(),
                "names": list(table.names),
                "hidden": not subwindow.isVisible(),
                "geometry": _rect_to_list(subwindow.geometry()),
            }
        )

    return {
        "format_version": 1,
        "main_window": {
            "geometry": _encode_qbytearray(app.ui.saveGeometry()),
            "state": _encode_qbytearray(app.ui.saveState()),
        },
        "tool_windows": {
            "command": _subwindow_state(app.command_subwindow),
            "logging": _subwindow_state(app.logging_subwindow),
            "procedures": _subwindow_state(app.procedures_subwindow),
            "data_browser": _subwindow_state(app.data_browser_subwindow),
        },
        "data_browser": {
            "waves": bool(app.data_browser.ui.wavesCheckBox.isChecked()),
            "variables": bool(app.data_browser.ui.variablesCheckBox.isChecked()),
            "strings": bool(app.data_browser.ui.stringsCheckBox.isChecked()),
            "info": bool(app.data_browser.ui.infoCheckBox.isChecked()),
        },
        "active_table_handle": app.active_table_handle,
        "table_counter": app.table_counter,
        "tables": tables,
    }


def write_session(app, project_dir):
    path = _session_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_toml(path, capture_session(app))


def read_session(project_dir):
    path = _session_path(project_dir)
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def try_read_session(project_dir):
    try:
        return read_session(project_dir), None
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        return {}, str(exc)


def write_history(command_window, project_dir):
    history_path = _history_path(project_dir)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history = command_window.history_entries() if command_window is not None else []
    with history_path.open("w", encoding="utf-8") as handle:
        handle.write("# Hyde terminal history starts here.\n")
        handle.write("history = ")
        handle.write(repr(history))
        handle.write("\n")


def read_history(project_dir):
    history_path = _history_path(project_dir)
    if not history_path.exists():
        return []
    text = history_path.read_text(encoding="utf-8")
    module = ast.parse(text or "")
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "history":
                    return list(ast.literal_eval(node.value))
    return []


def try_read_history(project_dir):
    try:
        return read_history(project_dir), None
    except (OSError, SyntaxError, ValueError) as exc:
        return [], str(exc)


def restore_main_window(app, session):
    main = session.get("main_window", {})
    geometry = main.get("geometry")
    state = main.get("state")
    if geometry:
        app.ui.restoreGeometry(_decode_qbytearray(geometry))
    if state:
        app.ui.restoreState(_decode_qbytearray(state))


def restore_tool_windows(app, session):
    tool_windows = session.get("tool_windows", {})
    mapping = {
        "command": app.command_subwindow,
        "logging": app.logging_subwindow,
        "procedures": app.procedures_subwindow,
        "data_browser": app.data_browser_subwindow,
    }
    for key, subwindow in mapping.items():
        geometry = tool_windows.get(f"{key}_geometry")
        if geometry:
            subwindow.setGeometry(_list_to_rect(geometry))
        subwindow.setVisible(bool(tool_windows.get(f"{key}_visible", False)))


def restore_data_browser_state(app, session):
    info = session.get("data_browser", {})
    app.data_browser.ui.wavesCheckBox.setChecked(bool(info.get("waves", True)))
    app.data_browser.ui.variablesCheckBox.setChecked(bool(info.get("variables", True)))
    app.data_browser.ui.stringsCheckBox.setChecked(bool(info.get("strings", True)))
    app.data_browser.ui.infoCheckBox.setChecked(bool(info.get("info", True)))
    app.data_browser._on_filter_changed()
    app.data_browser._toggle_info_pane(app.data_browser.ui.infoCheckBox.isChecked())


def restore_tables(app, session):
    saved_counter = int(session.get("table_counter", 0))
    for table_state in session.get("tables", []):
        handle = table_state["handle"]
        app.open_table(table_state.get("names", []), target=handle, visible_title=table_state.get("title"))
        table = app.tables.get(handle)
        if table is None:
            continue
        subwindow = table.parentWidget()
        geometry = table_state.get("geometry")
        if geometry:
            subwindow.setGeometry(_list_to_rect(geometry))
        subwindow.setVisible(not bool(table_state.get("hidden", False)))
    app.table_counter = saved_counter
    app.active_table_handle = session.get("active_table_handle")


def clear_tables(app):
    for table in list(app.tables.values()):
        subwindow = table.parentWidget()
        if subwindow is not None:
            subwindow.close()
    app.tables.clear()
    app.active_table_handle = None
    app.table_counter = 0
