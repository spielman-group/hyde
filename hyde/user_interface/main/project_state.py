"""GUI-owned project session and history persistence helpers."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import tomllib
import tomli_w
from qtutils.qt import QtCore, QtWidgets


def _encode_qbytearray(value):
    return bytes(value.toBase64()).decode("ascii")


def _decode_qbytearray(value):
    return QtCore.QByteArray.fromBase64(value.encode("ascii"))


def _write_toml(path: Path, session):
    with path.open("wb") as handle:
        tomli_w.dump(session, handle)


def _session_path(project_dir):
    return Path(project_dir) / "session.toml"


def _session_source_path(project_dir):
    return Path(project_dir) / "session.py"


def _history_path(project_dir):
    return Path(project_dir) / "terminal" / "history.py"


def _merge_session_data(session, plugin_data):
    for key, value in plugin_data.items():
        if isinstance(value, dict) and isinstance(session.get(key), dict):
            _merge_session_data(session[key], value)
        else:
            session[key] = value


def _plugin_items(app):
    plugin_manager = getattr(app, "plugin_manager", None)
    return getattr(plugin_manager, "plugins", {}).items()

def capture_session(app):
    logger = logging.getLogger("hyde")
    mdi_area = getattr(app.ui, "mdiArea", None)
    session = {
        "format_version": 1,
        "main_window": {
            "geometry": _encode_qbytearray(app.ui.saveGeometry()),
            "state": _encode_qbytearray(app.ui.saveState()),
        },
    }
    for plugin_name, plugin in _plugin_items(app):
        try:
            plugin_data = plugin.get_session_toml_data()
        except Exception:
            logger.exception(
                "Plugin session TOML capture failed for '%s'.",
                plugin_name,
            )
            continue
        if plugin_data:
            _merge_session_data(session, plugin_data)
    if mdi_area is not None:
        session["main_window"]["mdi_window_order"] = capture_mdi_window_order(
            mdi_area
        )
    return session

def capture_session_source(app):
    logger = logging.getLogger("hyde")
    blocks = []
    for plugin_name, plugin in _plugin_items(app):
        try:
            source = plugin.get_session_restore_source()
        except Exception:
            logger.exception(
                "Plugin session Python capture failed for '%s'.",
                plugin_name,
            )
            continue
        source = str(source or "").strip()
        if source:
            blocks.append(source)
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def capture_session_restore_warnings(app):
    logger = logging.getLogger("hyde")
    warnings = []
    for plugin_name, plugin in _plugin_items(app):
        warning_getter = getattr(plugin, "get_session_restore_warnings", None)
        if warning_getter is None:
            continue
        try:
            plugin_warnings = warning_getter()
        except Exception:
            logger.exception(
                "Plugin session warning capture failed for '%s'.",
                plugin_name,
            )
            continue
        for warning in plugin_warnings or ():
            text = str(warning or "").strip()
            if text:
                warnings.append(text)
    return warnings


def write_session(app, project_dir):
    path = _session_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    session = capture_session(app)
    _write_toml(path, session)
    session_source_path = _session_source_path(project_dir)
    with session_source_path.open("w", encoding="utf-8") as handle:
        handle.write(capture_session_source(app))
    return capture_session_restore_warnings(app)


def read_session(project_dir):
    path = _session_path(project_dir)
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def read_session_source(project_dir):
    path = _session_source_path(project_dir)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def try_read_session(project_dir):
    try:
        return read_session(project_dir), None
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        return {}, str(exc)


def try_read_session_source(project_dir):
    try:
        return read_session_source(project_dir), None
    except OSError as exc:
        return "", str(exc)


def write_history(app, project_dir):
    history_path = _history_path(project_dir)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_manager = getattr(app, "plugin_manager", None)
    services = getattr(plugin_manager, "services", {})
    python_terminal_service = services.get("visible_terminal_service")
    history = (
        [] if python_terminal_service is None else python_terminal_service.history_entries()
    )
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


def capture_mdi_window_order(mdi_area):
    return [
        name
        for name in (
            str(subwindow.objectName() or "").strip()
            for subwindow in mdi_area.subWindowList(QtWidgets.QMdiArea.StackingOrder)
        )
        if name
    ]


def apply_mdi_window_order(mdi_area, window_order):
    if not isinstance(window_order, (list, tuple)):
        return
    subwindows = {
        str(subwindow.objectName() or "").strip(): subwindow
        for subwindow in mdi_area.subWindowList(QtWidgets.QMdiArea.StackingOrder)
        if str(subwindow.objectName() or "").strip()
    }
    for name in window_order:
        subwindow = subwindows.get(str(name).strip())
        if subwindow is None or subwindow.isHidden():
            continue
        subwindow.raise_()

