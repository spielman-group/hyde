from qtconsole.rich_jupyter_widget import RichJupyterWidget
from qtconsole.client import QtKernelClient
from labscript_utils.plugins import BasePlugin
from hyde.paths import CONNECTION_FILE
from hyde.user_interface.plugin_tools import capture_subwindow_state, restore_subwindow_state

class CommandWindow(RichJupyterWidget):
    def __init__(self, connection_file, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Create and connect the live QtKernelClient before attaching it to
        # the widget so visible and hidden execution both use the same session.
        client = QtKernelClient(connection_file=connection_file)
        client.load_connection_file()
        client.start_channels()

        self.kernel_client = client

    def execute(self, source=None, hidden=False, interactive=False):
        """
        Execute code in the kernel.
        
        Args:
            source: The code to execute.
            hidden: If True, the command is executed but not shown in history/console.
            interactive: If True, the console behaves as if the user typed it.
        """
        return super().execute(source=source, hidden=hidden, interactive=interactive)

    def history_entries(self):
        history = getattr(self, "_history", [])
        return list(self.history_tail(len(history)))

    def restore_history_entries(self, entries):
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


class Plugin(BasePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})

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

    def create_widget(self, parent=None, data=None):
        del data
        widget = CommandWindow(connection_file=CONNECTION_FILE, parent=parent)
        widget.executed.connect(self.services["on_visible_command_executed"])
        return widget

    def show_window(self, checked=False):
        del checked
        self.services["show_window"]("command_window")

    def get_event_handlers(self):
        return {
            "request_project_save": self.on_request_project_save,
            "project_loaded": self.on_project_loaded,
        }

    def on_request_project_save(self, data):
        session = data["session"]
        session.setdefault("tool_windows", {})["command"] = capture_subwindow_state(
            self.services["mdi_context"].subwindow("command_window")
        )

    def on_project_loaded(self, data):
        info = data["session"].get("tool_windows", {}).get("command", {})
        restore_subwindow_state(
            self.services["mdi_context"].subwindow("command_window"),
            info,
        )
