import concurrent.futures
import time
from concurrent.futures import CancelledError, Future

import pytest

from sequence_extensions import GraphFuture, GraphPool

# concurrent.futures.TimeoutError is a distinct class from the builtin
# TimeoutError on Python 3.10; catch both.
_TIMEOUT_ERRORS = (TimeoutError, concurrent.futures.TimeoutError)


def fn_1(x, y):
    assert not isinstance(x, Future)
    return x


def fn_2(x, y):
    assert not isinstance(x, Future)
    return x * 2


def internal_func_3(y):
    return y


def fn_3(y, x):
    assert not isinstance(y, Future)
    return GraphFuture(internal_func_3, y)


def fn_exception(x):
    raise RuntimeError("boom")


def create_dependency(x, y):
    assert not isinstance(x, Future)
    assert not isinstance(y, Future)
    return y


def test_nested_future_one_nest():
    """Test with mixed args and kwargs"""
    with GraphPool(max_workers=3) as executor:
        future_1 = GraphFuture(fn_1, 5, y=4)

        nested_future_1 = GraphFuture(fn_2, future_1, y=4)

        nested_future_1_result = executor.result(nested_future_1)

        assert nested_future_1_result == 10


def test_nested_future_one_nest_2():
    """Run with only args"""
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_1, 5, 4)

        nested_future_1 = GraphFuture(fn_2, future_1, 4)

        nested_future_1_result = executor.result(nested_future_1)

        assert nested_future_1_result == 10


def test_nested_future_one_nest_3():
    """Run with only kwargs"""
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_1, x=5, y=4)

        nested_future_1_result = executor.result(future_1)

        assert nested_future_1_result == 5


def test_nested_future_multinested():
    """Run with multinested, GraphFuture returned from first node"""
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_3, 5, 5)
        future_2 = GraphFuture(fn_2, future_1, None)
        res = executor.result(future_2)
        assert res == 10


def test_nested_future_multinested_2():
    """Run with multinested, GraphFuture returned from second node"""
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_2, 5, 5)
        future_2 = GraphFuture(fn_3, future_1, 5)
        res = executor.result(future_2)

        assert res == 10


def test_nested_future_chaining_keeps_node_identity():
    # White-box: the chaining design keeps the user-facing node intact (the
    # inner GraphFuture is chained onto its future, not swapped in). This is
    # an internal design invariant, not a behavioral contract.
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_3, 5, 5)
        future_2 = GraphFuture(fn_2, future_1, None)
        assert executor.result(future_2) == 10
        assert future_2.function == fn_2
        assert future_1.function == fn_3


def test_nested_future_split():
    """Split graph: 6 nodes in 3 dependency layers.

    Layer 1 (leaves): fn_1(5,4)=5, fn_1(2,4)=2, fn_2(2,4)=4, fn_2(4,8)=8
    Layer 2: dependency_future_1 = create_dependency(5, 2) -> 2
             dependency_future_2 = create_dependency(4, 8) -> 8
    Layer 3: dependency_future_3 = create_dependency(2, 8) -> 8
    """
    with GraphPool(max_workers=3) as executor:
        fn_1_1_future = GraphFuture(fn_1, 5, 4)

        fn_1_2_future = GraphFuture(fn_1, 2, 4)

        fn_2_1_future = GraphFuture(fn_2, 2, 4)

        fn_2_2_future = GraphFuture(fn_2, 4, 8)

        dependency_future_1 = GraphFuture(create_dependency, fn_1_1_future, fn_1_2_future)

        dependency_future_2 = GraphFuture(create_dependency, fn_2_1_future, fn_2_2_future)

        dependency_future_3 = GraphFuture(
            create_dependency, dependency_future_1, dependency_future_2
        )

        dependency_result = executor.result(dependency_future_3)
        assert dependency_result == 8


def test_diamond_graph_shared_dependency():
    """Diamond: two parents share one dependency; the shared node runs once."""
    calls = []

    def shared(x):
        calls.append(x)
        return x * 10

    def left(x):
        return x + 1

    def right(x):
        return x + 2

    def combine(a, b):
        return a + b

    with GraphPool(max_workers=4) as p:
        dep = GraphFuture(shared, 1)
        left_future = GraphFuture(left, dep)
        r = GraphFuture(right, dep)
        top = GraphFuture(combine, left_future, r)
        assert p.result(top) == 23  # (10+1) + (10+2)
        assert len(calls) == 1  # shared dependency executed exactly once


def test_exception():
    """A node whose fn raises: the exception propagates from result()."""
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_exception, 45)
        with pytest.raises(RuntimeError, match="boom"):
            executor.result(future_1)
        # future state after the exception
        assert future_1.done() is True
        assert future_1.exception() is not None
        assert future_1.has_result() is False


def test_unbound_node_fn_never_called():
    """A node that is never bound to a pool never has its fn invoked."""
    called = []

    def never_run(x):
        called.append(x)
        return x

    node = GraphFuture(never_run, 1)
    # never passed to a pool -> fn must never be called
    assert called == []
    assert not node.future.done()

    # after binding to a pool, the fn DOES run (lazy but eventually runnable)
    with GraphPool(max_workers=2) as p:
        assert p.result(node) == 1
    assert called == [1]


def test_graphfuture_kwargs_constructor():
    """GraphFuture(function=fn, args=(1,2)) works (no positional-only)."""
    with GraphPool(max_workers=2) as p:
        gf = GraphFuture(function=fn_1, args=(1, 2))
        assert p.result(gf) == 1


