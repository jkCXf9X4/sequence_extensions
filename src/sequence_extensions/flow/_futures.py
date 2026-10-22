"""Deferred result types shared by the flow engine and process pools.

``FlowOutcome`` is the per-attempt future; ``FlowFuture`` is a submitted
node's graph future.  Both reject blocking on an incomplete future inside a
node body or pool worker, where blocking would deadlock the attempt.
"""

from __future__ import annotations

import concurrent.futures

from sequence_extensions.flow._context import in_node_body, in_worker
from sequence_extensions.graph.graph_future import GraphFuture

_BLOCKED_IN_BODY = (
    "blocked on an incomplete future inside a node body; return the future "
    "instead (or submit a dependent node)"
)

def _is_future(value) -> bool:
    return isinstance(value, (GraphFuture, concurrent.futures.Future))


class NodeTimeoutError(TimeoutError):
    """A node attempt exceeded its ``timeout`` budget.

    Attributes: ``node`` (node name), ``timeout`` (seconds), ``attempt``
    (the attempt that exceeded it).
    """

    def __init__(self, node, timeout, attempt):
        self.node = node
        self.timeout = timeout
        self.attempt = attempt
        super().__init__(f"node '{node}' exceeded its timeout of {timeout}s (attempt {attempt})")

    def __reduce__(self):
        """Pickle transport for process pools."""
        return (type(self), (self.node, self.timeout, self.attempt))


class FlowOutcome(concurrent.futures.Future):
    """A deferred node outcome; blocking on it inside a node body is rejected."""

    def result(self, timeout=None):
        if (in_node_body() or in_worker()) and not self.done():
            raise RuntimeError(_BLOCKED_IN_BODY)
        return super().result(timeout=timeout)


class FlowFuture(GraphFuture):
    """A submitted node's graph future; blocking on it inside a node body is rejected."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path: tuple = ()
        self.parent_attempt = None
        self.attempted = False
        self.process_records: list[dict] | None = None

    def result(self, timeout=None):
        if (in_node_body() or in_worker()) and not self.future.done():
            raise RuntimeError(_BLOCKED_IN_BODY)
        return super().result(timeout=timeout)
