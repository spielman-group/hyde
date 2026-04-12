import sys
import subprocess
import threading
import time
from labscript_utils.ls_zprocess import ProcessTree
from labscript_utils.setup_logging import setup_logging
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
        self.exiting = False

    def start(self):
        import os

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

            # Notify GUI that kernel is ready
            if not self.exiting and self.kernel_process.poll() is None:
                self.to_parent.put(['KERNEL_READY', self.connection_file])
            
            # Block until kernel dies or is terminated
            self.kernel_process.wait()
            
            if not self.exiting:
                print("[Watchdog] Kernel crashed or exited unexpectedly. Restarting...")
                self.to_parent.put(['KERNEL_CRASHED', None])
                time.sleep(1)

    def listen_for_gui(self):
        while not self.exiting:
            try:
                task, data = self.from_parent.get()
                if task == 'QUIT':
                    self.exiting = True
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
