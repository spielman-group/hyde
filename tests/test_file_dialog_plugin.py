import os
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from qtutils.qt import QtGui, QtWidgets

from tests.kernel_fakes import KernelRequestRecorder
from hyde.features.hyde_ir import HydeAppIR
from hyde.features.hyde_features import hyde_app_python_source
from hyde.user_interface.main import HydeApp, HydeMainWindow
from hyde.user_interface.plugins.kernel_runtime import KernelRequest
from hyde.user_interface.plugins.file import Plugin
from hyde.user_interface.plugins.file.dialogs import (
    HealProjectDialog,
    LoadProjectDialog,
    NewProjectDialog,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
)


class ExecutionService(KernelRequestRecorder):
    """A stand-in kernel that can also be an absent one.

    `ready` is what a caller cannot see for itself. An absent kernel refuses
    both verbs -- `execute_hidden` with False, `request` with None -- as
    `Plugin.execute_frontend` and `Plugin.request_frontend` do before the
    kernel is ready, so nothing reaches `dispatched` that a kernel would not
    have received.
    """

    def __init__(self, dispatched, ready=True):
        self._dispatched = dispatched
        self.ready = ready

    def execute_hidden(self, code, silent=True):
        if not self.ready:
            return False
        self._dispatched.append((code, silent))
        return True

    def request(self, code, *, on_finished):
        if not self.ready:
            return None
        return super().request(code, on_finished=on_finished)


class VisibleTerminalService:
    def __init__(self):
        self.executed = []

    def execute_visible(self, code):
        self.executed.append(code)


class TestFileDialogPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def build_actions(self):
        action_names = (
            "New...",
            "Load...",
            "Heal Project...",
            "Save",
            "Save As...",
            "Save a Copy...",
            "Quit",
        )
        return {
            ("file", name): QtGui.QAction(name, None)
            for name in action_names
        }

    def build_plugin(self, services):
        plugin = Plugin({})
        plugin.bind_services({"services": services})
        return plugin

    def test_plugin_setup_keeps_file_action_state_in_sync_with_project_state(self):
        actions = self.build_actions()
        services = {
            "lookup_menu_action": lambda location, name, path=(): actions.get(
                (location, name)
            ),
            "get_current_project_dir": lambda: None,
        }
        plugin = self.build_plugin(services)

        plugin.setup()

        self.assertTrue(actions[("file", "New...")].isEnabled())
        self.assertTrue(actions[("file", "Load...")].isEnabled())
        self.assertTrue(actions[("file", "Quit")].isEnabled())
        self.assertFalse(actions[("file", "Heal Project...")].isEnabled())
        self.assertFalse(actions[("file", "Save")].isEnabled())
        self.assertFalse(actions[("file", "Save As...")].isEnabled())
        self.assertFalse(actions[("file", "Save a Copy...")].isEnabled())

        plugin.on_project_activated({})

        self.assertTrue(actions[("file", "Heal Project...")].isEnabled())
        self.assertTrue(actions[("file", "Save")].isEnabled())
        self.assertTrue(actions[("file", "Save As...")].isEnabled())
        self.assertTrue(actions[("file", "Save a Copy...")].isEnabled())

        plugin.on_enter_no_project_state({})

        self.assertFalse(actions[("file", "Heal Project...")].isEnabled())
        self.assertFalse(actions[("file", "Save")].isEnabled())
        self.assertFalse(actions[("file", "Save As...")].isEnabled())
        self.assertFalse(actions[("file", "Save a Copy...")].isEnabled())

    def test_new_project_dialog_previews_and_dispatches_hidden_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "new_project.hy")
            dispatched = []
            operations = []
            services = {
                "ui": QtWidgets.QWidget(),
                "begin_project_operation": operations.append,
                "python_execution_service": ExecutionService(dispatched),
                "project_target_needs_confirmation": lambda path: True,
                "confirm_overwrite_project": lambda path: True,
            }

            dialog = NewProjectDialog(services)
            self.assertEqual(
                dialog.file_widget.selectedNameFilter(),
                "Hyde Packages (*.hy)",
            )
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.ok_button.click()

            self.assertEqual(operations, ["Creating Hyde project..."])
            self.assertEqual(
                dialog.preview_string(),
                f"hyde.new_project({project_dir!r}, load=True, overwrite=True)",
            )
            self.assertEqual(
                dispatched,
                [
                    (
                        f"hyde.new_project({project_dir!r}, load=True, overwrite=True)",
                        True,
                    )
                ],
            )

    def test_load_project_ir_diff_preserves_python_source(self):
        initial_ir = HydeAppIR(current_project_dir="/tmp/current.hy")
        current_ir = initial_ir.with_load_project("/tmp/demo.hy")

        self.assertEqual(
            initial_ir.current_diff(current_ir).python_source(),
            "hyde.load_project('/tmp/demo.hy')",
        )

    def test_app_ir_python_source_matches_feature_lowerer_for_file_commands(self):
        ir = HydeAppIR(current_project_dir="/tmp/current.hy")

        self.assertEqual(
            ir.with_new_project("/tmp/new.hy", load=False, overwrite=True).python_source(
                log=False
            ),
            hyde_app_python_source(
                command="new_project",
                target_project_dir="/tmp/new.hy",
                load=False,
                overwrite=True,
            ),
        )
        self.assertEqual(
            ir.with_load_project("/tmp/load.hy").python_source(log=False),
            hyde_app_python_source(
                command="load_project",
                target_project_dir="/tmp/load.hy",
            ),
        )
        self.assertEqual(
            ir.with_heal_project("/tmp/heal.hy").python_source(log=False),
            hyde_app_python_source(
                command="heal_project",
                target_project_dir="/tmp/heal.hy",
            ),
        )
        self.assertEqual(
            ir.with_save_project(
                target_project_dir="/tmp/copy.hy",
                mode="copy",
                overwrite=True,
            ).python_source(log=False),
            hyde_app_python_source(
                command="save_project",
                target_project_dir="/tmp/copy.hy",
                save_mode="copy",
                overwrite=True,
            ),
        )

    def test_load_project_dialog_uses_hyde_app_ir_and_carries_app_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            services = {
                "ui": QtWidgets.QWidget(),
                "python_execution_service": ExecutionService([]),
                "get_current_app_ir": lambda: HydeAppIR(current_project_dir="/tmp/current.hy"),
            }

            dialog = LoadProjectDialog(services)
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()

            self.assertIsInstance(dialog.widget_ir, HydeAppIR)
            self.assertEqual(
                dialog.widget_ir.current_project_dir,
                "/tmp/current.hy",
            )
            self.assertEqual(
                dialog.widget_ir.command,
                "load_project",
            )
            self.assertEqual(
                dialog.widget_ir.target_project_dir,
                project_dir,
            )
            self.assertEqual(
                dialog.widget_ir.python_source(log=False),
                f"hyde.load_project({project_dir!r})",
            )
            self.assertEqual(
                dialog.preview_string(),
                dialog.widget_ir.python_source(log=False),
            )

    def test_existing_project_dialogs_preview_and_dispatch_hidden_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            scenarios = (
                (
                    LoadProjectDialog,
                    "Loading Hyde project...",
                    f"hyde.load_project({project_dir!r})",
                ),
                (
                    HealProjectDialog,
                    "Healing Hyde project...",
                    f"hyde.heal_project({project_dir!r})",
                ),
            )

            for dialog_class, operation_label, expected_payload in scenarios:
                with self.subTest(dialog_class=dialog_class.__name__):
                    dispatched = []
                    operations = []
                    services = {
                        "ui": QtWidgets.QWidget(),
                        "begin_project_operation": operations.append,
                        "python_execution_service": ExecutionService(dispatched),
                    }

                    dialog = dialog_class(services)
                    dialog.file_widget.set_selected_path(project_dir)
                    self.qapp.processEvents()
                    dialog.ok_button.click()

                    self.assertEqual(dialog.preview_string(), expected_payload)
                    self.assertEqual(dialog.lower_text_edit.toPlainText(), expected_payload)
                    self.assertEqual(operations, [operation_label])
                    self.assertEqual(dispatched, [(expected_payload, True)])

    def test_load_project_dialog_never_prompts_overwrite_for_existing_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            dispatched = []
            operations = []
            confirmations = []
            services = {
                "ui": QtWidgets.QWidget(),
                "begin_project_operation": operations.append,
                "python_execution_service": ExecutionService(dispatched),
                "project_target_needs_confirmation": lambda path: True,
                "confirm_overwrite_project": lambda path: confirmations.append(path) or True,
            }

            dialog = LoadProjectDialog(services)
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.ok_button.click()

            self.assertEqual(confirmations, [])
            self.assertEqual(operations, ["Loading Hyde project..."])
            self.assertEqual(
                dispatched,
                [(f"hyde.load_project({project_dir!r})", True)],
            )

    def test_project_dialog_preview_generation_updates_preview_without_dispatching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            dispatched = []
            services = {
                "ui": QtWidgets.QWidget(),
                "python_execution_service": ExecutionService(dispatched),
            }

            dialog = LoadProjectDialog(services)
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()

            self.assertEqual(
                dialog.preview_string(),
                f"hyde.load_project({project_dir!r})",
            )
            self.assertEqual(dialog.lower_text_edit.toPlainText(), dialog.preview_string())
            self.assertEqual(dispatched, [])

    def test_save_as_same_target_previews_and_dispatches_plain_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "current.hy")
            os.makedirs(project_dir)
            dispatched = []
            operations = []
            services = {
                "ui": QtWidgets.QWidget(),
                "get_current_project_dir": lambda: project_dir,
                "begin_project_operation": operations.append,
                "python_execution_service": ExecutionService(dispatched),
                "project_target_needs_confirmation": lambda path: False,
                "confirm_overwrite_project": lambda path: True,
            }

            dialog = SaveAsProjectDialog(services)
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.ok_button.click()

            self.assertEqual(dialog.preview_string(), "hyde.save_project(mode='save')")
            self.assertEqual(dialog.lower_text_edit.toPlainText(), dialog.preview_string())
            self.assertEqual(operations, ["Saving Hyde project..."])
            self.assertEqual(dispatched, [("hyde.save_project(mode='save')", True)])

    def test_save_as_same_target_skips_overwrite_confirmation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "current.hy")
            os.makedirs(project_dir)
            dispatched = []
            operations = []
            confirmations = []
            services = {
                "ui": QtWidgets.QWidget(),
                "get_current_project_dir": lambda: project_dir,
                "begin_project_operation": operations.append,
                "python_execution_service": ExecutionService(dispatched),
                "project_target_needs_confirmation": lambda path: True,
                "confirm_overwrite_project": lambda path: confirmations.append(path) or True,
            }

            dialog = SaveAsProjectDialog(services)
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.ok_button.click()

            self.assertEqual(confirmations, [])
            self.assertEqual(dialog.preview_string(), "hyde.save_project(mode='save')")
            self.assertEqual(operations, ["Saving Hyde project..."])
            self.assertEqual(dispatched, [("hyde.save_project(mode='save')", True)])

    def test_save_copy_same_path_requires_different_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "current.hy")
            os.makedirs(project_dir)
            services = {
                "ui": QtWidgets.QWidget(),
                "get_current_project_dir": lambda: project_dir,
                "python_execution_service": ExecutionService([]),
                "project_target_needs_confirmation": lambda path: False,
                "confirm_overwrite_project": lambda path: True,
            }

            dialog = SaveCopyProjectDialog(services)
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()

            self.assertEqual(dialog.preview_string(), "")
            self.assertIn("requires a different .hy directory", dialog.lower_text_edit.toPlainText())
            self.assertFalse(dialog.ok_button.isEnabled())

    def test_project_dialog_footer_actions_reuse_preview_payload(self):
        clipboard = QtWidgets.QApplication.clipboard()
        terminal_service = VisibleTerminalService()
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            services = {
                "ui": QtWidgets.QWidget(),
                "python_execution_service": ExecutionService([]),
                "visible_terminal_service": terminal_service,
            }

            dialog = LoadProjectDialog(services)
            dialog.file_widget.set_selected_path(project_dir)
            self.qapp.processEvents()
            dialog.copy_button.click()
            dialog.to_ipython_button.click()

            expected_payload = f"hyde.load_project({project_dir!r})"
            self.assertEqual(dialog.preview_string(), expected_payload)
            self.assertEqual(dialog.lower_text_edit.toPlainText(), expected_payload)
            self.assertEqual(clipboard.text(), expected_payload)
            self.assertEqual(terminal_service.executed, [expected_payload])

    def test_plugin_save_project_dispatches_hidden_save(self):
        dispatched = []
        operations = []
        services = {
            "get_current_project_dir": lambda: "/tmp/project.hy",
            "begin_project_operation": operations.append,
            "python_execution_service": ExecutionService(dispatched),
        }
        plugin = self.build_plugin(services)

        plugin.save_project()

        self.assertEqual(operations, ["Saving Hyde project..."])
        self.assertEqual(dispatched, [("hyde.save_project(mode='save')", True)])

    def build_quit_plugin(self, execution_service):
        state = {"quit_sent": False}
        return self.build_plugin(
            {
                "get_shutting_down": lambda: False,
                "get_quit_command_sent": lambda: state["quit_sent"],
                "set_quit_command_sent": (
                    lambda value: state.__setitem__("quit_sent", value)
                ),
                "python_execution_service": execution_service,
            }
        )

    def test_plugin_quit_application_dispatches_hidden_quit_once(self):
        """The kernel needs asking once, and a quit in flight is in flight."""
        dispatched = []
        plugin = self.build_quit_plugin(ExecutionService(dispatched))

        plugin.quit_application()
        plugin.quit_application()

        self.assertEqual(dispatched, [("hyde.quit()", True)])

    def test_plugin_quit_application_survives_a_kernel_that_was_not_there(self):
        """Quit chosen a moment before the kernel is up must not be the last.

        Nothing reached a kernel, so nothing is in flight, so the next quit is
        the first one rather than a refused second.
        """
        dispatched = []
        execution_service = ExecutionService(dispatched, ready=False)
        plugin = self.build_quit_plugin(execution_service)

        plugin.quit_application()
        execution_service.ready = True
        plugin.quit_application()

        self.assertEqual(dispatched, [("hyde.quit()", True)])

    def test_plugin_quit_application_survives_a_quit_that_did_not_run(self):
        """The kernel answered, and the answer was not "I am going down".

        A `hyde.quit()` that raises -- the user reset the namespace out from
        under it -- and a quit a dying kernel abandoned both leave Hyde up and
        unasked. Either way the user gets to ask again.
        """
        for outcome in (KernelRequest.RAISED, KernelRequest.ABANDONED):
            with self.subTest(outcome=outcome):
                dispatched = []
                execution_service = ExecutionService(dispatched)
                plugin = self.build_quit_plugin(execution_service)

                plugin.quit_application()
                execution_service.answer_last(outcome, "the quit did not run")
                plugin.quit_application()

                self.assertEqual(
                    dispatched,
                    [("hyde.quit()", True), ("hyde.quit()", True)],
                )

    def test_plugin_quit_application_does_not_ask_twice_for_a_quit_that_ran(self):
        """A quit the kernel ran has already asked the GUI to come down."""
        dispatched = []
        execution_service = ExecutionService(dispatched)
        plugin = self.build_quit_plugin(execution_service)

        plugin.quit_application()
        execution_service.answer_last(KernelRequest.RAN)
        plugin.quit_application()

        self.assertEqual(dispatched, [("hyde.quit()", True)])


