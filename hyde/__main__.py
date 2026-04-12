import sys
import os

# Set desktop app ID before anything else
import desktop_app
desktop_app.set_process_appid('hyde')

# Splash screen
import labscript_utils.splash
from hyde.paths import SPLASH_SVG
splash = labscript_utils.splash.Splash(SPLASH_SVG)
splash.show()

# Update splash text and import qtutils, which can take time
splash.update_text('importing qtutils')
from qtutils.qt import QtWidgets

# Framework error hooks
splash.update_text('importing labscript mechanics')
import labscript_utils.excepthook
from labscript_utils.setup_logging import setup_logging
setup_logging('hyde')
from labscript_utils.ls_zprocess import ProcessTree

splash.update_text('initializing ProcessTree')
process_tree = ProcessTree.instance()
process_tree.zlock_client.set_process_name('hyde')

# Core application
splash.update_text('loading Hyde UI')
from hyde.user_interface.main import HydeApp

if __name__ == '__main__':
    splash.update_text('starting Qt event loop')
    
    qapplication = QtWidgets.QApplication.instance()
    if qapplication is None:
        qapplication = QtWidgets.QApplication(sys.argv)
        
    qapplication.setApplicationName('hyde')
    
    try:
        labscript_utils.splash.configure_qapplication(qapplication)
    except AttributeError:
        pass # Handle if splash doesn't have this method defined natively
    
    splash.update_text('Waiting for Watchdog and spyder_kernels spin-up...')
    
    hyde_instance = HydeApp(qapplication, process_tree, splash)
    
    # splash.hide() and hyde_instance.ui.show() are now explicitly handled 
    # dynamically by HydeApp when KERNEL_READY is caught from the ProcessTree queue.
    
    sys.exit(qapplication.exec_())
