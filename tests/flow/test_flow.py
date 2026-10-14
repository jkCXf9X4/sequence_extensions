"""Unit tests for @flow: run identity, logging, drain, failure handling."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sequence_extensions import __version__
from sequence_extensions.flow import (
    SCHEMA_VERSION,
    RunLog,
    TaskTimeoutError,
    flow,
    task,
)


def _task_records(recs):
    return [r for r in recs if r["record"] == "task"]


def _read_log(log_dir):
    return RunLog.records(next(Path(log_dir).glob("*.jsonl")))


# ---------------------------------------------------------------- #
# Run identity and the log file
# ---------------------------------------------------------------- #
def test_flow_writes_run_start_and_run_end(tmp_path):
    @flow(log=tmp_path)
    def run():
        return 42

    assert run() == 42
    recs = _read_log(tmp_path)
    assert recs[0]["record"] == "run_start"
    assert recs[-1]["record"] == "run_end"
    assert recs[0]["flow"] == "run"
    assert recs[0]["version"] == __version__
    assert recs[-1]["status"] == "ok"
    assert recs[-1]["result"] == 42
    assert recs[0]["run_id"] == recs[-1]["run_id"]
    assert all(r["schema"] == SCHEMA_VERSION for r in recs)


def test_flow_run_id_is_unique_and_prefixed():
    from sequence_extensions.flow import current_run

    ids = []

    @flow(log=None, name="camp")
    def run():
        ids.append(current_run().run_id)
        return None

    run()
    run()
    assert ids[0] != ids[1]
    assert ids[0].startswith("camp-")


def test_flow_default_log_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    @flow
    def run():
        return 1

    run()
    assert list((tmp_path / "runs").glob("*.jsonl"))


def test_flow_log_none_writes_nothing(tmp_path):
    @flow(log=None)
    def run():
        return 1

    assert run() == 1
    assert list(tmp_path.glob("**/*.jsonl")) == []


def test_flow_rejects_bad_log_type():
    with pytest.raises(TypeError, match="log"):

        @flow(log=123)
        def run():
            return 1


def test_flow_name_override(tmp_path):
    @flow(log=tmp_path, name="campaign")
    def run():
        return 1

    run()
    recs = _read_log(tmp_path)
    assert recs[0]["flow"] == "campaign"
    assert recs[0]["run_id"].startswith("campaign-")


def test_flow_metadata_preserved():
    @flow(log=None)
    def documented():
        """Doc."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Doc."


def test_flow_args_are_recorded(tmp_path):
    case = tmp_path / "case.csv"
    case.write_text("value\n10\n")

    @flow(log=tmp_path)
    def run(path, tolerance=0.5):
        return str(path)

    run(case, tolerance=0.25)
    recs = _read_log(tmp_path)
    start = recs[0]
    assert start["args"][0]["path"] == str(case)
    assert start["args"][0]["sha256"] is not None
    assert start["kwargs"] == {"tolerance": 0.25}


def test_flow_summary_mode_condenses_bulky_results(tmp_path):
    @flow(log=tmp_path, summary=True)
    def run():
        return list(range(50))

    run()
    recs = _read_log(tmp_path)
    assert recs[-1]["result"] == {"type": "list", "len": 50}


# ---------------------------------------------------------------- #
# Drain and failure
# ---------------------------------------------------------------- #
def test_flow_drains_pending_tasks_before_returning(tmp_path):
    done = []

    @task
    def sleeper(i):
        time.sleep(0.1)
        done.append(i)
        return i

    @flow(log=tmp_path)
    def run():
        [sleeper.submit(i) for i in range(4)]
        return "returned before gather"

    result = run()
    assert result == "returned before gather"
    assert sorted(done) == [0, 1, 2, 3]  # flow returned only after drain


def test_flow_error_is_recorded_and_reraised(tmp_path):
    @flow(log=tmp_path)
    def run():
        raise ValueError("campaign failed")

    with pytest.raises(ValueError, match="campaign failed"):
        run()
    recs = _read_log(tmp_path)
    assert recs[-1]["record"] == "run_end"
    assert recs[-1]["status"] == "error"
    assert recs[-1]["error"] == {"type": "ValueError", "message": "campaign failed"}


def test_flow_failed_dependency_gets_skipped_record(tmp_path):
    @task
    def boom():
        raise ValueError("upstream failed")

    @task
    def downstream(x):
        return x

    @flow(log=tmp_path)
    def run():
        a = boom.submit()
        b = downstream.submit(a)
        try:
            b.result()
        except ValueError:
            return "handled"

    assert run() == "handled"
    recs = _read_log(tmp_path)
    tasks = _task_records(recs)
    by_name = {}
    for t in tasks:
        by_name.setdefault(t["task"], []).append(t)
    assert [t["status"] for t in by_name["boom"]] == ["error"]
    assert by_name["boom"][0]["attempt"] == 1
    assert [t["status"] for t in by_name["downstream"]] == ["skipped"]
    assert by_name["downstream"][0]["attempt"] == 0
    assert by_name["downstream"][0]["reason"] == "dependency failed"
    assert by_name["downstream"][0]["error"]["type"] == "ValueError"


