from types import SimpleNamespace

import pytest

qt = pytest.importorskip("qtutils.qt")
QtCore = qt.QtCore
QtWidgets = qt.QtWidgets

from hyde.app import HydeApplication
from hyde.main_window import (
    CombinedTableModel,
    DataBrowserWidget,
    NewGraphDialog,
    SaveGraphicsDialog,
    TableWindow,
    TraceEditDialog,
)


def _qapplication():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_new_graph_dialog_generates_multiline_graph_command():
    _qapplication()
    dialog = NewGraphDialog(["delay2", "numtotal2", "fit_numtotal2"], selected_names=["numtotal2", "delay2"])
    dialog._select_items(dialog.y_list, ["numtotal2", "fit_numtotal2"])
    dialog._select_items(dialog.x_list, ["delay2"])
    dialog.title_edit.setText("Display delay2")

    command = dialog.command()

    assert "display('numtotal2', x='delay2', title='Display delay2', figure_name=" in command
    assert "append_to_graph(" in command
    assert "'fit_numtotal2', x='delay2'" in command


def test_new_graph_dialog_markers_mode_uses_marker_only_display_commands():
    _qapplication()
    dialog = NewGraphDialog(["b"], selected_names=["b"])
    dialog._select_items(dialog.y_list, ["b"])
    dialog.style_combo.setCurrentText("Markers")

    command = dialog.command()

    assert "display('b', figure_name=" in command
    assert "style='None'" in command
    assert "marker='o'" in command
    assert "linewidth=0.0" in command
    assert "edit_trace(" not in command


def test_combined_table_model_merges_multiple_objects_into_one_table():
    model = CombinedTableModel(
        {
            "id": "table0",
            "title": "Table0",
            "objects": ["delay2", "fit_delay2"],
            "data": {"delay2": [0.0, 0.5], "fit_delay2": [1.0, 1.5]},
        }
    )

    assert model.columnCount() == 3
    assert model.headerData(0, QtCore.Qt.Horizontal) == "Point"
    assert model.headerData(1, QtCore.Qt.Horizontal) == "delay2"
    assert model.headerData(2, QtCore.Qt.Horizontal) == "fit_delay2"
    assert model.data(model.index(1, 2)) == "1.5"
    assert model.rowCount() == 3
    assert model.data(model.index(2, 0)) == ""
    assert model.data(model.index(2, 1), QtCore.Qt.BackgroundRole) is not None
    assert model.data(model.index(1, 1), QtCore.Qt.TextAlignmentRole) == int(
        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
    )


def test_data_browser_reports_full_root_paths():
    _qapplication()
    browser = DataBrowserWidget()
    browser.set_objects(
        [
            {
                "name": "fit_delay2",
                "kind": "numpy",
                "type_name": "ndarray",
                "shape": [200],
                "dtype": "float64",
                "preview": "[0.1, 0.2]",
            }
        ]
    )
    item = browser.tree.topLevelItem(0)
    item.setSelected(True)
    browser._update_summary()

    assert "root:fit_delay2" in browser.details_text.toPlainText()


def test_ui_uses_array_terminology():
    _qapplication()
    browser = DataBrowserWidget()
    dialog = NewGraphDialog(["a"])

    assert browser.waves_checkbox.text() == "Arrays"
    assert dialog.ui.y_group.title() == "Y Array(s)"
    assert dialog.ui.x_group.title() == "X Array"


def test_trace_edit_dialog_markers_mode_disables_line_style():
    _qapplication()
    dialog = TraceEditDialog(
        "fig",
        {
            "traces": [
                {
                    "label": "a",
                    "style": "-",
                    "color": "",
                    "visible": True,
                    "marker": None,
                    "markersize": 6.0,
                    "linewidth": 1.5,
                    "gaps": False,
                }
            ]
        },
    )
    dialog.mode_combo.setCurrentText("Markers")

    command = dialog.command()

    assert "style='None'" in command


def test_save_graphics_dialog_generates_command_preview():
    _qapplication()
    dialog = SaveGraphicsDialog("fig", "/tmp/graph.pdf", size_inches=(12.0, 6.5))
    dialog.custom_size_radio.setChecked(True)
    dialog.width_spin.setValue(10.0)
    dialog.height_spin.setValue(4.0)
    dialog.color_checkbox.setChecked(False)
    dialog.overwrite_checkbox.setChecked(True)

    command = dialog.command()

    assert command.startswith("save_graphics('fig', '/tmp/graph.pdf', format='pdf'")
    assert "size=(10.0, 4.0)" in command
    assert "color=False" in command
    assert "overwrite=True" in command
    assert dialog.command_preview.toPlainText() == command


def test_save_graphics_dialog_same_size_omits_size_arguments():
    _qapplication()
    dialog = SaveGraphicsDialog("fig", "/tmp/graph.pdf", size_inches=(12.0, 6.5))
    dialog.same_size_radio.setChecked(True)

    command = dialog.command()

    assert command == "save_graphics('fig', '/tmp/graph.pdf', format='pdf')"


def test_fit_dialog_graph_now_command_targets_current_graph_and_uses_preview():
    _qapplication()
    entry = SimpleNamespace(
        title="Line",
        path="procedures/fitters.py",
        function_name="line",
        parameters=["slope", "intercept"],
    )
    dialog = FitDialog([entry], ["y", "x"], "/tmp/demo.hy")
    dialog.y_combo.setCurrentText("y")
    dialog.x_combo.setCurrentText("x")

    command = dialog.command(graph_override=True, graph_target="fig0", preview=True)

    assert "result_name='fit_y'" in command
    assert "graph=True" in command
    assert "graph_target='fig0'" in command
    assert "preview=True" in command
    assert "store_residuals=False" in command


def test_graph_fit_preview_requires_matching_top_figure(monkeypatch):
    _qapplication()
    called = {"commands": [], "messages": []}
    dialog = SimpleNamespace(y_combo=SimpleNamespace(currentText=lambda: "y"), command=lambda **_: "fitcmd")
    app = SimpleNamespace(
        window=QtWidgets.QWidget(),
        _fit_graph_target=lambda _name: None,
        generated_command=lambda command: called["commands"].append(command),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *_args: called["messages"].append(_args[2]),
    )

    HydeApplication._graph_fit_preview(app, dialog)

    assert called["commands"] == []
    assert called["messages"] == [
        "Graph Now only works when the top window is a figure containing the selected Y data."
    ]


def test_table_window_hides_vertical_header_and_tracks_selection():
    _qapplication()
    window = TableWindow(
        {
            "id": "table0",
            "title": "Table0",
            "objects": ["delay2", "fit_delay2"],
            "data": {"delay2": [3.75, 3.85], "fit_delay2": [1.0, 1.5]},
        },
        lambda *_args: None,
        lambda *_args: None,
    )
    window.table.selectRow(1)
    window.table.setCurrentIndex(window.model.index(1, 1))
    window._sync_selection_state()
    window._sync_current_editor()

    assert window.table.verticalHeader().isHidden()
    assert window.selection_label.text() == "1R X 2C"
    assert window.edit_bar.text().startswith("3.85")


def test_combined_table_model_formats_numpy_scalars():
    model = CombinedTableModel(
        {
            "id": "table0",
            "title": "Table0",
            "objects": ["delay2"],
            "data": {"delay2": [1.234567890123]},
        }
    )

    assert model.data(model.index(0, 1)) == "1.23456789"
    assert model.full_precision_text(model.index(0, 1)).startswith("1.234567890123")
