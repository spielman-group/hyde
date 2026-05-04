import logging
import os
import time
from labscript_utils.plugins import MenuContext
from qtutils import UiLoader, inmain_decorator
from qtutils.qt import QtWidgets, QtCore
from qtutils.outputbox import BLUE, GREEN, ORANGE, RED, WHITE
from labscript_utils.filewatcher import FileWatcher
from zmq.error import ZMQError

from hyde.paths import (
    CONNECTION_FILE,
    HYDE_DIR,
    KERNEL_LAUNCHER,
    get_project_paths,
)
from hyde.features.hyde_features import (
    format_procedures_bootstrap_code,
)
from hyde.user_interface.file_dialogs import (
    LoadProjectState,
    QuitCommand,
)
from hyde.user_interface.runtime_helper import HYDE_REMOTE_PORT, RemoteRequestServer, RuntimeHelper
from hyde.user_interface.project_state import (
    clear_tables,
    try_read_history,
    try_read_session,
    restore_main_window,
    write_history,
    write_session,
)
from hyde.user_interface.plugin_tools import HydeMDIContext, HydePluginManager

qt_slot = getattr(QtCore, "Slot", QtCore.pyqtSlot)

class PersistentSubwindowFilter(QtCore.QObject):
    """Turn MDI close requests into hide requests so tool windows persist."""

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Close:
            watched.hide()
            event.ignore()
            return True
        return super().eventFilter(watched, event)


def connect_logger_to_output_box(logger_name, output_box):
    class OutputBoxLogHandler(logging.Handler):
        def emit(self, record):
            message = self.format(record)
            raw_message = record.getMessage()
            # OutputBox.write() is the thread-safe entry point here: it pushes
            # text through OutputBox's internal socket/queue path and its
            # add_text() method is already marshalled onto the Qt main thread.
            if raw_message.startswith("[Hyde state] "):
                prefix, _, _ = message.partition(raw_message)
                header, rest = raw_message.split("\nstate:\n", 1)
                header = f"{prefix}{header}" if prefix else header
                state_text, python_text = rest.split("\npython:\n", 1)
                output_box.write(f"{header}\n", color=ORANGE)
                output_box.write("state:\n", color=ORANGE)
                output_box.write(f"{state_text}\n", color=GREEN)
                output_box.write("python:\n", color=ORANGE)
                output_box.write(f"{python_text}\n", color=BLUE)
            else:
                output_box.write(
                    f"{message}\n",
                    color=RED if record.levelno >= logging.WARNING else WHITE,
                )

    logger = logging.getLogger(logger_name)
    handler = OutputBoxLogHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    return handler

