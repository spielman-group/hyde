"""GUI-owned project session and history persistence helpers."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import tomllib
import tomli_w
from qtutils.qt import QtCore


def _encode_qbytearray(value):
    return bytes(value.toBase64()).decode("ascii")


def _decode_qbytearray(value):
    return QtCore.QByteArray.fromBase64(value.encode("ascii"))


def _write_toml(path: Path, session):
    with path.open("wb") as handle:
        tomli_w.dump(session, handle)


def _session_path(project_dir):
    return Path(project_dir) / "session.toml"


def _history_path(project_dir):
    return Path(project_dir) / "terminal" / "history.py"


def _merge_session_data(session, plugin_data):
    for key, value in plugin_data.items():
        if isinstance(value, dict) and isinstance(session.get(key), dict):
            _merge_session_data(session[key], value)
        else:
            session[key] = value


def _capture_plugin_session(app, session):
    plugin_manager = getattr(app, "plugin_manager", None)
    plugins = getattr(plugin_manager, "plugins", {})
    logger = logging.getLogger("hyde")

    for plugin_name, plugin in plugins.items():
        try:
            plugin_data = plugin.get_save_data()
        except Exception:
            logger.exception(
                "Plugin save-data capture failed for '%s'.", plugin_name
            )
            continue
        if not plugin_data:
            continue
        _merge_session_data(session, plugin_data)


def capture_session(app):
    session = {
        "format_version": 1,
        "main_window": {
            "geometry": _encode_qbytearray(app.ui.saveGeometry()),
            "state": _encode_qbytearray(app.ui.saveState()),
        },
    }
    _capture_plugin_session(app, session)
    return session


def write_session(app, project_dir):
    path = _session_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    session = capture_session(app)
    _write_toml(path, session)


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


def write_history(app, project_dir):
    history_path = _history_path(project_dir)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_manager = getattr(app, "plugin_manager", None)
    services = getattr(plugin_manager, "services", {})
    command_window_service = services.get("visible_command_service")
    history = (
        [] if command_window_service is None else command_window_service.history_entries()
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
