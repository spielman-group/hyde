"""Shared fakes for the kernel request verb.

`execute_hidden` answers "was it sent". `request` answers "what became of it",
which is the question the kernel request owner exists to make askable, so a fake
standing in for `python_execution_service` has to offer both.
"""

from hyde.user_interface.plugins.kernel_runtime import KernelRequest


class KernelRequestRecorder:
    """Give a fake execution service the `request` verb and a way to answer.

    Mixed in rather than written out per fake: the recorder needs no `__init__`
    of its own, so an existing fake gains both by naming it as a base.
    """

    @property
    def kernel_requests(self):
        if not hasattr(self, "_kernel_requests"):
            self._kernel_requests = []
        return self._kernel_requests

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
