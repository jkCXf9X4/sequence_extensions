"""ProcessGraphPool — CPU-bound parallelism behind the ``pool=`` seam.

Covers: results and record replay, error and retry records, dependency
edges and skip records, dispatch failure, timeout across the process
boundary, pool exit cancelling queued nodes, ``execute_flow`` rejection
inside a process worker, and the wall-time gain on CPU-bound work.
"""

from __future__ import annotations

import pickle
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sequence_extensions.flow import (
    NodePolicy,
    NodeTimeoutError,
    ProcessDispatchError,
    ProcessGraphPool,
    RunLog,
    RunOptions,
    execute_flow,
    gather,
    node,
)
from sequence_extensions.graph.graph_future import GraphFuture


def _read_log(log_dir):
    return RunLog.records(next(Path(log_dir).glob("*.jsonl")))


def _node_records(recs):
    return [r for r in recs if r["record"] == "node"]


# Module-level nodes: picklable by contract (fork and spawn alike).
@node(retries=0)
def _plain(x):
    return x * 2


@node(retries=0, timeout=0.15)
def _slow_timeout(x):
    time.sleep(2.0)
    return x


@node(retries=0)
def _boom(x):
    raise ValueError(f"bad {x}")


@node(retries=2, retry_delay_seconds=0.01)
def _flaky(x):
    seen = getattr(_flaky, "seen", None)
    if seen is None:
        seen = _flaky.seen = {}
    seen[x] = seen.get(x, 0) + 1
    if seen[x] <= 2:
        raise RuntimeError(f"flake {seen[x]}")
    return x + 1


@node(retries=0)
def _sleepy(x):
    time.sleep(0.3)
    return x


@node(retries=0)
def _burn(n):
    total = 0
    for i in range(n):
        total += i * i
    return total


@node
def _nested():
    from sequence_extensions.flow import execute_flow

    @node
    def child():
        return 1

    return execute_flow(child, options=RunOptions(log=None)).result


@node
def _submits_in_worker():
    return _plain.submit(1)


@node
def _returns_a_future():
    import concurrent.futures

    future = concurrent.futures.Future()
    future.set_result(1)
    return future


# ---------------------------------------------------------------- #
# Results and record replay
# ---------------------------------------------------------------- #
def test_process_worker_keeps_node_defaults_for_direct_calls(tmp_path):
    counter = tmp_path / "calls"
    counter.write_text("0")

    @node
    def leaf():
        n = int(counter.read_text()) + 1
        counter.write_text(str(n))
        if n == 1:
            raise RuntimeError("first attempt")
        return n

    @node(retries=0)
    def outer():
        return leaf()

    @node(retries=0)
    def root():
        return outer.submit()

    pool = ProcessGraphPool(max_workers=1)
    with pool:
        run = execute_flow(
            root,
            options=RunOptions(
                log=None,
                pool=pool,
                node_defaults=NodePolicy(retries=1),
            ),
        )

    assert run.result == 2
    assert counter.read_text() == "2"


def test_process_pool_results_and_records(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @node
    def campaign():
        futures = [_plain.submit(i) for i in range(4)]
        return gather(futures)

    with pool:
        run = execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    assert run.result == [0, 2, 4, 6]
    recs = _read_log(tmp_path)
    nodes = _node_records(recs)
    assert len(nodes) == 5  # four leaves and the root
    assert all(n["status"] == "ok" for n in nodes)
    assert all(n["worker"].startswith("proc-") for n in nodes if n["node"] == "_plain")
    assert recs[-1]["record"] == "run_end" and recs[-1]["status"] == "ok"


def test_process_pool_error_records(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @node
    def campaign():
        return _boom.submit(1)

    with pool:
        with pytest.raises(ValueError, match="bad 1"):
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    nodes = _node_records(_read_log(tmp_path))
    boom = next(n for n in nodes if n["node"] == "_boom")
    assert boom["status"] == "error"
    assert boom["error"]["type"] == "ValueError"


def test_process_pool_retry_records(tmp_path):
    pool = ProcessGraphPool(max_workers=2)
    _flaky.seen = {}

    @node
    def campaign():
        return _flaky.submit(7)

    with pool:
        execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    nodes = [n for n in _node_records(_read_log(tmp_path)) if n["node"] == "_flaky"]
    assert [n["status"] for n in nodes] == ["error", "error", "ok"]
    assert [n["attempt"] for n in nodes] == [1, 2, 3]


# ---------------------------------------------------------------- #
# Dependency edges and skip records
# ---------------------------------------------------------------- #
def test_process_pool_dependency_and_skip_record(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @node
    def campaign():
        a = _boom.submit(1)
        return _plain.submit(a)

    with pool:
        with pytest.raises(ValueError, match="bad 1"):
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    nodes = _node_records(_read_log(tmp_path))
    statuses = {(n["node"], n["status"]) for n in nodes}
    assert ("_boom", "error") in statuses
    assert ("_plain", "skipped") in statuses
    skip = next(n for n in nodes if n["status"] == "skipped")
    assert skip["reason"] == "dependency failed"


def test_process_pool_gather_template_crosses_the_boundary(tmp_path):
    """The gather template is dispatched too, so it must pickle."""
    pool = ProcessGraphPool(max_workers=2)

    @node
    def root():
        return gather(
            {"a": _plain.submit(1), "b": [_plain.submit(2), {"c": _plain.submit(3)}]}
        )

    with pool:
        run = execute_flow(root, options=RunOptions(pool=pool, log=tmp_path))

    assert run.result == {"a": 2, "b": [4, {"c": 6}]}


# ---------------------------------------------------------------- #
# Dispatch failure and timeout
# ---------------------------------------------------------------- #
def test_process_pool_dispatch_failure(tmp_path):
    pool = ProcessGraphPool(max_workers=1)

    @node
    def campaign():
        return _plain.submit(_unpicklable())

    with pool:
        with pytest.raises(ProcessDispatchError):
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    nodes = _node_records(_read_log(tmp_path))
    plain = next(n for n in nodes if n["node"] == "_plain")
    assert plain["status"] == "skipped"
    assert plain["reason"] == "dispatch failed"
    assert plain["error"]["type"] == "ProcessDispatchError"


def _unpicklable():
    import threading

    return threading.Lock()


def test_process_pool_timeout_crosses_boundary(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @node
    def campaign():
        return _slow_timeout.submit(1)

    with pool:
        with pytest.raises(NodeTimeoutError) as info:
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    error = info.value
    assert error.node == "_slow_timeout"
    assert error.timeout == 0.15
    nodes = _node_records(_read_log(tmp_path))
    slow = next(n for n in nodes if n["node"] == "_slow_timeout")
    assert slow["status"] == "timeout"


def test_node_timeout_error_pickles():
    exc = NodeTimeoutError("n", 1.5, 2)
    clone = pickle.loads(pickle.dumps(exc))
    assert clone.node == "n"
    assert clone.timeout == 1.5
    assert clone.attempt == 2
    assert "n" in str(clone)


def test_execute_flow_inside_process_worker_is_rejected(tmp_path):
    pool = ProcessGraphPool(max_workers=1)

    @node
    def campaign():
        return _nested.submit()

    with pool:
        with pytest.raises(RuntimeError, match="process worker"):
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))


def test_submit_inside_process_worker_is_rejected(tmp_path):
    pool = ProcessGraphPool(max_workers=1)

    @node
    def campaign():
        return _submits_in_worker.submit()

    with pool:
        with pytest.raises(RuntimeError, match="process worker"):
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))


