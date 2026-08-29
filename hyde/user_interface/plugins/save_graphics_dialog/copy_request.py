"""In-flight state for one figure copy.

Copy renders in the kernel and the bytes return asynchronously, so between the
menu action and the clipboard write there is a request that has to be settled
however it ends. Every exit that forgets to settle leaves a timer armed and a
wait cursor on its way, for an operation that has already finished.

Keeping that in one object is what makes forgetting hard: the plugin asks
whether a request is in flight and settles it, rather than tracking a format, two
timers and a cursor flag by hand at each return.
"""

from qtutils.qt import QtCore, QtWidgets


class FigureCopyRequest:
    """One copy, from menu action to settled.

    `on_show_busy` and `on_timeout` are called on the Qt main thread. A settled
    request is inert: settling twice, or timing out after settling, does
    nothing.
    """

    def __init__(self, output_format, *, busy_delay_ms, timeout_ms, on_timeout):
        self.output_format = str(output_format)
        self._busy_cursor_shown = False

        self._busy_timer = QtCore.QTimer()
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self.show_busy_cursor)
        self._busy_timer.start(busy_delay_ms)

        self._timeout_timer = QtCore.QTimer()
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(on_timeout)
        self._timeout_timer.start(timeout_ms)

    def show_busy_cursor(self):
        if self._busy_cursor_shown:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self._busy_cursor_shown = True

    def settle(self):
        """Stop the timers and restore the cursor. Safe to call more than once."""
        for timer in (self._busy_timer, self._timeout_timer):
            if timer is not None:
                timer.stop()
        self._busy_timer = None
        self._timeout_timer = None
        if self._busy_cursor_shown:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._busy_cursor_shown = False
