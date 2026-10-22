"""Nested workflows: node composition and future-first fan-out.

A node tree is one run and one log.  A submitted composite frees its worker
by returning a future; ``gather`` combines several futures; a blocking
``.result()`` inside a node body is rejected instead of deadlocking.  Composite
retry/timeout policy applies to the returned future as a whole.
"""

from __future__ import annotations

import threading
import time

import pytest

from sequence_extensions.flow import (
    NodeTimeoutError,
    RunLog,
    RunOptions,
    execute_flow,
    gather,
    node,
)


def _node_records(log_path):
    return [r for r in RunLog.records(log_path) if r["record"] == "node"]


def test_three_level_nesting_shares_one_run_and_log(tmp_path):
    @node
    def leaf(x):
        return x + 1

    @node
    def middle():
        return leaf(1)

    @node
    def outer():
        return middle()

    run = execute_flow(outer, options=RunOptions(log=tmp_path))
    assert run.result == 2

    assert [p.name for p in tmp_path.glob("*.jsonl")] == [run.log.name]
    records = _node_records(run.log)
    leaf_record = next(r for r in records if r["node"] == "leaf")
    assert leaf_record["path"] == ["outer", "middle", "leaf"]
    assert leaf_record["parent_attempt"] == 1
    assert {r["node"] for r in records} == {"outer", "middle", "leaf"}
    removed = {"children", "parent_run_id", "child_run_id", "follow_children"}
    assert not removed & set(leaf_record)


def test_submitted_composite_fans_out_with_one_worker(tmp_path):
    @node
    def leaf(x):
        time.sleep(0.01)
        return x * 2

    @node
    def campaign():
        return gather([leaf.submit(i) for i in range(4)])

    @node
    def pipeline():
        return campaign.submit()

    run = execute_flow(
        pipeline,
        options=RunOptions(log=tmp_path, max_workers=1),
    )
    assert run.result == [0, 2, 4, 6]

    assert [p.name for p in tmp_path.glob("*.jsonl")] == [run.log.name]
    records = _node_records(run.log)
    campaign_record = next(r for r in records if r["node"] == "campaign")
    assert campaign_record["path"] == ["pipeline", "campaign"]
    assert campaign_record["result"] == [0, 2, 4, 6]
    leaf_records = [r for r in records if r["node"] == "leaf"]
    assert len(leaf_records) == 4
    assert {tuple(r["path"]) for r in leaf_records} == {("pipeline", "campaign", "leaf")}
    assert records.index(campaign_record) > max(records.index(r) for r in leaf_records)
    assert campaign_record["duration_ms"] >= max(r["duration_ms"] for r in leaf_records)


