import sys
import subprocess
import threading
import time
from labscript_utils.ls_zprocess import ProcessTree

class ExecutionWatchdog:
    """
    Spins up and monitors the isolated IPC Jupyter kernel via subprocess.
    Communicates overarching state to the PyQt GUI process via ProcessTree queues.
    """
    def __init__(self, to_parent, from_parent):
        self.to_parent = to_parent
        self.from_parent = from_parent
        self.exiting = False
        self.kernel_process = None
        
        import os
        HYDE_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.connection_file = os.path.join(HYDE_PKG_DIR, 'kernel-hyde.json')

    def start(self):
        # Start daemon thread listening to commands from GUI ProcessTree
        listener = threading.Thread(target=self.listen_for_gui)
        listener.daemon = True
        listener.start()
        
        while not self.exiting:
            print(f"[Watchdog] Starting spyder_kernels connected to {self.connection_file}...")
            
            # Wipe any stale connection files to prevent premature KERNEL_READY pings
            import os
            if os.path.exists(self.connection_file):
                os.remove(self.connection_file)

            self.kernel_process = subprocess.Popen([sys.executable, "-m", "spyder_kernels.console", "-f", self.connection_file])
            
            def wait_for_file():
                while not os.path.exists(self.connection_file):
                    if self.exiting or self.kernel_process.poll() is not None:
                        return
                    time.sleep(0.1)
                self.to_parent.put(["KERNEL_READY", None])
                
            threading.Thread(target=wait_for_file, daemon=True).start()
            
            # Block until kernel dies or is terminated
            self.kernel_process.wait()
            
            if not self.exiting:
                print("[Watchdog] spyder_kernels instance crashed unexpectedly! Restarting in 1s...")
                self.to_parent.put(["KERNEL_CRASHED", None])
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
    
    watchdog = ExecutionWatchdog(process_tree.to_parent, process_tree.from_parent)
    watchdog.start()
