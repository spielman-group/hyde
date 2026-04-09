"""Main window UI package."""

import base64
import sys

from qtutils.qt import QtCore, QtGui, QtWidgets

from labscript_utils.qtwidgets.outputbox import OutputBox

from hyde.user_interface import load_ui
from hyde.user_interface.command_window import CommandInputHandler
from hyde.user_interface.data_browser import DataBrowserWidget
from hyde.user_interface.procedure_browser import ProcedureBrowserWidget
from hyde.user_interface.figure_window import FigureWindow
from hyde.user_interface.table_window import TableWindow, PanelWindow


def encode_qbytes(value):
    return base64.b64encode(bytes(value)).decode("ascii")


def decode_qbytes(value):
    if not value:
        return QtCore.QByteArray()
    return QtCore.QByteArray.fromBase64(value.encode("ascii"))


class HydeMainWindow(QtWidgets.QMainWindow):
    PANEL_KEYS = ("command", "data_browser", "script_browser")

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.ui = load_ui("main/main.ui", self)
        self.mdi = self.ui.mdiArea
        self.mdi.setOption(QtWidgets.QMdiArea.DontMaximizeSubWindowOnActivation, True)
        self.mdi.setViewMode(QtWidgets.QMdiArea.SubWindowView)
        self.figure_windows = {}
        self.table_windows = {}
        self.panel_windows = {}
        self._saved_subwindow_layouts = {}

        self.command_panel = QtWidgets.QWidget()
        command_layout = QtWidgets.QVBoxLayout(self.command_panel)
        command_layout.setContentsMargins(0, 0, 0, 0)
        self.output_box = OutputBox(command_layout)
        self.command_input = CommandInputHandler(None)
        input_frame = QtWidgets.QFrame()
        input_frame.setFrameShape(QtWidgets.QFrame.Panel)
        input_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        input_layout = QtWidgets.QHBoxLayout(input_frame)
        input_layout.setContentsMargins(4, 2, 4, 2)
        prompt_label = QtWidgets.QLabel(">>>")
        font = QtGui.QFont("Monaco", 11)
        font.setBold(True)
        prompt_label.setFont(font)
        input_layout.addWidget(prompt_label)
        input_layout.addWidget(self.command_input.input)
        command_layout.addWidget(input_frame)

        self.command_input.command_submitted.connect(self.app.execute_command)
        self.command_input.completion_requested.connect(self.app.request_terminal_completion)
        self.data_browser = DataBrowserWidget()
        self.data_browser.display_requested.connect(self.app.display_selection)
        self.data_browser.edit_requested.connect(self.app.table_selection)
        self.data_browser.table_requested.connect(self.app.table_selection)
        self.data_browser.append_graph_requested.connect(self.app.append_to_graph_selection)
        self.data_browser.append_table_requested.connect(self.app.append_to_table_selection)
        self.data_browser.delete_requested.connect(self.app.delete_selection)
        self.data_browser.where_used_requested.connect(self.app.where_used_selection)
        self.data_browser.fit_requested.connect(self.app.fit_selection)
        self.data_browser.copy_path_requested.connect(self.app.copy_object_paths)
        self.procedure_browser = ProcedureBrowserWidget()
        self.procedure_browser.open_requested.connect(self.app.open_external_editor)
        self.procedure_browser.run_requested.connect(self.app.run_script_entry)

        self._create_panel_windows()
        self._connect_actions()

    def _create_panel_windows(self):
        self.command_window = self._add_panel_window("command", "Command window", self.command_panel)
        self.data_window = self._add_panel_window("data_browser", "Data Browser", self.data_browser)
        self.script_window = self._add_panel_window("script_browser", "Script browser", self.procedure_browser)

        self.command_window.setGeometry(20, 560, 1080, 260)
        self.data_window.setGeometry(20, 20, 420, 500)
        self.script_window.setGeometry(460, 20, 420, 500)

        self.command_window.show()
        self.data_window.show()
        self.script_window.show()

    def _add_panel_window(self, key, title, widget):
        window = PanelWindow(key, title, widget, self)
        self.panel_windows[key] = window
        self.mdi.addSubWindow(window)
        return window

    def _connect_actions(self):
        self.actionNewProject.triggered.connect(self.app.new_project)
        self.actionOpenProject.triggered.connect(self.app.open_project)
        self.actionSaveProject.triggered.connect(self.app.save_project)
        self.actionSaveProjectAs.triggered.connect(self.app.save_project_as)
        self.actionSaveGraphics.triggered.connect(self.app.save_graphics)
        self.actionExportArchive.triggered.connect(self.app.export_archive)
        self.actionQuit.triggered.connect(self.close)
        self.actionEditAxes.triggered.connect(self.app.edit_active_figure)
        self.actionEditTraces.triggered.connect(self.app.edit_active_trace)
        self.actionCurveFit.triggered.connect(self.app.open_fit_dialog)
        self.actionNewGraph.triggered.connect(self.app.new_graph)
        self.actionNewTable.triggered.connect(self.app.new_table)
        self.actionNewPythonScript.triggered.connect(self.app.new_python_script)

        command_shortcut = "Meta+J" if sys.platform == "darwin" else "Ctrl+J"
        self.actionCommandWindow.setShortcut(QtGui.QKeySequence(command_shortcut))
        self.actionCommandWindow.setShortcutContext(QtCore.Qt.ApplicationShortcut)
        self.actionCommandWindow.triggered.connect(self._focus_command_input)

        self._bind_window_actions(self.command_window, self.actionCommandWindow)
        self._bind_window_actions(
            self.data_window,
            self.actionDataBrowser,
        )
        self._bind_window_actions(self.script_window, self.actionScriptBrowser)

        self.actionRetrieveWindow.triggered.connect(self._retrieve_window)
        self.actionRetrieveAll.triggered.connect(self._retrieve_all_windows)

        self.scripts_menu = self.menuScripts
        self.graph_macros_menu = self.menuGraphMacros
        self.table_macros_menu = self.menuTableMacros

    def _bind_window_actions(self, window, *actions):
        def set_visible(checked):
            if checked:
                window.show_and_raise()
            else:
                window.close()

        def sync(visible):
            for action in actions:
                was_blocked = action.blockSignals(True)
                action.setChecked(visible)
                action.blockSignals(was_blocked)

        for action in actions:
            action.setCheckable(True)
            action.toggled.connect(set_visible)
        window.visibility_changed.connect(sync)
        sync(window.isVisible())

    def _retrieve_window(self):
        subwindows = self.mdi.subWindowList()
        if not subwindows:
            return
        if len(subwindows) == 1:
            self._ensure_window_visible(subwindows[0])
            return
        window, _selected = QtWidgets.QInputDialog.getItem(
            self,
            "Retrieve Window",
            "Select window to retrieve:",
            [sw.windowTitle() or f"Window {i+1}" for i, sw in enumerate(subwindows)],
            0,
            False,
        )
        if window:
            for sub in subwindows:
                if sub.windowTitle() == window:
                    self._ensure_window_visible(sub)
                    break

    def _retrieve_all_windows(self):
        for subwindow in self.mdi.subWindowList():
            self._ensure_window_visible(subwindow)
        if self.mdi.subWindowList():
            self.mdi.subWindowList()[0].activateWindow()

    def _ensure_window_visible(self, window):
        screen = self.mdi.screen()
        available_geometry = screen.availableGeometry()
        geometry = window.geometry()
        
        if not available_geometry.contains(geometry):
            x = max(available_geometry.left(), available_geometry.left() + 50)
            y = max(available_geometry.top(), available_geometry.top() + 50)
            width = min(geometry.width(), available_geometry.width() - 50)
            height = min(geometry.height(), available_geometry.height() - 50)
            window.setGeometry(x, y, width, height)
        
        window.showNormal()
        window.activateWindow()
        window.raise_()

    def apply_snapshot(self, snapshot, script_entries):
        self.data_browser.set_objects(snapshot.get("namespace_summary", []))
        self.procedure_browser.set_entries(script_entries)
        self._rebuild_scripts_menu(script_entries)
        self._sync_figures(snapshot.get("figures", []))
        self._sync_tables(snapshot.get("tables", []))
        if not self.script_window.widget():
            self.script_window.setWidget(self.procedure_browser)

    def _focus_command_input(self):
        self.command_input.input.setFocus(QtCore.Qt.OtherFocusReason)

    def closeEvent(self, event):
        if self.app.shutdown_requested():
            return super().closeEvent(event)
        event.ignore()

    def _rebuild_scripts_menu(self, entries):
        self.scripts_menu.clear()
        self.graph_macros_menu.clear()
        self.table_macros_menu.clear()
        for entry in entries:
            if entry.kind == "figure":
                menu = self.graph_macros_menu
            elif entry.kind == "table":
                menu = self.table_macros_menu
            else:
                menu = self.scripts_menu
            action = menu.addAction(entry.title)
            action.triggered.connect(
                lambda checked=False, e=entry: self.app.run_script_entry(e.path, e.function_name)
            )

    def _sync_figures(self, figures):
        active_ids = set()
        for figure in figures:
            figure_id = figure["id"]
            active_ids.add(figure_id)
            if figure_id not in self.figure_windows:
                window = FigureWindow(figure_id)
                window.close_requested.connect(self.app.close_figure_requested)
                self.figure_windows[figure_id] = window
                self.mdi.addSubWindow(window)
                self._restore_subwindow_geometry(f"figure:{figure_id}", window)
                window.show()
            self.figure_windows[figure_id].apply_snapshot(figure)
        for figure_id in list(self.figure_windows):
            if figure_id not in active_ids:
                window = self.figure_windows.pop(figure_id)
                window.close_from_sync()

    def _sync_tables(self, tables):
        active_ids = set()
        for table in tables:
            table_id = table["id"]
            active_ids.add(table_id)
            if table_id not in self.table_windows:
                window = TableWindow(
                    table,
                    self.app.edit_table_value,
                    self.app.delete_table_values,
                )
                window.close_requested.connect(self.app.close_table_requested)
                self.table_windows[table_id] = window
                self.mdi.addSubWindow(window)
                self._restore_subwindow_geometry(f"table:{table_id}", window)
                window.show()
            self.table_windows[table_id].apply_snapshot(table)
        for table_id in list(self.table_windows):
            if table_id not in active_ids:
                window = self.table_windows.pop(table_id)
                window.close_from_sync()

    def current_figure_id(self):
        active = self.mdi.activeSubWindow()
        if isinstance(active, FigureWindow):
            return active.figure_id
        return None

    def current_figure_size_inches(self):
        active = self.mdi.activeSubWindow()
        if isinstance(active, FigureWindow):
            width, height = active.figure.get_size_inches()
            return (float(width), float(height))
        return None

    def current_table_id(self):
        active = self.mdi.activeSubWindow()
        if isinstance(active, TableWindow):
            return active.table_id
        return None

    def save_window_layout(self):
        subwindows = {
            f"panel:{key}": self._serialize_subwindow(window)
            for key, window in self.panel_windows.items()
        }
        subwindows.update(
            {
                f"figure:{figure_id}": self._serialize_subwindow(window)
                for figure_id, window in self.figure_windows.items()
            }
        )
        subwindows.update(
            {
                f"table:{table_id}": self._serialize_subwindow(window)
                for table_id, window in self.table_windows.items()
            }
        )
        return {
            "geometry": encode_qbytes(self.saveGeometry()),
            "subwindows": subwindows,
        }

    def restore_window_layout(self, layout):
        geometry = decode_qbytes(layout.get("geometry", ""))
        if not geometry.isEmpty():
            self.restoreGeometry(geometry)
        self._saved_subwindow_layouts = dict(layout.get("subwindows", {}))
        for key, window in self.panel_windows.items():
            self._restore_subwindow_geometry(f"panel:{key}", window)

    def _serialize_subwindow(self, window):
        return {
            "geometry": encode_qbytes(window.saveGeometry()),
            "visible": window.isVisible(),
        }

    def _restore_subwindow_geometry(self, key, window):
        layout = self._saved_subwindow_layouts.get(key)
        if not layout:
            return
        geometry_data = decode_qbytes(layout.get("geometry", ""))
        if geometry_data:
            window.restoreGeometry(geometry_data)
            mdi_geometry = self.mdi.viewport().rect()
            window_geometry = window.geometry()
            if not mdi_geometry.contains(window_geometry):
                window.setGeometry(mdi_geometry.x(), mdi_geometry.y(), window_geometry.width(), window_geometry.height())
        if not layout.get("visible", True):
            window.hide()


__all__ = ["HydeMainWindow", "CommandInputHandler", "encode_qbytes", "decode_qbytes"]