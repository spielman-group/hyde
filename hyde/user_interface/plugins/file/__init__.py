from hyde.user_interface.shared.plugin import HydePlugin

from .dialogs import (
    HealProjectDialog,
    LoadProjectDialog,
    NewProjectDialog,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
)


class Plugin(HydePlugin):
    def setup(self, data=None):
        del data
        self.bind_menu_action("_new_action", "file", "New...")
        self.bind_menu_action("_load_action", "file", "Load...")
        self.bind_menu_action("_heal_project_action", "file", "Heal Project...")
        self.bind_menu_action("_save_action", "file", "Save")
        self.bind_menu_action("_save_as_action", "file", "Save As...")
        self.bind_menu_action("_save_copy_action", "file", "Save a Copy...")
        self.bind_menu_action("_quit_action", "file", "Quit")
        self._set_project_action_state(
            self.services["get_current_project_dir"]() is not None
        )

    def get_menu_contributions(self):
        return [
            {
                "location": "file",
                "group": "10_project",
                "order": 10,
                "name": "New...",
                "shortcut": "Ctrl+N",
                "action": self.new_project,
            },
            {
                "location": "file",
                "group": "10_project",
                "order": 20,
                "name": "Load...",
                "shortcut": "Ctrl+O",
                "action": self.load_project,
            },
            {
                "location": "file",
                "group": "10_project",
                "order": 30,
                "name": "Heal Project...",
                "action": self.heal_project,
            },
            {
                "location": "file",
                "group": "20_save",
                "order": 10,
                "name": "Save",
                "shortcut": "Ctrl+S",
                "action": self.save_project,
            },
            {
                "location": "file",
                "group": "20_save",
                "order": 20,
                "name": "Save As...",
                "action": self.save_project_as,
            },
            {
                "location": "file",
                "group": "20_save",
                "order": 30,
                "name": "Save a Copy...",
                "action": self.save_project_copy,
            },
            {
                "location": "file",
                "group": "30_application",
                "order": 100,
                "name": "Quit",
                "shortcut": "Ctrl+Q",
                "action": self.quit_application,
            },
        ]

    def _set_project_action_state(self, has_project):
        for attr_name in ("_new_action", "_load_action", "_quit_action"):
            self.set_bound_action_enabled(attr_name, True)
        for attr_name in (
            "_heal_project_action",
            "_save_action",
            "_save_as_action",
            "_save_copy_action",
        ):
            self.set_bound_action_enabled(attr_name, has_project)

    def new_project(self, checked=False):
        del checked
        NewProjectDialog(self.services).exec()

    def load_project(self, checked=False):
        del checked
        LoadProjectDialog(self.services).exec()

    def heal_project(self, checked=False):
        del checked
        HealProjectDialog(self.services).exec()

    def save_project(self, checked=False):
        del checked
        if not self.services["get_current_project_dir"]():
            return False
        app_ir = self.current_app_ir()
        save_ir = app_ir.with_save_project()
        self.services["begin_project_operation"]("Saving Hyde project...")
        return bool(
            self.services["python_execution_service"].execute_hidden(
                app_ir.current_diff(save_ir).python_source()
            )
        )

    def save_project_as(self, checked=False):
        del checked
        SaveAsProjectDialog(self.services).exec()

    def save_project_copy(self, checked=False):
        del checked
        SaveCopyProjectDialog(self.services).exec()

    def quit_application(self, checked=False):
        """Ask the kernel to bring Hyde down, once.

        A quit already in flight is refused, because the kernel needs asking
        only once and a second ask would tear down what the first is already
        taking apart. That refusal is only correct while "in flight" means a
        quit the kernel really has: it is recorded once the request is away and
        retracted by `on_quit_reply` if the kernel says the quit did not run,
        so a quit that never reached a kernel leaves Hyde as quittable as it
        was. Dispatched blind, the record could never be retracted, and one
        unlucky quit -- issued a moment before the kernel was ready -- would
        refuse every quit and every close for the rest of the session.
        """
        del checked
        if (
            self.services["get_shutting_down"]()
            or self.services["get_quit_command_sent"]()
        ):
            return False
        app_ir = self.current_app_ir()
        quit_ir = app_ir.with_quit()
        request = self.services["python_execution_service"].request(
            app_ir.current_diff(quit_ir).python_source(),
            on_finished=self.on_quit_reply,
        )
        if request is None:
            return False
        self.services["set_quit_command_sent"](True)
        return True

    def on_quit_reply(self, request):
        """The kernel answered the quit.

        A quit that ran has already asked the GUI to come down, so it stays on
        the books and the next quit is the second one this refuses. A quit that
        raised, or one a dying kernel took with it, asked for nothing: forget
        it, so the user can quit again.
        """
        if not request.ran():
            self.services["set_quit_command_sent"](False)

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
            app_ir = self.current_app_ir()
            load_ir = app_ir.with_load_project(project_dir)
            self.services["begin_project_operation"]("Loading Hyde project...")
            self.services["python_execution_service"].execute_hidden(
                app_ir.current_diff(load_ir).python_source()
            )
