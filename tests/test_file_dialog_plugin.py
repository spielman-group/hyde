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

from qtutils.qt import QtWidgets

from hyde.user_interface.plugins.file_dialogs.dialogs import (
    QuitCommand,
    SaveCopyProjectDialog,
    SaveProjectCommand,
)


class TestFileDialogPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication(sys.argv)

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
                "python_execution_service": type(
                    "ExecutionService",
                    (),
                    {"execute_hidden": lambda self, code, silent=True: dispatched.append((code, silent))},
                )(),
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

    def test_save_project_command_is_muted(self):
        dispatched = []
        operations = []
        services = {
            "get_current_project_dir": lambda: "/tmp/project.hy",
            "begin_project_operation": operations.append,
            "python_execution_service": type(
                "ExecutionService",
                (),
                {"execute_hidden": lambda self, code, silent=True: dispatched.append((code, silent))},
            )(),
        }

        self.assertTrue(SaveProjectCommand(services).run())

        self.assertEqual(operations, ["Saving Hyde project..."])
        self.assertEqual(dispatched, [("hyde.save_project(mode='save')", True)])

    def test_quit_command_is_muted(self):
        dispatched = []
        flags = {"quit_sent": False}
        services = {
            "get_shutting_down": lambda: False,
            "get_quit_command_sent": lambda: flags["quit_sent"],
            "set_quit_command_sent": lambda value: flags.__setitem__("quit_sent", value),
            "python_execution_service": type(
                "ExecutionService",
                (),
                {"execute_hidden": lambda self, code, silent=True: dispatched.append((code, silent))},
            )(),
        }

        self.assertTrue(QuitCommand(services).run())
        self.assertTrue(flags["quit_sent"])
        self.assertEqual(dispatched, [("hyde.quit()", True)])


if __name__ == "__main__":
    unittest.main()
