"""Package-level smoke tests and coverage for previously-untested public methods."""

import concurrent.futures
import threading
import time
from statistics import StatisticsError

import pytest

from sequence_extensions import (
    GraphFuture,
    GraphPool,
    __version__,
    dict_ext,
    gen_ext,
    list_ext,
)


# ---------------------------------------------------------------- #
# Package smoke test
# ---------------------------------------------------------------- #
def test_imports_and_version():
    from sequence_extensions import (
        GraphFuture,
        GraphPool,
        dict_ext,
        gen_ext,
        list_ext,
    )

    assert __version__ == "0.1.4"


# ---------------------------------------------------------------- #
# list_ext
# ---------------------------------------------------------------- #
def test_execute_or_default_default_on_exception():
    assert (
        list_ext.execute_or_default(
            lambda: 1 / 0, default=5, exception=ZeroDivisionError
        )
        == 5
    )


def test_execute_or_default_custom_exception_class():
    class MyError(Exception):
        pass

    assert (
        list_ext.execute_or_default(
            lambda: (_ for _ in ()).throw(MyError("x")),
            default="d",
            exception=MyError,
        )
        == "d"
    )

    # a different exception type is NOT caught
    with pytest.raises(MyError):
        list_ext.execute_or_default(
            lambda: (_ for _ in ()).throw(MyError("x")),
            default="d",
            exception=KeyError,
        )


def test_execute_or_default_no_exception_passthrough():
    assert list_ext.execute_or_default(lambda: 42) == 42


def test_intersect_basic():
    r = list_ext([1, 2, 3]).intersect([2, 3, 4])
    assert set(r) == {2, 3}
    assert isinstance(r, list_ext)


def test_intersect_empty():
    assert list_ext([1, 2, 3]).intersect([4, 5]) == []


def test_union_basic():
    r = list_ext([1, 2, 3]).union([3, 4, 5])
    assert set(r) == {1, 2, 3, 4, 5}
    assert isinstance(r, list_ext)


def test_union_dedup():
    r = list_ext([1, 1, 2]).union([2, 2, 3])
    assert set(r) == {1, 2, 3}
    assert len(r) == 3


def test_average():
    assert list_ext([1, 2, 3, 4]).average() == 2.5


def test_average_empty_raises():
    with pytest.raises(StatisticsError):
        list_ext().average()


def test_max_min():
    assert list_ext([1, 5, 3]).max() == 5
    assert list_ext([1, 5, 3]).min() == 1
    with pytest.raises(ValueError):
        list_ext().max()
    with pytest.raises(ValueError):
        list_ext().min()


def test_window_zero_raises():
    with pytest.raises(ValueError):
        list_ext([1, 2, 3]).window(n=0)


def test_window_select_requires_func():
    with pytest.raises(TypeError):
        list_ext([1, 2, 3]).window_select()


def test_single_empty_and_zero_match():
    with pytest.raises(ValueError, match="Expected exactly one item"):
        list_ext().single()
    with pytest.raises(ValueError, match="Expected exactly one item"):
        list_ext([1, 2]).single(lambda x: x > 5)


def test_chainmap_first_dict_wins():
    assert list_ext([{"a": 1}, {"a": 2}]).chainmap() == {"a": 1}


# ---------------------------------------------------------------- #
# dict_ext
# ---------------------------------------------------------------- #
def test_dict_union_merge():
    assert dict_ext({"a": 1}).union({"a": 9, "b": 2}) == {"a": 9, "b": 2}


def test_dict_filter_none_keeps_all():
    d = dict_ext({"a": 1, "b": 2})
    f = d.filter(None)
    assert f == {"a": 1, "b": 2}
    assert f is not d


def test_dict_reduce_empty():
    assert (
        dict_ext().reduce(lambda a, b: (a.key + b.key, a.value + b.value))
        == dict_ext()
    )


def test_dict_all_any_values_not_keys():
    assert dict_ext({0: "x"}).all() is True
    assert dict_ext({"a": 0}).any() is False


def test_dict_extend_other_wins():
    assert dict_ext({"a": 1}).extend({"a": 9, "b": 2}) == {"a": 9, "b": 2}


def test_dict_map_non_tuple_raises():
    with pytest.raises(TypeError):
        dict_ext({"a": 1}).map(lambda k, v: k)


# ---------------------------------------------------------------- #
# gen_ext
# ---------------------------------------------------------------- #
def test_gen_to_list():
    r = gen_ext.to_list(iter([1, 2, 3]))
    assert r == [1, 2, 3]
    assert type(r) is list


def test_recursive_gen_new_semantics():
    # stop_f is called on the *next* item: True keeps yielding, False stops
    # before yielding that item. 5 -> 4 -> 3 -> 2 -> 1 -> (0 stops).
    assert (
        list(gen_ext.recursive_gen(5, lambda x: x - 1, stop_f=lambda x: x > 0))
        == [4, 3, 2, 1]
    )


# ---------------------------------------------------------------- #
# graph_future
# ---------------------------------------------------------------- #
def test_set_name():
    gf = GraphFuture(lambda: 1)
    assert gf.set_name("my_node") is gf
    assert gf.name == "my_node"


def test_has_result():
    gf = GraphFuture(lambda: 1)
    assert gf.has_result() is False
    with GraphPool(max_workers=2) as p:
        p.result(gf)
    assert gf.has_result() is True


def test_str_repr_contain_name():
    gf = GraphFuture(lambda: 1).set_name("my_node")
    assert "my_node" in str(gf)
    assert "my_node" in repr(gf)


def test_future_passthroughs():
    with GraphPool(max_workers=2) as p:
        gf = GraphFuture(lambda: 42)
        assert gf.done() is False
        assert gf.cancelled() is False
        callbacks = []
        gf.add_done_callback(lambda f: callbacks.append(f))
        assert p.result(gf) == 42
        assert gf.done() is True
        assert gf.cancelled() is False
        assert gf.exception() is None
        assert len(callbacks) == 1


def test_pool_without_with_lazy_executor():
    p = GraphPool(max_workers=2)
    a = GraphFuture(lambda: 1)
    assert p.result(a) == 1
    p._executor.shutdown()


def test_pool_cycle_detection():
    a = GraphFuture(lambda: 1)
    b = GraphFuture(lambda x: x, a)
    # close the loop: a now depends on b
    a.arguments = {0: b}
    a.dependencies = [b]
    with GraphPool(max_workers=2) as p:
        with pytest.raises(ValueError, match="cycle"):
            p.result(a)


def test_pool_reentrant_enter_raises():
    with GraphPool(max_workers=2) as p:
        with pytest.raises(RuntimeError):
            p.__enter__()


def test_multi_dependency_node():
    a = GraphFuture(lambda: 1)
    b = GraphFuture(lambda: 2)
    c = GraphFuture(lambda x, y: x + y, a, b)
    with GraphPool(max_workers=2) as p:
        assert p.result(c) == 3


def test_result_timeout():
    with GraphPool(max_workers=2) as p:
        gf = GraphFuture(lambda: (time.sleep(0.1), 42)[1])
        t = threading.Thread(target=lambda: p.result(gf))
        t.start()
        with pytest.raises((TimeoutError, concurrent.futures.TimeoutError)):
            gf.result(timeout=0.001)
        t.join()
        assert gf.result() == 42