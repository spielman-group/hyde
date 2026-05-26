from abc import ABC, abstractmethod
import logging
import pprint

import hyde


def log_hyde_state_debug(label, state, source):
    if not hyde.HYDE_DEBUG:
        return
    logging.getLogger("hyde").debug(
        "[Hyde state] %s\nstate:\n%s\npython:\n%s",
        str(label),
        pprint.pformat(state, sort_dicts=True),
        str(source),
    )


def log_hyde_dispatch_debug(mode, source):
    log_hyde_state_debug(
        "TransportDispatchState",
        {"mode": str(mode)},
        str(source),
    )


class HydeIR(ABC):
    def debug_state(self):
        return dict(vars(self))

    def validate(self):
        return self

    @abstractmethod
    def _python_source(self):
        raise NotImplementedError

    def python_source(self, *, log=True):
        self.validate()
        source = self._python_source()
        if log:
            log_hyde_state_debug(type(self).__name__, self.debug_state(), source)
        return source


class HydeIRDiff(HydeIR):
    pass
