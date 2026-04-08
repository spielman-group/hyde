from pathlib import Path

import numpy as np

from hyde.project import HydeProject
from hyde.runtime import ExecutionRuntime


def test_runtime_refreshes_figures_when_wave_changes():
    runtime = ExecutionRuntime()
    response = runtime.execute("wave('y', np.arange(4)); display('y', figure_name='fig')")
    assert response["success"] is True
    assert "import matplotlib.pyplot as plt" in response["stdout"]
    names = {item["name"] for item in response["snapshot"]["namespace_summary"]}
    assert "In" not in names
    assert "Out" not in names
    summary = next(item for item in response["snapshot"]["namespace_summary"] if item["name"] == "y")
    assert summary["kind"] == "numpy"
    assert summary["type_name"] == "ndarray"
    runtime.execute("y[1] = 42")
    figure = runtime.snapshot()["figures"][0]
    assert figure["traces"][0]["y_data"] == [0, 42, 2, 3]


def test_runtime_serializes_plain_numpy_arrays_as_data_objects():
    runtime = ExecutionRuntime()
    response = runtime.execute("a = np.array([2, 3, 4])", echo=False)
    exported = response["snapshot"]["objects"]["a"]
    assert exported["kind"] == "wave"
    assert exported["data"] == [2, 3, 4]


def test_tracked_array_supports_numpy_operator_protocol():
    runtime = ExecutionRuntime()
    response = runtime.execute("a = wave('a', [3.0, 4.0, 5.0]); b = a**2", echo=False)

    assert response["success"] is True
    assert runtime.namespace["b"].tolist() == [9.0, 16.0, 25.0]

    runtime.execute("a += 1", echo=False)
    assert runtime.namespace["a"].array.tolist() == [4.0, 5.0, 6.0]
    assert runtime.namespace["a"].revision == 1


def test_runtime_uses_ipython_completion():
    runtime = ExecutionRuntime()
    runtime.execute("alpha_value = 1", echo=False)

    completion = runtime.complete("alp", 3)

    assert completion["token"] == "alp"
    assert "alpha_value" in completion["matches"]


def test_runtime_can_execute_without_recording_history():
    runtime = ExecutionRuntime()
    runtime.execute("alpha_value = 1", echo=False, record_history=False)

    assert runtime.namespace["alpha_value"] == 1
    assert runtime.snapshot()["history"] == []


def test_runtime_silent_execute_suppresses_expression_output():
    runtime = ExecutionRuntime()
    runtime.execute("wave('a', [1.0, 2.0, 3.0]); display('a', figure_name='fig')", echo=False)

    response = runtime.execute(
        "edit_figure('fig', xgrid=True)",
        echo=False,
        record_history=False,
        silent=True,
    )

    assert response["success"] is True
    assert response["stdout"] == ""
    assert runtime.figures["fig"]["axes"]["xgrid"] is True


def test_runtime_marker_only_trace_source_uses_linestyle_none():
    runtime = ExecutionRuntime()
    runtime.execute(
        "a = wave('a', [1.0, 2.0, 3.0]); "
        "display('a', figure_name='fig', style='None', marker='o', linewidth=0.0)",
        echo=False,
    )

    source = runtime.figure_replay_source("fig", "marker_only")

    assert "linestyle='None'" in source
    assert "marker='o'" in source


def test_runtime_save_graphics_writes_file(tmp_path):
    runtime = ExecutionRuntime()
    output = tmp_path / "graph.pdf"
    runtime.execute("a = wave('a', [1.0, 2.0, 3.0]); display('a', figure_name='fig')", echo=False)

    saved_path = runtime.save_graphics("fig", output, format="pdf", size=(5.0, 3.0), overwrite=True)

    assert Path(saved_path) == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_runtime_runs_project_scripts_and_curve_fits(tmp_path):
    runtime = ExecutionRuntime()
    project_root = tmp_path / "demo.hy"
    project_root.mkdir()
    procedures = project_root / "procedures"
    procedures.mkdir()
    fit_file = procedures / "fitters.py"
    fit_file.write_text(
        "from hyde import *\nimport numpy as np\n\n"
        "@fit_function\n"
        "def line(x, slope, intercept):\n"
        "    return slope * x + intercept\n\n"
        "@procedure\n"
        "def make_data():\n"
        "    wave('x', np.arange(5, dtype=float))\n"
        "    wave('y', 2 * np.arange(5, dtype=float) + 1)\n"
        "    return display('y', x='x', figure_name='line_fig')\n",
        encoding="utf-8",
    )
    runtime.set_project_root(project_root)
    runtime.run_hyde_script("procedures/fitters.py", "make_data")
    result = runtime.do_fit(
        "procedures/fitters.py",
        "line",
        "y",
        x="x",
        result_name="line_fit",
        params={
            "slope": {"value": 1.0, "vary": True},
            "intercept": {"value": 0.0, "vary": True},
        },
        graph=True,
    )
    assert round(result["best_values"]["slope"], 6) == 2.0
    assert round(result["best_values"]["intercept"], 6) == 1.0
    assert np.allclose(runtime.namespace["line_fit"].array.tolist(), [1.0, 3.0, 5.0, 7.0, 9.0])
    assert round(runtime.namespace["line_fit_result"]["best_values"]["slope"], 6) == 2.0
    figure_ids = {figure["id"] for figure in runtime.snapshot()["figures"]}
    assert "line_fit_graph" in figure_ids


