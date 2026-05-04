from labscript_utils.plugins import BasePlugin

from hyde.user_interface.file_dialogs import (
    HealProjectDialog,
    LoadProjectDialog,
    NewProjectDialog,
    QuitCommand,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
    SaveProjectCommand,
)


class _ProjectShellProxy:
    def __init__(self, services):
        self.services = services

    @property
    def ui(self):
        return self.services["ui"]

    @property
    def current_project_dir(self):
        return self.services["get_current_project_dir"]()

    @property
    def command_window(self):
        return self.services["get_command_window"]()

    @property
    def shutting_down(self):
        return self.services["get_shutting_down"]()

    @shutting_down.setter
    def shutting_down(self, value):
        self.services["set_shutting_down"](value)

    @property
    def _quit_command_sent(self):
        return self.services["get_quit_command_sent"]()

    @_quit_command_sent.setter
    def _quit_command_sent(self, value):
        self.services["set_quit_command_sent"](value)

    def begin_project_operation(self, label):
        self.services["begin_project_operation"](label)

    def execute_command(self, code, visible=True):
        self.services["execute_command"](code, visible=visible)

    def project_target_needs_confirmation(self, project_dir):
        return self.services["project_target_needs_confirmation"](project_dir)

    def confirm_overwrite_project(self, project_dir):
        return self.services["confirm_overwrite_project"](project_dir)

    def begin_shutdown_from_close_event(self):
        self.services["begin_shutdown_from_close_event"]()


class Plugin(BasePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}

    def plugin_setup_complete(self, data=None):
        data = data or {}
        self.services = data.get("services", {})

    def get_menu_contributions(self):
        return [
            {
                "location": "file",
                "group": "project",
                "order": 10,
                "name": "New...",
                "shortcut": "Ctrl+N",
                "action": self.new_project,
            },
            {
                "location": "file",
                "group": "project",
                "order": 20,
                "name": "Load...",
                "shortcut": "Ctrl+O",
                "action": self.load_project,
            },
            {
                "location": "file",
                "group": "project",
                "order": 30,
                "name": "Heal Project...",
                "action": self.heal_project,
            },
            {
                "location": "file",
                "group": "save",
                "order": 10,
                "name": "Save",
                "shortcut": "Ctrl+S",
                "action": self.save_project,
            },
            {
                "location": "file",
                "group": "save",
                "order": 20,
                "name": "Save As...",
                "action": self.save_project_as,
            },
            {
                "location": "file",
                "group": "save",
                "order": 30,
                "name": "Save a Copy...",
                "action": self.save_project_copy,
            },
            {
                "location": "file",
                "group": "application",
                "order": 100,
                "name": "Quit",
                "action": self.quit_application,
            },
        ]

    def _shell_proxy(self):
        return _ProjectShellProxy(self.services)

    def new_project(self, checked=False):
        del checked
        NewProjectDialog(self._shell_proxy()).run()

    def load_project(self, checked=False):
        del checked
        LoadProjectDialog(self._shell_proxy()).run()

    def heal_project(self, checked=False):
        del checked
        HealProjectDialog(self._shell_proxy()).run()

    def save_project(self, checked=False):
        del checked
        SaveProjectCommand(self._shell_proxy()).run()

    def save_project_as(self, checked=False):
        del checked
        SaveAsProjectDialog(self._shell_proxy()).run()

    def save_project_copy(self, checked=False):
        del checked
        SaveCopyProjectDialog(self._shell_proxy()).run()

    def quit_application(self, checked=False):
        del checked
        QuitCommand(self._shell_proxy()).run()
