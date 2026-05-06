from qtconsole.rich_jupyter_widget import RichJupyterWidget
from hyde.user_interface.plugin_tools import HydePlugin

class PythonTerminal(RichJupyterWidget):
    def __init__(self, kernel_client, history_sink=None, initial_history=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history_sink = history_sink
        self.kernel_client = kernel_client
        self.restore_history_entries(initial_history or [])

    def _command_source(self, source):
        if source is not None:
            return source
        get_input_buffer = getattr(self, "_get_input_buffer", None)
        if callable(get_input_buffer):
            return get_input_buffer()
        return getattr(self, "input_buffer", "")

    def execute(self, source=None, hidden=False, interactive=False):
        """
        Execute code in the kernel.
        
        Args:
            source: The code to execute.
            hidden: If True, the command is executed but not shown in history/console.
            interactive: If True, the console behaves as if the user typed it.
        """
        command_source = self._command_source(source)
        if (
            not hidden
            and self._history_sink is not None
            and isinstance(command_source, str)
            and command_source.strip()
        ):
            result = super().execute(
                source=source,
                hidden=hidden,
                interactive=interactive,
            )
            self._history_sink(command_source)
            return result
        return super().execute(source=source, hidden=hidden, interactive=interactive)

    def restore_history_entries(self, entries):
        if hasattr(self, "_set_history"):
            self._set_history(entries or [])

    def shutdown(self):
        self.kernel_client = None


class PythonTerminalService:
    def __init__(self, plugin):
        self.plugin = plugin
        self._history_entries = []

    def ensure_widget(self):
        return self.plugin.ensure_mdi_widget("python_terminal")

    def widget(self):
        return self.plugin.mdi_widget("python_terminal")

    def subwindow(self):
        return self.plugin.mdi_subwindow("python_terminal")

    def ensure_kernel_client(self):
        kernel_runtime_service = self.plugin.services.get("kernel_runtime_service")
        return None if kernel_runtime_service is None else kernel_runtime_service.kernel_client()

    def execute_visible(self, code):
        widget = self.ensure_widget()
        widget.execute(code, hidden=False)

    def history_entries(self):
        return list(self._history_entries)

    def record_history_entry(self, entry):
        if isinstance(entry, str) and entry.strip():
            self._history_entries.append(entry)

    def restore_history_entries(self, entries):
        self._history_entries = list(entries or [])
        widget = self.ensure_widget()
        widget.restore_history_entries(self._history_entries)

    def shutdown_client(self):
        widget = self.widget()
        if widget is not None:
            widget.shutdown()

    def kernel_client(self):
        return self.ensure_kernel_client()

    def destroy(self):
        self.plugin.destroy_mdi_widget("python_terminal")


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.python_terminal_service = PythonTerminalService(self)
        self._action = None

    def on_setup_complete(self, data=None):
        del data
        self.bind_menu_action("_action", "window", "Python Terminal")

    def get_ui_contributions(self):
        return [
            {
                "context": "mdi",
                "key": "python_terminal",
                "title": "Python Terminal",
                "factory": self.create_widget,
            }
        ]

    def get_menu_contributions(self):
        return [
            {
                "location": "window",
                "group": "tool_windows",
                "order": 10,
                "name": "Python Terminal",
                "action": self.show_window,
            }
        ]

    def get_services(self):
        return {"visible_terminal_service": self.python_terminal_service}

    def create_widget(self, parent=None, data=None):
        del data
        widget = PythonTerminal(
            kernel_client=self.python_terminal_service.ensure_kernel_client(),
            history_sink=self.python_terminal_service.record_history_entry,
            initial_history=self.python_terminal_service.history_entries(),
            parent=parent,
        )
        widget.executed.connect(self.services["on_visible_command_executed"])
        return widget

    def show_window(self, checked=False):
        del checked
        self.services["show_window"]("python_terminal")

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "kernel_crashed": self.on_kernel_crashed,
            "kernel_ready": self.on_kernel_ready,
            "project_activated": self.on_project_activated,
            "project_loaded": self.on_project_loaded,
        }

    def get_session_toml_data(self):
        return self.tool_window_save_data("python_terminal")

    def on_project_loaded(self, data):
        self.restore_tool_window(data["session"], "python_terminal")

    def on_enter_no_project_state(self, data):
        del data
        self.set_bound_action_enabled("_action", False)
        self.hide_mdi_subwindow("python_terminal")

    def on_project_activated(self, data):
        del data
        self.set_bound_action_enabled("_action", True)

    def on_kernel_ready(self, data):
        del data
        self.python_terminal_service.ensure_widget()

    def on_kernel_crashed(self, data):
        del data
        self.python_terminal_service.destroy()
