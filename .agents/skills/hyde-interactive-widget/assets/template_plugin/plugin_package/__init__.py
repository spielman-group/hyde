from functools import partial

from qtutils.qt import QtCore

from hyde.user_interface.shared.plugin import (
    HydePlugin,
    apply_saveable_window_state,
    blank_window_icon,
)
from hyde.user_interface.shared.project import resolve_requested_name

from .window import ExampleInteractiveWindow


class ExampleWorkspaceService:
    """Owns the open interactive windows for this plugin.

    Interactive windows are created on demand and added to the MDI area
    directly; they are not persistent tool windows, so they keep Qt's normal
    delete-on-close behavior.
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self.windows = {}

    def open_window(self, name=None, window_state=None):
        handle = resolve_requested_name(
            "ExampleInteractive",
            self.windows,
            requested_name=name,
        )
        window = ExampleInteractiveWindow(
            services=self.plugin.services,
            initial_window_name=handle,
        )
        subwindow = self.plugin.services["mdi_area"].addSubWindow(window)
        subwindow.setWindowIcon(blank_window_icon())
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        window.bind_subwindow(subwindow, stable_name=handle)

        stable_name = window.window_handle()
        self.windows[stable_name] = window
        subwindow.setWindowTitle(window.formatted_window_title())
        subwindow.show()
        apply_saveable_window_state(subwindow, window_state)
        subwindow.destroyed.connect(
            partial(self._on_subwindow_destroyed, stable_name)
        )
        return window

    def _on_subwindow_destroyed(self, stable_name, *args):
        del args
        self.windows.pop(stable_name, None)


class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.workspace = ExampleWorkspaceService(self)

    def get_services(self):
        return {"example_workspace_service": self.workspace}

    def get_menu_contributions(self):
        return [
            {
                # Separator groups within a location order by group name, so
                # the name carries a leading ordinal.
                "location": "window",
                "group": "40_example",
                "order": 20,
                "name": "New Example...",
                "action": self.open_example_window,
            }
        ]

    def open_example_window(self, checked=False):
        del checked
        return self.workspace.open_window()
