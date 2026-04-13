import sys
import subprocess
import threading
import time
import os
from labscript_utils.ls_zprocess import ProcessTree
from labscript_utils.filewatcher import FileWatcher
from labscript_utils.setup_logging import setup_logging
from jupyter_client import BlockingKernelClient
from zprocess.utils import TimeoutError as ZprocessTimeoutError
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
        self.procedures_init = None
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

            # Launch the real Spyder kernel through the ProcessTree-managed
            # entrypoint so the kernel process itself is the tree child.
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

            # Monitor kernel-side Hyde signaling as long as this kernel is alive
            monitor_thread = threading.Thread(
                target=self.monitor_kernel, 
                args=(self.from_kernel,)
            )
            monitor_thread.daemon = True
            monitor_thread.start()

            if not self.exiting and self.kernel_process.poll() is None:
                self.to_parent.put(['KERNEL_READY', self.connection_file])
            
            while not self.exiting and self.kernel_process.poll() is None:
                if self.reload_requested.wait(timeout=0.1):
                    self.reload_requested.clear()
                    if self.exiting:
                        break
                    self.execute_procedures_init()

            if self.kernel_client is not None:
                self.kernel_client.stop_channels()
                self.kernel_client = None
            
            if not self.exiting:
                print("[Watchdog] Kernel crashed or exited unexpectedly. Restarting...")
                self.to_parent.put(['KERNEL_CRASHED', None])
                time.sleep(1)

        if self.filewatcher is not None:
            self.filewatcher.stop()
            self.filewatcher = None
        if self.kernel_process is not None and self.kernel_process.poll() is None:
            self.kernel_process.terminate()

    def execute_procedures_init(self):
        if self.kernel_client is None or self.project_dir is None or self.procedures_init is None:
            return
        if not os.path.exists(self.procedures_init):
            return
        code = self.build_procedures_bootstrap_code()
        self.kernel_client.execute(code, silent=True)

    def build_procedures_bootstrap_code(self):
        return (
            "import os\n"
            "import sys\n"
            "import importlib\n"
            "import __main__\n"
            f"os.chdir({self.project_dir!r})\n"
            "project_root = os.getcwd()\n"
            "if sys.path[:1] != [project_root]:\n"
            "    while project_root in sys.path:\n"
            "        sys.path.remove(project_root)\n"
            "    sys.path.insert(0, project_root)\n"
            "for name in list(getattr(__main__, '__hyde_procedures_exports__', set())):\n"
            "    __main__.__dict__.pop(name, None)\n"
            "importlib.invalidate_caches()\n"
            "for name in list(sys.modules):\n"
            "    if name == 'procedures' or name.startswith('procedures.'):\n"
            "        del sys.modules[name]\n"
            "import procedures\n"
            "__hyde_exports = {\n"
            "    name: value\n"
            "    for name, value in procedures.__dict__.items()\n"
            "    if not name.startswith('_')\n"
            "}\n"
            "__main__.__dict__.update(__hyde_exports)\n"
            "__main__.__hyde_procedures_exports__ = set(__hyde_exports)\n"
        )

    def on_procedure_change(self, name, info, event=None):
        if event == 'original':
            return
        if name != 'all' and not name.endswith('.py'):
            return
        self.reload_requested.set()

    def watch_project(self, data):
        self.project_dir = data['project_dir']
        self.procedures_dir = data['procedures_dir']
        self.procedures_init = data['procedures_init']
        if self.filewatcher is not None:
            self.filewatcher.stop()
        watched_files = [self.procedures_init] if os.path.exists(self.procedures_init) else []
        self.filewatcher = FileWatcher(
            self.on_procedure_change,
            files=watched_files,
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
                elif task == 'FETCH_TABLE_DATA':
                    if self.kernel_client is not None:
                        names = data.get('names', [])
                        request_id = data.get('request_id')
                        code = (
                            f"import hyde.execution.ipc; "
                            f"hyde.execution.ipc.push_table_data({names!r}, {request_id!r})"
                        )
                        self.kernel_client.execute(code, silent=True)
                elif task == 'QUIT':
                    self.exiting = True
                    self.reload_requested.set()
                    break
            except Exception as e:
                print(f"[Watchdog] Error polling ProcessTree queue: {e}")

    def monitor_kernel(self, from_kernel):
        """Relay Hyde signals from the kernel ProcessTree queue to the GUI."""
        while not self.exiting:
            try:
                # Pulse based on the kernel subprocess queue
                msg = from_kernel.get(timeout=0.1)
                if not msg:
                    continue
                
                task, data = msg
                if task == 'OPEN_TABLE_REQUEST':
                    self.to_parent.put(['OPEN_TABLE', data])
                elif task == 'TABLE_DATA_RESPONSE':
                    self.to_parent.put(['TABLE_DATA', data])
            except ZprocessTimeoutError:
                continue
            except Exception:
                # Kernel queue likely closed or kernel died
                break

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
