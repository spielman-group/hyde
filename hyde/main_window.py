"""Hyde main window - backward compatibility module.

All classes have been moved to user_interface subpackages.
Import from the new locations instead:
- from hyde.user_interface.main import HydeMainWindow
- from hyde.user_interface.data_browser import DataBrowserWidget
- etc.
"""

from hyde.user_interface.main import HydeMainWindow, load_ui, encode_qbytes, decode_qbytes
from hyde.user_interface.command_window import CommandInputHandler
from hyde.user_interface.data_browser import DataBrowserWidget
from hyde.user_interface.procedure_browser import ProcedureBrowserWidget
from hyde.user_interface.table_window import PanelWindow, TableWindow, CombinedTableModel
from hyde.user_interface.figure_window import FigureWindow
from hyde.user_interface.figure_edit_dialog import FigureEditDialog
from hyde.user_interface.new_graph_dialog import NewGraphDialog
from hyde.user_interface.trace_edit_dialog import TraceEditDialog
from hyde.user_interface.close_figure_dialog import CloseFigureDialog
from hyde.user_interface.save_graphics_dialog import SaveGraphicsDialog
from hyde.user_interface.fit_dialog import FitDialog