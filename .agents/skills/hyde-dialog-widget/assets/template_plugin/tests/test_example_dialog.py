import unittest

from qtutils.qt import QtWidgets

from plugin_package.dialogs import ExampleDialog


class FakeExecutionService:
    def __init__(self):
        self.hidden_calls = []

    def execute_hidden(self, code, silent=True):
        self.hidden_calls.append((code, silent))
        return True


class FakeVisibleTerminalService:
    def __init__(self):
        self.visible_calls = []

    def execute_visible(self, code):
        self.visible_calls.append(code)
        return True


class TestExampleDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_footer_actions_use_backing_preview_string(self):
        execution = FakeExecutionService()
        terminal = FakeVisibleTerminalService()
        dialog = ExampleDialog(
            services={
                "python_execution_service": execution,
                "visible_terminal_service": terminal,
            }
        )
        try:
            dialog.set_preview_string(
                "print('command source')",
                display_text="User-facing preview",
            )
            dialog.refresh_shell()

            dialog.to_clip_button.click()
            dialog.to_cmd_line_button.click()
            dialog.do_it_button.click()

            self.assertEqual(dialog.lower_text_edit.toPlainText(), "User-facing preview")
            self.assertEqual(terminal.visible_calls, ["print('command source')"])
            self.assertEqual(
                execution.hidden_calls,
                [("print('command source')", True)],
            )
        finally:
            dialog.close()
