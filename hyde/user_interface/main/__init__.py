import logging
import os
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore
from qtutils.outputbox import BLUE, GREEN, ORANGE, RED, WHITE
from labscript_utils.filewatcher import FileWatcher

from hyde.features.hyde_ir import HydeAppIR
from hyde.paths import (
    HYDE_DIR,
    get_project_paths,
)
from hyde.user_interface.main.project_state import (
    apply_mdi_window_order,
    try_read_history,
    try_read_session,
    try_read_session_source,
    restore_main_window,
    write_history,
    write_session,
)
from hyde.user_interface.shared.plugin import (
    HydeMDIContext,
    HydeMenuContext,
    HydePluginManager,
    blank_window_icon,
    finalize_subwindow_state,
)

class PersistentSubwindowFilter(QtCore.QObject):
    """Turn MDI close requests into hide requests so tool windows persist."""

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Close:
            widget = watched.widget()
            allows_close = getattr(widget, "allows_subwindow_close", None)
            if callable(allows_close) and allows_close():
                return super().eventFilter(watched, event)
            watched.hide()
            event.ignore()
            return True
        return super().eventFilter(watched, event)


def connect_logger_to_output_sink(logger_name, sink):
    class OutputSinkLogHandler(logging.Handler):
        def emit(self, record):
            message = self.format(record)
            raw_message = record.getMessage()
            # The runtime output sink owns the thread-safe transport to the
            # logging window, including the OutputBox queue path.
            if raw_message.startswith("[Hyde state] "):
                prefix, _, _ = message.partition(raw_message)
                header, rest = raw_message.split("\nstate:\n", 1)
                header = f"{prefix}{header}" if prefix else header
                state_text, python_text = rest.split("\npython:\n", 1)
                sink.write(f"{header}\n", color=ORANGE)
                sink.write("state:\n", color=ORANGE)
                sink.write(f"{state_text}\n", color=GREEN)
                sink.write("python:\n", color=ORANGE)
                sink.write(f"{python_text}\n", color=BLUE)
            else:
                sink.write(
                    f"{message}\n",
                    color=RED if record.levelno >= logging.WARNING else WHITE,
                )

    logger = logging.getLogger(logger_name)
    handler = OutputSinkLogHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    return handler


class VisibleCommandNotificationService:
    def __init__(self, app):
        self._app = app

    def on_command_executed(self, message):
        handler = getattr(self._app, "on_visible_command_executed", None)
        return None if handler is None else handler(message)


class ProjectProceduresService:
    def __init__(self, app):
        self._app = app

    def current_project_dir(self):
        getter = getattr(self._app, "get_current_project_dir", None)
        if callable(getter):
            return getter()
        return getattr(self._app, "current_project_dir", None)

    def procedures_init(self):
        getter = getattr(self._app, "get_procedures_init", None)
        if callable(getter):
            return getter()
        return getattr(self._app, "procedures_init", None)

    def reload_procedures(self):
        reloader = getattr(self._app, "reload_procedures", None)
        return None if reloader is None else reloader()


