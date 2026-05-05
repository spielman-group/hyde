import copy
import logging
import uuid

from qtutils import inmain_decorator
from qtutils.qt import QtCore, QtWidgets

from hyde.features.matplotlib_features import FigureCodec, FigureIRCodec
from hyde.user_interface.figure_comm import COMM_TARGET
from hyde.user_interface.base import RuntimeCommandState
from hyde.user_interface.plugin_tools import HydePlugin, blank_window_icon
from hyde.user_interface.window_naming import next_numbered_name

from .dialogs import NewFigureDialog
from .window import FigureState, FigureWindow, prompt_to_save_figure_macro


LOGGER = logging.getLogger("hyde")


def _figure_state_with_default_title(state, default_title):
    normalized = FigureCodec.normalize_state(copy.deepcopy(state))
    if default_title and not normalized["settings"].get("title"):
        normalized["settings"]["title"] = str(default_title)
    return normalized


class FigureWorkspaceService:
    def __init__(self, plugin):
        self.plugin = plugin
        self.figures = {}
        self.figure_title_counter = 0
        self._pending_open_payloads = {}

    def next_generated_title(self):
        existing_titles = {
            figure.snapshot_state.default_macro_name()
            for figure in self.figures.values()
        }
        title, self.figure_title_counter = next_numbered_name(
            "Figure",
            existing_titles,
            self.figure_title_counter,
        )
        return title

    def open_or_update_figure(self, payload):
        figure_number = int(payload.get("figure_number"))
        snapshot = dict(payload.get("snapshot", {}) or {})
        snapshot_metadata = dict(snapshot.get("hyde_metadata", {}) or {})
        open_token = snapshot.get("open_token")
        pending = (
            None
            if open_token is None
            else self._pending_open_payloads.pop(str(open_token), None)
        )
        figure = self.figures.get(figure_number)
        created_new = figure is None
        if figure is None:
            services = dict(self.plugin.services)
            services["request_save_figure_macro"] = self.plugin.request_save_figure_macro
            if hasattr(self.plugin, "send_figure_action"):
                services["send_figure_action"] = self.plugin.send_figure_action
            figure = FigureWindow(
                figure_number=figure_number,
                services=services,
            )
            subwindow = self.plugin.services["mdi_area"].addSubWindow(figure)
            subwindow.setWindowIcon(blank_window_icon())
            subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
            figure.bind_subwindow(subwindow)
            self.figures[figure_number] = figure
            subwindow.destroyed.connect(
                lambda _=None, number=figure_number, workspace=self: (
                    workspace._remove_figure(number)
                )
            )
            subwindow.show()
        else:
            subwindow = figure.parentWidget()
            if subwindow is not None:
                subwindow.show()

        figure.update_payload(payload)
        pending_figure_ir = None if pending is None else pending.get("figure_ir")
        pending_live_state = None if pending is None else pending.get("live_state")
        snapshot_has_figure_ir = snapshot.get("figure_ir") is not None
        if pending_figure_ir is not None and snapshot.get("figure_ir") is None:
            figure.snapshot_state.update(
                default_macro_name=snapshot.get("default_macro_name"),
                call_source=snapshot.get("call_source"),
                save_error=snapshot.get("save_error"),
                figure_size=snapshot.get("figure_size"),
                tracked_names=snapshot.get("tracked_names"),
                figure_ir=pending_figure_ir,
                live_state=None,
            )
        if pending_live_state is not None and not snapshot_has_figure_ir:
            figure.set_live_state(pending_live_state)
            self.plugin.track_live_figure(figure_number, pending_live_state)
        if created_new:
            figure.apply_window_pos(snapshot_metadata.get("window_pos"))
        subwindow = figure.parentWidget()
        if subwindow is not None:
            subwindow.setFocus()
            subwindow.raise_()
        return figure

    def close_figure(self, figure_number):
        figure = self.figures.get(int(figure_number))
        if figure is None:
            return
        figure.close_from_kernel()

    def clear(self):
        for figure in list(self.figures.values()):
            figure.force_close()
        self.figures.clear()
        self.figure_title_counter = 0
        self._pending_open_payloads = {}

    def register_pending_open(self, *, figure_ir=None, live_state=None):
        token = str(uuid.uuid4())
        self._pending_open_payloads[token] = {
            "figure_ir": copy.deepcopy(figure_ir),
            "live_state": copy.deepcopy(live_state),
        }
        return token

    def _remove_figure(self, figure_number):
        figures = getattr(self, "figures", None)
        if figures is None:
            return
        figures.pop(int(figure_number), None)


