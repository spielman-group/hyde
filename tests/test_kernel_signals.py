import io
import signal
import unittest
from unittest.mock import Mock, call, patch

from hyde.execution import kernel_signals


class TestKernelSignals(unittest.TestCase):
    def tearDown(self):
        kernel_signals._PREVIOUS_SIGNAL_HANDLERS.clear()

    def test_install_signal_marker_handlers_registers_sigint_and_sigterm(self):
        previous_handlers = {
            signal.SIGINT: signal.default_int_handler,
            signal.SIGTERM: signal.SIG_DFL,
        }

        with patch(
            "hyde.execution.kernel_signals.signal.getsignal",
            side_effect=lambda signum: previous_handlers[signum],
        ), patch("hyde.execution.kernel_signals.signal.signal") as set_signal:
            kernel_signals.install_signal_marker_handlers()

        self.assertEqual(
            kernel_signals._PREVIOUS_SIGNAL_HANDLERS,
            previous_handlers,
        )
        self.assertEqual(
            set_signal.call_args_list,
            [
                call(signal.SIGINT, kernel_signals._signal_marker_handler),
                call(signal.SIGTERM, kernel_signals._signal_marker_handler),
            ],
        )

    def test_signal_marker_handler_logs_receipt_before_accepting_default_signal(self):
        stderr = io.StringIO()
        kernel_signals._PREVIOUS_SIGNAL_HANDLERS[signal.SIGTERM] = signal.SIG_DFL

        with patch("sys.stderr", stderr), patch(
            "hyde.execution.kernel_signals.signal.signal"
        ) as set_signal, patch(
            "hyde.execution.kernel_signals.os.kill"
        ) as kill, patch(
            "hyde.execution.kernel_signals.os.getpid",
            return_value=4321,
        ):
            kernel_signals._signal_marker_handler(signal.SIGTERM, object())

        self.assertIn("Received SIGTERM", stderr.getvalue())
        set_signal.assert_called_once_with(signal.SIGTERM, signal.SIG_DFL)
        kill.assert_called_once_with(4321, signal.SIGTERM)

    def test_signal_marker_handler_delegates_to_previous_callable_handler(self):
        previous_handler = Mock()
        frame = object()
        kernel_signals._PREVIOUS_SIGNAL_HANDLERS[signal.SIGINT] = previous_handler

        with patch("hyde.execution.kernel_signals._write_stderr") as write_stderr:
            kernel_signals._signal_marker_handler(signal.SIGINT, frame)

        write_stderr.assert_called_once()
        previous_handler.assert_called_once_with(signal.SIGINT, frame)

    def test_signal_marker_handler_respects_previous_ignore_handler(self):
        kernel_signals._PREVIOUS_SIGNAL_HANDLERS[signal.SIGTERM] = signal.SIG_IGN

        with patch("hyde.execution.kernel_signals._write_stderr"), patch(
            "hyde.execution.kernel_signals.os.kill"
        ) as kill:
            kernel_signals._signal_marker_handler(signal.SIGTERM, object())

        kill.assert_not_called()

    def test_restore_signal_marker_handlers_restores_previous_handlers(self):
        previous_handlers = {
            signal.SIGINT: signal.default_int_handler,
            signal.SIGTERM: signal.SIG_DFL,
        }
        kernel_signals._PREVIOUS_SIGNAL_HANDLERS.update(previous_handlers)

        with patch(
            "hyde.execution.kernel_signals.signal.getsignal",
            return_value=kernel_signals._signal_marker_handler,
        ), patch("hyde.execution.kernel_signals.signal.signal") as set_signal:
            kernel_signals.restore_signal_marker_handlers()

        self.assertEqual(
            set_signal.call_args_list,
            [
                call(signal.SIGINT, signal.default_int_handler),
                call(signal.SIGTERM, signal.SIG_DFL),
            ],
        )
        self.assertEqual(kernel_signals._PREVIOUS_SIGNAL_HANDLERS, {})


if __name__ == "__main__":
    unittest.main()
