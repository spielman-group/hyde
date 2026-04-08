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


def test_project_upsert_master_entry_appends_and_overwrites_functions(tmp_path):
    project = HydeProject(tmp_path / "master_entries.hy")
    project.create()

    project.upsert_master_entry(
        "figure_alpha",
        "from hyde import *\n"
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n\n"
        "@figure\n"
        "def figure_alpha(a, b):\n"
        "    return b\n",
    )
    project.upsert_master_entry(
        "table_alpha",
        "from hyde import *\n\n"
        "@table\n"
        "def table_alpha(a):\n"
        "    return open_table(a, title='table_alpha')\n",
    )
    project.upsert_master_entry(
        "figure_alpha",
        "from hyde import *\n"
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n\n"
        "@figure\n"
        "def figure_alpha(a, b):\n"
        "    return a + b\n",
    )

    master_text = project.master_path.read_text(encoding="utf-8")

    assert master_text.count("def figure_alpha(") == 1
    assert master_text.count("def table_alpha(") == 1
    assert "return a + b" in master_text
    assert "return b" not in master_text
    assert "import numpy as np" in master_text
    assert "import matplotlib.pyplot as plt" in master_text
    entries = {(entry.kind, entry.function_name, entry.parameters) for entry in project.scan_scripts()}
    assert ("figure", "figure_alpha", ("a", "b")) in entries
    assert ("table", "table_alpha", ("a",)) in entries