def test_pool_result_timeout_param():
    """GraphPool.result(gf, timeout=None) — timeout param exists and works."""
    with GraphPool(max_workers=2) as p:
        gf = GraphFuture(lambda: (time.sleep(0.2), 42)[1])
        with pytest.raises(_TIMEOUT_ERRORS):
            p.result(gf, timeout=0.01)
        # the node is still pending; give it time to finish, then read it
        assert gf.result(timeout=2) == 42


def test_unbound_node_cancelled_at_pool_exit():
    """__exit__ cancels ALL live nodes, including unbound ones created inside
    the with-block: after exit, result() raises CancelledError (NOT hangs)."""
    node = None
    with GraphPool(max_workers=2):
        node = GraphFuture(lambda: (time.sleep(5), 1)[1])  # never bound
        assert not node.future.done()
    # pool exited -> the unbound node must have been cancelled
    assert node.future.done() is True
    assert node.future.cancelled() is True
    assert node.has_result() is False
    with pytest.raises(CancelledError):
        node.result()
    with pytest.raises(CancelledError):
        node.exception()


def test_pool_shutdown_with_pending_nodes():
    """Pool shutdown with pending nodes: a bound-but-queued node (waiting
    behind a running blocker) is cancelled at __exit__."""
    blocker = GraphFuture(lambda: (time.sleep(0.5), 1)[1])
    pending = GraphFuture(lambda: 2)
    with GraphPool(max_workers=1) as p:
        with pytest.raises(_TIMEOUT_ERRORS):
            p.result(blocker, timeout=0.05)  # starts running (sleeps)
        with pytest.raises(_TIMEOUT_ERRORS):
            p.result(pending, timeout=0.05)  # queued behind the blocker
        assert not pending.future.done()
    # __exit__ cancelled the queued node
    assert pending.future.done() is True
    assert pending.future.cancelled() is True
    with pytest.raises(CancelledError):
        pending.result()


def test_chained_inner_future_raising():
    """A chained inner future that raises: the exception propagates to the
    outer node."""

    def inner_raises(x):
        raise ValueError("inner failure")

    def returns_inner(x):
        return GraphFuture(inner_raises, x)

    with GraphPool(max_workers=2) as p:
        outer = GraphFuture(returns_inner, 1)
        with pytest.raises(ValueError, match="inner failure"):
            p.result(outer)
        assert outer.done() is True
        assert outer.exception() is not None
        assert outer.has_result() is False


def test_chained_inner_cycle_outer_settles():
    """A chained inner future that is cyclic (the fn returns the outer node
    itself): the outer settles with ValueError, no hang."""
    outer = None

    def returns_outer(x):
        return outer  # the inner future IS the outer node -> cycle

    outer = GraphFuture(returns_outer, 1)
    with GraphPool(max_workers=2) as p:
        with pytest.raises(ValueError, match="cycle"):
            p.result(outer, timeout=2)
        assert outer.done() is True


def test_pool_cycle_detection_whitebox():
    # White-box test: fabricate a cycle by mutating private state (a now
    # depends on b, which depends on a). This exercises _bind_graph's DFS
    # back-edge detection; the public constructor cannot build a cycle.
    a = GraphFuture(lambda: 1)
    b = GraphFuture(lambda x: x, a)
    # close the loop: a now depends on b
    a.arguments = {0: b}
    a.dependencies = [b]
    with GraphPool(max_workers=2) as p:
        with pytest.raises(ValueError, match="cycle"):
            p.result(a)
        # the pool is left usable after the cycle error
        fresh = GraphFuture(lambda: 7)
        assert p.result(fresh) == 7


def test_pool_cycle_detection_public_path():
    """Public-path cycle: a node that depends on itself (via post-hoc
    mutation) raises ValueError without deadlock."""
    a = GraphFuture(lambda: 1)
    a.arguments = {0: a}
    a.dependencies = [a]
    with GraphPool(max_workers=2) as p:
        with pytest.raises(ValueError, match="cycle"):
            p.result(a)


def test_bind_graph_dedup():
    """White-box: calling pool.result twice keeps _nodes length stable
    (_bind_graph dedups nodes)."""
    with GraphPool(max_workers=2) as p:
        a = GraphFuture(lambda: 1)
        b = GraphFuture(lambda x: x + 1, a)
        assert p.result(b) == 2
        first_len = len(p._nodes)
        assert p.result(b) == 2
        assert len(p._nodes) == first_len


def test_double_wire_double_submit_idempotent():
    """White-box: wiring/submitting a node twice does not double-run its fn."""
    calls = []

    def counted(x):
        calls.append(x)
        return x

    with GraphPool(max_workers=2) as p:
        a = GraphFuture(counted, 1)
        b = GraphFuture(lambda x: x, a)
        assert p.result(b) == 1
        # re-wire and re-submit the same nodes
        a._wire(p)
        b._wire(p)
        a._submit(p)
        b._submit(p)
        assert p.result(b) == 1
        assert len(calls) == 1


def test_has_result_false_after_exception():
    gf = GraphFuture(fn_exception, 1)
    with GraphPool(max_workers=2) as p:
        with pytest.raises(RuntimeError):
            p.result(gf)
    assert gf.done() is True
    assert gf.has_result() is False
