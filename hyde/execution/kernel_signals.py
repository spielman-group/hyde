import os
import signal
import sys


_PREVIOUS_SIGNAL_HANDLERS = {}


def _signal_name(signum):
    try:
        return signal.Signals(signum).name
    except Exception:
        return str(signum)


def _write_stderr(message):
    try:
        print(str(message), file=sys.stderr, flush=True)
    except Exception:
        pass


def _accept_signal(signum, frame):
    previous_handler = _PREVIOUS_SIGNAL_HANDLERS.get(signum, signal.SIG_DFL)
    if callable(previous_handler):
        previous_handler(signum, frame)
        return
    if previous_handler == signal.SIG_IGN:
        return
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _signal_marker_handler(signum, frame):
    _write_stderr(
        "[Hyde kernel] Received "
        f"{_signal_name(signum)} before accepting termination signal."
    )
    _accept_signal(signum, frame)


def install_signal_marker_handlers():
    for signum in (signal.SIGINT, signal.SIGTERM):
        # Hyde may install first and then be wrapped by zprocess KillLock.
        # Later gui_mode(True) calls must not replace that active wrapper.
        if (
            signum in _PREVIOUS_SIGNAL_HANDLERS
            or signal.getsignal(signum) is _signal_marker_handler
        ):
            continue
        _PREVIOUS_SIGNAL_HANDLERS[signum] = signal.getsignal(signum)
        signal.signal(signum, _signal_marker_handler)


def restore_signal_marker_handlers():
    for signum, previous_handler in list(_PREVIOUS_SIGNAL_HANDLERS.items()):
        # If another handler has wrapped Hyde's marker, leave both the active
        # wrapper and Hyde's registration record intact. Dropping the record
        # would let a later gui_mode(True) replace the wrapper.
        if signal.getsignal(signum) is _signal_marker_handler:
            signal.signal(signum, previous_handler)
            _PREVIOUS_SIGNAL_HANDLERS.pop(signum, None)
