import os
from qtconsole.rich_jupyter_widget import RichJupyterWidget
from qtconsole.client import QtKernelClient

class CommandWindow(RichJupyterWidget):
    def __init__(self, connection_file, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Create the client instance first
        client = QtKernelClient(connection_file=connection_file)
        client.load_connection_file()
        
        # Start the channels before assigning to the widget
        client.start_channels()
        
        # Assign to the widget property
        self.kernel_client = client
