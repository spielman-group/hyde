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