class HydeMainWindow(QtWidgets.QMainWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    def closeEvent(self, event):
        if self.app._close_ready:
            return super().closeEvent(event)
        if self.app.shutting_down:
            self.app.begin_shutdown_from_close_event()
        else:
            self.app.request_quit()
        event.ignore()

class HydeApp:
    def __init__(self, qapplication, process_tree, splash, argv=None):
        self.qapplication = qapplication
        self.process_tree = process_tree
        self.splash = splash
        self.argv = argv or []
        self.current_project_dir = None
        self.current_app_ir = self._build_current_app_ir()
        self.procedures_dir = None
        self.procedures_init = None
        self.filewatcher = None
        self._subwindow_filters = []
        self.shutting_down = False
        self._runtime_shutdown = False
        self._close_ready = False
        self._quit_command_sent = False
        self._startup_complete = False
        self._session_restore_presentation_deferred = False
        self._session_restore_tool_windows = {}
        self._session_restore_session = None
        self._session_restore_finalize_retries = 0
        self._session_restore_last_named_count = None
        self.plugin_manager = HydePluginManager(
            plugin_package="hyde.user_interface.plugins",
            plugins_dir=os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins"),
            logger=logging.getLogger("hyde"),
        )
        
        # Load the UI
        loader = UiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), 'main.ui')
        self.ui = loader.load(ui_path, HydeMainWindow(self))
        self.ui.mdiArea.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.mdiArea.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.menuFile.clear()
        self.ui.menuWindow.clear()
        self.ui.menuFigure.clear()
        self.ui.menuTable.clear()
        self.plugin_manager.discover_modules()
        self.plugin_manager.instantiate_plugins()
        self.setup_plugins()
        self.logging_handler = None
        logging_service = self.plugin_service("runtime_output_service")
        if logging_service is not None:
            try:
                self.logging_handler = connect_logger_to_output_sink(
                    "hyde",
                    logging_service,
                )
            except Exception as exc:
                print(
                    "[Hyde] Could not connect runtime output service; "
                    f"continuing without log redirection: {exc}"
                )

        self.qapplication.aboutToQuit.connect(self._mark_shutting_down)

    def plugin_services(self):
        plugin_manager = getattr(self, "plugin_manager", None)
        return getattr(plugin_manager, "services", {})

    def plugin_service(self, key):
        return self.plugin_services().get(key)

    def build_plugin_services(self):
        return {
            "ui": self.ui,
            "mdi_area": self.ui.mdiArea,
            "menu_context": getattr(self, "menu_context", None),
            "lookup_menu_action": self.lookup_menu_action,
            "show_menu": self.show_menu,
            "hide_menu": self.hide_menu,
            "popup_menu": self.popup_menu,
            "mdi_context": getattr(self, "mdi_context", None),
            "configure_persistent_subwindow": self.configure_persistent_subwindow,
            "emit_plugin_event": self.emit_plugin_event,
            "process_tree": self.process_tree,
            "project_procedures_service": ProjectProceduresService(self),
            "visible_command_notification_service": (
                VisibleCommandNotificationService(self)
            ),
            "get_current_project_dir": self.get_current_project_dir,
            "get_current_app_ir": self.get_current_app_ir,
            "get_shutting_down": self.get_shutting_down,
            "set_shutting_down": self.set_shutting_down,
            "get_quit_command_sent": self.get_quit_command_sent,
            "set_quit_command_sent": self.set_quit_command_sent,
            "begin_project_operation": self.begin_project_operation,
            "project_target_needs_confirmation": self.project_target_needs_confirmation,
            "confirm_overwrite_project": self.confirm_overwrite_project,
            "finalize_quit": self.finalize_quit,
            "show_window": self.show_plugin_window,
            "on_kernel_ready": self.on_kernel_ready,
            "on_kernel_crashed": self.on_kernel_crashed,
            "enter_no_project_state": self.enter_no_project_state,
            "activate_project": self.activate_project,
            "on_project_state_result": self.on_project_state_result,
            "request_gui_quit": self.request_gui_quit,
            "get_session_restore_presentation_deferred": (
                getattr(
                    self,
                    "get_session_restore_presentation_deferred",
                    lambda: False,
                )
            ),
            "register_session_restore_tool_window": (
                getattr(
                    self,
                    "register_session_restore_tool_window",
                    lambda name, subwindow, info: None,
                )
            ),
            "on_task_complete": getattr(self, "on_task_complete", lambda data: None),
        }

    def get_current_project_dir(self):
        return self.current_project_dir

    def _build_current_app_ir(self):
        return HydeAppIR(current_project_dir=self.current_project_dir)

    def get_current_app_ir(self):
        return self.current_app_ir

    def get_procedures_init(self):
        return self.procedures_init

    def get_shutting_down(self):
        return self.shutting_down

    def set_shutting_down(self, value):
        self.shutting_down = bool(value)

    def get_quit_command_sent(self):
        return self._quit_command_sent

    def set_quit_command_sent(self, value):
        self._quit_command_sent = bool(value)

    def get_session_restore_presentation_deferred(self):
        return self._session_restore_presentation_deferred

    def register_session_restore_tool_window(self, name, subwindow, info):
        self._session_restore_tool_windows[str(name)] = (
            subwindow,
            dict(info or {}),
        )

    def lookup_menu_action(self, location, name, path=()):
        menu_context = getattr(self, "menu_context", None)
        if menu_context is None:
            return None
        return menu_context.lookup_action(location, name, path=path)

    def show_menu(self, location):
        menu_context = getattr(self, "menu_context", None)
        menu = None if menu_context is None else menu_context.locations.get(location)
        if menu is None:
            return None
        menu.menuAction().setVisible(True)
        return menu

    def hide_menu(self, location):
        menu_context = getattr(self, "menu_context", None)
        menu = None if menu_context is None else menu_context.locations.get(location)
        if menu is None:
            return None
        menu.menuAction().setVisible(False)
        return menu

    def popup_menu(self, location, global_pos):
        menu_context = getattr(self, "menu_context", None)
        menu = None if menu_context is None else menu_context.build_popup_menu(
            location,
            parent=self.ui,
        )
        if menu is None:
            return None
        return menu.exec_(global_pos)

    def setup_plugins(self):
        self.menu_context = HydeMenuContext(logger=logging.getLogger("hyde"))
        self.menu_context.register_location("file", self.ui.menuFile)
        self.menu_context.register_location("analysis", self.ui.menuAnalysis)
        self.menu_context.register_location("window", self.ui.menuWindow)
        self.menu_context.register_location("figure", self.ui.menuFigure)
        self.menu_context.register_location("table", self.ui.menuTable)

        self.mdi_context = HydeMDIContext(
            self.ui.mdiArea,
            configure_subwindow=self.configure_persistent_subwindow,
        )

        self.plugin_manager.register_context("menus", self.menu_context)
        self.plugin_manager.register_context("mdi", self.mdi_context)

        plugin_data = {
            "services": self.plugin_manager.collect_services(
                self.build_plugin_services()
            ),
        }
        self.plugin_manager.setup_contexts(plugin_data)
        self.menu_context.render()
        # Opening a menu refreshes its own items, but a keyboard shortcut never
        # opens one. Refresh on activation so a shortcut is gated by the window
        # the user is actually looking at.
        self.ui.mdiArea.subWindowActivated.connect(
            lambda _subwindow: self.menu_context.refresh_enabled_states()
        )
        self.hide_menu("figure")
        self.hide_menu("table")
        self.plugin_manager.setup_complete(plugin_data)

    def show_plugin_window(self, key):
        return self.mdi_context.show(key)

    @inmain_decorator()
    def emit_plugin_event(self, name, data=None):
        payload = {} if data is None else data
        logger = logging.getLogger("hyde")
        for handler in self.plugin_manager.get_event_handlers(name):
            try:
                handler(payload)
            except Exception:
                logger.exception(
                    "Plugin event handler failed for '%s'.", name
                )
        return payload

    def stop_project_watcher(self):
        if self.filewatcher is not None:
            self.filewatcher.stop()
            self.filewatcher = None

    def restart_project_watcher(self):
        self.stop_project_watcher()
        if self.current_project_dir is None or self.procedures_dir is None or self.procedures_init is None:
            return
        watched_files = [self.procedures_init] if os.path.exists(self.procedures_init) else []
        self.filewatcher = FileWatcher(
            self.on_procedure_change,
            files=watched_files,
            folders=[self.procedures_dir],
            hashable_types=[".py"],
            interval=0.5,
        )

    @inmain_decorator()
    def on_procedure_change(self, name, info, event=None):
        del info
        if event == "original":
            return
        if name != "all" and not name.endswith(".py"):
            return
        HydeApp.reload_procedures(self)

    def configure_persistent_subwindow(self, subwindow):
        subwindow.setWindowIcon(blank_window_icon())
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        event_filter = PersistentSubwindowFilter(subwindow)
        subwindow.installEventFilter(event_filter)
        self._subwindow_filters.append(event_filter)

    def resolve_startup_project(self):
        if not self.argv:
            return None
        candidate = os.path.abspath(self.argv[0])
        if candidate.endswith('.hy') and os.path.isdir(candidate):
            return candidate
        return None

    def confirm_overwrite_project(self, project_dir):
        response = QtWidgets.QMessageBox.question(
            self.ui,
            "Overwrite Project",
            (
                f"{project_dir} already exists.\n\n"
                "Overwrite the existing path?"
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def project_target_needs_confirmation(self, project_dir):
        if not os.path.exists(project_dir):
            return False
        if not os.path.isdir(project_dir):
            return True
        with os.scandir(project_dir) as entries:
            return any(entries)

    def begin_project_operation(self, label):
        self.set_project_status_message(label)

    def set_project_status_message(self, label):
        self.ui.statusbar.showMessage(label)

    def clear_project_status_message(self):
        self.ui.statusbar.clearMessage()

    def end_project_operation(self):
        self.clear_project_status_message()

    def request_quit(self, checked=False):
        del checked
        self.emit_plugin_event("request_application_quit", {})

    @inmain_decorator()
    def enter_no_project_state(self):
        self.current_project_dir = None
        self.current_app_ir = self._build_current_app_ir()
        self.procedures_dir = None
        self.procedures_init = None
        self.stop_project_watcher()
        self.ui.setWindowTitle("Hyde")
        self.emit_plugin_event("enter_no_project_state", {})

    @inmain_decorator()
    def activate_project(self, project_dir):
        if not project_dir:
            return
        project_dir = os.path.abspath(project_dir)
        if self.current_project_dir is not None and os.path.abspath(self.current_project_dir) == project_dir:
            return
        self.current_project_dir, self.procedures_dir, self.procedures_init = get_project_paths(project_dir)
        self.current_app_ir = self._build_current_app_ir()
        self.ui.setWindowTitle(f"Hyde - {os.path.basename(self.current_project_dir)}")
        self.restart_project_watcher()
        self.emit_plugin_event(
            "project_activated",
            {
                "project_dir": self.current_project_dir,
                "procedures_dir": self.procedures_dir,
            },
        )

    def reload_procedures(self):
        app_ir = getattr(self, "current_app_ir", None)
        project_dir = getattr(app_ir, "current_project_dir", None)
        if project_dir is None:
            project_dir = self.current_project_dir
        if project_dir is None:
            return
        if app_ir is None:
            app_ir = HydeAppIR(current_project_dir=project_dir)
        reload_ir = app_ir.with_reload_procedures(
            project_dir,
            os.path.dirname(HYDE_DIR),
            reset_namespace=False,
        )
        python_execution_service = self.plugin_service("python_execution_service")
        if python_execution_service is not None:
            python_execution_service.execute_hidden(
                app_ir.current_diff(reload_ir).python_source()
            )

    @inmain_decorator()
    def finalize_startup(self):
        try:
            startup_project = None
            if not self._startup_complete:
                self.ui.show()
                self.splash.hide()
                self._startup_complete = True
                startup_project = self.resolve_startup_project()
            self.set_project_status_message("Connecting to Jupyter Kernel Socket...")
            self.emit_plugin_event("kernel_ready", {})
            self.enter_no_project_state()
            if startup_project is not None:
                QtCore.QTimer.singleShot(
                    100,
                    lambda path=startup_project: self._load_startup_project(path),
                )
            else:
                self.clear_project_status_message()
        except Exception:
            import traceback
            traceback.print_exc()

    def _load_startup_project(self, path):
        self.emit_plugin_event("request_project_load", {"project_dir": path})

    @inmain_decorator()
    def on_kernel_ready(self):
        self.finalize_startup()

    @inmain_decorator()
    def on_kernel_crashed(self):
        if self.shutting_down:
            return
        self._quit_command_sent = False
        self.enter_no_project_state()
        self.end_project_operation()
        self.emit_plugin_event("kernel_crashed", {})
        QtWidgets.QMessageBox.warning(
            self.ui,
            "Kernel Crashed",
            "The IPython execution kernel died unexpectedly. Hyde is reconnecting to a fresh kernel.",
        )

    @inmain_decorator()
    def on_project_state_result(self, data):
        operation = data.get('operation')
        mode = data.get('mode')
        success = bool(data.get('success', False))
        path = data.get('path')
        errors = list(data.get('errors', []))

        self.end_project_operation()

        if operation == 'save':
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Save Warnings", "\\n".join(errors))
            if success:
                try:
                    errors.extend(write_session(self, path) or [])
                except Exception as exc:
                    errors.append(f"session persistence: {exc}")
                try:
                    write_history(self, path)
                except Exception as exc:
                    errors.append(f"history persistence: {exc}")
                if errors:
                    QtWidgets.QMessageBox.warning(
                        self.ui,
                        "Project Save Warnings",
                        "\\n".join(errors),
                    )
                if mode == 'save_as':
                    self.restore_project_session()
            
        elif operation == 'new':
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Creation Warnings", "\\n".join(errors))

        elif operation == 'load':
            if success:
                self.restore_project_session()
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Load Warnings", "\\n".join(errors))
        elif operation == 'heal':
            if success and errors:
                QtWidgets.QMessageBox.information(self.ui, "Project Heal Complete", "\\n".join(errors))
            elif not success and errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Heal Warnings", "\\n".join(errors))

    @inmain_decorator()
    def on_visible_command_executed(self, msg):
        content = msg.get("content", {})
        if content.get("status") != "ok":
            self._quit_command_sent = False
            self.end_project_operation()

    def _mark_shutting_down(self):
        self.shutting_down = True

    @inmain_decorator()
    def request_gui_quit(self):
        self.shutting_down = True
        self.ui.close()

    def finalize_quit(self):
        if self._close_ready:
            return
        self.shutting_down = True
        self._close_ready = True
        self.ui.close()

    def begin_shutdown_from_close_event(self):
        if self._runtime_shutdown:
            return
        self._runtime_shutdown = True
        self.stop_project_watcher()
        self.emit_plugin_event("application_shutdown", {})
        self.emit_plugin_event("request_runtime_shutdown", {})

    def _clear_session_restore_state(self):
        self._session_restore_presentation_deferred = False
        self._session_restore_tool_windows = {}
        self._session_restore_session = None
        self._session_restore_finalize_retries = 0
        self._session_restore_last_named_count = None

    def _schedule_session_restore_order_finalize(self):
        QtCore.QTimer.singleShot(0, self._finalize_session_restore_order)

    def _finalize_session_restore_order(self):
        session = self._session_restore_session
        if session is None:
            return
        mdi_area = getattr(self.ui, "mdiArea", None)
        if mdi_area is None:
            self._clear_session_restore_state()
            return
        window_order = session.get("main_window", {}).get("mdi_window_order", [])
        apply_mdi_window_order(mdi_area, window_order)
        named_count = sum(
            1
            for subwindow in mdi_area.subWindowList(QtWidgets.QMdiArea.StackingOrder)
            if str(subwindow.objectName() or "").strip()
        )
        if (
            self._session_restore_finalize_retries <= 0
            or named_count == self._session_restore_last_named_count
        ):
            self._clear_session_restore_state()
            return
        self._session_restore_last_named_count = named_count
        self._session_restore_finalize_retries -= 1
        self._schedule_session_restore_order_finalize()

    def _complete_session_restore(self, success):
        session = self._session_restore_session
        if session is None:
            return
        if success:
            for name, (subwindow, info) in list(
                self._session_restore_tool_windows.items()
            ):
                finalize_subwindow_state(
                    subwindow,
                    info,
                    session_key=name,
                )
            self._session_restore_finalize_retries = 3
            self._session_restore_last_named_count = None
            self._schedule_session_restore_order_finalize()
            return
        self._clear_session_restore_state()

    @inmain_decorator()
    def on_task_complete(self, data):
        data = dict(data or {})
        if data.get("name") != "session_restore":
            return
        self._complete_session_restore(bool(data.get("success", False)))

    def restore_project_session(self):
        self._clear_session_restore_state()
        warnings = []
        history_entries, history_error = try_read_history(self.current_project_dir)
        if history_error:
            warnings.append(f"terminal/history.py: {history_error}")
        python_terminal_service = self.plugin_service("visible_terminal_service")
        if python_terminal_service is not None:
            python_terminal_service.restore_history_entries(history_entries)
        session, session_error = try_read_session(self.current_project_dir)
        if session_error:
            warnings.append(f"session.toml: {session_error}")
        session_source, session_source_error = try_read_session_source(
            self.current_project_dir
        )
        if session_source_error:
            warnings.append(f"session.py: {session_source_error}")
        if warnings:
            QtWidgets.QMessageBox.warning(
                self.ui,
                "Project Session Restore Warnings",
                "\n".join(warnings),
            )
        self._session_restore_presentation_deferred = True
        self._session_restore_session = session
        if session:
            restore_main_window(self, session)
        self.emit_plugin_event("project_loaded", {"session": session})
        if str(session_source or "").strip():
            python_execution_service = self.plugin_service("python_execution_service")
            if python_execution_service is not None:
                restore_ir = self.current_app_ir.with_session_restore_source(
                    session_source
                )
                if python_execution_service.execute_hidden(
                    self.current_app_ir.current_diff(restore_ir).python_source()
                ):
                    return
            self._complete_session_restore(False)
        else:
            self._complete_session_restore(True)
