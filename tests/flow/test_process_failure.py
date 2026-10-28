"""ProcessGraphPool — failure evidence across the process boundary.

Covers: a worker that dies mid-attempt, an exception that cannot be pickled
back to the parent, a dispatch that fails before it reaches a worker, a
dispatch cancelled before it settles, and the timeout/process limitation
(there is no process-group kill: a timed-out body keeps running in its
worker).

Every wait here is bounded.  A deadlock fails the test instead of hanging
the suite.
"""

from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from pathlib import Path

import pytest

from sequence_extensions.flow import (
    NodeTimeoutError,
    ProcessDispatchError,
    ProcessGraphPool,
    RunLog,
    RunOptions,
    execute_flow,
    node,
)
from sequence_extensions.graph.graph_future import GraphFuture


def _read_log(log_dir):
    return RunLog.records(next(Path(log_dir).glob("*.jsonl")))


def _node_records(recs):
    return [r for r in recs if r["record"] == "node"]


def _within(seconds, fn):
    """Run ``fn`` on a daemon thread; fail instead of hanging the suite."""
    box = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"flow did not return within {seconds}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# Module-level nodes: picklable by contract.
@node(retries=0)
def _kills_its_worker(x):
    os._exit(1)


class _UnpicklableError(Exception):
    """An exception the worker cannot send back across the process boundary."""

    def __reduce__(self):
        raise TypeError("cannot pickle _UnpicklableError")


@node(retries=0)
def _raises_unpicklable(x):
    raise _UnpicklableError(f"bad {x}")


@node(retries=0)
def _plain(x):
    return x * 2


@node(retries=0, timeout=0.1)
def _slow_then_mark(x, marker):
    time.sleep(0.35)
    Path(marker).write_text("body ran")
    return x


# ---------------------------------------------------------------- #
# Worker death
# ---------------------------------------------------------------- #
def test_worker_crash_fails_the_flow_and_returns(tmp_path):
    """``os._exit`` in a worker breaks the executor; the run returns.

    The worker died before it could return its buffered ``_ProcessOutcome``,
    so the attempt's own record is lost and the parent represents the node
    as a dispatch failure.  ``run_end`` is still the last line.
    """
    pool = ProcessGraphPool(max_workers=1)

    @node
    def campaign():
        return _kills_its_worker.submit(1)

    def flow():
        with pool:
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    with pytest.raises(ProcessDispatchError) as info:
        _within(15, flow)
    assert "BrokenProcessPool" in str(info.value)

    recs = _read_log(tmp_path)
    crashed = next(r for r in _node_records(recs) if r["node"] == "_kills_its_worker")
    assert crashed["status"] == "skipped"
    assert crashed["attempt"] == 0
    assert crashed["reason"] == "dispatch failed"
    assert crashed["error"]["type"] == "ProcessDispatchError"
    assert recs[-1]["record"] == "run_end"
    assert recs[-1]["status"] == "error"


def test_unpicklable_exception_fails_the_flow_and_returns(tmp_path):
    """A non-picklable exception cannot cross back; it surfaces as dispatch failure.

    The worker's buffered attempt record dies with the payload, so the parent
    records the node as ``skipped`` / ``dispatch failed`` with the pickling
    error rather than hanging on a future that can never settle.
    """
    pool = ProcessGraphPool(max_workers=1)

    @node
    def campaign():
        return _raises_unpicklable.submit(1)

    def flow():
        with pool:
            execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path))

    with pytest.raises(ProcessDispatchError) as info:
        _within(15, flow)
    assert "TypeError" in str(info.value)
    assert "cannot pickle" in str(info.value)

    recs = _read_log(tmp_path)
    failed = next(r for r in _node_records(recs) if r["node"] == "_raises_unpicklable")
    assert failed["status"] == "skipped"
    assert failed["reason"] == "dispatch failed"
    assert failed["error"]["type"] == "ProcessDispatchError"
    assert recs[-1]["record"] == "run_end"
    assert recs[-1]["status"] == "error"


# ---------------------------------------------------------------- #
# Dispatch failure before a worker takes the node
# ---------------------------------------------------------------- #
class _BrokenSubmitExecutor:
    def submit(self, fn, *args, **kwargs):
        raise RuntimeError("executor unavailable")

    def shutdown(self, wait=True, cancel_futures=False):
        pass


def test_dispatch_submit_failure_records_skip_and_returns(tmp_path):
    """``executor.submit`` raising settles the node instead of losing it."""
    pool = ProcessGraphPool(max_workers=1)
    pool._executor = _BrokenSubmitExecutor()

    @node
    def campaign():
        return _plain.submit(1)

    try:
        with pytest.raises(ProcessDispatchError, match="executor unavailable"):
            _within(
                10,
                lambda: execute_flow(campaign, options=RunOptions(pool=pool, log=tmp_path)),
            )
    finally:
        pool.__exit__(None, None, None)

    recs = _read_log(tmp_path)
    skipped = next(r for r in _node_records(recs) if r["node"] == "_plain")
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "dispatch failed"
    assert skipped["error"]["type"] == "ProcessDispatchError"


class _CancelledSubmitExecutor:
    def submit(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()
        future.cancel()
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        pass


def test_cancelled_process_future_cancels_the_node():
    """A worker future cancelled before settle cancels the bound node."""
    pool = ProcessGraphPool(max_workers=1)
    pool._executor = _CancelledSubmitExecutor()
    gf = GraphFuture(_plain, 1)
    try:
        pool.bind(gf)
    finally:
        pool.__exit__(None, None, None)
    assert gf.future.cancelled() is True


# ---------------------------------------------------------------- #
# Timeout cannot kill a subprocess (EVAL-002 limitation)
# ---------------------------------------------------------------- #
def test_process_timeout_is_recorded_and_the_pool_stays_usable(tmp_path):
    """Pin the limitation: a timed-out process attempt is abandoned, not killed.

    The node runs in a worker process; its own attempt runner joins the body
    on a thread and returns ``timeout`` when the budget expires.  There is no
    process-group kill, so the abandoned body keeps running inside that
    worker (it writes its marker later) while the worker's main thread takes
    the next node — the pool stays usable.  This is the EVAL-002 limit, not a
    cancellation guarantee.
    """
    marker = tmp_path / "late-body"
    pool = ProcessGraphPool(max_workers=1)
    timeout_log = tmp_path / "timeout"
    after_log = tmp_path / "after"

    @node
    def timed():
        return _slow_then_mark.submit(1, str(marker))

    @node
    def after():
        return _plain.submit(21)

    with pool:
        with pytest.raises(NodeTimeoutError) as info:
            _within(15, lambda: execute_flow(timed, options=RunOptions(pool=pool, log=timeout_log)))
        assert info.value.node == "_slow_then_mark"

        run = _within(
            15, lambda: execute_flow(after, options=RunOptions(pool=pool, log=after_log))
        )
        assert run.result == 42

        # Bounded wait for the abandoned body, which proves it was not killed.
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)

    assert marker.exists(), "abandoned process body was killed; update the documented limit"

    timeout_records = _read_log(timeout_log)
    timed_record = next(
        r for r in _node_records(timeout_records) if r["node"] == "_slow_then_mark"
    )
    assert timed_record["status"] == "timeout"
    assert timed_record["error"]["type"] == "NodeTimeoutError"
    assert timeout_records[-1]["record"] == "run_end"
    assert timeout_records[-1]["status"] == "error"

    after_records = _read_log(after_log)
    assert after_records[-1]["record"] == "run_end"
    assert after_records[-1]["status"] == "ok"
