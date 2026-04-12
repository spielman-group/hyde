import sys
import subprocess
from labscript_utils.ls_zprocess import ProcessTree
from labscript_utils.setup_logging import setup_logging
import labscript_utils.excepthook

if __name__ == '__main__':
    # Connect to the Watchdog parent. This fulfills the handshake
    # required by ProcessTree.subprocess() and initializes heartbeats.
    process_tree = ProcessTree.connect_to_parent()
    
    # Initialize unified logging for the kernel launcher.
    # The actual IPython kernel output will be captured via stdout inheritance.
    setup_logging('hyde-kernel')
    
    # Kernel connection file is passed via arguments
    # Launch the actual IPython kernel
    kernel_cmd = [sys.executable, "-m", "spyder_kernels.console"] + sys.argv[1:]
    
    # We use Popen and wait so this process remains alive as a managed 
    # zprocess node. Its output is naturally inherited and pushed to 
    # the redirection port specified by the GUI.
    p = subprocess.Popen(kernel_cmd)
    
    try:
        p.wait()
    finally:
        if p.poll() is None:
            p.terminate()