def test_inline_fanout_node_returns_its_future_on_a_worker(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def fanout():
        return gather([leaf.submit(1), leaf.submit(2)])

    @node
    def outer():
        return fanout()

    @node
    def root():
        return outer.submit()

    run = execute_flow(root, options=RunOptions(log=tmp_path, max_workers=1))
    assert run.result == [1, 2]
    fanout_record = next(r for r in _node_records(run.log) if r["node"] == "fanout")
    assert fanout_record["path"] == ["root", "outer", "fanout"]


def test_gather_accepts_a_single_future(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def composite():
        return gather(leaf.submit(7))

    run = execute_flow(composite, options=RunOptions(log=tmp_path))
    assert run.result == [7]


def test_gather_empty_and_generator_forms(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def empty():
        return gather([])

    @node
    def generated():
        return gather(leaf.submit(i) for i in range(3))

    assert execute_flow(empty, options=RunOptions(log=None)).result == []
    assert execute_flow(generated, options=RunOptions(log=None)).result == [0, 1, 2]


def test_merge_node_depends_on_gather(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def merge(values):
        return sum(values)

    @node
    def campaign():
        return merge.submit(gather([leaf.submit(i) for i in range(4)]))

    run = execute_flow(campaign, options=RunOptions(log=tmp_path, max_workers=2))
    assert run.result == 6

    records = _node_records(run.log)
    merge_record = next(r for r in records if r["node"] == "merge")
    assert merge_record["path"] == ["campaign", "merge"]
    assert merge_record["result"] == 6
    assert len([r for r in records if r["node"] == "leaf"]) == 4


def test_inline_fanout_result_is_rejected_on_a_worker(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def fanout():
        return gather([leaf.submit(1), leaf.submit(2)])

    @node
    def outer():
        return fanout().result()

    @node
    def root():
        return outer.submit()

    with pytest.raises(RuntimeError, match="incomplete future inside a node body"):
        execute_flow(root, options=RunOptions(log=tmp_path, max_workers=1))


def test_run_timeout_bounds_a_future_root(tmp_path):
    @node
    def slow():
        time.sleep(0.2)
        return 1

    @node
    def composite():
        return slow.submit()

    with pytest.raises(NodeTimeoutError):
        execute_flow(
            composite,
            options=RunOptions(log=tmp_path, timeout=0.05, max_workers=1),
        )

    records = RunLog.records(next(tmp_path.glob("*.jsonl")))
    assert records[-1]["status"] == "timeout"
    assert not [r for r in records if r.get("node") == "slow"]
    # The abandoned slow body is still running at return; its late record
    # must remain dropped after it finishes.
    time.sleep(0.3)
    later = RunLog.records(next(tmp_path.glob("*.jsonl")))
    assert [r["record"] for r in later] == ["run_start", "run_end"]
    assert later[-1]["status"] == "timeout"


def test_failure_drains_a_pending_future_subtree(tmp_path):
    composite_started = threading.Event()
    slow_started = threading.Event()

    @node
    def slow():
        slow_started.set()
        time.sleep(0.05)
        return 1

    @node
    def composite():
        composite_started.set()
        return slow.submit()

    @node
    def root():
        composite.submit()  # deliberately not awaited
        assert composite_started.wait(5.0)
        assert slow_started.wait(5.0)
        raise ValueError("root failed")

    with pytest.raises(ValueError, match="root failed"):
        execute_flow(root, options=RunOptions(log=tmp_path, max_workers=2))

    records = RunLog.records(next(tmp_path.glob("*.jsonl")))
    assert records[-1]["record"] == "run_end"
    composite_record = next(r for r in records if r.get("node") == "composite")
    # The child and composite may settle just before or after the failure
    # cancels pending graph futures; either way the record must be drained.
    assert composite_record["status"] in {"ok", "error"}
    assert {r.get("node") for r in records} >= {"root", "composite", "slow"}
    assert records.index(composite_record) < len(records) - 1


def test_composite_retry_reruns_the_subtree(tmp_path):
    state = {"n": 0}

    @node
    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError("first")
        return "ok"

    @node(retries=1)
    def composite():
        return flaky.submit()

    run = execute_flow(composite, options=RunOptions(log=tmp_path, max_workers=1))
    assert run.result == "ok"
    assert state["n"] == 2

    records = _node_records(run.log)
    composite_records = [r for r in records if r["node"] == "composite"]
    flaky_records = [r for r in records if r["node"] == "flaky"]
    assert [(r["attempt"], r["status"]) for r in composite_records] == [
        (1, "error"),
        (2, "ok"),
    ]
    assert [(r["parent_attempt"], r["status"]) for r in flaky_records] == [
        (1, "error"),
        (2, "ok"),
    ]


def test_composite_timeout_bounds_the_returned_future(tmp_path):
    @node
    def slow():
        time.sleep(0.2)
        return 1

    @node(timeout=0.05)
    def composite():
        return slow.submit()

    with pytest.raises(NodeTimeoutError):
        execute_flow(composite, options=RunOptions(log=tmp_path, max_workers=1))

    records = _node_records(next(tmp_path.glob("*.jsonl")))
    composite_record = next(r for r in records if r["node"] == "composite")
    assert composite_record["status"] == "timeout"
    # Late records from the abandoned subtree are dropped.
    assert not [r for r in records if r["node"] == "slow"]


def test_composite_failure_is_recorded_and_propagates(tmp_path):
    @node
    def boom(x):
        raise ValueError("boom")

    @node
    def composite():
        return gather([boom.submit(1), boom.submit(2)])

    with pytest.raises(ValueError, match="boom"):
        execute_flow(composite, options=RunOptions(log=tmp_path, max_workers=1))

    log_path = next(tmp_path.glob("*.jsonl"))
    records = _node_records(log_path)
    assert any(r["node"] == "boom" and r["status"] == "error" for r in records)
    composite_record = next(r for r in records if r["node"] == "composite")
    assert composite_record["status"] == "error"
    assert RunLog.records(log_path)[-1]["status"] == "error"


def test_returning_a_container_of_futures_is_rejected(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def composite():
        return [leaf.submit(1), leaf.submit(2)]

    with pytest.raises(RuntimeError, match="container holding futures"):
        execute_flow(composite, options=RunOptions(log=tmp_path))


def test_fixed_clock_concurrent_fanout_is_byte_stable(tmp_path):
    @node
    def leaf(x):
        return x * 2

    @node
    def campaign():
        return gather([leaf.submit(i) for i in range(4)])

    def run_once():
        execute_flow(
            campaign,
            options=RunOptions(log=tmp_path, max_workers=4, fixed_clock=True),
        )
        return (tmp_path / "campaign-fixed.jsonl").read_bytes()

    first = run_once()
    records = RunLog.records(tmp_path / "campaign-fixed.jsonl")
    assert [r["record"] for r in records] == ["run_start"] + ["node"] * 5 + ["run_end"]
    assert {tuple(r["path"]) for r in records if r.get("node") == "leaf"} == {
        ("campaign", "leaf")
    }
    assert run_once() == first