class QuitLaneApp(HydeApp):
    """A `HydeApp` whose quit is real from the close event to the kernel.

    Subclassed rather than faked, because the defect this guards lived in the
    seam between the parts: the window's close event, the app's record of a
    quit in flight, the file plugin's dispatch and the shutdown that follows
    are each their own code here, over a real `HydeMainWindow`. Only the
    kernel is stood in for.
    """

    def __init__(self, execution_service):
        self.shutting_down = False
        self._runtime_shutdown = False
        self._close_ready = False
        self._quit_command_sent = False
        self.current_project_dir = None
        self.procedures_dir = None
        self.procedures_init = None
        self.current_app_ir = self._build_current_app_ir()
        self._project_operation_message = None
        self.events = []
        self.ui = HydeMainWindow(self)
        self.file_plugin = Plugin({})
        self.file_plugin.bind_services(
            {
                "services": {
                    "get_shutting_down": self.get_shutting_down,
                    "set_shutting_down": self.set_shutting_down,
                    "get_quit_command_sent": self.get_quit_command_sent,
                    "set_quit_command_sent": self.set_quit_command_sent,
                    "get_current_app_ir": self.get_current_app_ir,
                    "python_execution_service": execution_service,
                }
            }
        )

    def emit_plugin_event(self, name, data=None):
        self.events.append(name)
        handler = self.file_plugin.get_event_handlers().get(name)
        if handler is not None:
            handler(data or {})

    def stop_project_watcher(self):
        return None


