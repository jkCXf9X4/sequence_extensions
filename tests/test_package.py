"""Package-level smoke tests and coverage for previously-untested public methods."""

import concurrent.futures
import re
import subprocess
import sys
import threading
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

# concurrent.futures.TimeoutError is a distinct class from the builtin
# TimeoutError on Python 3.10; catch both.
_TIMEOUT_ERRORS = (TimeoutError, concurrent.futures.TimeoutError)


# ---------------------------------------------------------------- #
# Package smoke test
# ---------------------------------------------------------------- #
def test_imports_and_version():
    # contract: __version__ matches semver-ish \d+.\d+.\d+ (no hardcoded value)
    assert re.match(r"^\d+\.\d+\.\d+$", __version__) is not None


def test_package_exports():
    # contract: __init__ exports the graph_future module and KeyValueTuple
    import sequence_extensions

    assert hasattr(sequence_extensions, "graph_future")
    assert hasattr(sequence_extensions, "KeyValueTuple")


# ---------------------------------------------------------------- #
# list_ext
# ---------------------------------------------------------------- #
def test_execute_or_default_default_on_exception():
    assert list_ext.execute_or_default(lambda: 1 / 0, default=5, exception=ZeroDivisionError) == 5


def test_execute_or_default_custom_exception_class():
    class MyError(Exception):
        pass

    def _raise(e):
        raise e

    assert (
        list_ext.execute_or_default(
            lambda: _raise(MyError("x")),
            default="d",
            exception=MyError,
        )
        == "d"
    )

    # a different exception type is NOT caught
    with pytest.raises(MyError):
        list_ext.execute_or_default(
            lambda: _raise(MyError("x")),
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


def test_intersect_with_tuple():
    assert list_ext([1, 2]).intersect((2, 3)) == [2]


def test_union_basic():
    r = list_ext([1, 2, 3]).union([3, 4, 5])
    assert set(r) == {1, 2, 3, 4, 5}
    assert isinstance(r, list_ext)


def test_union_dedup():
    r = list_ext([1, 1, 2]).union([2, 2, 3])
    assert set(r) == {1, 2, 3}
    assert len(r) == 3


def test_union_with_set():
    r = list_ext([1, 2]).union({3, 4})
    assert set(r) == {1, 2, 3, 4}


def test_average():
    assert list_ext([1, 2, 3, 4]).average() == 2.5


def test_average_empty_raises():
    with pytest.raises(StatisticsError):
        list_ext().average()


def test_average_non_numeric_raises():
    with pytest.raises(TypeError):
        list_ext(["a", "b"]).average()


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


# ---------------------------------------------------------------- #
# dict_ext
# ---------------------------------------------------------------- #
def test_dict_union_merge():
    assert dict_ext({"a": 1}).union({"a": 9, "b": 2}) == {"a": 9, "b": 2}


def test_dict_map_non_tuple_raises():
    with pytest.raises(TypeError, match="2-tuple"):
        dict_ext({"a": 1}).map(lambda k, v: k)


# ---------------------------------------------------------------- #
# gen_ext
# ---------------------------------------------------------------- #
def test_recursive_gen_new_semantics():
    # stop_f is called on the *next* item: True keeps yielding, False stops
    # before yielding that item. 5 -> 4 -> 3 -> 2 -> 1 -> (0 stops).
    assert list(gen_ext.recursive_gen(5, lambda x: x - 1, stop_f=lambda x: x > 0)) == [4, 3, 2, 1]


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


def test_pool_usable_without_context_manager():
    # a pool used without `with` still works (lazy executor); the atexit
    # shutdown hook guarantees the process does not hang at exit.
    p = GraphPool(max_workers=2)
    a = GraphFuture(lambda: 1)
    assert p.result(a) == 1


def test_lazy_pool_atexit_shutdown_no_hang():
    # contract: lazy pool use (no `with`) gets an atexit shutdown — the
    # process does not hang at exit. Run in a subprocess and assert it exits.
    code = (
        "from sequence_extensions import GraphFuture, GraphPool\n"
        "p = GraphPool(max_workers=2)\n"
        "a = GraphFuture(lambda: 1)\n"
        "assert p.result(a) == 1\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


def test_pool_reentrant_enter_raises():
    # Public `with` protocol: a second `with` on the same pool raises.
    p = GraphPool(max_workers=2)
    with p:
        pass
    with pytest.raises(RuntimeError):
        with p:
            pass


def test_multi_dependency_node():
    a = GraphFuture(lambda: 1)
    b = GraphFuture(lambda: 2)
    c = GraphFuture(lambda x, y: x + y, a, b)
    with GraphPool(max_workers=2) as p:
        assert p.result(c) == 3


def test_result_timeout():
    """Deterministic timeout test: worker signals it started, then blocks on
    an Event; the timeout must raise while the future is provably pending."""
    started = threading.Event()
    release = threading.Event()

    def slow():
        started.set()
        release.wait(5)
        return 42

    with GraphPool(max_workers=2) as p:
        gf = GraphFuture(slow)
        t = threading.Thread(target=lambda: p.result(gf))
        t.start()
        try:
            assert started.wait(5), "worker never started"
            with pytest.raises(_TIMEOUT_ERRORS):
                gf.result(timeout=0.01)
        finally:
            release.set()
            t.join(5)
        assert gf.result(timeout=5) == 42