def test_process_worker_cannot_return_a_live_future(tmp_path):
    pool = ProcessGraphPool(max_workers=1)

    @node
    def campaign():
        return _returns_a_future.submit()

    with pool:
        with pytest.raises(RuntimeError, match="live future"):
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))


# ---------------------------------------------------------------- #
# Pool lifecycle
# ---------------------------------------------------------------- #
def _sleep_plain(x, marker=None):
    time.sleep(0.3)
    if marker is not None:
        Path(marker).write_text("ran")
    return x


def test_process_pool_exit_cancels_queued_nodes(tmp_path):
    marker = tmp_path / "ran"
    pool = ProcessGraphPool(max_workers=1)
    with pool:
        a = GraphFuture(_sleep_plain, 0, str(marker))
        b = GraphFuture(_sleep_plain, 1)
        pool.bind(a)
        pool.bind(b)
    assert marker.exists()
    assert a.future.cancelled() is True
    assert b.future.cancelled() is True


def test_process_pool_shared_across_two_runs(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @node
    def run_a():
        return _plain.submit(5)

    @node
    def run_b():
        return _plain.submit(6)

    with pool:
        a = execute_flow(run_a, options=RunOptions(pool=pool, log=tmp_path, name="first"))
        b = execute_flow(run_b, options=RunOptions(pool=pool, log=tmp_path, name="second"))
    assert a.result == 10
    assert b.result == 12

    logs = sorted(Path(tmp_path).glob("*.jsonl"))
    assert len(logs) == 2
    for log in logs:
        recs = RunLog.records(log)
        assert recs[-1]["record"] == "run_end" and recs[-1]["status"] == "ok"


# ---------------------------------------------------------------- #
# The point: CPU-bound parallelism
# ---------------------------------------------------------------- #
def test_process_pool_beats_gil_on_cpu_bound_work(tmp_path):
    n = 3_000_000
    t0 = time.perf_counter()
    baseline = _burn(n)
    one = time.perf_counter() - t0
    assert baseline > 0

    pool = ProcessGraphPool(max_workers=2)

    @node
    def campaign():
        futures = [_burn.submit(n) for _ in range(2)]
        return gather(futures)

    t0 = time.perf_counter()
    with pool:
        results = execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path)).result
    wall = time.perf_counter() - t0

    assert results == [baseline, baseline]
    assert wall < 1.7 * one, f"wall={wall:.3f}s one={one:.3f}s"


def test_process_pool_submit_after_exit_settles_cancelled():
    import concurrent.futures

    pool = ProcessGraphPool(max_workers=1)
    with pool:
        pass
    gf = GraphFuture(_sleep_plain, 1)
    pool.bind(gf)
    with pytest.raises(concurrent.futures.CancelledError):
        gf.result(timeout=2)
    assert pool._executor is None


def test_concurrent_runs_one_process_pool_per_run(tmp_path):
    @node
    def run_a():
        return _sleepy.submit(1)

    @node
    def run_b():
        return _sleepy.submit(2)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(
            execute_flow,
            run_a,
            options=RunOptions(
                pool=ProcessGraphPool(max_workers=1), log=tmp_path / "a", name="fa"
            ),
        )
        f2 = ex.submit(
            execute_flow,
            run_b,
            options=RunOptions(
                pool=ProcessGraphPool(max_workers=1), log=tmp_path / "b", name="fb"
            ),
        )
        assert f1.result(timeout=10).result == 1
        assert f2.result(timeout=10).result == 2

    for sub in ("a", "b"):
        recs = _read_log(tmp_path / sub)
        assert recs[-1]["record"] == "run_end" and recs[-1]["status"] == "ok"
