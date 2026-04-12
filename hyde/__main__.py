import sys
import os

# Set desktop app ID before anything else
import desktop_app
desktop_app.set_process_appid('hyde')

# Splash screen
import labscript_utils.splash
splash = labscript_utils.splash.Splash(os.path.join(os.path.dirname(__file__), 'hyde.svg'))
splash.show()

# Update splash text and import qtutils, which can take time
splash.update_text('importing qtutils')
from qtutils.qt import QtWidgets

# Framework error hooks
splash.update_text('importing labscript mechanics')
import labscript_utils.excepthook

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
    
    hyde_instance = HydeApp(qapplication)
    hyde_instance.ui.show()
    
    splash.hide()
    sys.exit(qapplication.exec_())
