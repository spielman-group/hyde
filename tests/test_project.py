from pathlib import Path

from hyde.project import HydeProject, HydeProjectLoadError


def test_project_save_and_load_roundtrip(tmp_path):
    project = HydeProject(tmp_path / "example.hy")
    project.create()
    (project.root / "procedures" / "demo.py").write_text(
        "from hyde import *\n\n@procedure\ndef run_demo():\n    return 1\n",
        encoding="utf-8",
    )
    export_data = {
        "application_version": "0.1.0",
        "window_layout": {"geometry": "abc", "state": "def"},
        "history": ["wave('x', [1, 2, 3])"],
        "incoming_shots": [{"filepath": "/tmp/example.h5"}],
        "message_handler": {"enabled": True},
        "figures": [{"id": "fig1", "title": "Example", "traces": [], "axes": {}}],
        "tables": [{"id": "table1", "title": "Table", "objects": ["x"], "data": {"x": [1, 2, 3]}}],
        "objects": {
            "x": {
                "kind": "wave",
                "name": "x",
                "title": "x",
                "data": [1, 2, 3],
                "revision": 0,
            },
            "status": {"kind": "json", "value": {"ok": True}},
        },
    }
    project.save_session(export_data)
    loaded = project.load_session()
    assert loaded.manifest["layout"]["geometry"] == "abc"
    assert loaded.session["history"] == ["wave('x', [1, 2, 3])"]
    assert loaded.objects["x"].array.tolist() == [1, 2, 3]
    assert loaded.objects["status"] == {"ok": True}
    assert {entry.function_name for entry in project.scan_scripts()} == {"line", "master", "run_demo"}


def test_project_creates_master_procedure_and_loads_plain_numpy_arrays(tmp_path):
    project = HydeProject(tmp_path / "plain_arrays.hy")
    project.create()
    assert (project.root / "procedures" / "master.py").exists()
    assert (project.root / "scripts" / "fit_functions.py").exists()

    project.save_session(
        {
            "application_version": "0.1.0",
            "window_layout": {},
            "history": [],
            "incoming_shots": [],
            "message_handler": {"enabled": True},
            "figures": [],
            "tables": [],
            "objects": {
                "a": {
                    "kind": "wave",
                    "name": "a",
                    "title": "a",
                    "data": [2, 3, 4],
                    "dtype": "int64",
                    "shape": [3],
                    "revision": 0,
                }
            },
        }
    )

    loaded = project.load_session()
    assert loaded.objects["a"].array.tolist() == [2, 3, 4]


def test_project_copy_to_preserves_scripts_and_session_files(tmp_path):
    source = HydeProject(tmp_path / "source.hy")
    source.create()
    (source.root / "procedures" / "demo.py").write_text(
        "from hyde import *\n\n@procedure\ndef run_demo():\n    return 1\n",
        encoding="utf-8",
    )
    source.save_session(
        {
            "application_version": "0.1.0",
            "window_layout": {},
            "history": ["master()"],
            "incoming_shots": [],
            "message_handler": {"enabled": True},
            "figures": [],
            "tables": [],
            "objects": {},
        }
    )

    copied = source.copy_to(tmp_path / "copied.hy")
    loaded = copied.load_session()

    assert copied.root.name == "copied.hy"
    assert (copied.root / "procedures" / "demo.py").exists()
    assert loaded.session["history"] == ["master()"]
    assert {entry.function_name for entry in copied.scan_scripts()} == {"line", "master", "run_demo"}


def test_project_roundtrips_window_layout_keys_with_colons(tmp_path):
    project = HydeProject(tmp_path / "layout_keys.hy")
    project.create()

    project.save_session(
        {
            "application_version": "0.1.0",
            "window_layout": {
                "panel:command": {"x": 1, "y": 2},
                "figure:figure_1234": {"visible": True},
            },
            "history": [],
            "incoming_shots": [],
            "message_handler": {"enabled": True},
            "figures": [],
            "tables": [],
            "objects": {},
        }
    )

    loaded = project.load_session()

    assert loaded.manifest["layout"]["panel:command"]["x"] == 1
    assert loaded.manifest["layout"]["figure:figure_1234"]["visible"] is True


def test_project_load_session_reports_partial_state_for_malformed_toml(tmp_path):
    project = HydeProject(tmp_path / "broken.hy")
    project.create()
    (project.root / "manifest.toml").write_text(
        'hyde_version = 1\napplication_version = "0.1.0"\n[layout."panel:command"\nx = 1\n',
        encoding="utf-8",
    )

    try:
        project.load_session()
    except HydeProjectLoadError as exc:
        assert "manifest.toml" in exc.errors[0]
        partial = exc.partial_state
    else:
        raise AssertionError("Expected HydeProjectLoadError for malformed TOML")

    assert partial.manifest["layout"] == {}
    assert partial.session["history"] == []

    loaded = project.load_session(allow_partial=True)
    assert loaded.manifest["layout"] == {}
    assert loaded.session["history"] == []