def test_fit_preview_adds_to_existing_graph_without_creating_new_window(tmp_path):
    runtime = ExecutionRuntime()
    project_root = tmp_path / "demo.hy"
    procedures = project_root / "procedures"
    procedures.mkdir(parents=True)
    fit_file = procedures / "fitters.py"
    fit_file.write_text(
        "from hyde import *\nimport numpy as np\n\n"
        "@fit_function\n"
        "def line(x, slope, intercept):\n"
        "    return slope * x + intercept\n",
        encoding="utf-8",
    )
    runtime.set_project_root(project_root)
    runtime.execute(
        "wave('x', np.arange(3, dtype=float)); "
        "wave('y', np.array([1.0, 3.0, 5.0])); "
        "display('y', x='x', figure_name='fig0')",
        echo=False,
    )

    preview = runtime.do_fit(
        "procedures/fitters.py",
        "line",
        "y",
        x="x",
        result_name="fit_y",
        params={
            "slope": {"value": 2.0, "vary": True},
            "intercept": {"value": 1.0, "vary": True},
        },
        store_residuals=False,
        graph=True,
        graph_target="fig0",
        preview=True,
    )

    assert preview["kind"] == "fit_preview"
    assert set(runtime.figures) == {"fig0"}
    assert len(runtime.figures["fig0"]["traces"]) == 2
    assert runtime.figures["fig0"]["traces"][1]["y_name"] == "fit_y"
    assert runtime.namespace["fit_y"].array.tolist() == [1.0, 3.0, 5.0]
    assert "fit_y_result" not in runtime.namespace

    runtime.do_fit(
        "procedures/fitters.py",
        "line",
        "y",
        x="x",
        result_name="fit_y",
        params={
            "slope": {"value": 3.0, "vary": True},
            "intercept": {"value": 0.0, "vary": True},
        },
        store_residuals=False,
        graph=True,
        graph_target="fig0",
        preview=True,
    )

    assert len(runtime.figures["fig0"]["traces"]) == 2
    assert runtime.namespace["fit_y"].array.tolist() == [0.0, 3.0, 6.0]


def test_fit_run_updates_preview_destination_wave_without_new_graph(tmp_path):
    runtime = ExecutionRuntime()
    project_root = tmp_path / "demo.hy"
    procedures = project_root / "procedures"
    procedures.mkdir(parents=True)
    fit_file = procedures / "fitters.py"
    fit_file.write_text(
        "from hyde import *\nimport numpy as np\n\n"
        "@fit_function\n"
        "def line(x, slope, intercept):\n"
        "    return slope * x + intercept\n",
        encoding="utf-8",
    )
    runtime.set_project_root(project_root)
    runtime.execute(
        "wave('x', np.arange(3, dtype=float)); "
        "wave('a', np.array([1.0, 3.0, 5.0])); "
        "display('a', x='x', figure_name='fig0')",
        echo=False,
    )
    runtime.do_fit(
        "procedures/fitters.py",
        "line",
        "a",
        x="x",
        result_name="a_fit",
        params={
            "slope": {"value": 3.0, "vary": True},
            "intercept": {"value": 0.0, "vary": True},
        },
        store_residuals=False,
        graph=True,
        graph_target="fig0",
        preview=True,
    )

    runtime.do_fit(
        "procedures/fitters.py",
        "line",
        "a",
        x="x",
        result_name="a_fit",
        params={
            "slope": {"value": 0.0, "vary": True},
            "intercept": {"value": 0.0, "vary": True},
        },
        store_residuals=False,
        graph=False,
        graph_target="fig0",
        preview=False,
    )

    assert runtime.namespace["a_fit"].array.tolist() == [1.0, 3.0, 5.0]
    assert "a_fit_result" in runtime.namespace
    trace = runtime.figures["fig0"]["traces"][1]
    assert trace["y_name"] == "a_fit"
    assert np.allclose(trace["y_data"], [1.0, 3.0, 5.0])


