"""What the kernel does when it cannot tell the GUI something.

The senders in `hyde.execution.ipc` are reachable from a Hyde-managed kernel,
which has a channel to the GUI process, and from a plain interpreter, a script,
or a test, which has none. Only the first can fail: the second has nothing to
fail at, and must stay quiet.
"""

import unittest
from contextlib import contextmanager
from unittest.mock import patch

import hyde
from hyde.execution import ipc


class _AcceptingChannel:
    """A parent channel that takes messages, as a live GUI's does."""

    def __init__(self):
        self.messages = []

    def put(self, message):
        self.messages.append(message)


class _RefusingChannel:
    """A parent channel that is there but will not take a message."""

    def put(self, message):
        del message
        raise OSError("the parent process is not listening")


class _StubProcessTree:
    """A process tree with, or without, a channel to a parent process.

    `to_parent` is None in a process that never connected to a parent, which
    is the shape a real `ProcessTree` has in a plain interpreter.
    """

    def __init__(self, to_parent):
        self.to_parent = to_parent

    def instance(self):
        return self


@contextmanager
def _parent_channel(channel):
    with patch.object(ipc, "_ProcessTree", _StubProcessTree(channel)):
        yield channel


def _senders():
    """Every kernel-to-GUI signal, paired with the name it travels under.

    `signal_copy_to_clipboard` is deliberately absent: it belongs to the
    clipboard work and is left alone.
    """
    return [
        ("QUIT_REQUESTED", ipc.signal_quit_requested),
        ("ENTER_NO_PROJECT_STATE", ipc.signal_enter_no_project_state),
        ("ACTIVATE_PROJECT", lambda: ipc.signal_activate_project("/tmp/demo.hy")),
        ("OPEN_TABLE_REQUEST", lambda: ipc.signal_open_table(["counts"])),
        (
            "APPEND_TABLE_REQUEST",
            lambda: ipc.signal_append_table(["counts"], name="Table0"),
        ),
        (
            "PROJECT_STATE_RESULT",
            lambda: ipc.publish_project_state_result("save", "/tmp/demo.hy"),
        ),
    ]


class TestUndeliverableKernelSignals(unittest.TestCase):
    def test_a_signal_a_live_channel_refuses_is_logged_by_name(self):
        """A lost signal says which one it was, and does not reach its caller.

        The caller asked the GUI for something and carries on either way, so
        the log line is the only place the loss can show up.
        """
        for signal_name, send in _senders():
            with self.subTest(signal=signal_name):
                with _parent_channel(_RefusingChannel()):
                    with self.assertLogs("hyde", level="ERROR") as logged:
                        send()
                self.assertTrue(
                    any(signal_name in line for line in logged.output),
                    f"{signal_name} is not named in {logged.output}",
                )

    def test_a_process_with_no_parent_channel_says_nothing(self):
        """Importing `hyde` outside a Hyde kernel must not start logging errors.

        There is no GUI to tell, so nothing has gone wrong.
        """
        for description, process_tree in [
            ("a process that never connected to a parent", _StubProcessTree(None)),
            ("a process with no process tree at all", None),
        ]:
            with self.subTest(process=description):
                with patch.object(ipc, "_ProcessTree", process_tree):
                    with self.assertNoLogs("hyde", level="DEBUG"):
                        for _signal_name, send in _senders():
                            send()


class TestQuitTheGuiNeverHears(unittest.TestCase):
    def test_a_quit_that_cannot_be_delivered_is_in_the_log(self):
        with patch.object(hyde, "HYDE_GUI", True), _parent_channel(_RefusingChannel()):
            with self.assertLogs("hyde", level="ERROR") as logged:
                hyde.quit()

        self.assertTrue(
            any("QUIT_REQUESTED" in line for line in logged.output),
            f"QUIT_REQUESTED is not named in {logged.output}",
        )

    def test_a_quit_asks_for_the_shutdown_before_anything_else(self):
        """A quit must not cost the user their project before it is deliverable.

        The GUI acts on each request as it arrives, so anything sent ahead of
        the quit lands whether or not the quit does. A project dropped by a
        quit that never arrives leaves a Hyde with no project and no way out.
        """
        with patch.object(hyde, "HYDE_GUI", True), _parent_channel(
            _AcceptingChannel()
        ) as channel:
            hyde.quit()

        self.assertEqual(
            [message[0] for message in channel.messages][:1],
            ["QUIT_REQUESTED"],
        )


if __name__ == "__main__":
    unittest.main()
