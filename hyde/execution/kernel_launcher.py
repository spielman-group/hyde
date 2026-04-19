from labscript_utils.ls_zprocess import ProcessTree
from labscript_utils.setup_logging import setup_logging
import labscript_utils.excepthook
from spyder_kernels.console.start import main

if __name__ == '__main__':
    # Connect the real kernel process directly to the Watchdog parent.
    # This fulfills the ProcessTree handshake and keeps the actual
    # spyder_kernels process inside the managed tree.
    ProcessTree.connect_to_parent()

    # Initialize unified logging before entering the Spyder kernel startup.
    setup_logging('hyde-kernel')

    # Reuse Spyder's standard kernel entrypoint in-process so this
    # ProcessTree child is the real Jupyter kernel process.
    main()
