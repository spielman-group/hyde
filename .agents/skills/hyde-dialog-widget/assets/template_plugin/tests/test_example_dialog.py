import unittest

from qtutils.qt import QtWidgets

from hyde.user_interface.plugins.kernel_runtime import KernelRequest

from plugin_package.dialogs import ExampleDialog


class FakeExecutionService:
    """`execute_hidden` says a command was sent; `request` says what became of
    it. `HydeDialogWidget`'s OK dispatches through `request`, so a fake standing
    in for `python_execution_service` has to offer both. Mirrors
    `tests/kernel_fakes.KernelRequestRecorder` in the Hyde repo.
    """

    def __init__(self):
        self.hidden_calls = []
        self.kernel_requests = []

    def execute_hidden(self, code, silent=True):
        self.hidden_calls.append((code, silent))
        return True

    def request(self, code, *, on_finished):
        self.execute_hidden(code)
        request = KernelRequest(f"msg-{len(self.kernel_requests) + 1}", code)
        self.kernel_requests.append((request, on_finished))
        return request

    def answer_last(self, outcome=KernelRequest.RAN, error=""):
        """Deliver the kernel's reply to the most recent request."""
        request, on_finished = self.kernel_requests[-1]
        request.settle(outcome, error)
        on_finished(request)
        return request


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

            dialog.copy_button.click()
            dialog.to_ipython_button.click()
            dialog.ok_button.click()

            self.assertEqual(dialog.lower_text_edit.toPlainText(), "User-facing preview")
            self.assertEqual(terminal.visible_calls, ["print('command source')"])
            self.assertEqual(
                execution.hidden_calls,
                [("print('command source')", True)],
            )
        finally:
            dialog.close()
