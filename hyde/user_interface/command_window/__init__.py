from qtconsole.rich_jupyter_widget import RichJupyterWidget
from qtconsole.client import QtKernelClient

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
