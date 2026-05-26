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

from hyde.user_interface.plugins.file import Plugin
from hyde.user_interface.plugins.file.dialogs import (
    HealProjectDialog,
    HydeAppIR,
    LoadProjectDialog,
    NewProjectDialog,
    ProjectSelectionDialogIR,
    SaveAsProjectDialog,
    SaveCopyProjectDialog,
)


class ExecutionService:
    def __init__(self, dispatched):
        self._dispatched = dispatched

    def execute_hidden(self, code, silent=True):
        self._dispatched.append((code, silent))
        return True


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
            dialog.do_it_button.click()

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

    def test_load_project_dialog_owns_dialog_ir_and_carries_app_snapshot(self):
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

            self.assertFalse(hasattr(dialog, "app_ir"))
            self.assertIsInstance(dialog.widget_ir, ProjectSelectionDialogIR)
            self.assertEqual(
                dialog.widget_ir.current_project_dir(),
                "/tmp/current.hy",
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
                    dialog.do_it_button.click()

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
            dialog.do_it_button.click()

            self.assertEqual(confirmations, [])
            self.assertEqual(operations, ["Loading Hyde project..."])
            self.assertEqual(
                dispatched,
                [(f"hyde.load_project({project_dir!r})", True)],
            )

    def test_project_dialog_preview_generation_does_not_log_hyde_state_debug(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            services = {
                "ui": QtWidgets.QWidget(),
                "python_execution_service": ExecutionService([]),
            }

            dialog = LoadProjectDialog(services)
            with patch(
                "hyde.user_interface.shared.core.log_hyde_state_debug"
            ) as log_debug:
                dialog.file_widget.set_selected_path(project_dir)
                self.qapp.processEvents()

            self.assertEqual(
                dialog.preview_string(),
                f"hyde.load_project({project_dir!r})",
            )
            log_debug.assert_not_called()

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
            dialog.do_it_button.click()

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
            dialog.do_it_button.click()

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
            self.assertFalse(dialog.do_it_button.isEnabled())

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
            dialog.to_clip_button.click()
            dialog.to_cmd_line_button.click()

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

    def test_plugin_quit_application_dispatches_hidden_quit_once(self):
        dispatched = []
        flags = {"quit_sent": False}
        services = {
            "get_shutting_down": lambda: False,
            "get_quit_command_sent": lambda: flags["quit_sent"],
            "set_quit_command_sent": lambda value: flags.__setitem__("quit_sent", value),
            "python_execution_service": ExecutionService(dispatched),
        }
        plugin = self.build_plugin(services)

        plugin.quit_application()
        plugin.quit_application()

        self.assertTrue(flags["quit_sent"])
        self.assertEqual(dispatched, [("hyde.quit()", True)])


if __name__ == "__main__":
    unittest.main()
