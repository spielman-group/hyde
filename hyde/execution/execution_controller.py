import os
import queue
import sys
import threading
import time

HYDE_SOURCE_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if HYDE_SOURCE_ROOT not in sys.path:
    sys.path.insert(0, HYDE_SOURCE_ROOT)

from labscript_utils.labconfig import LabConfig
from labscript_utils import shared_drive
from labscript_utils.ls_zprocess import ProcessTree, ZMQServer
from labscript_utils.filewatcher import FileWatcher
from labscript_utils.setup_logging import setup_logging
from jupyter_client import BlockingKernelClient
from zprocess.utils import TimeoutError as ZprocessTimeoutError
from zmq.error import ZMQError
from hyde.paths import HYDE_PKG_DIR, KERNEL_LAUNCHER
import labscript_utils.excepthook


class RemoteListener(ZMQServer):
    """Listen for lyse-compatible remote payloads and relay them to the kernel."""

    def __init__(self, watchdog, port):
        self.watchdog = watchdog
        super().__init__(port=port, bind_address='tcp://*')

    def handler(self, request_data):
        if request_data == 'hello':
            return 'hello'
        if isinstance(request_data, dict) and 'filepath' in request_data:
            request_data = shared_drive.path_to_local(str(request_data['filepath']))
            if isinstance(request_data, bytes):
                request_data = request_data.decode('utf8')
        if isinstance(request_data, str):
            if (
                self.watchdog.kernel_client is None
                or self.watchdog.kernel_process is None
                or self.watchdog.kernel_process.poll() is not None
            ):
                return 'error: kernel unavailable'
            self.watchdog.local_queue.put([
                'EXECUTE_COMMAND',
                {'code': f"remote({request_data!r})", 'silent': False},
            ])
            return 'added successfully'
        return ("error: operation not supported. Recognised requests are:\n "
                "'hello'\n {'filepath': <some_agnostic_path>}\n <some_agnostic_path>")


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
        self.remote_listener = None
        self.project_dir = None
        self.procedures_dir = None
        self.procedures_init = None
        self.exiting = False
        self.reload_requested = threading.Event()
        self.reset_namespace_requested = False
        self.local_queue = queue.Queue()

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
                if self.remote_listener is None:
                    try:
                        try:
                            port = int(LabConfig().get('ports', 'lyse'))
                        except Exception:
                            port = 42519
                        self.remote_listener = RemoteListener(self, port)
                    except ZMQError as exc:
                        print(f"[Watchdog] Could not start lyse-compatible remote listener: {exc}")
                        self.remote_listener = None

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
                    ok = self.execute_procedures_init()
                    self.to_parent.put(['PROCEDURES_RELOADED', {'ok': bool(ok)}])

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
        if self.remote_listener is not None:
            self.remote_listener.shutdown()
            self.remote_listener = None
        if self.kernel_process is not None and self.kernel_process.poll() is None:
            self.kernel_process.terminate()

    def execute_procedures_init(self):
        if self.kernel_client is None or self.project_dir is None or self.procedures_init is None:
            return False
        if not os.path.exists(self.procedures_init):
            return False
        code = self.build_procedures_bootstrap_code(
            reset_namespace=self.reset_namespace_requested
        )
        msg_id = self.kernel_client.execute(code, silent=True)
        while True:
            reply = self.kernel_client.get_shell_msg(timeout=10)
            if reply['parent_header'].get('msg_id') != msg_id:
                continue
            ok = reply['content'].get('status') == 'ok'
            if ok:
                self.reset_namespace_requested = False
            return ok

    def build_procedures_bootstrap_code(self, reset_namespace=False):
        hyde_source_root = os.path.dirname(HYDE_PKG_DIR)
        lines = [
            "import os",
            "import sys",
            "import importlib",
            "import __main__",
            f"os.chdir({self.project_dir!r})",
            "def _hyde_bootstrap_procedures():",
            "    _os = os",
            "    _sys = sys",
            "    _importlib = importlib",
            "    _main = __main__",
            f"    _hyde_source_root = {hyde_source_root!r}",
            "    project_root = _os.getcwd()",
            "    while project_root in _sys.path:",
            "        _sys.path.remove(project_root)",
            "    _sys.path.insert(0, project_root)",
            "    while _hyde_source_root in _sys.path:",
            "        _sys.path.remove(_hyde_source_root)",
            "    _sys.path.insert(1, _hyde_source_root)",
            "    if '__hyde_clean_dict__' not in _main.__dict__:",
            "        _main.__dict__['__hyde_clean_dict__'] = _main.__dict__.copy()",
        ]
        if reset_namespace:
            lines.extend(
                [
                    "    _hyde_clean_dict = _main.__dict__.get('__hyde_clean_dict__')",
                    "    if _hyde_clean_dict is None:",
                    "        _hyde_clean_dict = _main.__dict__.copy()",
                    "    _main.__dict__.clear()",
                    "    _main.__dict__.update(_hyde_clean_dict)",
                    "    _main.__dict__['__hyde_clean_dict__'] = _hyde_clean_dict",
                ]
            )
        lines.extend(
            [
                "    _importlib.invalidate_caches()",
                "    for name in list(_sys.modules):",
                "        if name == 'procedures' or name.startswith('procedures.') or name == 'hyde' or name.startswith('hyde.'):",
                "            del _sys.modules[name]",
                "    import hyde._table_macros as _hyde_table_macros",
                "    _hyde_table_macros.clear_table_macros()",
                "    import procedures",
                "    __hyde_exports = {",
                "        name: value",
                "        for name, value in procedures.__dict__.items()",
                "        if not name.startswith('_')",
                "    }",
                "    _main.__dict__.update(__hyde_exports)",
                "    _main.__hyde_procedures_exports__ = set(__hyde_exports)",
                "    _hyde_table_macros.publish_table_macro_registry()",
                "_hyde_bootstrap_procedures()",
            ]
        )
        return "\n".join(lines) + "\n"

    def on_procedure_change(self, name, info, event=None):
        if event == 'original':
            return
        if name != 'all' and not name.endswith('.py'):
            return
        self.reload_requested.set()

    def watch_project(self, data):
        switching_project = (
            self.project_dir is not None and data['project_dir'] != self.project_dir
        )
        self.project_dir = data['project_dir']
        self.procedures_dir = data['procedures_dir']
        self.procedures_init = data['procedures_init']
        if switching_project:
            self.reset_namespace_requested = True
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
                try:
                    task, data = self.local_queue.get_nowait()
                except queue.Empty:
                    task, data = self.from_parent.get(timeout=0.1)
                if task == 'EXECUTE_COMMAND':
                    if (
                        self.kernel_client is not None
                        and self.kernel_process is not None
                        and self.kernel_process.poll() is None
                    ):
                        self.kernel_client.execute(
                            data['code'],
                            silent=data.get('silent', True),
                        )
                elif task == 'WATCH_PROJECT':
                    self.watch_project(data)
                elif task == 'RELOAD_PROCEDURES':
                    self.execute_procedures_init()
                elif task == 'QUIT':
                    self.exiting = True
                    self.reload_requested.set()
                    break
            except ZprocessTimeoutError:
                continue
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
                elif task == 'PROJECT_STATE_RESULT':
                    self.to_parent.put(['PROJECT_STATE_RESULT', data])
                elif task == 'WINDOW_MACROS_RESPONSE':
                    self.to_parent.put(['WINDOW_MACROS', data])
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
