from pathlib import Path

from hyde.annotations import discover_script_entries


def test_discover_script_entries(tmp_path):
    script = tmp_path / "demo.py"
    script.write_text(
        "from hyde import *\n\n"
        "@figure\n"
        "def make_plot(x, amplitude=1):\n"
        "    return x\n\n"
        "@fit_function\n"
        "def gaussian(x, amp, center, sigma):\n"
        "    return amp\n",
        encoding="utf-8",
    )
    entries = discover_script_entries(script)
    assert [entry.kind for entry in entries] == ["figure", "fit_function"]
    assert entries[1].parameters == ("amp", "center", "sigma")

