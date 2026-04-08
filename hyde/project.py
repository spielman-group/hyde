from __future__ import annotations

import ast
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from labscript_profile.toml_config import dump_toml_file, load_toml_file

from .annotations import ScriptEntry, discover_script_entries
from .data import TrackedArray


PACKAGE_DIRS = [
    "terminal",
    "scripts",
    "procedures",
    "data",
    "figures",
    "tables",
    "exports",
]

DEFAULT_MASTER_PROCEDURE = """from hyde import *


@procedure
def master():
    pass
"""

DEFAULT_FIT_FUNCTIONS = """from hyde import *


@fit_function
def line(x, slope=1.0, intercept=0.0):
    return slope * x + intercept
"""


@dataclass
class HydeProjectState:
    path: str
    manifest: dict
    session: dict
    objects: dict


class HydeProjectLoadError(RuntimeError):
    def __init__(self, path, errors, partial_state):
        super().__init__("\n".join(errors))
        self.path = str(path)
        self.errors = list(errors)
        self.partial_state = partial_state


class HydeProject:
    def __init__(self, root):
        self.root = Path(root)
        if self.root.suffix != ".hy":
            self.root = self.root.with_suffix(".hy")

    @property
    def manifest_path(self):
        return self.root / "manifest.toml"

    @property
    def session_path(self):
        return self.root / "session.toml"

    @property
    def master_path(self):
        return self.root / "procedures" / "master.py"

    def _default_manifest(self, application_version="0.1.0", layout=None, objects=None, scripts=None):
        return {
            "hyde_version": 1,
            "application_version": application_version,
            "layout": {} if layout is None else layout,
            "objects": {} if objects is None else objects,
            "scripts": {} if scripts is None else scripts,
        }

    def _default_session(self, history=None, figures=None, tables=None, incoming_shots=None, message_handler=None):
        return {
            "project_path": self.root.name,
            "history_file": "terminal/history.py",
            "history": [] if history is None else history,
            "figures": [] if figures is None else figures,
            "tables": [] if tables is None else tables,
            "incoming_shots": [] if incoming_shots is None else incoming_shots,
            "message_handler": {"enabled": True} if message_handler is None else message_handler,
        }

    def ensure_layout(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for dirname in PACKAGE_DIRS:
            (self.root / dirname).mkdir(exist_ok=True)
        history_path = self.root / "terminal" / "history.py"
        if not history_path.exists():
            history_path.write_text("", encoding="utf-8")
        master_path = self.root / "procedures" / "master.py"
        if not master_path.exists():
            master_path.write_text(DEFAULT_MASTER_PROCEDURE, encoding="utf-8")
        fit_functions_path = self.root / "scripts" / "fit_functions.py"
        if not fit_functions_path.exists():
            fit_functions_path.write_text(DEFAULT_FIT_FUNCTIONS, encoding="utf-8")

    def create(self):
        self.ensure_layout()
        manifest = self._default_manifest()
        session = self._default_session()
        dump_toml_file(self.manifest_path, manifest)
        dump_toml_file(self.session_path, self._encode_session(session))
        return HydeProjectState(str(self.root), manifest, session, {})

    def save_session(self, export_data):
        self.ensure_layout()
        object_manifest = {}
        for name, object_data in export_data["objects"].items():
            kind = object_data["kind"]
            if kind == "wave":
                filename = self._save_wave(name, object_data)
                object_manifest[name] = {
                    "kind": "wave",
                    "path": str(filename.relative_to(self.root)),
                    "title": object_data.get("title", name),
                }
            else:
                filename = self._save_json_object(name, object_data)
                object_manifest[name] = {
                    "kind": "json",
                    "path": str(filename.relative_to(self.root)),
                }
        scripts = self.scan_scripts()
        manifest = self._default_manifest(
            application_version=export_data.get("application_version", "0.1.0"),
            layout=export_data.get("window_layout", {}),
            objects=object_manifest,
            scripts={
                entry.function_name: {
                    "path": str(Path(entry.path).relative_to(self.root)),
                    "function": entry.function_name,
                    "kind": entry.kind,
                }
                for entry in scripts
            },
        )
        session = self._default_session(
            history=export_data.get("history", []),
            figures=export_data.get("figures", []),
            tables=export_data.get("tables", []),
            incoming_shots=export_data.get("incoming_shots", []),
            message_handler=export_data.get("message_handler", {"enabled": True}),
        )
        dump_toml_file(self.manifest_path, manifest)
        dump_toml_file(self.session_path, self._encode_session(session))
        (self.root / "terminal" / "history.py").write_text(
            "\n".join(session["history"]) + ("\n" if session["history"] else ""),
            encoding="utf-8",
        )
        return HydeProjectState(str(self.root), manifest, session, export_data["objects"])

    def load_session(self, allow_partial=False):
        self.ensure_layout()
        errors = []
        try:
            manifest = load_toml_file(self.manifest_path)
        except Exception as exc:
            manifest = self._default_manifest()
            errors.append(f"Could not load {self.manifest_path.name}: {exc}")
        try:
            session = self._decode_session(load_toml_file(self.session_path))
        except Exception as exc:
            session = self._default_session()
            errors.append(f"Could not load {self.session_path.name}: {exc}")
        objects = {}
        for name, info in manifest.get("objects", {}).items():
            path = self.root / info["path"]
            if info["kind"] == "wave":
                objects[name] = TrackedArray(name, np.load(path, allow_pickle=False))
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
                objects[name] = payload.get("value", payload)
        state = HydeProjectState(str(self.root), manifest, session, objects)
        if errors and not allow_partial:
            raise HydeProjectLoadError(self.root, errors, state)
        return state

    def scan_scripts(self):
        entries = []
        for relative_dir in ("scripts", "procedures", "figures", "tables"):
            for path in sorted((self.root / relative_dir).rglob("*.py")):
                entries.extend(discover_script_entries(path))
        return entries

    def export_archive(self, destination):
        destination = Path(destination)
        if destination.suffix == ".zip":
            destination = destination.with_suffix("")
        return shutil.make_archive(str(destination), "zip", root_dir=self.root.parent, base_dir=self.root.name)

    def copy_to(self, destination):
        destination_project = HydeProject(destination)
        self.ensure_layout()
        if self.root.resolve() != destination_project.root.resolve():
            shutil.copytree(self.root, destination_project.root, dirs_exist_ok=True)
        destination_project.ensure_layout()
        return destination_project

    def upsert_master_entry(self, function_name, source):
        self.ensure_layout()
        master_path = self.master_path
        text = master_path.read_text(encoding="utf-8")
        imports, definition = self._split_module_source(source)
        text = self._ensure_import_lines(text, imports)
        lines = text.splitlines()
        module = ast.parse(text, filename=str(master_path))
        replacement = definition.rstrip().splitlines()
        for node in module.body:
            if not isinstance(node, ast.FunctionDef) or node.name != function_name:
                continue
            start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list]) - 1
            end = node.end_lineno
            lines[start:end] = replacement
            break
        else:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(replacement)
        master_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def import_archive(self, archive_path):
        shutil.unpack_archive(str(archive_path), extract_dir=str(self.root.parent))
        return self.load_session()

    def _save_wave(self, name, object_data):
        filename = self.root / "data" / f"{name}.npy"
        np.save(filename, np.asarray(object_data["data"]), allow_pickle=False)
        return filename

    def _save_json_object(self, name, object_data):
        filename = self.root / "data" / f"{name}.json"
        filename.write_text(json.dumps(object_data, indent=2, sort_keys=True), encoding="utf-8")
        return filename

    def _encode_session(self, session):
        encoded = dict(session)
        encoded["figures_json"] = json.dumps(encoded.pop("figures", []))
        encoded["tables_json"] = json.dumps(encoded.pop("tables", []))
        encoded["incoming_shots_json"] = json.dumps(encoded.pop("incoming_shots", []))
        encoded["message_handler_json"] = json.dumps(
            encoded.pop("message_handler", {"enabled": True})
        )
        return encoded

    def _decode_session(self, session):
        decoded = self._default_session()
        decoded.update(session)
        decoded["figures"] = json.loads(decoded.pop("figures_json", "[]"))
        decoded["tables"] = json.loads(decoded.pop("tables_json", "[]"))
        decoded["incoming_shots"] = json.loads(decoded.pop("incoming_shots_json", "[]"))
        decoded["message_handler"] = json.loads(
            decoded.pop("message_handler_json", '{"enabled": true}')
        )
        return decoded

    def _split_module_source(self, source):
        imports = []
        body = []
        in_body = False
        for line in source.strip().splitlines():
            stripped = line.strip()
            if not in_body and (
                not stripped or stripped.startswith("import ") or stripped.startswith("from ")
            ):
                if stripped:
                    imports.append(stripped)
                continue
            in_body = True
            body.append(line.rstrip())
        return imports, "\n".join(body)

    def _ensure_import_lines(self, text, imports):
        lines = text.splitlines()
        existing = {line.strip() for line in lines}
        missing = [line for line in imports if line and line not in existing]
        if not missing:
            return text
        insert_at = 0
        for index, line in enumerate(lines):
            if line.startswith("from ") or line.startswith("import "):
                insert_at = index + 1
        lines[insert_at:insert_at] = missing + [""]
        return "\n".join(lines).rstrip() + "\n"
