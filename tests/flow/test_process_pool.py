"""ProcessGraphPool — CPU-bound parallelism behind the ``pool=`` seam.

Covers: results and record replay, error and retry records, dependency
edges and skip records, dispatch failure, timeout across the process
boundary, pool exit cancelling queued nodes, and the wall-time gain on
CPU-bound work.
"""

from __future__ import annotations

import pickle
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sequence_extensions.flow import (
    ProcessDispatchError,
    ProcessGraphPool,
    RunLog,
    TaskTimeoutError,
    flow,
    task,
)
from sequence_extensions.graph.graph_future import GraphFuture


def _read_log(log_dir):
    return RunLog.records(next(Path(log_dir).glob("*.jsonl")))


def _task_records(recs):
    return [r for r in recs if r["record"] == "task"]


# Module-level tasks: picklable by contract (fork and spawn alike).
@task(retries=0)
def _plain(x):
    return x * 2


@task(retries=0)
def _boom(x):
    raise ValueError(f"bad {x}")


@task(retries=2, retry_delay_seconds=0.01)
def _flaky(x):
    # Fails twice per distinct argument, then succeeds; per-argument
    # state lives in the worker that runs the attempt loop.
    seen = getattr(_flaky, "seen", None)
    if seen is None:
        seen = _flaky.seen = {}
    seen[x] = seen.get(x, 0) + 1
    if seen[x] <= 2:
        raise RuntimeError(f"flake {seen[x]}")
    return x + 1


@task(retries=0)
def _sleepy(x):
    time.sleep(0.3)
    return x


@task(retries=0)
def _burn(n):
    total = 0
    for i in range(n):
        total += i * i
    return total


