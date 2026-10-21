"""Unit tests for execute_flow: run identity, logging, drain, nesting."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sequence_extensions import __version__
from sequence_extensions.flow import (
    SCHEMA_VERSION,
    NodePolicy,
    NodeTimeoutError,
    Run,
    RunLog,
    RunOptions,
    execute_flow,
    gather,
    node,
)


def _node_records(recs):
    return [r for r in recs if r["record"] == "node"]


def _read_log(log_dir):
    return RunLog.records(next(Path(log_dir).glob("*.jsonl")))


# ---------------------------------------------------------------- #
# Run identity and the log file
# ---------------------------------------------------------------- #
def test_run_writes_run_start_and_run_end(tmp_path):
    @node
    def campaign():
        return 42

    run = execute_flow(campaign, options=RunOptions(log=tmp_path))
    assert isinstance(run, Run)
    assert run.result == 42
    assert run.status == "ok"
    recs = _read_log(tmp_path)
    assert recs[0]["record"] == "run_start"
    assert recs[-1]["record"] == "run_end"
    assert recs[0]["node"] == "campaign"
    assert recs[0]["version"] == __version__
    assert recs[-1]["status"] == "ok"
    assert recs[-1]["result"] == 42
    assert recs[0]["run_id"] == recs[-1]["run_id"] == run.run_id
    assert all(r["schema"] == SCHEMA_VERSION for r in recs)
    assert run.log == Path(next(Path(tmp_path).glob("*.jsonl")))


def test_run_id_is_unique_and_prefixed():
    @node
    def campaign():
        return 1

    a = execute_flow(campaign, options=RunOptions(log=None, name="camp"))
    b = execute_flow(campaign, options=RunOptions(log=None, name="camp"))
    assert a.run_id != b.run_id
    assert a.run_id.startswith("camp-")


def test_default_log_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    @node
    def campaign():
        return 1

    run = execute_flow(campaign)
    assert (tmp_path / "runs").exists()
    assert run.log.parent == Path("runs")


def test_log_none_writes_nothing(tmp_path):
    @node
    def campaign():
        return 1

    run = execute_flow(campaign, options=RunOptions(log=None))
    assert run.result == 1
    assert run.log is None
    assert list(tmp_path.glob("**/*.jsonl")) == []


def test_bad_log_type_is_rejected():
    with pytest.raises(ValueError, match="log"):
        RunOptions(log=123)


def test_name_override(tmp_path):
    @node
    def campaign():
        return 1

    run = execute_flow(campaign, options=RunOptions(log=tmp_path, name="renamed"))
    recs = _read_log(tmp_path)
    assert recs[0]["node"] == "renamed"
    assert run.run_id.startswith("renamed-")
    # The execution path keeps the node's own name.
    assert _node_records(recs)[0]["path"] == ["campaign"]


def test_args_are_recorded(tmp_path):
    case = tmp_path / "case.csv"
    case.write_text("value\n10\n")

    @node
    def campaign(path, tolerance=0.5):
        return str(path)

    execute_flow(campaign, case, tolerance=0.25, options=RunOptions(log=tmp_path))
    start = _read_log(tmp_path)[0]
    assert start["args"][0]["path"] == str(case)
    assert start["args"][0]["sha256"] is not None
    assert start["kwargs"] == {"tolerance": 0.25}


def test_summary_mode_condenses_bulky_results(tmp_path):
    @node
    def campaign():
        return list(range(50))

    execute_flow(campaign, options=RunOptions(log=tmp_path, summary=True))
    recs = _read_log(tmp_path)
    assert recs[-1]["result"] == {"type": "list", "len": 50}


# ---------------------------------------------------------------- #
# Drain and failure
# ---------------------------------------------------------------- #
def test_run_drains_pending_nodes_before_returning(tmp_path):
    done = []

    @node
    def sleeper(i):
        time.sleep(0.1)
        done.append(i)
        return i

    @node
    def campaign():
        [sleeper.submit(i) for i in range(4)]
        return "returned before gather"

    run = execute_flow(campaign, options=RunOptions(log=tmp_path))
    assert run.result == "returned before gather"
    assert sorted(done) == [0, 1, 2, 3]


def test_error_is_recorded_and_reraised_with_run(tmp_path):
    @node
    def campaign():
        raise ValueError("campaign failed")

    with pytest.raises(ValueError, match="campaign failed") as excinfo:
        execute_flow(campaign, options=RunOptions(log=tmp_path))
    run = excinfo.value.run
    assert run.status == "error"
    recs = _read_log(tmp_path)
    assert recs[-1]["record"] == "run_end"
    assert recs[-1]["status"] == "error"
    assert recs[-1]["error"] == {"type": "ValueError", "message": "campaign failed"}


def test_failed_dependency_gets_skipped_record(tmp_path):
    @node
    def boom():
        raise ValueError("upstream failed")

    @node
    def downstream(x):
        return x

    @node
    def campaign():
        a = boom.submit()
        b = downstream.submit(a)
        try:
            b.result()
        except ValueError:
            return "handled"

    run = execute_flow(campaign, options=RunOptions(log=tmp_path))
    assert run.result == "handled"
    recs = _read_log(tmp_path)
    by_name = {}
    for rec in _node_records(recs):
        by_name.setdefault(rec["node"], []).append(rec)
    assert [r["status"] for r in by_name["boom"]] == ["error"]
    assert by_name["boom"][0]["attempt"] == 1
    assert [r["status"] for r in by_name["downstream"]] == ["skipped"]
    assert by_name["downstream"][0]["attempt"] == 0
    assert by_name["downstream"][0]["reason"] == "dependency failed"
    assert by_name["downstream"][0]["error"]["type"] == "ValueError"
    assert by_name["downstream"][0]["path"] == ["campaign", "downstream"]


def test_failure_cancels_pending_and_records_them(tmp_path):
    @node
    def slow():
        time.sleep(0.3)
        return "done"

    @node
    def campaign():
        slow.submit()
        slow.submit()
        slow.submit()
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        execute_flow(campaign, options=RunOptions(log=tmp_path, max_workers=1))
    recs = _read_log(tmp_path)
    tasks = _node_records(recs)
    statuses = [r["status"] for r in tasks]
    assert statuses.count("ok") >= 1
    assert statuses.count("skipped") >= 2
    skipped = [r for r in tasks if r["status"] == "skipped"]
    assert all(r["reason"] == "cancelled (run failed)" for r in skipped)
    assert recs[-1]["status"] == "error"


def test_max_workers_bounds_concurrency(tmp_path):
    @node
    def sleepish():
        time.sleep(0.1)
        return 1

    @node
    def campaign():
        return [f.result() for f in [sleepish.submit(), sleepish.submit()]]

    t0 = time.perf_counter()
    execute_flow(campaign, options=RunOptions(log=None, max_workers=1))
    assert time.perf_counter() - t0 >= 0.2


def test_node_records_carry_worker_names(tmp_path):
    @node
    def noop():
        return 1

    @node
    def campaign():
        return noop.submit().result()

    execute_flow(campaign, options=RunOptions(log=tmp_path))
    nodes = [r for r in _read_log(tmp_path) if r["record"] == "node" and r["node"] == "noop"]
    assert nodes[0]["worker"].startswith("graph-worker")


# ---------------------------------------------------------------- #
# Nesting
# ---------------------------------------------------------------- #
def test_nested_nodes_share_one_log_and_record_their_path(tmp_path):
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
    records = _node_records(_read_log(tmp_path))
    leaf_record = next(r for r in records if r["node"] == "leaf")
    assert leaf_record["path"] == ["outer", "middle", "leaf"]
    assert leaf_record["parent_attempt"] == 1
    assert {r["node"] for r in records} == {"outer", "middle", "leaf"}


def test_execute_flow_inside_a_node_is_rejected(tmp_path):
    @node
    def child():
        return 1

    @node
    def parent():
        return execute_flow(child, options=RunOptions(log=tmp_path / "child")).result

    with pytest.raises(RuntimeError, match="top-level entry point"):
        execute_flow(parent, options=RunOptions(log=tmp_path))


def test_run_timeout_records_timeout_and_drops_late_records(tmp_path):
    @node
    def slow():
        time.sleep(1.0)
        return 1

    t0 = time.perf_counter()
    with pytest.raises(NodeTimeoutError) as excinfo:
        execute_flow(slow, options=RunOptions(log=tmp_path, timeout=0.05))
    assert time.perf_counter() - t0 < 0.5
    run = excinfo.value.run
    assert run.status == "timeout"
    recs = _read_log(tmp_path)
    assert [r["record"] for r in recs] == ["run_start", "run_end"]
    assert recs[-1]["status"] == "timeout"
    time.sleep(1.1)  # the abandoned body finishes; no late record may appear
    assert [r["record"] for r in _read_log(tmp_path)] == ["run_start", "run_end"]


def test_node_timeout_is_an_error_in_the_run_verdict(tmp_path):
    @node(timeout=0.05)
    def slow():
        time.sleep(2.0)

    @node
    def campaign():
        return slow.submit().result()

    with pytest.raises(NodeTimeoutError):
        execute_flow(campaign, options=RunOptions(log=tmp_path))
    recs = _read_log(tmp_path)
    assert _node_records(recs)[0]["status"] == "timeout"
    # The run's own budget did not expire; a node did.
    assert recs[-1]["status"] == "error"


# ---------------------------------------------------------------- #
# Caller-owned pool
# ---------------------------------------------------------------- #
def test_caller_owned_pool_is_reused_and_not_settled():
    from sequence_extensions.graph import GraphPool

    @node
    def work(x):
        return x * 2

    with GraphPool(max_workers=4) as shared:
        for _ in range(2):

            @node
            def campaign():
                a = work.submit(21)
                return work.submit(a).result()

            assert (
                execute_flow(campaign, options=RunOptions(log=None, pool=shared)).result == 84
            )


def test_caller_owned_pool_is_drained_not_settled_on_error(tmp_path):
    from sequence_extensions.graph import GraphPool

    recorded = []

    @node
    def slow(i):
        time.sleep(0.1)
        recorded.append(i)
        return i

    shared = GraphPool(max_workers=2)

    @node
    def campaign():
        slow.submit(1)
        slow.submit(2)
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        execute_flow(campaign, options=RunOptions(log=tmp_path, pool=shared))
    assert sorted(recorded) == [1, 2]
    recs = _read_log(tmp_path)
    assert recs[-1]["status"] == "error"
    assert all(
        r["status"] == "ok"
        for r in _node_records(recs)
        if r["node"] == "slow"
    )
    shared.__exit__(None, None, None)


def test_concurrent_runs_in_one_process(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    @node
    def slow(x):
        time.sleep(0.2)
        return x

    @node
    def run_a():
        return slow.submit(1).result()

    @node
    def run_b():
        return slow.submit(2).result()

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(
            execute_flow, run_a, options=RunOptions(log=tmp_path / "a", name="fa")
        )
        f2 = ex.submit(
            execute_flow, run_b, options=RunOptions(log=tmp_path / "b", name="fb")
        )
        assert f1.result(timeout=10).result == 1
        assert f2.result(timeout=10).result == 2

    for sub in ("a", "b"):
        recs = _read_log(tmp_path / sub)
        assert recs[-1]["record"] == "run_end"
        assert recs[-1]["status"] == "ok"


# ---------------------------------------------------------------- #
# fixed_clock: reference mode
# ---------------------------------------------------------------- #
def test_fixed_clock_pins_identity_timing_and_order(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def campaign(values):
        futures = [leaf.submit(v) for v in values]
        return [f.result() for f in futures]

    execute_flow(
        campaign,
        list(range(4)),
        options=RunOptions(log=tmp_path, fixed_clock=True),
    )
    path = tmp_path / "campaign-fixed.jsonl"
    first = path.read_bytes()
    recs = RunLog.records(path)
    assert recs[0]["record"] == "run_start"
    assert recs[-1]["record"] == "run_end"
    assert all(r["run_id"] == "campaign-fixed" for r in recs)
    assert recs[0]["started"] == "1970-01-01T00:00:00+00:00"
    assert recs[-1]["ended"] == "1970-01-01T00:00:00+00:00"
    assert recs[-1]["duration_ms"] == 0
    assert [r["record"] for r in recs] == ["run_start"] + ["node"] * 5 + ["run_end"]
    assert sum(1 for r in recs if r["record"] == "node" and r.get("node") == "campaign") == 1

    execute_flow(
        campaign,
        list(range(4)),
        options=RunOptions(log=tmp_path, fixed_clock=True),
    )
    assert path.read_bytes() == first


def test_fixed_clock_nested_nodes_are_byte_stable(tmp_path):
    @node
    def leaf(x):
        return x

    @node
    def middle(values):
        return gather([leaf.submit(v) for v in values])

    @node
    def outer(values):
        return middle(values)

    execute_flow(outer, [1, 2], options=RunOptions(log=tmp_path, fixed_clock=True))
    path = tmp_path / "outer-fixed.jsonl"
    first = path.read_bytes()
    records = RunLog.records(path)
    assert [r["record"] for r in records] == ["run_start"] + ["node"] * 4 + ["run_end"]
    leaf_records = [r for r in records if r.get("node") == "leaf"]
    assert {tuple(r["path"]) for r in leaf_records} == {("outer", "middle", "leaf")}

    execute_flow(outer, [1, 2], options=RunOptions(log=tmp_path, fixed_clock=True))
    assert path.read_bytes() == first


def test_run_level_retry_writes_one_file_per_attempt(tmp_path):
    state = {"root": 0, "child": 0}

    @node
    def child():
        state["child"] += 1
        return 1

    @node
    def root():
        state["root"] += 1
        child.submit().result()
        if state["root"] == 1:
            raise ValueError("first")
        return "ok"

    run = execute_flow(
        root,
        options=RunOptions(log=tmp_path, retries=1, retry_delay_seconds=0.0),
    )
    assert run.result == "ok"
    assert run.attempt == 2
    assert state == {"root": 2, "child": 2}

    logs = sorted(tmp_path.glob("*.jsonl"))
    assert len(logs) == 2
    starts = {RunLog.records(path)[0]["attempt"]: path for path in logs}
    assert set(starts) == {1, 2}
    for path in starts.values():
        child_records = _node_records(RunLog.records(path))
        child_record = next(r for r in child_records if r["node"] == "child")
        assert child_record["attempt"] == 1


def test_run_level_retry_exception_carries_last_attempt(tmp_path):
    @node
    def always():
        raise ValueError("always")

    with pytest.raises(ValueError, match="always") as info:
        execute_flow(
            always,
            options=RunOptions(log=tmp_path, retries=1, retry_delay_seconds=0.0),
        )

    assert info.value.run.attempt == 2
    assert len(list(tmp_path.glob("*.jsonl"))) == 2


def test_root_fixed_clock_rejects_run_retries(tmp_path):
    @node
    def campaign():
        return 1

    with pytest.raises(ValueError, match="does not support run retries"):
        execute_flow(
            campaign,
            options=RunOptions(log=tmp_path, fixed_clock=True, retries=1),
        )


def test_node_defaults_apply_to_nested_nodes(tmp_path):
    state = {"n": 0}

    @node
    def child():
        state["n"] += 1
        if state["n"] < 2:
            raise ValueError("first")
        return 1

    @node
    def middle():
        return child.submit()

    @node
    def outer():
        return middle.submit()

    run = execute_flow(
        outer,
        options=RunOptions(log=tmp_path, node_defaults=NodePolicy(retries=1)),
    )
    assert run.result == 1
    assert state["n"] == 2
    child_records = [r for r in _node_records(_read_log(tmp_path)) if r["node"] == "child"]
    assert [r["status"] for r in child_records] == ["error", "ok"]
