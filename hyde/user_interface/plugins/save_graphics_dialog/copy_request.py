"""In-flight state for one figure copy.

A copy is answered twice, by routes nothing orders against each other. The
kernel's `execute_reply` says the render ran and carries the reason when it did
not; the rendered bytes arrive separately on the parent-message channel. Either
can turn up first, so the copy stays open until it has what it needs.

Nothing here bounds how long the kernel may take. A copy issued while the user's
own cell is running waits its turn in the kernel's queue, and waiting is not
failing. The only clocks are cosmetic -- when to raise and lower a wait cursor
-- and the short gap between a successful render and its bytes.

Keeping that in one object is what makes forgetting hard: the plugin asks
whether a copy is in flight and settles it, rather than tracking three timers
and a cursor flag by hand at each return.
"""

from qtutils.qt import QtCore, QtWidgets


def _single_shot(receiver):
    # Bound methods only; see STYLE.md on Qt receiver lifetimes.
    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(receiver)
    return timer


class FigureCopyRequest:
    """One copy, from menu action to settled.

    `kernel_request` is the `KernelRequest` this copy is waiting on, so a reply
    can be matched to the copy that asked for it. A settled request is inert:
    settling twice, or a timer firing after settling, does nothing.
    """

    def __init__(
        self,
        *,
        busy_delay_ms,
        busy_hold_ms,
        on_payload_timeout,
    ):
        self.kernel_request = None
        self._busy_hold_ms = int(busy_hold_ms)
        self._busy_cursor_shown = False

        self._busy_timer = _single_shot(self.show_busy_cursor)
        self._busy_timer.start(int(busy_delay_ms))
        self._hold_timer = _single_shot(self.release_busy_cursor)
        self._payload_timer = _single_shot(on_payload_timeout)

    def show_busy_cursor(self):
        if self._busy_cursor_shown:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self._busy_cursor_shown = True
        # The cursor says something started, not how long it will take. Held
        # for a minute behind a long user cell it would read as a hang, so it
        # comes back down on its own and the status message carries the rest.
        self._hold_timer.start(self._busy_hold_ms)

    def release_busy_cursor(self):
        """Lower the cursor without settling; the copy is still waiting."""
        if not self._busy_cursor_shown:
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self._busy_cursor_shown = False

    def await_payload(self, timeout_ms):
        """The render ran. Bound the wait for bytes already in transit."""
        self._payload_timer.start(int(timeout_ms))

    def settle(self):
        """Stop the timers and restore the cursor. Safe to call more than once."""
        for timer in (self._busy_timer, self._hold_timer, self._payload_timer):
            timer.stop()
        self.release_busy_cursor()
