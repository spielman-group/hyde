import sys
import os
from labscript_utils.ls_zprocess import ProcessTree
from labscript_utils.setup_logging import setup_logging
if os.environ.get("HYDE_DISABLE_LABSCRIPT_ERROR_DIALOGS") != "1":
    import labscript_utils.excepthook
from spyder_kernels.console.start import main

if __name__ == '__main__':
    # Connect the real kernel process directly to the Hyde GUI parent.
    # This fulfills the ProcessTree handshake and keeps the actual
    # spyder_kernels process inside the managed tree.
    ProcessTree.connect_to_parent()

    # Initialize unified logging before entering the Spyder kernel startup.
    setup_logging('hyde-kernel')

    # Ensure hyde is importable from within the kernel before any user code runs.
    # The Hyde source root is two levels up from this file.
    _hyde_source_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _hyde_source_root not in sys.path:
        sys.path.insert(0, _hyde_source_root)

    # Mark hyde as running inside a managed GUI session so IPC signals are enabled.
    import hyde
    hyde.gui_mode(True)

    # Reuse Spyder's standard kernel entrypoint in-process so this
    # ProcessTree child is the real Jupyter kernel process.
    main()
