import sys
import subprocess
import threading
import time
import os
from labscript_utils.ls_zprocess import ProcessTree
from labscript_utils.filewatcher import FileWatcher
from labscript_utils.setup_logging import setup_logging
from jupyter_client import BlockingKernelClient
from hyde.paths import KERNEL_LAUNCHER
import labscript_utils.excepthook

class ExecutionWatchdog:
    """
    Spins up and monitors the isolated IPC Jupyter kernel via subprocess.
    Communicates overarching state to the PyQt GUI process via ProcessTree queues.
    """
    def __init__(self, to_parent, from_parent, connection_file):
        self.to_parent = to_parent
        self.from_parent = from_parent
        self.connection_file = connection_file
        self.process_tree = ProcessTree.instance()
        self.kernel_process = None
        self.kernel_client = None
        self.filewatcher = None
        self.project_dir = None
        self.procedures_dir = None
        self.master_script = None
        self.exiting = False
        self.reload_requested = threading.Event()

    def start(self):
        # Start daemon thread listening to commands from GUI ProcessTree
        listener = threading.Thread(target=self.listen_for_gui)
        listener.daemon = True
        listener.start()
        
        while not self.exiting:
            # Wipe any stale connection files from previous crashes in this session
            if os.path.exists(self.connection_file):
                os.remove(self.connection_file)

            # Launch the IPython kernel via the managed launcher.
            # This launcher performs the zprocess handshake to prevent timeouts.
            self.to_kernel, self.from_kernel, self.kernel_process = self.process_tree.subprocess(
                KERNEL_LAUNCHER,
                args=["-f", self.connection_file]
            )
            
            # Wait for the connection file to be written by spyder_kernels
            while not os.path.exists(self.connection_file):
                if self.exiting or self.kernel_process.poll() is not None:
                    break
                time.sleep(0.1)

            if not self.exiting and self.kernel_process.poll() is None:
                self.kernel_client = BlockingKernelClient(connection_file=self.connection_file)
                self.kernel_client.load_connection_file()
                self.kernel_client.start_channels()

            if not self.exiting and self.kernel_process.poll() is None:
                self.to_parent.put(['KERNEL_READY', self.connection_file])
            
            while not self.exiting and self.kernel_process.poll() is None:
                if self.reload_requested.wait(timeout=0.1):
                    self.reload_requested.clear()
                    self.execute_master_script()

            if self.kernel_client is not None:
                self.kernel_client.stop_channels()
                self.kernel_client = None
            
            if not self.exiting:
                print("[Watchdog] Kernel crashed or exited unexpectedly. Restarting...")
                self.to_parent.put(['KERNEL_CRASHED', None])
                time.sleep(1)

    def execute_master_script(self):
        if self.kernel_client is None or self.project_dir is None or self.master_script is None:
            return
        if not os.path.exists(self.master_script):
            return
        code = (
            f"import os\n"
            f"os.chdir({self.project_dir!r})\n"
            f"with open({self.master_script!r}) as f:\n"
            f"    exec(f.read())\n"
        )
        self.kernel_client.execute(code)

    def on_procedure_change(self, name, info, event=None):
        if event == 'original':
            return
        if name != 'all' and not name.endswith('.py'):
            return
        self.reload_requested.set()

    def watch_project(self, data):
        self.project_dir = data['project_dir']
        self.procedures_dir = data['procedures_dir']
        self.master_script = data['master_script']
        if self.filewatcher is not None:
            self.filewatcher.stop()
        self.filewatcher = FileWatcher(
            self.on_procedure_change,
            files=[self.master_script],
            folders=[self.procedures_dir],
            hashable_types=['.py'],
            interval=0.5,
        )
        self.reload_requested.set()

    def listen_for_gui(self):
        while not self.exiting:
            try:
                task, data = self.from_parent.get()
                if task == 'WATCH_PROJECT':
                    self.watch_project(data)
                elif task == 'QUIT':
                    self.exiting = True
                    self.reload_requested.set()
                    if self.filewatcher is not None:
                        self.filewatcher.stop()
                    if self.kernel_client is not None:
                        self.kernel_client.stop_channels()
                        self.kernel_client = None
                    if self.kernel_process:
                        self.kernel_process.terminate()
                    break
            except Exception as e:
                print(f"[Watchdog] Error polling ProcessTree queue: {e}")

if __name__ == '__main__':
    # Bootstrap into the labscript ProcessTree parent
    process_tree = ProcessTree.connect_to_parent()
    
    # Initialize unified logging for the watchdog
    setup_logging('hyde-watchdog')
    
    # Connection file path is passed as the first command-line argument
    # by the GUI via ProcessTree.subprocess(..., args=[CONNECTION_FILE])
    connection_file = sys.argv[1]
    
    watchdog = ExecutionWatchdog(process_tree.to_parent, process_tree.from_parent, connection_file)
    watchdog.start()
