from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import desktop_app
import qtutils.icons
from labscript_utils.labconfig import LabConfig, LabscriptApplication, load_appconfig, save_appconfig
from labscript_utils.ls_zprocess import ProcessTree
from labscript_utils.splash import Splash, configure_qapplication
from qtutils.qt import QtCore, QtWidgets

from .execution.execution_controller import ExecutionController
from .user_interface.main import HydeMainWindow
from .user_interface.figure_edit_dialog import FigureEditDialog
from .user_interface.fit_dialog import FitDialog
from .user_interface.new_graph_dialog import NewGraphDialog
from .user_interface.save_graphics_dialog import SaveGraphicsDialog
from .user_interface.trace_edit_dialog import TraceEditDialog
from .user_interface.close_figure_dialog import CloseFigureDialog
from .message_server import HydeMessageServer
from .project import HydeProject, HydeProjectLoadError
from .features import register_all_features
from .user_interface.close_figure_dialog import CloseFigureDialog


class HydeApplication(QtCore.QObject, LabscriptApplication):
    app_name = "hyde"
    default_config_filename = "hyde.toml"

    def __init__(self, qapplication, splash=None):
        super().__init__()
        register_all_features()
        self.qapplication = qapplication
        self.splash = splash
        self.process_tree = ProcessTree.instance()
        self.process_tree.zlock_client.set_process_name("hyde")
        if self.splash is not None:
            self.splash.update_text("loading Hyde configuration")
        self.exp_config = LabConfig(
            required_params={
                "default": ["apparatus_name"],
                "ports": ["lyse"],
                "programs": ["text_editor", "text_editor_arguments"],
            }
        )
        if self.splash is not None:
            self.splash.update_text("starting Hyde execution process")
        self.controller = ExecutionController(self)
        self.controller.response_received.connect(self._handle_response)
        if self.splash is not None:
            self.splash.update_text("loading Hyde graphical interface")
        self.window = HydeMainWindow(self)
        self.controller.set_output_redirection_port(self.window.output_box.port)
        self.controller.start()
        self.window.show()
        self.pending_callbacks = {}
        self.project = None
        self.project_state = None
        self.project_path = None
        self.script_entries = []
        self.last_snapshot = None
        self.session_dirty = False
        self._dirty_request_ids = set()
        if self.splash is not None:
            self.splash.update_text("starting Hyde message server")
        self.server = HydeMessageServer(self, self.exp_config.getint("ports", "lyse"))
        if self.splash is not None:
            self.splash.update_text("restoring Hyde session")
        self._load_last_project()
        self.controller.send("snapshot")

    def _load_last_project(self):
        appconfig = load_appconfig(self.get_default_config_file())
        state = appconfig.get("hyde_state", {})
        last_project = state.get("last_project")
        if last_project and Path(last_project).exists():
            if self._open_project_path(last_project):
                return
        default_project = Path(self.get_default_config_file(ensure_directory=True)).with_name("default.hy")
        self._open_project_path(
            str(default_project),
            create=not HydeProject(default_project).manifest_path.exists(),
        )

    def _save_last_project(self):
        save_appconfig(
            self.get_default_config_file(ensure_directory=True),
            {"hyde_state": {"last_project": self.project_path or ""}},
        )

    def _handle_response(self, response):
        request_id = response["request_id"]
        callback = self.pending_callbacks.pop(response["request_id"], None)
        snapshot = response.get("snapshot")
        if snapshot is not None:
            self.last_snapshot = snapshot
            self.window.command_input.set_history(snapshot.get("history", []))
            self._update_ui(snapshot)
        if request_id in self._dirty_request_ids:
            self._dirty_request_ids.discard(request_id)
            if response.get("success", False):
                self.session_dirty = True
        if callback is not None:
            callback(response)
        if response.get("error"):
            self.window.output_box.output(response["error"], red=True)

    def _update_ui(self, snapshot):
        if self.project is not None:
            self.script_entries = self.project.scan_scripts()
        self.window.apply_snapshot(snapshot, self.script_entries)

    def execute_command(self, command, echo=True, record_history=True, mark_dirty=True, silent=False):
        if echo:
            self.window.output_box.output(f">>> {command}\n")
        request_id = self.controller.execute(
            command,
            echo=echo,
            record_history=record_history,
            silent=silent,
        )
        if mark_dirty:
            self._dirty_request_ids.add(request_id)
        return request_id

    def request_terminal_completion(self, code, cursor_pos):
        request_id = self.controller.send("complete", {"code": code, "cursor_pos": cursor_pos})
        self.pending_callbacks[request_id] = lambda response: self.window.command_input.apply_completion(
            response.get("token", ""),
            cursor_pos,
            response.get("matches", []),
        )

    def generated_command(
        self,
        command,
        execute=True,
        show_in_terminal=True,
        echo=True,
        record_history=True,
        silent=False,
    ):
        if show_in_terminal and not execute:
            self.window.command_input.insert_command(command)
        if execute:
            self.execute_command(
                command,
                echo=echo,
                record_history=record_history,
                mark_dirty=record_history,
                silent=silent,
            )

    def new_project(self):
        default_path = str(Path.cwd() / "untitled.hy")
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            "Create Hyde Project",
            default_path,
            "Hyde Projects (*.hy)",
        )
        if not path:
            return
        self._open_project_path(path, create=True)

    def open_project(self):
        base = QtWidgets.QFileDialog.getExistingDirectory(self.window, "Open Hyde Project")
        if not base:
            return
        self._open_project_path(base)

    def _open_project_path(self, path, create=False):
        path_obj = Path(path)
        if not create and not path_obj.exists():
            QtWidgets.QMessageBox.critical(
                self.window,
                "Project Not Found",
                f"The project directory does not exist:\n{path}",
            )
            return False
        self.project = HydeProject(path)
        try:
            state = self.project.create() if create else self.project.load_session()
        except HydeProjectLoadError as exc:
            details = "\n".join(exc.errors)
            result = QtWidgets.QMessageBox.warning(
                self.window,
                "Problem Loading Hyde Project",
                f"Hyde found errors while loading {Path(exc.path).name}.\n\n{details}\n\nContinue with a partial load?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if result != QtWidgets.QMessageBox.Yes:
                self.project = None
                self.project_state = None
                self.project_path = None
                return False
            state = exc.partial_state
        self.project_state = state
        self.project_path = state.path
        self.window.setWindowTitle(f"Hyde - {Path(self.project_path).name}")
        self.script_entries = self.project.scan_scripts()
        restore_state = {
            "objects": {
                name: self._serialize_loaded_object(value)
                for name, value in state.objects.items()
            },
            "figures": state.session.get("figures", []),
            "tables": state.session.get("tables", []),
            "history": state.session.get("history", []),
            "incoming_shots": state.session.get("incoming_shots", []),
            "message_handler": state.session.get("message_handler", {"enabled": True}),
        }
        self._save_last_project()
        self.pending_callbacks[self.controller.send("set_project_root", self.project_path)] = lambda _r: None
        self.pending_callbacks[self.controller.send("restore", restore_state)] = self._after_project_restore
        return True

    def _after_project_restore(self, _response):
        if self.project is None or self.project_state is None:
            return
        layout = self.project_state.manifest.get("layout", {})
        self.window.restore_window_layout(layout)
        self.script_entries = self.project.scan_scripts()
        self._update_ui(self.last_snapshot or {"namespace_summary": [], "figures": [], "tables": []})
        if self.window.script_window.widget() is None:
            self.window.script_window.setWidget(self.window.procedure_browser)
        self.session_dirty = False

    def save_project(self):
        if self.project is None:
            self.save_project_as()
            return
        self._request_save()

    def save_project_as(self):
        default_path = self.project_path or str(Path.cwd() / "untitled.hy")
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            "Save Hyde Project As",
            default_path,
            "Hyde Projects (*.hy)",
        )
        if not path:
            return
        if self.project is not None:
            self.project = self.project.copy_to(path)
        else:
            self.project = HydeProject(path)
            self.project.ensure_layout()
        self.project_path = str(self.project.root)
        self.window.setWindowTitle(f"Hyde - {Path(self.project_path).name}")
        self.pending_callbacks[self.controller.send("set_project_root", self.project_path)] = lambda _r: None
        self._request_save()

    def _request_save(self):
        request_id = self.controller.send("snapshot")
        self.pending_callbacks[request_id] = self._save_snapshot_to_project

    def _request_save_sync(self):
        if self.project is None:
            return
        loop = QtCore.QEventLoop()
        request_id = self.controller.send("snapshot")

        def callback(response):
            self._save_snapshot_to_project(response)
            loop.quit()

        self.pending_callbacks[request_id] = callback
        loop.exec()

    def _save_snapshot_to_project(self, response):
        if self.project is None:
            return
        snapshot = response["snapshot"]
        snapshot["window_layout"] = self.window.save_window_layout()
        self.project_state = self.project.save_session(snapshot)
        self._save_last_project()
        self.script_entries = self.project.scan_scripts()
        self._update_ui(snapshot)
        self.session_dirty = False

    def export_archive(self):
        if self.project is None:
            return
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            "Export Hyde Archive",
            str(Path(self.project_path).with_suffix(".zip")),
            "Zip Archives (*.zip)",
        )
        if not path:
            return
        self.save_project()
        self.project.export_archive(path)

    def save_graphics(self):
        figure_id = self.window.current_figure_id()
        if figure_id is None:
            QtWidgets.QMessageBox.information(
                self.window,
                "Save Graphics",
                "Activate a figure window first.",
            )
            return
        snapshot = next((item for item in (self.last_snapshot or {}).get("figures", []) if item["id"] == figure_id), None)
        suggested_name = snapshot["title"] if snapshot is not None else figure_id
        suggested_name = re.sub(r"\W|^(?=\d)", "_", suggested_name) or "graph"
        default_base = Path(self.project.root if self.project is not None else Path.cwd())
        default_path = str(default_base / f"{suggested_name}.pdf")
        size_inches = self.window.current_figure_size_inches() or (6.4, 4.8)
        dialog = SaveGraphicsDialog(figure_id, default_path, size_inches=size_inches, parent=self.window)
        dialog.do_it_button.clicked.connect(lambda: self.generated_command(dialog.command()) or dialog.accept())
        dialog.to_cmd_button.clicked.connect(lambda: self.window.command_input.insert_command(dialog.command()))
        dialog.to_clip_button.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(dialog.command())
        )
        dialog.exec()

    def display_selection(self, names):
        if not names:
            return
        request_id = self.controller.send("snapshot")
        self.pending_callbacks[request_id] = self._display_figure_commands

    def _display_figure_commands(self, response):
        figure_dict = response.get("snapshot", {}).get("figures", {})
        if not figure_dict:
            return
        figure_id = list(figure_dict.keys())[0]
        figure = figure_dict[figure_id]
        script_source = figure.get("script_source", "")
        lines = script_source.strip().split("\n")
        for i, line in enumerate(lines):
            if line.startswith("from hyde"):
                lines.pop(i)
                break
        for line in lines:
            self.generated_command(line)

    def table_selection(self, names):
        if not names:
            return
        args = ", ".join(repr(name) for name in names)
        self.generated_command(f"open_table({args})")

    def append_to_graph_selection(self, names):
        figure_id = self.window.current_figure_id()
        if figure_id is None or not names:
            return
        if len(names) == 1:
            command = f"append_to_graph({figure_id!r}, {names[0]!r})"
            self.generated_command(command)
            return
        self.generated_command(f"append_to_graph({figure_id!r}, {names[0]!r}, x={names[1]!r})")

    def append_to_table_selection(self, names):
        table_id = self.window.current_table_id()
        if self.last_snapshot is None or not names:
            return
        if table_id is None:
            self.table_selection(names)
            return
        table = next((item for item in self.last_snapshot["tables"] if item["id"] == table_id), None)
        if table is None:
            self.table_selection(names)
            return
        object_names = list(dict.fromkeys(table["objects"] + list(names)))
        args = ", ".join(repr(name) for name in object_names)
        self.generated_command(f"open_table({args}, title={table['id']!r})")

    def copy_object_paths(self, names):
        if not names:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(f"root:{name}" for name in names))

    def delete_selection(self, names):
        for name in names:
            self.generated_command(f"delete_object({name!r})")

    def where_used_selection(self, names):
        for name in names:
            self.generated_command(f"show_where_used({name!r})")

    def fit_selection(self, names):
        self.open_fit_dialog(names)

    def new_graph(self):
        object_names = []
        if self.last_snapshot is not None:
            object_names = [
                entry["name"]
                for entry in self.last_snapshot.get("namespace_summary", [])
                if entry["kind"] == "numpy"
            ]
        selected_names = self.window.data_browser.selected_names()
        if not object_names:
            QtWidgets.QMessageBox.information(
                self.window,
                "New Graph",
                "Select one or more array-backed objects in the Data Browser first.",
            )
            return
        dialog = NewGraphDialog(object_names, selected_names=selected_names, parent=self.window)
        dialog.do_it_button.clicked.connect(lambda: self._execute_generated_multiline(dialog.command(), dialog))
        dialog.to_cmd_button.clicked.connect(
            lambda: self.window.command_input.insert_command(self._flatten_command(dialog.command()))
        )
        dialog.to_clip_button.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(dialog.command())
        )
        dialog.exec()

    def new_table(self):
        names = self.window.data_browser.selected_names()
        if not names:
            QtWidgets.QMessageBox.information(
                self.window,
                "New Table",
                "Select one or more objects in the Data Browser first.",
            )
            return
        self.table_selection(names)

    def new_python_script(self):
        if self.project is None:
            QtWidgets.QMessageBox.information(
                self.window,
                "New Python Script",
                "Open or create a Hyde project first.",
            )
            return
        default_path = self.project.root / "procedures" / "untitled.py"
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            "New Python Script",
            str(default_path),
            "Python files (*.py)",
        )
        if not path:
            return
        script_path = Path(path)
        if script_path.suffix != ".py":
            script_path = script_path.with_suffix(".py")
        try:
            script_path.resolve().relative_to(self.project.root.resolve())
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self.window,
                "New Python Script",
                "Scripts must live inside the current .hy project.",
            )
            return
        script_path.parent.mkdir(parents=True, exist_ok=True)
        if not script_path.exists():
            function_name = re.sub(r"\W|^(?=\d)", "_", script_path.stem) or "new_script"
            script_path.write_text(
                "from hyde import *\n\n\n@procedure\ndef "
                f"{function_name}():\n    pass\n",
                encoding="utf-8",
            )
        self.script_entries = self.project.scan_scripts()
        self._update_ui(self.last_snapshot or {"namespace_summary": [], "figures": [], "tables": []})
        self.open_external_editor(str(script_path))

    def open_fit_dialog(self, selected_names=None):
        selected_names = selected_names or self.window.data_browser.selected_names()
        if not selected_names and self.last_snapshot is not None:
            selected_names = [
                entry["name"]
                for entry in self.last_snapshot.get("namespace_summary", [])
                if entry["kind"] == "numpy"
            ]
        fit_entries = [entry for entry in self.script_entries if entry.kind == "fit_function"]
        if not fit_entries:
            QtWidgets.QMessageBox.information(
                self.window,
                "Curve Fit",
                "No fit functions are available. Add a script with an @fit_function or reopen the project to pick up the default fit functions.",
            )
            return
        if not selected_names:
            QtWidgets.QMessageBox.information(
                self.window,
                "Curve Fit",
                "Create or select at least one array before opening the fit dialog.",
            )
            return
        dialog = FitDialog(fit_entries, selected_names, self.project_path, self.window)
        dialog.do_it_button.clicked.connect(lambda: self.generated_command(dialog.command()) or dialog.accept())
        dialog.to_cmd_button.clicked.connect(lambda: self.window.command_input.insert_command(dialog.command()))
        dialog.graph_now_button.clicked.connect(lambda: self._graph_fit_preview(dialog))
        dialog.exec()

    def _fit_graph_target(self, y_name):
        if self.last_snapshot is None:
            return None
        figure_id = self.window.current_figure_id()
        if figure_id is None:
            return None
        figure = next((item for item in self.last_snapshot.get("figures", []) if item["id"] == figure_id), None)
        if figure is None:
            return None
        if any(trace.get("y_name") == y_name for trace in figure.get("traces", [])):
            return figure_id
        return None

    def _graph_fit_preview(self, dialog):
        graph_target = self._fit_graph_target(dialog.y_combo.currentText())
        if graph_target is None:
            QtWidgets.QMessageBox.information(
                self.window,
                "Graph Now",
                "Graph Now only works when the top window is a figure containing the selected Y data.",
            )
            return
        self.generated_command(
            dialog.command(
                graph_override=True,
                graph_target=graph_target,
                preview=True,
            )
        )

    def edit_table_value(self, object_name, row, column, value, append=False):
        if append:
            self.generated_command(f"{object_name}.append([{value!r}])")
            return
        index = f"{row}" if column == 0 else f"{row}, {column}"
        self.generated_command(f"{object_name}[{index}] = {value!r}")

    def delete_table_values(self, object_name, rows):
        if not rows:
            return
        self.generated_command(
            f"{object_name}.set_data(np.delete(np.asarray({object_name}), {rows!r}, axis=0))"
        )

    def run_script_entry(self, path, function_name):
        if self.project is None:
            return
        entry = next(
            (
                item
                for item in self.script_entries
                if item.path == path and item.function_name == function_name
            ),
            None,
        )
        if entry is not None and Path(path).resolve() == self.project.master_path.resolve():
            arguments = ", ".join(entry.parameters)
            self.generated_command(f"{function_name}({arguments})")
            return
        relative_path = os.path.relpath(path, self.project_path)
        self.generated_command(f"run_hyde_script({relative_path!r}, entry_point={function_name!r})")

    def open_external_editor(self, path):
        editor_path = self.exp_config.get("programs", "text_editor")
        editor_args = self.exp_config.get("programs", "text_editor_arguments")
        if "{file}" in editor_args:
            args = [arg if arg != "{file}" else path for arg in shlex.split(editor_args)]
        else:
            args = [path] + shlex.split(editor_args)
        subprocess.Popen([editor_path] + args)

    def handle_incoming_filepath(self, filepath):
        self.generated_command(f"record_incoming_shot({filepath!r})")

    def close_figure_requested(self, figure_id):
        if figure_id not in self.window.figure_windows:
            return
        snapshot = next((item for item in (self.last_snapshot or {}).get("figures", []) if item["id"] == figure_id), None)
        suggested_name = snapshot["title"] if snapshot is not None else figure_id
        suggested_name = re.sub(r"\W|^(?=\d)", "_", suggested_name) or "graph"
        dialog = CloseFigureDialog(suggested_name, self.window)
        if self.project is not None:
            dialog.save_selected.connect(
                lambda function_name: self._request_figure_script_and_close(figure_id, function_name)
            )
        else:
            dialog.save_button.setEnabled(False)
        dialog.discard_selected.connect(
            lambda: self.generated_command(f"close_figure({figure_id!r})", show_in_terminal=False, echo=False)
        )
        dialog.exec()

    def _request_figure_script_and_close(self, figure_id, function_name):
        if self.project is None:
            return
        if not function_name.strip():
            return
        request_id = self.controller.send(
            "get_figure_script",
            {"figure_id": figure_id, "function_name": function_name.strip()},
        )
        self.pending_callbacks[request_id] = lambda response: self._write_figure_script_and_close(
            figure_id, function_name.strip(), response
        )

    def _write_figure_script_and_close(self, figure_id, function_name, response):
        if self.project is None:
            return
        self.project.upsert_master_entry(function_name, response["script_source"])
        request_id = self.controller.send("set_project_root", self.project_path)
        self.pending_callbacks[request_id] = lambda _response: self._finalize_saved_master_entry(
            f"close_figure({figure_id!r})"
        )

    def close_table_requested(self, table_id):
        if table_id not in self.window.table_windows:
            return
        snapshot = next((item for item in (self.last_snapshot or {}).get("tables", []) if item["id"] == table_id), None)
        suggested_name = snapshot["title"] if snapshot is not None else table_id
        suggested_name = re.sub(r"\W|^(?=\d)", "_", suggested_name) or "table"
        dialog = CloseFigureDialog(suggested_name, self.window)
        if self.project is not None:
            dialog.save_selected.connect(
                lambda function_name: self._request_table_script_and_close(table_id, function_name)
            )
        else:
            dialog.save_button.setEnabled(False)
        dialog.discard_selected.connect(
            lambda: self.generated_command(f"close_table({table_id!r})", show_in_terminal=False, echo=False)
        )
        dialog.exec()

    def _request_table_script_and_close(self, table_id, function_name):
        if self.project is None:
            return
        if not function_name.strip():
            return
        request_id = self.controller.send(
            "get_table_script",
            {"table_id": table_id, "function_name": function_name.strip()},
        )
        self.pending_callbacks[request_id] = lambda response: self._write_table_script_and_close(
            table_id, function_name.strip(), response
        )

    def _write_table_script_and_close(self, table_id, function_name, response):
        if self.project is None:
            return
        self.project.upsert_master_entry(function_name, response["script_source"])
        request_id = self.controller.send("set_project_root", self.project_path)
        self.pending_callbacks[request_id] = lambda _response: self._finalize_saved_master_entry(
            f"close_table({table_id!r})"
        )

    def _finalize_saved_master_entry(self, close_command):
        self.script_entries = self.project.scan_scripts()
        self._update_ui(self.last_snapshot or {"namespace_summary": [], "figures": [], "tables": []})
        self.generated_command(
            close_command,
            show_in_terminal=False,
            echo=False,
            record_history=False,
        )

    def _execute_generated_multiline(self, command, dialog):
        if not command.strip():
            return
        for line in command.splitlines():
            self.generated_command(line)
        dialog.accept()

    def _flatten_command(self, command):
        return "; ".join(line.strip() for line in command.splitlines() if line.strip())

    def edit_active_figure(self):
        figure_id = self.window.current_figure_id()
        if figure_id is None or self.last_snapshot is None:
            return
        figure = next(item for item in self.last_snapshot["figures"] if item["id"] == figure_id)
        dialog = FigureEditDialog(figure_id, figure, self.window)
        live_state = {"dirty": False}
        dialog.command_changed.connect(
            lambda command: self._apply_live_dialog_command(dialog, command, live_state)
        )
        dialog.do_it_button.clicked.connect(lambda: self.generated_command(dialog.command()) or dialog.accept())
        dialog.to_cmd_button.clicked.connect(lambda: self.window.command_input.insert_command(dialog.command()))
        dialog.to_clip_button.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(dialog.command())
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            if live_state["dirty"]:
                self.generated_command(
                    self._suppressed_command(dialog.revert_command()),
                    show_in_terminal=False,
                    echo=False,
                    record_history=False,
                    silent=True,
                )
            return

    def edit_active_trace(self):
        figure_id = self.window.current_figure_id()
        if figure_id is None or self.last_snapshot is None:
            return
        figure = next(item for item in self.last_snapshot["figures"] if item["id"] == figure_id)
        dialog = TraceEditDialog(figure_id, figure, self.window)
        live_state = {"dirty": False}
        dialog.command_changed.connect(
            lambda command: self._apply_live_dialog_command(dialog, command, live_state)
        )
        dialog.do_it_button.clicked.connect(lambda: self.generated_command(dialog.command()) or dialog.accept())
        dialog.to_cmd_button.clicked.connect(lambda: self.window.command_input.insert_command(dialog.command()))
        dialog.to_clip_button.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(dialog.command())
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            if live_state["dirty"]:
                self.generated_command(
                    self._suppressed_command(dialog.revert_command()),
                    show_in_terminal=False,
                    echo=False,
                    record_history=False,
                    silent=True,
                )
            return

    def _apply_live_dialog_command(self, dialog, command, live_state):
        live_toggle = getattr(dialog, "live_update_checkbox", None)
        if live_toggle is not None and not live_toggle.isChecked():
            return
        if not command:
            return
        live_state["dirty"] = True
        self.generated_command(
            self._suppressed_command(command),
            show_in_terminal=False,
            echo=False,
            record_history=False,
            silent=True,
        )

    def _suppressed_command(self, command):
        command = command.rstrip()
        if not command or command.endswith(";"):
            return command
        return f"{command};"

    def close(self):
        self.window.close()

    def shutdown_requested(self):
        if self.session_dirty:
            result = QtWidgets.QMessageBox.question(
                self.window,
                "Save Changes?",
                "Save changes to the current Hyde project before quitting?",
                QtWidgets.QMessageBox.Save
                | QtWidgets.QMessageBox.Discard
                | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save,
            )
            if result == QtWidgets.QMessageBox.Cancel:
                return False
            if result == QtWidgets.QMessageBox.Save:
                self._request_save_sync()
        self.controller.stop()
        self._save_last_project()
        return True

    def _serialize_loaded_object(self, value):
        if hasattr(value, "to_serializable"):
            data = value.to_serializable()
            data["data"] = value.array.tolist()
            return data
        return {"kind": "json", "value": value}


def main(argv=None):
    desktop_app.set_process_appid("hyde")
    icon_path = os.path.join(os.path.dirname(__file__), "hyde.svg")
    splash = Splash(icon_path) if os.path.exists(icon_path) else None
    if splash is not None:
        splash.show()
        splash.update_text("starting Hyde")
    qapplication = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv or [])
    configure_qapplication(qapplication)
    if splash is not None:
        splash.update_text("creating QApplication")
    app = HydeApplication(qapplication, splash=splash)
    if splash is not None:
        splash.hide()
    return qapplication.exec()
