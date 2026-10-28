"""The settle guarantee: a returned run log holds every node outcome.

``execute_flow`` returns only after every submitted node *and* every deferred
node outcome has settled, so the log is complete when the call returns.  A
deferred outcome is the future a direct call inside a node body hands back
when it cannot wait; nothing else may reference it, so only the run's drain
can keep the return path open until its attempt record is in the log.
"""

from __future__ import annotations

import concurrent.futures
import threading

from sequence_extensions.flow import RunLog, RunOptions, execute_flow, node


def _node_records(log_path):
    return [r for r in RunLog.records(log_path) if r["record"] == "node"]


def test_deferred_outcome_keeps_the_run_open_until_recorded(tmp_path):
    """A pending deferred outcome blocks the return, then appears in the log."""
    started = threading.Event()
    release = concurrent.futures.Future()

    @node
    def inner():
        started.set()
        return release  # the body returns a caller-owned future: outcome deferred

    @node
    def root():
        inner()  # direct call in a body: the pending outcome is discarded
        return "root"

    outcome = {}

    def go():
        outcome["run"] = execute_flow(root, options=RunOptions(log=tmp_path))

    helper = threading.Thread(target=go, name="settle-test-run")
    helper.start()
    try:
        assert started.wait(5.0), "inner node never started"
        # Ordering comes from the unresolved future, not the clock: the run
        # may not return while a deferred outcome is pending.  The join only
        # bounds the negative check.
        helper.join(0.5)
        assert helper.is_alive(), (
            "execute_flow returned while a deferred node outcome was still pending"
        )
    finally:
        release.set_result("inner")
    helper.join(5.0)
    assert not helper.is_alive()

    run = outcome["run"]
    assert run.result == "root"
    records = RunLog.records(run.log)
    assert [r["record"] for r in records] == ["run_start", "node", "node", "run_end"]
    by_name = {r["node"]: r for r in records if r["record"] == "node"}
    assert set(by_name) == {"root", "inner"}
    assert by_name["root"]["status"] == "ok"
    assert by_name["inner"]["status"] == "ok"
    assert by_name["inner"]["result"] == "inner"
    assert records[-1]["status"] == "ok"


def test_drain_records_fast_slow_and_late_submitted_nodes(tmp_path):
    """Fast, slow, and late nodes each leave exactly one ok record."""
    slow_started = threading.Event()
    release_slow = threading.Event()

    @node
    def fast():
        return "fast"

    @node
    def slow():
        slow_started.set()
        assert release_slow.wait(5.0), "slow node was never released"
        return "slow"

    @node
    def late():
        assert release_slow.wait(5.0), "late node was never released"
        return "late"

    @node
    def releaser():
        assert slow_started.wait(5.0), "slow node never started"
        release_slow.set()
        return "released"

    @node
    def root():
        fast.submit()
        slow.submit()
        late.submit()
        releaser.submit()
        return "root"  # returns while every submitted node is still running

    run = execute_flow(root, options=RunOptions(log=tmp_path, max_workers=4))
    assert run.result == "root"

    node_records = _node_records(run.log)
    assert len(node_records) == 5
    by_name = {r["node"]: r for r in node_records}
    assert set(by_name) == {"root", "fast", "slow", "late", "releaser"}
    assert {r["status"] for r in node_records} == {"ok"}
    records = RunLog.records(run.log)
    assert records[-1]["record"] == "run_end"
    assert records[-1]["status"] == "ok"


def test_deferred_retry_attempts_are_all_recorded(tmp_path):
    """Retry-then-success records the failed attempt and the successful one."""
    state = {"attempt": 0}

    @node
    def leaf(fail):
        if fail:
            raise ValueError("first attempt")
        return "ok"

    @node(retries=1)
    def composite():
        state["attempt"] += 1
        return leaf.submit(fail=state["attempt"] == 1)  # deferred attempt

    run = execute_flow(composite, options=RunOptions(log=tmp_path, max_workers=1))
    assert run.result == "ok"
    assert state["attempt"] == 2

    node_records = _node_records(run.log)
    composite_records = [r for r in node_records if r["node"] == "composite"]
    leaf_records = [r for r in node_records if r["node"] == "leaf"]
    assert [(r["attempt"], r["status"]) for r in composite_records] == [
        (1, "error"),
        (2, "ok"),
    ]

    assert [(r["attempt"], r["status"]) for r in leaf_records] == [
        (1, "error"),
        (1, "ok"),
    ]
    assert len(node_records) == 4
    assert RunLog.records(run.log)[-1]["status"] == "ok"


# ---------------------------------------------------------------- #
# A future cancelled between the done() and exception() checks
# ---------------------------------------------------------------- #
class _CancelledWhileSettling:
    """Race stand-in: ``cancelled()`` is false, ``exception()`` raises."""

    name = "ghost"
    path = ("ghost",)
    parent_attempt = None
    process_records = ()
    attempted = False

    def cancelled(self):
        return False

    def done(self):
        return True

    def exception(self, timeout=None):
        raise concurrent.futures.CancelledError()


class _RecordSink:
    summary = False

    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


def test_failed_node_paths_skips_a_future_cancelled_while_settling():
    from sequence_extensions.flow._context import RunContext
    from sequence_extensions.flow._settle import failed_node_paths

    ctx = RunContext(run_id="r", node_name="r", runlog=None, pool=None, options=RunOptions())
    ctx.nodes.append(_CancelledWhileSettling())
    assert failed_node_paths(ctx) == ()


def test_write_settle_records_skips_a_future_cancelled_while_settling():
    from sequence_extensions.flow._context import RunContext
    from sequence_extensions.flow._settle import write_settle_records

    sink = _RecordSink()
    ctx = RunContext(run_id="r", node_name="r", runlog=sink, pool=None, options=RunOptions())
    ctx.nodes.append(_CancelledWhileSettling())
    write_settle_records(ctx, run_failed=True)
    assert sink.records == []