class FigureFeatureService:
    def __init__(self, plugin):
        self.plugin = plugin

    def show_new_figure_dialog(self, objects_metadata, preselection=None, parent=None):
        dialog = NewFigureDialog(
            objects_metadata,
            preselection=preselection,
            parent=parent,
        )
        if not dialog.exec_():
            return False
        generated_title = self.plugin.workspace.next_generated_title()
        state = _figure_state_with_default_title(
            dialog.normalized_state(),
            generated_title,
        )
        if not state["items"]:
            return False
        open_token = self.plugin.workspace.register_pending_open(live_state=state)
        command = FigureCodec.state_to_python(
            {
                **copy.deepcopy(state),
                "settings": {
                    **copy.deepcopy(state.get("settings", {})),
                    "command": "create",
                    "open_token": open_token,
                },
            }
        )
        self.plugin.services["execute_command"](command, visible=False)
        return True


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.workspace = FigureWorkspaceService(self)
        self.figure_feature = FigureFeatureService(self)
        self.figure_macros = []
        self._signals_connected = False
        self._new_figure_action = None
        self._macro_menu = None
        self._registered_kernel_client = None
        self._figure_to_comm = {}
        self._comm_to_figure = {}

    def on_setup_complete(self, data=None):
        del data
        if self._signals_connected:
            return
        self.bind_menu_action("_new_figure_action", "window", "New Figure...")
        self._macro_menu = self._ensure_macro_menu()
        self._macro_menu.aboutToShow.connect(self.rebuild_figure_macros_menu)
        self.rebuild_figure_macros_menu()
        self._signals_connected = True

    def get_services(self):
        return {"figure_feature": self.figure_feature}

    def get_menu_contributions(self):
        return [
            {
                "location": "window",
                "group": "figures",
                "order": 30,
                "name": "New Figure...",
                "action": self.show_new_figure_dialog,
            }
        ]

    def show_new_figure_dialog(self, checked=False):
        del checked
        python_variables_service = self.services.get("namespace_view_service")
        self.figure_feature.show_new_figure_dialog(
            (
                {}
                if python_variables_service is None
                else python_variables_service.namespace_view()
            ),
            parent=self.services["ui"],
        )

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "kernel_crashed": self.on_kernel_crashed,
            "kernel_message": self.on_kernel_message,
            "kernel_ready": self.on_kernel_ready,
            "project_activated": self.on_project_activated,
            "project_loaded": self.on_project_loaded,
        }

    def get_session_toml_data(self):
        return {"figure_title_counter": self.workspace.figure_title_counter}

    def get_session_restore_source(self):
        blocks = []
        for figure_number in sorted(self.workspace.figures):
            figure = self.workspace.figures[figure_number]
            try:
                source = figure.session_restore_source()
            except Exception:
                LOGGER.exception(
                    "Figure session restore-source generation failed for figure %s.",
                    figure_number,
                )
                continue
            if source:
                blocks.append(source.strip())
        return "\n\n".join(blocks) + ("\n" if blocks else "")

    def on_enter_no_project_state(self, data):
        del data
        self.workspace.clear()
        self.figure_macros = []
        self.rebuild_figure_macros_menu()

    def on_kernel_crashed(self, data):
        del data
        self.workspace.clear()
        self._registered_kernel_client = None
        self._comm_to_figure = {}

    def on_project_activated(self, data):
        del data
        self.figure_macros = []
        self.rebuild_figure_macros_menu()
        state = FigureState()
        self.plugin_queue_background_command(
            state.source_for_command("publish_figure_macros"),
            silent=True,
        )

    def on_project_loaded(self, data):
        session = data["session"]
        saved_counter = int(session.get("figure_title_counter", 0))
        self.workspace.clear()
        self.workspace.figure_title_counter = saved_counter

    def on_kernel_ready(self, data):
        del data
        self._register_comm_target()

    def on_kernel_message(self, payload):
        if payload.get("task") != "WINDOW_MACROS_RESPONSE":
            return
        data = payload.get("data", {})
        if data.get("kind") != "figure":
            return
        self.figure_macros = [
            {
                "name": macro["name"],
                "args": list(macro.get("args", [])),
            }
            for macro in data.get("macros", [])
        ]
        self.rebuild_figure_macros_menu()

    def rebuild_figure_macros_menu(self):
        menu = self._macro_menu
        menu.clear()
        has_project = self.services["get_current_project_dir"]() is not None
        if self._new_figure_action is not None:
            self._new_figure_action.setEnabled(has_project)
        if not has_project:
            menu.setEnabled(False)
            return
        if not self.figure_macros:
            placeholder = menu.addAction("No Saved Graph Macros")
            placeholder.setEnabled(False)
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        for macro in self.figure_macros:
            macro_name = macro["name"]
            macro_args = tuple(macro.get("args", []))
            action = menu.addAction(macro_name)
            action.triggered.connect(
                lambda checked=False, name=macro_name, args=macro_args: (
                    self._execute_macro(name, args)
                )
            )

    def request_save_figure_macro(self, saveable):
        procedures_init = self.services["get_procedures_init"]()
        if not procedures_init:
            return True
        return prompt_to_save_figure_macro(
            saveable,
            parent=self.services["ui"],
            procedures_init=procedures_init,
            reload_procedures=self.services["reload_procedures"],
        )

    def plugin_queue_background_command(self, code, silent=True):
        return self.services["queue_background_command"](code, silent=silent)

    def track_live_figure(self, figure_number, state):
        command_state = FigureState()
        return self.plugin_queue_background_command(
            command_state.source_for_command(
                "track",
                figure_number=figure_number,
                tracked_state=state,
            ),
            silent=True,
        )

    def _execute_macro(self, macro_name, macro_args):
        state = RuntimeCommandState()
        state.set_callable_invocation(macro_name, macro_args)
        self.services["execute_command"](f"{state.python_source()};", visible=True)

    def _ensure_macro_menu(self):
        if self._macro_menu is None:
            ui = self.services["ui"]
            self._macro_menu = QtWidgets.QMenu("Graph Macros", ui.menuWindow)
            ui.menuWindow.addMenu(self._macro_menu)
        return self._macro_menu

    def _register_comm_target(self):
        terminal_service = self.services.get("visible_terminal_service")
        if terminal_service is None:
            return
        widget = terminal_service.ensure_widget()
        kernel_client = None if widget is None else widget.kernel_client
        comm_manager = None if kernel_client is None else getattr(kernel_client, "comm_manager", None)
        if comm_manager is None:
            return
        if kernel_client is self._registered_kernel_client:
            return
        comm_manager.register_target(COMM_TARGET, self._on_figure_comm_open)
        self._registered_kernel_client = kernel_client

    def _on_figure_comm_open(self, comm, msg):
        payload = msg["content"]["data"]
        figure_number = int(payload.get("figure_number"))
        LOGGER.debug(
            "Figure plugin opened comm %s for figure %s.",
            comm.comm_id,
            figure_number,
        )
        self._figure_to_comm[figure_number] = comm
        self._comm_to_figure[comm.comm_id] = figure_number
        comm.on_msg(lambda message, current_comm=comm: self._on_figure_comm_message(current_comm, message))
        comm.on_close(lambda message, current_comm=comm: self._on_figure_comm_close(current_comm, message))
        self._handle_figure_payload(payload)

    def _on_figure_comm_message(self, comm, msg):
        LOGGER.debug(
            "Figure plugin received comm message on %s: %s",
            comm.comm_id,
            msg.get("content", {}).get("data", {}).get("event"),
        )
        self._handle_figure_payload(msg["content"]["data"])

    def _on_figure_comm_close(self, comm, msg):
        del msg
        figure_number = self._comm_to_figure.pop(comm.comm_id, None)
        if figure_number is not None:
            LOGGER.debug(
                "Figure plugin observed comm %s close for figure %s.",
                comm.comm_id,
                figure_number,
            )
            self._figure_to_comm.pop(figure_number, None)
            self._handle_figure_close(figure_number)

    @inmain_decorator()
    def _handle_figure_payload(self, payload):
        event = payload.get("event")
        if event == "close":
            self._handle_figure_close(payload.get("figure_number"))
            return
        self.workspace.open_or_update_figure(payload)

    @inmain_decorator()
    def _handle_figure_close(self, figure_number):
        if figure_number is None:
            return
        self.workspace.close_figure(figure_number)

    def send_figure_action(self, figure_number, action):
        comm = self._figure_to_comm.get(int(figure_number))
        if comm is None:
            LOGGER.warning(
                "Figure plugin could not send action for figure %s because no comm is registered.",
                figure_number,
            )
            return False
        try:
            comm.send(
                {
                    "event": "action",
                    "figure_number": int(figure_number),
                    "action": dict(action or {}),
                }
            )
        except Exception:
            LOGGER.exception(
                "Figure plugin failed to send action for figure %s: %r",
                figure_number,
                action,
            )
            return False
        LOGGER.debug(
            "Figure plugin sent action for figure %s: %r",
            figure_number,
            action,
        )
        return True
