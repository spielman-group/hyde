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

from hyde.user_interface.plugins.file_dialogs.dialogs import SaveCopyProjectDialog


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
                "execute_command": lambda code, visible=True: dispatched.append(
                    (code, visible)
                ),
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


if __name__ == "__main__":
    unittest.main()