class TestClosingHydeKeepsWorking(unittest.TestCase):
    """Hyde stays closable, however badly a quit went.

    Driven through the window's own close event, because the close button is
    the path a user reaches for when the Quit item has stopped answering, and
    it must not stop answering with it.
    """

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

    def build_app(self, execution_service):
        app = QuitLaneApp(execution_service)
        self.addCleanup(app.ui.deleteLater)
        app.ui.show()
        return app

    def land_the_quit(self, app, execution_service):
        """Everything the kernel does once it has run `hyde.quit()`."""
        execution_service.answer_last(KernelRequest.RAN)
        app.request_gui_quit()
        app.finalize_quit()

    def test_the_close_button_still_closes_after_a_quit_that_never_landed(self):
        """Closing the window a moment too early must not seal Hyde shut.

        The first close finds no kernel to ask and Hyde stays open, which is
        all it can do. What it must not do is stay open for good.
        """
        dispatched = []
        execution_service = ExecutionService(dispatched, ready=False)
        app = self.build_app(execution_service)

        app.ui.close()
        self.assertTrue(app.ui.isVisible())
        self.assertEqual(dispatched, [])

        execution_service.ready = True
        app.ui.close()
        self.assertEqual(dispatched, [("hyde.quit()", True)])

        self.land_the_quit(app, execution_service)
        self.assertFalse(app.ui.isVisible())

    def test_the_close_button_still_closes_after_a_quit_the_kernel_refused(self):
        """The kernel raised on `hyde.quit()`; the window is still a window."""
        dispatched = []
        execution_service = ExecutionService(dispatched)
        app = self.build_app(execution_service)

        app.ui.close()
        execution_service.answer_last(KernelRequest.RAISED, "no hyde in the namespace")
        self.assertTrue(app.ui.isVisible())

        app.ui.close()
        self.land_the_quit(app, execution_service)

        self.assertFalse(app.ui.isVisible())

    def test_a_quit_in_flight_refuses_the_close_button_behind_it(self):
        """Quit, then the close button before Hyde has had time to go.

        The kernel has the quit and has not answered yet, so this second ask
        is the one the guard exists for.
        """
        dispatched = []
        execution_service = ExecutionService(dispatched)
        app = self.build_app(execution_service)

        app.file_plugin.quit_application()
        app.ui.close()

        self.assertEqual(dispatched, [("hyde.quit()", True)])
        self.assertTrue(app.ui.isVisible())

    def test_a_quit_that_landed_shuts_hyde_down_once(self):
        """Three close events over one quit, and one shutdown out of them.

        The close button raises a close event, the kernel's answer closes the
        window again, and the runtime's own teardown closes it a third time.
        Only the first of those may ask the runtime to come down.
        """
        dispatched = []
        execution_service = ExecutionService(dispatched)
        app = self.build_app(execution_service)

        app.ui.close()
        self.land_the_quit(app, execution_service)

        self.assertEqual(dispatched, [("hyde.quit()", True)])
        self.assertEqual(app.events.count("application_shutdown"), 1)
        self.assertEqual(app.events.count("request_runtime_shutdown"), 1)
        self.assertFalse(app.ui.isVisible())

    def test_the_close_button_still_closes_after_the_kernel_crashed(self):
        """A crash takes any quit in flight with it, answer or no answer."""
        dispatched = []
        execution_service = ExecutionService(dispatched)
        app = self.build_app(execution_service)

        app.ui.close()
        with patch("hyde.user_interface.main.QtWidgets.QMessageBox.warning"):
            app.on_kernel_crashed()

        app.ui.close()
        self.assertEqual(
            dispatched,
            [("hyde.quit()", True), ("hyde.quit()", True)],
        )

        self.land_the_quit(app, execution_service)
        self.assertFalse(app.ui.isVisible())


if __name__ == "__main__":
    unittest.main()