def test_flow_failure_cancels_pending_and_records_them(tmp_path):
    @task
    def slow():
        time.sleep(0.3)
        return "done"

    @flow(log=tmp_path, max_workers=1)
    def run():
        slow.submit()  # occupies the only worker
        slow.submit()  # stays queued
        slow.submit()  # stays queued
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        run()
    recs = _read_log(tmp_path)
    tasks = _task_records(recs)
    statuses = [t["status"] for t in tasks]
    # the running one finished and was recorded; the queued ones were
    # cancelled and each got a skipped record
    assert statuses.count("ok") >= 1
    assert statuses.count("skipped") >= 2
    skipped = [t for t in tasks if t["status"] == "skipped"]
    assert all(t["reason"] == "cancelled (flow failed)" for t in skipped)
    assert recs[-1]["status"] == "error"


def test_flow_max_workers_bounds_concurrency(tmp_path):
    @task
    def sleepish():
        time.sleep(0.1)
        return 1

    @flow(log=None, max_workers=1)
    def run():
        return [f.result() for f in [sleepish.submit(), sleepish.submit()]]

    t0 = time.perf_counter()
    run()
    assert time.perf_counter() - t0 >= 0.2  # serialized on one worker


def test_flow_task_records_carry_worker_names(tmp_path):
    @task
    def noop():
        return 1

    @flow(log=tmp_path)
    def run():
        return noop.submit().result()

    run()
    tasks = _task_records(_read_log(tmp_path))
    assert tasks[0]["worker"].startswith("graph-worker")


# ---------------------------------------------------------------- #
# Nesting
# ---------------------------------------------------------------- #
def test_nested_flow_gets_its_own_run_and_log(tmp_path):
    inner_dir = tmp_path / "inner"
    outer_dir = tmp_path / "outer"

    @task
    def work():
        return 1

    @flow(log=inner_dir)
    def inner():
        return work.submit().result() + 1

    @flow(log=outer_dir)
    def outer():
        return inner() * 10

    assert outer() == 20
    inner_recs = _read_log(inner_dir)
    outer_recs = _read_log(outer_dir)
    # the task record belongs to the inner run only
    assert _task_records(inner_recs) and not _task_records(outer_recs)
    assert inner_recs[0]["run_id"] != outer_recs[0]["run_id"]
    assert outer_recs[-1]["result"] == 20


def test_task_timeout_error_surfaces_from_flow(tmp_path):
    @task(timeout=0.05)
    def slow():
        time.sleep(2.0)

    @flow(log=tmp_path)
    def run():
        return slow.submit().result()

    with pytest.raises(TaskTimeoutError, match="slow"):
        run()
    recs = _read_log(tmp_path)
    assert _task_records(recs)[0]["status"] == "timeout"
    assert recs[-1]["status"] == "error"


# ---------------------------------------------------------------- #
# Caller-owned pool
# ---------------------------------------------------------------- #
def test_flow_accepts_caller_owned_pool():
    from sequence_extensions.graph import GraphPool

    @task
    def work(x):
        return x * 2

    with GraphPool(max_workers=4) as shared:
        for _ in range(2):  # two sequential flows share one pool

            @flow(log=None, pool=shared)
            def run():
                a = work.submit(21)
                return work.submit(a).result()

            assert run() == 84  # pool still usable after each flow


def test_flow_rejects_bad_pool_type():
    with pytest.raises(TypeError, match="pool"):
        flow(log=None, pool="not-a-pool")(lambda: 1)


def test_caller_owned_pool_is_drained_not_settled_on_error(tmp_path):
    from sequence_extensions.graph import GraphPool

    recorded = []

    @task
    def slow(i):
        time.sleep(0.1)
        recorded.append(i)
        return i

    shared = GraphPool(max_workers=2)

    @flow(log=tmp_path, pool=shared)
    def run():
        slow.submit(1)
        slow.submit(2)
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        run()
    # caller-owned: nothing was cancelled — every submitted task ran
    assert sorted(recorded) == [1, 2]
    recs = _read_log(tmp_path)
    assert recs[-1]["status"] == "error"
    assert all(t["status"] == "ok" for t in _task_records(recs))
    shared.__exit__(None, None, None)  # owner closes the pool


def test_concurrent_flows_in_one_process(tmp_path):
    """Two flows run at the same time in one process, each on its own
    pool: both complete (pool-scoped cancellation — a pool's exit no
    longer cancels the other flow's pending nodes)."""
    from concurrent.futures import ThreadPoolExecutor

    @task
    def slow(x):
        time.sleep(0.2)
        return x

    @flow(log=tmp_path / "a", name="fa")
    def fa():
        return slow.submit(1).result()

    @flow(log=tmp_path / "b", name="fb")
    def fb():
        return slow.submit(2).result()

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(fa)
        f2 = ex.submit(fb)
        assert f1.result(timeout=10) == 1
        assert f2.result(timeout=10) == 2

    for sub in ("a", "b"):
        recs = _read_log(tmp_path / sub)
        assert recs[-1]["record"] == "run_end"
        assert recs[-1]["status"] == "ok"