class HydeMainWindow(QtWidgets.QMainWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    @qt_slot()
    def _on_kernel_ready(self):
        self.app.finalize_startup()

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
        self.procedures_dir = None
        self.procedures_init = None
        self.kernel_to_child = None
        self.kernel_from_child = None
        self.kernel_process = None
        self.runtime_helper = None
        self.filewatcher = None
        self.remote_server = None
        self._subwindow_filters = []
        self.shutting_down = False
        self._runtime_shutdown = False
        self._close_ready = False
        self._quit_command_sent = False
        self._quit_deadline = None
        self._startup_complete = False
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
        self.plugin_manager.discover_modules()
        self.plugin_manager.instantiate_plugins()
        self.setup_plugins()
        self._ensure_static_plugin_windows()
        self.logging_handler = connect_logger_to_output_box(
            "hyde",
            self.logging_window.output_box,
        )

        self.qapplication.aboutToQuit.connect(self._mark_shutting_down)

        try:
            self.remote_server = RemoteRequestServer(self, HYDE_REMOTE_PORT)
        except ZMQError as exc:
            print(f"[Hyde] Could not start lyse-compatible remote listener: {exc}")
            self.remote_server = None
        self.start_kernel_runtime()

    def _plugin_widget(self, key):
        mdi_context = getattr(self, "mdi_context", None)
        if mdi_context is None:
            return None
        return mdi_context.widget(key)

    def _plugin_subwindow(self, key):
        mdi_context = getattr(self, "mdi_context", None)
        if mdi_context is None:
            return None
        return mdi_context.subwindow(key)

    @property
    def command_window(self):
        return self._plugin_widget("command_window")

    @property
    def command_subwindow(self):
        return self._plugin_subwindow("command_window")

    @property
    def data_browser(self):
        return self._plugin_widget("data_browser")

    @property
    def data_browser_subwindow(self):
        return self._plugin_subwindow("data_browser")

    @property
    def logging_window(self):
        return self._plugin_widget("logging")

    @property
    def logging_subwindow(self):
        return self._plugin_subwindow("logging")

    @property
    def procedure_browser(self):
        return self._plugin_widget("procedures")

    @property
    def procedures_subwindow(self):
        return self._plugin_subwindow("procedures")

    def build_plugin_services(self):
        return {
            "ui": self.ui,
            "mdi_area": self.ui.mdiArea,
            "menu_context": getattr(self, "menu_context", None),
            "mdi_context": getattr(self, "mdi_context", None),
            "configure_persistent_subwindow": self.configure_persistent_subwindow,
            "execute_command": self.execute_command,
            "queue_background_command": self.queue_background_command,
            "get_current_project_dir": self.get_current_project_dir,
            "get_procedures_init": self.get_procedures_init,
            "get_command_window": self.get_command_window,
            "get_namespace_view": self.get_namespace_view,
            "connect_namespace_view_updated": self.connect_namespace_view_updated,
            "disconnect_namespace_view_updated": self.disconnect_namespace_view_updated,
            "get_shutting_down": self.get_shutting_down,
            "set_shutting_down": self.set_shutting_down,
            "get_quit_command_sent": self.get_quit_command_sent,
            "set_quit_command_sent": self.set_quit_command_sent,
            "begin_project_operation": self.begin_project_operation,
            "project_target_needs_confirmation": self.project_target_needs_confirmation,
            "confirm_overwrite_project": self.confirm_overwrite_project,
            "begin_shutdown_from_close_event": self.begin_shutdown_from_close_event,
            "reload_procedures": self.reload_procedures,
            "show_window": self.show_plugin_window,
            "on_visible_command_executed": self.on_visible_command_executed,
        }

    def get_current_project_dir(self):
        return self.current_project_dir

    def get_procedures_init(self):
        return self.procedures_init

    def get_command_window(self):
        return self.command_window

    def get_namespace_view(self):
        if self.data_browser is None:
            return {}
        return self.data_browser.namespace_view()

    def connect_namespace_view_updated(self, callback):
        if self.data_browser is None:
            return False
        self.data_browser.namespace_view_updated.connect(callback)
        return True

    def disconnect_namespace_view_updated(self, callback):
        if self.data_browser is None:
            return False
        self.data_browser.namespace_view_updated.disconnect(callback)
        return True

    def get_shutting_down(self):
        return self.shutting_down

    def set_shutting_down(self, value):
        self.shutting_down = bool(value)

    def get_quit_command_sent(self):
        return self._quit_command_sent

    def set_quit_command_sent(self, value):
        self._quit_command_sent = bool(value)

    def setup_plugins(self):
        self.menu_context = MenuContext(logger=logging.getLogger("hyde"))
        self.menu_context.register_location("file", self.ui.menuFile)
        self.menu_context.register_location("window", self.ui.menuWindow)

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
        if getattr(self.ui, "menuTableMacros", None) is not None:
            self.ui.menuWindow.addMenu(self.ui.menuTableMacros)
        self._bind_plugin_action_aliases()
        self.plugin_manager.setup_complete(plugin_data)

    def _bind_plugin_action_aliases(self):
        mapping = {
            "actionNew": (self.ui.menuFile, "New..."),
            "actionLoad": (self.ui.menuFile, "Load..."),
            "actionHeal_Project": (self.ui.menuFile, "Heal Project..."),
            "actionSave": (self.ui.menuFile, "Save"),
            "actionSave_As": (self.ui.menuFile, "Save As..."),
            "actionSave_Copy": (self.ui.menuFile, "Save a Copy..."),
            "actionQuit": (self.ui.menuFile, "Quit"),
            "actionCommandWindow": (self.ui.menuWindow, "Command Window"),
            "actionLogging": (self.ui.menuWindow, "Logging"),
            "actionProcedures": (self.ui.menuWindow, "Procedures"),
            "actionDataBrowser": (self.ui.menuWindow, "Data Browser"),
            "actionNew_Table": (self.ui.menuWindow, "New Table..."),
        }
        for attr_name, (menu, text) in mapping.items():
            setattr(self.ui, attr_name, self._find_menu_action(menu, text))

    def _find_menu_action(self, menu, text):
        for action in menu.actions():
            if action.text() == text:
                return action
        return None

    def _ensure_static_plugin_windows(self):
        self.mdi_context.ensure_widget("logging")
        self.logging_subwindow.hide()
        self.mdi_context.ensure_widget("procedures")
        self.procedures_subwindow.hide()

    def show_plugin_window(self, key):
        return self.mdi_context.show(key)

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

    @inmain_decorator()
    def show_command_window(self, checked=False):
        del checked
        self.show_plugin_window("command_window")

    @inmain_decorator()
    def show_logging_window(self, checked=False):
        del checked
        self.show_plugin_window("logging")

    @inmain_decorator()
    def show_procedures_window(self, checked=False):
        del checked
        self.show_plugin_window("procedures")

    @inmain_decorator()
    def show_data_browser(self, checked=False):
        del checked
        self.show_plugin_window("data_browser")

    def start_kernel_runtime(self):
        if os.path.exists(CONNECTION_FILE):
            os.remove(CONNECTION_FILE)
        self.kernel_to_child, self.kernel_from_child, self.kernel_process = self.process_tree.subprocess(
            KERNEL_LAUNCHER,
            args=["-f", CONNECTION_FILE],
            output_redirection_port=self.logging_window.port,
            startup_timeout=60,
        )
        self.runtime_helper = RuntimeHelper(
            self,
            CONNECTION_FILE,
            self.kernel_from_child,
            self.kernel_process,
        )
        self.runtime_helper.start()

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

    def queue_background_command(self, code, silent=True):
        if self.runtime_helper is None:
            return
        self.runtime_helper.enqueue_execute(code, silent=silent)

    def on_procedure_change(self, name, info, event=None):
        del info
        if event == "original":
            return
        if name != "all" and not name.endswith(".py"):
            return
        if self.current_project_dir is None:
            return
        self.queue_background_command(
            format_procedures_bootstrap_code(
                self.current_project_dir,
                os.path.dirname(HYDE_DIR),
                reset_namespace=False,
            ),
            silent=True,
        )

    def execute_command(self, code, visible=True):
        """
        Execute a command in the kernel with a choice of visibility policy.
        
        Visible commands appear in the console history and history pane.
        Muted commands (visible=False) execute silently to avoid console clutter.
        """
        if visible:
            if self.command_window:
                self.command_window.execute(code, hidden=False)
            return
        self.queue_background_command(code, silent=True)

    def configure_persistent_subwindow(self, subwindow):
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

    def _set_project_action_state(self, has_project):
        self.ui.actionNew.setEnabled(True)
        self.ui.actionLoad.setEnabled(True)
        self.ui.actionHeal_Project.setEnabled(True)
        self.ui.actionLogging.setEnabled(True)
        self.ui.actionQuit.setEnabled(True)
        self.ui.actionSave.setEnabled(has_project)
        self.ui.actionSave_As.setEnabled(has_project)
        self.ui.actionSave_Copy.setEnabled(has_project)
        self.ui.actionCommandWindow.setEnabled(has_project)
        self.ui.actionProcedures.setEnabled(has_project)
        self.ui.actionDataBrowser.setEnabled(has_project)
        self.ui.actionNew_Table.setEnabled(has_project)
        self.ui.menuTableMacros.setEnabled(has_project)

    def request_quit(self, checked=False):
        del checked
        QuitCommand(self).run()

    @inmain_decorator()
    def enter_no_project_state(self):
        self.current_project_dir = None
        self.procedures_dir = None
        self.procedures_init = None
        self.stop_project_watcher()
        clear_tables(self)
        self.procedure_browser.set_procedures_dir(None)
        self.ui.setWindowTitle("Hyde")
        if self.command_subwindow is not None:
            self.command_subwindow.hide()
        if self.procedures_subwindow is not None:
            self.procedures_subwindow.hide()
        if self.data_browser_subwindow is not None:
            self.data_browser_subwindow.hide()
        self._set_project_action_state(False)
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event("enter_no_project_state", {})

    @inmain_decorator()
    def activate_project(self, project_dir):
        if not project_dir:
            return
        project_dir = os.path.abspath(project_dir)
        if self.current_project_dir is not None and os.path.abspath(self.current_project_dir) == project_dir:
            return
        self.current_project_dir, self.procedures_dir, self.procedures_init = get_project_paths(project_dir)
        self.procedure_browser.set_procedures_dir(self.procedures_dir)
        self.ui.setWindowTitle(f"Hyde - {os.path.basename(self.current_project_dir)}")
        self.restart_project_watcher()
        self._set_project_action_state(True)
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event(
                "project_activated",
                {
                    "project_dir": self.current_project_dir,
                    "procedures_dir": self.procedures_dir,
                },
            )

    def reload_procedures(self):
        if self.current_project_dir is None:
            return
        self.queue_background_command(
            format_procedures_bootstrap_code(
                self.current_project_dir,
                os.path.dirname(HYDE_DIR),
                reset_namespace=False,
            ),
            silent=True,
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
            self._rebuild_kernel_windows()
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

    def _shutdown_kernel_windows(self):
        if self.data_browser is not None:
            self.mdi_context.destroy("data_browser")
        if self.command_window is not None:
            self.mdi_context.destroy("command_window")

    def _rebuild_kernel_windows(self):
        self._shutdown_kernel_windows()
        self.mdi_context.ensure_widget("command_window")
        self.mdi_context.ensure_widget("data_browser")

    def _load_startup_project(self, path):
        self.begin_project_operation("Loading Hyde project...")
        state = LoadProjectState()
        state.set_project_dir(path)
        self.execute_command(state.python_source(), visible=True)

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
        if self.runtime_helper is not None:
            helper = self.runtime_helper
            self.runtime_helper = None
            helper.stop()
        self._shutdown_kernel_windows()
        QtWidgets.QMessageBox.warning(
            self.ui,
            "Kernel Crashed",
            "The IPython execution kernel died unexpectedly. Hyde is reconnecting to a fresh kernel.",
        )
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event("kernel_crashed", {})
        self.start_kernel_runtime()

    @inmain_decorator()
    def on_project_state_result(self, data):
        operation = data.get('operation')
        success = bool(data.get('success', False))
        path = data.get('path')
        errors = list(data.get('errors', []))

        self.end_project_operation()

        if operation == 'save':
            if errors:
                QtWidgets.QMessageBox.warning(self.ui, "Project Save Warnings", "\\n".join(errors))
            if success:
                write_session(self, path)
                if self.command_window is not None:
                    write_history(self.command_window, path)
            
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
        self.ui.close()

    def begin_shutdown_from_close_event(self):
        if self._runtime_shutdown:
            return
        self.shutdown_runtime()

    def shutdown_runtime(self):
        if self._runtime_shutdown:
            return
        self._runtime_shutdown = True
        self._quit_deadline = time.monotonic() + 2.0
        self.stop_project_watcher()
        if self.remote_server is not None:
            self.remote_server.shutdown()
            self.remote_server = None
        helper = self.runtime_helper
        if helper is not None and helper.kernel_client is not None:
            try:
                helper.kernel_client.shutdown(reply=False)
            except Exception:
                pass
        elif self.command_window is not None and self.command_window.kernel_client is not None:
            try:
                self.command_window.kernel_client.shutdown(reply=False)
            except Exception:
                pass
        if self.runtime_helper is not None:
            self.runtime_helper = None
            helper.stop()
        self._shutdown_kernel_windows()
        QtCore.QTimer.singleShot(0, self._complete_shutdown_runtime)

    def _complete_shutdown_runtime(self):
        if self.runtime_helper is not None:
            return
        kernel_running = self.kernel_process is not None and self.kernel_process.poll() is None
        quit_deadline = self._quit_deadline
        if kernel_running and quit_deadline is not None and time.monotonic() < quit_deadline:
            QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
            return
        if kernel_running:
            self.kernel_process.terminate()
            if self.kernel_process.poll() is None:
                QtCore.QTimer.singleShot(50, self._complete_shutdown_runtime)
                return
        self._close_ready = True
        self.ui.close()


    def restore_project_session(self):
        warnings = []
        history_entries, history_error = try_read_history(self.current_project_dir)
        if history_error:
            warnings.append(f"terminal/history.py: {history_error}")
        if self.command_window is not None:
            self.command_window.restore_history_entries(history_entries)
        session, session_error = try_read_session(self.current_project_dir)
        if session_error:
            warnings.append(f"session.toml: {session_error}")
        if warnings:
            QtWidgets.QMessageBox.warning(
                self.ui,
                "Project Session Restore Warnings",
                "\n".join(warnings),
            )
        clear_tables(self)
        if not session:
            return
        restore_main_window(self, session)
        if hasattr(self, "emit_plugin_event"):
            self.emit_plugin_event("project_loaded", {"session": session})