# ---------------------------------------------------------------- #
# Results and record replay
# ---------------------------------------------------------------- #
def test_process_pool_results_and_records(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @flow(pool=pool, log=tmp_path)
    def campaign():
        futures = [_plain.submit(i) for i in range(4)]
        return [f.result() for f in futures]

    with pool:
        assert campaign() == [0, 2, 4, 6]

    recs = _read_log(tmp_path)
    tasks = _task_records(recs)
    assert len(tasks) == 4
    assert all(t["status"] == "ok" for t in tasks)
    assert all(t["worker"].startswith("proc-") for t in tasks)
    assert recs[-1]["record"] == "run_end" and recs[-1]["status"] == "ok"


def test_process_pool_error_records(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @flow(pool=pool, log=tmp_path)
    def campaign():
        return _boom.submit(1).result()

    with pool:
        with pytest.raises(ValueError, match="bad 1"):
            campaign()

    tasks = _task_records(_read_log(tmp_path))
    assert len(tasks) == 1
    assert tasks[0]["status"] == "error"
    assert tasks[0]["error"]["type"] == "ValueError"


def test_process_pool_retry_records(tmp_path):
    pool = ProcessGraphPool(max_workers=2)
    _flaky.seen = {}  # reset the module-state flake marker (workers fork after)

    @flow(pool=pool, log=tmp_path)
    def campaign():
        return _flaky.submit(7).result()

    with pool:
        assert campaign() == 8

    tasks = _task_records(_read_log(tmp_path))
    assert [t["status"] for t in tasks] == ["error", "error", "ok"]
    assert [t["attempt"] for t in tasks] == [1, 2, 3]


# ---------------------------------------------------------------- #
# Dependency edges and skip records
# ---------------------------------------------------------------- #
def test_process_pool_dependency_and_skip_record(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @flow(pool=pool, log=tmp_path)
    def campaign():
        a = _boom.submit(1)
        b = _plain.submit(a)  # depends on the failing task
        try:
            a.result()
        except ValueError:
            return b
        raise AssertionError("unreachable")

    with pool:
        skipped = campaign()

    tasks = _task_records(_read_log(tmp_path))
    statuses = {(t["task"], t["status"]) for t in tasks}
    assert ("_boom", "error") in statuses
    assert ("_plain", "skipped") in statuses
    skip = next(t for t in tasks if t["status"] == "skipped")
    assert skip["reason"] == "dependency failed"
    assert skipped.exception() is not None


# ---------------------------------------------------------------- #
# Dispatch failure and timeout
# ---------------------------------------------------------------- #
def test_process_pool_dispatch_failure(tmp_path):
    pool = ProcessGraphPool(max_workers=1)

    @flow(pool=pool, log=tmp_path)
    def campaign():
        f = _plain.submit(_unpicklable())  # argument cannot cross a process boundary
        try:
            f.result()
        except ProcessDispatchError:
            return "dispatch-failed"
        raise AssertionError("unreachable")

    with pool:
        assert campaign() == "dispatch-failed"

    tasks = _task_records(_read_log(tmp_path))
    assert len(tasks) == 1
    assert tasks[0]["status"] == "skipped"
    assert tasks[0]["reason"] == "dispatch failed"
    assert tasks[0]["error"]["type"] == "ProcessDispatchError"


def _unpicklable():
    import threading

    return threading.Lock()  # locks cannot be pickled


def test_process_pool_timeout_crosses_boundary(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @flow(pool=pool, log=tmp_path)
    def campaign():
        @task(retries=0, timeout=0.15)
        def slow(x):
            time.sleep(2.0)
            return x

        f = slow.submit(1)
        try:
            f.result()
        except TaskTimeoutError as exc:
            return exc
        raise AssertionError("unreachable")

    with pool:
        error = campaign()

    assert error.task == "slow"
    assert error.timeout == 0.15
    tasks = _task_records(_read_log(tmp_path))
    assert tasks[0]["status"] == "timeout"


def test_task_timeout_error_pickles():
    """TaskTimeoutError survives the process boundary (custom __reduce__)."""
    exc = TaskTimeoutError("t", 1.5, 2)
    clone = pickle.loads(pickle.dumps(exc))
    assert clone.task == "t"
    assert clone.timeout == 1.5
    assert clone.attempt == 2
    assert "t" in str(clone)


# ---------------------------------------------------------------- #
# Pool lifecycle
# ---------------------------------------------------------------- #
def _sleep_plain(x, marker=None):
    time.sleep(0.3)
    if marker is not None:
        Path(marker).write_text("ran")
    return x


def test_process_pool_exit_cancels_queued_nodes(tmp_path):
    """Exit cancels this pool's pending nodes — thread-mode parity: the
    running node finishes in the worker (shutdown waits), but its node
    future is cancelled too; the queued node never runs."""
    marker = tmp_path / "ran"
    pool = ProcessGraphPool(max_workers=1)
    with pool:
        a = GraphFuture(_sleep_plain, 0, str(marker))  # occupies the worker
        b = GraphFuture(_sleep_plain, 1)  # queued behind it
        pool.bind(a)
        pool.bind(b)
    assert marker.exists()  # the running node finished before exit returned
    assert a.future.cancelled() is True  # completion discarded, as in threads
    assert b.future.cancelled() is True  # the queued node never ran


def test_process_pool_shared_across_two_flows(tmp_path):
    pool = ProcessGraphPool(max_workers=2)

    @flow(pool=pool, log=tmp_path, name="first")
    def first():
        return _plain.submit(5).result()

    @flow(pool=pool, log=tmp_path, name="second")
    def second():
        return _plain.submit(6).result()

    with pool:
        assert first() == 10
        assert second() == 12

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
    baseline = _burn(n)  # inline: one task's CPU time under the GIL
    one = time.perf_counter() - t0
    assert baseline > 0

    pool = ProcessGraphPool(max_workers=2)

    @flow(pool=pool, log=tmp_path)
    def campaign():
        futures = [_burn.submit(n) for _ in range(2)]
        return [f.result() for f in futures]

    t0 = time.perf_counter()
    with pool:
        results = campaign()
    wall = time.perf_counter() - t0

    assert results == [baseline, baseline]
    # Two CPU-bound tasks on two processes must beat running them under
    # the GIL (generous margin: fork startup, CI load).
    assert wall < 1.7 * one, f"wall={wall:.3f}s one={one:.3f}s"


def test_process_pool_submit_after_exit_settles_cancelled():
    """A node submitted after the pool exited settles CancelledError (the
    shutdown branch of the dispatch seam) instead of hanging."""
    import concurrent.futures

    pool = ProcessGraphPool(max_workers=1)
    with pool:
        pass
    gf = GraphFuture(_sleep_plain, 1)
    pool.bind(gf)
    with pytest.raises(concurrent.futures.CancelledError):
        gf.result(timeout=2)


def test_concurrent_flows_one_process_pool_per_flow(tmp_path):
    """Two flows in one process, each on its own process pool: both
    complete — pool-scoped cancellation (IMP-019) at flow level."""

    @flow(pool=ProcessGraphPool(max_workers=1), log=tmp_path / "a", name="fa")
    def fa():
        return _sleepy.submit(1).result()

    @flow(pool=ProcessGraphPool(max_workers=1), log=tmp_path / "b", name="fb")
    def fb():
        return _sleepy.submit(2).result()

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(fa)
        f2 = ex.submit(fb)
        assert f1.result(timeout=10) == 1
        assert f2.result(timeout=10) == 2

    for sub in ("a", "b"):
        recs = _read_log(tmp_path / sub)
        assert recs[-1]["record"] == "run_end" and recs[-1]["status"] == "ok"
