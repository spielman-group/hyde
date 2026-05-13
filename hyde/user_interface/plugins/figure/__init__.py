import logging
from functools import partial

from qtutils import inmain_decorator
from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.figure_comm import COMM_TARGET
from hyde.user_interface.plugin_tools import HydePlugin, blank_window_icon
from hyde.user_interface.window_naming import resolve_requested_name

from .dialogs import NewFigureDialog
from .window import FigureState, FigureWindow


LOGGER = logging.getLogger("hyde")


class FigureWorkspaceService:
    def __init__(self, plugin):
        self.plugin = plugin
        self.figures = {}

    def open_or_update_figure(self, payload):
        figure_number = int(payload.get("figure_number"))
        snapshot = dict(payload.get("snapshot", {}) or {})
        if not snapshot.get("is_first_class", False):
            LOGGER.debug(
                "Figure workspace ignored non-first-class figure payload for figure %s.",
                figure_number,
            )
            return None
        snapshot_metadata = dict(snapshot.get("hyde_metadata", {}) or {})
        figure = self.figures.get(figure_number)
        created_new = figure is None
        if figure is None:
            services = dict(self.plugin.services)
            services["save_window_dialog_service"] = self.plugin.services[
                "save_window_dialog_service"
            ]
            if hasattr(self.plugin, "send_figure_action"):
                services["send_figure_action"] = self.plugin.send_figure_action
            figure = FigureWindow(
                figure_number=figure_number,
                services=services,
            )
            stable_name, _ = resolve_requested_name(
                "Figure",
                {
                    live_figure.window_handle()
                    for live_figure in self.figures.values()
                },
                requested_name=(
                    snapshot.get("default_macro_name")
                    or payload.get("title")
                ),
            )
            subwindow = self.plugin.services["mdi_area"].addSubWindow(figure)
            subwindow.setWindowIcon(blank_window_icon())
            subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
            figure.bind_subwindow(subwindow, stable_name=stable_name)
            self.figures[figure_number] = figure
            subwindow.destroyed.connect(
                partial(self._on_subwindow_destroyed, figure_number)
            )
            subwindow.show()
        else:
            subwindow = figure.parentWidget()
            if subwindow is not None:
                subwindow.show()

        figure.update_payload(payload)
        if created_new:
            figure.apply_window_metadata(snapshot_metadata)
        subwindow = figure.parentWidget()
        if subwindow is not None and snapshot_metadata.get("window_state") != "minimized":
            subwindow.setFocus()
            subwindow.raise_()
        return figure

    def close_figure(self, figure_number):
        figure = self.figures.get(int(figure_number))
        if figure is None:
            return
        subwindow = figure.parentWidget()
        figure.close_from_kernel()
        if subwindow is None or not subwindow.isVisible():
            self._remove_figure(figure_number)

    def clear(self):
        for figure in list(self.figures.values()):
            figure.force_close()
        self.figures.clear()

    def _remove_figure(self, figure_number):
        figures = getattr(self, "figures", None)
        if figures is None:
            return
        figures.pop(int(figure_number), None)

    def _on_subwindow_destroyed(self, figure_number, *args):
        del args
        self._remove_figure(figure_number)


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
        command = dialog.get_command()
        if not command:
            return False
        self.plugin.services["python_execution_service"].execute_hidden(command)
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

    def setup(self, data=None):
        del data
        if self._signals_connected:
            return
        self.bind_menu_action("_new_figure_action", "window", "New Figure...")
        self._macro_menu = self._ensure_macro_menu()
        self.services["mdi_area"].subWindowActivated.connect(self.on_subwindow_activated)
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
            },
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

    def on_subwindow_activated(self, subwindow):
        show_menu = self.services.get("show_menu")
        hide_menu = self.services.get("hide_menu")
        widget = None if subwindow is None else subwindow.widget()
        if isinstance(widget, FigureWindow):
            if show_menu is not None:
                show_menu("figure")
        elif hide_menu is not None:
            hide_menu("figure")

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
        return {}

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
        self.services["python_execution_service"].execute_hidden(
            state.source_for_command("publish_figure_macros")
        )

    def on_project_loaded(self, data):
        del data
        self.workspace.clear()

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
        self.rebuild_window_macros_menu(
            menu=self._macro_menu,
            macros=self.figure_macros,
            empty_label="No Saved Graph Macros",
            new_action_attr="_new_figure_action",
            on_trigger=self._execute_macro,
        )

    def _ensure_macro_menu(self):
        if self._macro_menu is None:
            ui = self.services["ui"]
            self._macro_menu = QtWidgets.QMenu("Graph Macros", ui.menuWindow)
            ui.menuWindow.addMenu(self._macro_menu)
        return self._macro_menu

    def _register_comm_target(self):
        kernel_runtime_service = self.services.get("kernel_runtime_service")
        if kernel_runtime_service is None:
            return
        kernel_client = kernel_runtime_service.kernel_client()
        if kernel_client is None:
            return
        if kernel_client is self._registered_kernel_client:
            return
        if not kernel_runtime_service.register_comm_target(
            COMM_TARGET,
            self._on_figure_comm_open,
        ):
            return
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
