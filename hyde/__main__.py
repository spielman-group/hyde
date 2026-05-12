import sys
import os

# Set desktop app ID before anything else
import desktop_app
from hyde.paths import APPLICATION_NAME, SPLASH_SVG
desktop_app.set_process_appid(APPLICATION_NAME)

# Splash screen
import labscript_utils.splash
splash = labscript_utils.splash.Splash(SPLASH_SVG, application_name=APPLICATION_NAME)
splash.show()

# Update splash text and import qtutils, which can take time
splash.update_text('importing qtutils')
from qtutils.qt import QtWidgets, QtGui

# Framework error hooks
splash.update_text('importing labscript mechanics')
if os.environ.get("HYDE_DISABLE_LABSCRIPT_ERROR_DIALOGS") != "1":
    import labscript_utils.excepthook
from labscript_utils.setup_logging import setup_logging
setup_logging(APPLICATION_NAME)
from labscript_utils.ls_zprocess import ProcessTree

splash.update_text('initializing ProcessTree')
process_tree = ProcessTree.instance()
process_tree.zlock_client.set_process_name(APPLICATION_NAME)

# Core application
splash.update_text('loading Hyde UI')
from hyde.user_interface.main import HydeApp


def force_light_palette(qapplication):
    qapplication.setStyle('Fusion')
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(239, 239, 239))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 255, 255))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(245, 245, 245))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(255, 255, 220))
    palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(239, 239, 239))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor(255, 0, 0))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(76, 163, 224))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
    qapplication.setPalette(palette)

if __name__ == '__main__':
    splash.update_text('starting Qt event loop')
    
    qapplication = QtWidgets.QApplication.instance()
    if qapplication is None:
        qapplication = QtWidgets.QApplication(sys.argv)
        
    qapplication.setApplicationName(APPLICATION_NAME)
    force_light_palette(qapplication)
    
    try:
        labscript_utils.splash.configure_qapplication(qapplication)
    except AttributeError:
        pass # Handle if splash doesn't have this method defined natively
    
    splash.update_text('Waiting for spyder_kernels spin-up...')
    
    hyde_instance = HydeApp(qapplication, process_tree, splash, argv=sys.argv[1:])
    
    # splash.hide() and hyde_instance.ui.show() are handled by HydeApp once the
    # direct kernel child is ready.
    
    sys.exit(qapplication.exec_())