def test_runtime_loads_master_procedure_into_terminal_namespace(tmp_path):
    runtime = ExecutionRuntime()
    project_root = tmp_path / "demo.hy"
    procedures = project_root / "procedures"
    procedures.mkdir(parents=True)
    (procedures / "master.py").write_text(
        "from hyde import *\n\n"
        "@procedure\n"
        "def master():\n"
        "    wave('from_master', [1, 2, 3])\n"
        "    return 'ready'\n",
        encoding="utf-8",
    )

    runtime.set_project_root(project_root)
    response = runtime.execute("result = master()", echo=False)

    assert response["success"] is True
    assert runtime.namespace["result"] == "ready"
    assert runtime.namespace["from_master"].array.tolist() == [1, 2, 3]


def test_runtime_saved_figure_source_is_explicit_matplotlib_and_rerunnable(tmp_path):
    runtime = ExecutionRuntime()
    project_root = tmp_path / "demo.hy"
    figures_dir = project_root / "figures"
    figures_dir.mkdir(parents=True)

    runtime.execute("wave('a', np.array([2, 3, 4])); display('a', figure_name='fig_a')", echo=False)
    source = runtime.figure_replay_source("fig_a", "saved_figure")
    assert "import numpy as np" in source
    assert "import matplotlib.pyplot as plt" in source
    assert "ax.plot(" in source
    assert "def saved_figure(a):" in source

    (figures_dir / "saved_figure.py").write_text(source, encoding="utf-8")
    runtime.set_project_root(project_root)
    result = runtime.run_hyde_script("figures/saved_figure.py", "saved_figure")

    assert result.figure_id == "saved_figure"
    figure = runtime.figures["saved_figure"]
    assert figure["traces"][0]["y_name"] == "a"
    assert figure["traces"][0]["y_data"] == [2, 3, 4]


def test_runtime_figure_source_uses_all_trace_variables_as_arguments():
    runtime = ExecutionRuntime()
    runtime.execute(
        "wave('a', np.array([4.0, 5.0, 6.0])); "
        "wave('b', np.array([16.0, 25.0, 36.0])); "
        "display('b', x='a', figure_name='fig_ab')",
        echo=False,
    )

    source = runtime.figure_replay_source("fig_ab", "figure_ab")

    assert "def figure_ab(a, b):" in source


def test_runtime_loads_saved_master_figure_and_table_entries_into_namespace(tmp_path):
    project = HydeProject(tmp_path / "saved_entries.hy")
    project.create()
    runtime = ExecutionRuntime()
    runtime.execute(
        "wave('a', np.array([1.0, 2.0, 3.0])); "
        "wave('b', np.array([4.0, 5.0, 6.0])); "
        "display('b', x='a', figure_name='fig_ab'); "
        "open_table('a', 'b', title='table_ab')",
        echo=False,
    )
    project.upsert_master_entry("figure_ab", runtime.figure_replay_source("fig_ab", "figure_ab"))
    project.upsert_master_entry("table_ab", runtime.table_replay_source("table_ab", "table_ab"))

    runtime.set_project_root(project.root)

    assert callable(runtime.namespace["figure_ab"])
    assert callable(runtime.namespace["table_ab"])

    runtime.execute("close_figure('fig_ab'); close_table('table_ab')", echo=False, record_history=False)
    response = runtime.execute("figure_ab(a, b); table_ab(a, b)", echo=False)

    assert response["success"] is True
    assert "figure_ab" in runtime.figures
    assert "table_ab" in runtime.tables
    assert runtime.figures["figure_ab"]["traces"][0]["x_name"] == "a"
    assert runtime.figures["figure_ab"]["traces"][0]["y_name"] == "b"
    assert runtime.tables["table_ab"]["objects"] == ["a", "b"]
