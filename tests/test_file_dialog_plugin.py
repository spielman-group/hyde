import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import labscript_utils.plugins  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("labscript_utils.plugins is required") from exc

from qtutils.qt import QtWidgets

from hyde.user_interface.plugins.file_dialogs import Plugin
from hyde.user_interface.plugins.file_dialogs.dialogs import SaveCopyProjectDialog


class _DummyUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.menuFile = QtWidgets.QMenu("File", self)
        for text in (
            "New...",
            "Load...",
            "Heal Project...",
            "Save",
            "Save As...",
            "Save a Copy...",
            "Quit",
        ):
            self.menuFile.addAction(text)


def _lookup_file_action(ui):
    actions = {action.text(): action for action in ui.menuFile.actions()}

    def lookup_menu_action(location, name, path=()):
        if location != "file" or path:
            return None
        return actions.get(name)

    return lookup_menu_action


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

    def test_no_project_state_disables_heal_project(self):
        ui = _DummyUI()
        lookup_menu_action = Mock(side_effect=_lookup_file_action(ui))
        plugin = Plugin(initial_settings={})
        plugin.plugin_setup_complete(
            {
                "services": {
                    "ui": ui,
                    "lookup_menu_action": lookup_menu_action,
                    "get_current_project_dir": lambda: "/tmp/current.hy",
                }
            }
        )

        heal_action = next(
            action for action in ui.menuFile.actions() if action.text() == "Heal Project..."
        )
        self.assertTrue(heal_action.isEnabled())

        plugin.on_enter_no_project_state({})

        self.assertFalse(heal_action.isEnabled())
        self.assertIs(plugin._actions["heal_project"], heal_action)

    def test_plugin_binds_file_actions_from_lookup_service(self):
        ui = _DummyUI()
        lookup_menu_action = Mock(side_effect=_lookup_file_action(ui))
        plugin = Plugin(initial_settings={})

        plugin.plugin_setup_complete(
            {
                "services": {
                    "ui": ui,
                    "lookup_menu_action": lookup_menu_action,
                    "get_current_project_dir": lambda: None,
                }
            }
        )

        self.assertIs(
            plugin._actions["heal_project"],
            _lookup_file_action(ui)("file", "Heal Project..."),
        )
        self.assertIs(plugin._actions["quit"], _lookup_file_action(ui)("file", "Quit"))


if __name__ == "__main__":
    unittest.main()
