import pytest
from concurrent.futures import Future

from sequence_extensions import GraphFuture, GraphPool


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


def lazy_fn(x):
    assert False


def fn_exception(x):
    raise Exception("Random stuff went to shits")


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

        # The new chaining design keeps the user-facing node intact:
        # the inner GraphFuture is chained onto its future, not swapped in.
        assert future_2.function == fn_2
        assert future_1.function == fn_3


def test_nested_future_multinested_2():
    """Run with multinested, GraphFuture returned from second node"""
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_2, 5, 5)
        future_2 = GraphFuture(fn_3, future_1, 5)
        res = executor.result(future_2)

        assert res == 10

        assert future_2.function == fn_3
        assert future_1.function == fn_2


def test_nested_future_split():
    """graph 4->2->1

    Value derivation: dependency_future_1 = create_dependency(fn_1(5,4)=5, fn_1(2,4)=2) -> 2
    dependency_future_2 = create_dependency(fn_2(2,4)=4, fn_2(4,8)=8) -> 8
    dependency_future_3 = create_dependency(dep_1=2, dep_2=8) -> 8
    """
    with GraphPool(max_workers=3) as executor:
        fn_1_1_future = GraphFuture(fn_1, 5, 4)

        fn_1_2_future = GraphFuture(fn_1, 2, 4)

        fn_2_1_future = GraphFuture(fn_2, 2, 4)

        fn_2_2_future = GraphFuture(fn_2, 4, 8)

        dependency_future_1 = GraphFuture(
            create_dependency, fn_1_1_future, fn_1_2_future
        )

        dependency_future_2 = GraphFuture(
            create_dependency, fn_2_1_future, fn_2_2_future
        )

        dependency_future_3 = GraphFuture(
            create_dependency, dependency_future_1, dependency_future_2
        )

        dependency_result = executor.result(dependency_future_3)
        assert dependency_result == 8


def test_exception():
    """Run with multinested, GraphFuture returned from first node"""
    with GraphPool(max_workers=6) as executor:
        future_1 = GraphFuture(fn_exception, 45)
        with pytest.raises(Exception, match="Random stuff"):
            executor.result(future_1)


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