# Hyde user interface package
import os

from qtutils import UiLoader

HYDE_DIR = os.path.dirname(os.path.realpath(__file__))


def load_ui(relative_path, instance=None):
    """Load a UI file from the user_interface directory.
    
    Args:
        relative_path: Path relative to user_interface/ (e.g., 'close_figure_dialog/close_figure_dialog.ui')
        instance: Optional parent widget for the UI
    """
    return UiLoader().load(os.path.join(HYDE_DIR, relative_path), instance)