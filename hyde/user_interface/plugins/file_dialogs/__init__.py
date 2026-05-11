from hyde.user_interface.plugin_tools import HydePlugin

from .dialogs import (
    HealProjectDialog,
    LoadProjectState,
    LoadProjectDialog,
    NewProjectDialog,
    QuitCommand,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
    SaveProjectCommand,
)

class Plugin(HydePlugin):
    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self._actions = {}

    def setup(self, data=None):
        del data
        self._bind_actions()
        self._set_project_action_state(
            self.services["get_current_project_dir"]() is not None
        )

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
                "shortcut": "Ctrl+Q",
                "action": self.quit_application,
            },
        ]

    def _bind_actions(self):
        self._actions = {}
        bindings = {
            "new": ("file", "New..."),
            "load": ("file", "Load..."),
            "heal_project": ("file", "Heal Project..."),
            "save": ("file", "Save"),
            "save_as": ("file", "Save As..."),
            "save_copy": ("file", "Save a Copy..."),
            "quit": ("file", "Quit"),
        }
        for action_key, (location, text) in bindings.items():
            action = self.menu_action(location, text)
            if action is not None:
                self._actions[action_key] = action

    def _set_project_action_state(self, has_project):
        for name in ("new", "load", "quit"):
            action = self._actions.get(name)
            if action is not None:
                action.setEnabled(True)
        for name in ("heal_project", "save", "save_as", "save_copy"):
            action = self._actions.get(name)
            if action is not None:
                action.setEnabled(has_project)

    def _dispatch_load_project(self, project_dir):
        state = LoadProjectState()
        state.set_project_dir(project_dir)
        self.services["begin_project_operation"]("Loading Hyde project...")
        self.services["python_execution_service"].execute_hidden(
            state.python_source()
        )

    def new_project(self, checked=False):
        del checked
        NewProjectDialog(self.services).run()

    def load_project(self, checked=False):
        del checked
        LoadProjectDialog(self.services).run()

    def heal_project(self, checked=False):
        del checked
        HealProjectDialog(self.services).run()

    def save_project(self, checked=False):
        del checked
        SaveProjectCommand(self.services).run()

    def save_project_as(self, checked=False):
        del checked
        SaveAsProjectDialog(self.services).run()

    def save_project_copy(self, checked=False):
        del checked
        SaveCopyProjectDialog(self.services).run()

    def quit_application(self, checked=False):
        del checked
        QuitCommand(self.services).run()

    def get_event_handlers(self):
        return {
            "enter_no_project_state": self.on_enter_no_project_state,
            "project_activated": self.on_project_activated,
            "request_application_quit": self.on_request_application_quit,
            "request_project_load": self.on_request_project_load,
        }

    def on_enter_no_project_state(self, data):
        del data
        self._set_project_action_state(False)

    def on_project_activated(self, data):
        del data
        self._set_project_action_state(True)

    def on_request_application_quit(self, data):
        del data
        self.quit_application()

    def on_request_project_load(self, data):
        project_dir = data.get("project_dir")
        if project_dir:
            self._dispatch_load_project(project_dir)
