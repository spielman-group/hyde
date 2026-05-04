from qtconsole.rich_jupyter_widget import RichJupyterWidget
from qtconsole.client import QtKernelClient
from labscript_utils.plugins import BasePlugin
from hyde.paths import CONNECTION_FILE
from hyde.user_interface.plugin_tools import (
    capture_subwindow_state,
    restore_subwindow_state,
)

class CommandWindow(RichJupyterWidget):
    def __init__(self, connection_file, history_sink=None, initial_history=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history_sink = history_sink

        # Create and connect the live QtKernelClient before attaching it to
        # the widget so visible and hidden execution both use the same session.
        client = QtKernelClient(connection_file=connection_file)
        client.load_connection_file()
        client.start_channels()

        self.kernel_client = client
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
        if self.kernel_client is not None:
            for channel_name in ("iopub_channel", "shell_channel", "stdin_channel", "control_channel"):
                channel = getattr(self.kernel_client, channel_name, None)
                if channel is not None and hasattr(channel, "close"):
                    try:
                        channel.close()
                    except Exception:
                        pass
            self.kernel_client.stop_channels()
            self.kernel_client = None


class CommandWindowService:
    def __init__(self, plugin):
        self.plugin = plugin
        self._history_entries = []

    def ensure_widget(self):
        return self.plugin.services["mdi_context"].ensure_widget("command_window")

    def widget(self):
        return self.plugin.services["mdi_context"].widget("command_window")

    def subwindow(self):
        return self.plugin.services["mdi_context"].subwindow("command_window")

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
        widget = self.widget()
        return None if widget is None else widget.kernel_client

    def destroy(self):
        self.plugin.services["mdi_context"].destroy("command_window")


class Plugin(BasePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}
        self.command_window_service = CommandWindowService(self)
        self._action = None

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})
        lookup_menu_action = self.services.get("lookup_menu_action")
        if lookup_menu_action is not None:
            self._action = lookup_menu_action("window", "Command Window")

    def get_ui_contributions(self):
        return [
            {
                "context": "mdi",
                "key": "command_window",
                "title": "Command Window",
                "factory": self.create_widget,
            }
        ]

    def get_menu_contributions(self):
        return [
            {
                "location": "window",
                "group": "tool_windows",
                "order": 10,
                "name": "Command Window",
                "action": self.show_window,
            }
        ]

    def get_services(self):
        return {"visible_command_service": self.command_window_service}

    def create_widget(self, parent=None, data=None):
        del data
        widget = CommandWindow(
            connection_file=CONNECTION_FILE,
            history_sink=self.command_window_service.record_history_entry,
            initial_history=self.command_window_service.history_entries(),
            parent=parent,
        )
        widget.executed.connect(self.services["on_visible_command_executed"])
        return widget

    def show_window(self, checked=False):
        del checked
        self.services["show_window"]("command_window")

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "kernel_crashed": self.on_kernel_crashed,
            "kernel_ready": self.on_kernel_ready,
            "project_activated": self.on_project_activated,
            "project_loaded": self.on_project_loaded,
        }

    def get_save_data(self):
        subwindow = self.services["mdi_context"].subwindow("command_window")
        if subwindow is None:
            return {}
        return {
            "tool_windows": {
                "command": capture_subwindow_state(subwindow),
            }
        }

    def on_project_loaded(self, data):
        info = data["session"].get("tool_windows", {}).get("command", {})
        restore_subwindow_state(
            self.services["mdi_context"].subwindow("command_window"),
            info,
        )

    def on_enter_no_project_state(self, data):
        del data
        if self._action is not None:
            self._action.setEnabled(False)
        subwindow = self.command_window_service.subwindow()
        if subwindow is not None:
            subwindow.hide()

    def on_project_activated(self, data):
        del data
        if self._action is not None:
            self._action.setEnabled(True)

    def on_kernel_ready(self, data):
        del data
        self.command_window_service.ensure_widget()

    def on_kernel_crashed(self, data):
        del data
        self.command_window_service.destroy()
