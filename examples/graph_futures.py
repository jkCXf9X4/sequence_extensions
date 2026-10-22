"""Dependency-graph futures: ``GraphFuture`` and ``GraphPool``.

Builds a diamond DAG, shows that a node may return another future (its
result is forwarded), and checks the two failure modes a caller must
handle: a node raising, and a result that is not ready in time.

Run::

    python examples/graph_futures.py
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from sequence_extensions import GraphFuture, GraphPool


def add(a, b):
    return a + b


def scale(value, factor):
    return value * factor


def outer():
    """Returning a future chains it onto this node; the worker is freed."""
    return GraphFuture(lambda: 20).set_name("inner")


def main() -> dict:
    outcomes = {}

    with GraphPool(max_workers=4) as pool:
        # One diamond: base is evaluated once, left and right run in
        # parallel, total waits for both.
        base = GraphFuture(lambda: 10).set_name("base")
        left = GraphFuture(scale, base, 2).set_name("left")
        right = GraphFuture(scale, base, 3).set_name("right")
        total = GraphFuture(add, left, right).set_name("total")
        outcomes["diamond"] = pool.result(total)

        # A returned future is forwarded as the node's result.
        outcomes["chained"] = pool.result(GraphFuture(outer))

        # Any concurrent.futures.Future is a dependency too.
        with ThreadPoolExecutor(max_workers=1) as executor:
            plain = executor.submit(lambda: 4)
            outcomes["plain_future"] = pool.result(GraphFuture(scale, plain, 5))

        # An exception from a node function propagates from result().
        try:
            pool.result(GraphFuture(lambda: 1 / 0).set_name("bad"))
        except ZeroDivisionError:
            outcomes["error"] = "ZeroDivisionError"

        # timeout= bounds the wait; the node itself keeps running.
        try:
            pool.result(GraphFuture(lambda: time.sleep(0.2)).set_name("slow"), timeout=0.01)
        except TimeoutError:
            outcomes["timeout"] = "TimeoutError"

    print("diamond: ", outcomes["diamond"])
    print("chained: ", outcomes["chained"])
    print("plain:   ", outcomes["plain_future"])
    print("node error:", outcomes["error"])
    print("timeout:   ", outcomes["timeout"])
    return outcomes


if __name__ == "__main__":
    main()
