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
    LoadProjectDialog,
    NewProjectDialog,
    SaveCopyProjectDialog,
)


class ExecutionService:
    def __init__(self, dispatched):
        self._dispatched = dispatched

    def execute_hidden(self, code, silent=True):
        self._dispatched.append((code, silent))


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

    def test_new_project_dialog_dispatches_hidden_command(self):
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
            with patch.object(NewProjectDialog, "exec_", return_value=True):
                with patch.object(
                    NewProjectDialog, "selectedFiles", return_value=[project_dir]
                ):
                    self.assertTrue(dialog.run())

            self.assertEqual(operations, ["Creating Hyde project..."])
            self.assertEqual(
                dispatched,
                [
                    (
                        f"hyde.new_project({project_dir!r}, load=True, overwrite=True)",
                        True,
                    )
                ],
            )

    def test_load_project_dialog_dispatches_hidden_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "existing.hy")
            os.makedirs(project_dir)
            dispatched = []
            operations = []
            services = {
                "ui": QtWidgets.QWidget(),
                "begin_project_operation": operations.append,
                "python_execution_service": ExecutionService(dispatched),
            }

            dialog = LoadProjectDialog(services)
            with patch.object(LoadProjectDialog, "exec_", return_value=True):
                with patch.object(
                    LoadProjectDialog, "selectedFiles", return_value=[project_dir]
                ):
                    self.assertTrue(dialog.run())

            self.assertEqual(operations, ["Loading Hyde project..."])
            self.assertEqual(
                dispatched,
                [(f"hyde.load_project({project_dir!r})", True)],
            )

    def test_save_copy_same_path_stays_copy_only(self):
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

            dialog = SaveCopyProjectDialog(services)
            with patch.object(SaveCopyProjectDialog, "exec_", return_value=True):
                with patch.object(
                    SaveCopyProjectDialog, "selectedFiles", return_value=[project_dir]
                ):
                    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
                        self.assertFalse(dialog.run())

            warning.assert_called_once()
            self.assertEqual(dispatched, [])
            self.assertEqual(operations, [])

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
