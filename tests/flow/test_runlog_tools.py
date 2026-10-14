"""Tests for the run-log reading toolkit: filter, summarize, diff."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sequence_extensions.flow import RunLog
from sequence_extensions.flow.runlog import DIFF_EXCLUDE, SCHEMA_VERSION

_UNSET = object()


def _write_log(tmp_path, name, records):
    """Write records as raw JSON lines — full control over every field."""
    path = tmp_path / f"{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _run_start(run_id, *, seq=1, flow="campaign", args=("cases/",), version="1.2.0"):
    return {
        "seq": seq,
        "schema": SCHEMA_VERSION,
        "record": "run_start",
        "run_id": run_id,
        "flow": flow,
        "started": "2026-10-14T10:00:00+00:00",
        "version": version,
        "args": list(args),
        "kwargs": {},
    }


def _task(
    run_id,
    task,
    attempt,
    status,
    *,
    seq,
    duration_ms=10,
    worker="w1",
    args=("a.csv",),
    result=_UNSET,
    error=_UNSET,
):
    rec = {
        "seq": seq,
        "schema": SCHEMA_VERSION,
        "record": "task",
        "run_id": run_id,
        "task": task,
        "attempt": attempt,
        "status": status,
        "args": list(args),
        "kwargs": {},
        "start": "2026-10-14T10:00:00+00:00",
        "end": "2026-10-14T10:00:01+00:00",
        "duration_ms": duration_ms,
        "worker": worker,
    }
    if result is not _UNSET:
        rec["result"] = result
    if error is not _UNSET:
        rec["error"] = error
    return rec


def _skip(run_id, task, *, seq, reason="dependency failed"):
    """A settle-time skip record: no args, no timing, attempt 0."""
    return {
        "seq": seq,
        "schema": SCHEMA_VERSION,
        "record": "task",
        "run_id": run_id,
        "task": task,
        "attempt": 0,
        "status": "skipped",
        "reason": reason,
    }


def _run_end(run_id, *, seq=99, status="ok", result=_UNSET, duration_ms=500):
    rec = {
        "seq": seq,
        "schema": SCHEMA_VERSION,
        "record": "run_end",
        "run_id": run_id,
        "status": status,
        "ended": "2026-10-14T10:00:05+00:00",
        "duration_ms": duration_ms,
    }
    if result is not _UNSET:
        rec["result"] = result
    return rec


def _campaign_log(run_id, *, args=("cases/",)):
    """A small realistic log: bookends, one retried task, one skip."""
    return [
        _run_start(run_id, args=args),
        _task(
            run_id,
            "simulate",
            1,
            "error",
            seq=2,
            error={"type": "RuntimeError", "message": "solver crashed"},
        ),
        _task(run_id, "simulate", 2, "ok", seq=3, result={"score": 1.0}),
        _task(run_id, "evaluate", 1, "ok", seq=4, result={"passed": True}),
        _skip(run_id, "report", seq=5),
        _run_end(run_id, seq=6, result={"passed": True}),
    ]


def _retime(records, *, run_id="run-b", worker="OTHER", duration_ms=9999):
    """Same execution, different clocks: every timing field changed."""
    out = []
    for i, rec in enumerate(records, start=7):
        rec = dict(rec)
        rec["seq"] = 100 + i
        rec["run_id"] = run_id
        for field in ("start", "end", "started", "ended"):
            if field in rec:
                rec[field] = "2030-01-01T00:00:00+00:00"
        if "duration_ms" in rec:
            rec["duration_ms"] = duration_ms
        if "worker" in rec:
            rec["worker"] = worker
        out.append(rec)
    return out


# ---------------------------------------------------------------- #
# filter — selection
# ---------------------------------------------------------------- #
def test_filter_by_record_kind(tmp_path):
    recs = _campaign_log("run-a")
    path = _write_log(tmp_path, "a", recs)
    assert [r["task"] for r in RunLog.filter(path, record="task")] == [
        "simulate",
        "simulate",
        "evaluate",
        "report",
    ]
    assert RunLog.filter(recs, record="run_start")[0]["flow"] == "campaign"
    assert RunLog.filter(recs, record="run_end")[0]["status"] == "ok"


def test_filter_by_task_status_and_attempt():
    recs = _campaign_log("run-a")
    assert [r["attempt"] for r in RunLog.filter(recs, task="simulate")] == [1, 2]
    skips = RunLog.filter(recs, status="skipped")
    assert len(skips) == 1 and skips[0]["task"] == "report"
    errors = RunLog.filter(recs, record="task", status="error")
    assert len(errors) == 1 and errors[0]["task"] == "simulate"
    second = RunLog.filter(recs, task="simulate", attempt=2)
    assert len(second) == 1 and second[0]["status"] == "ok"


def test_filter_constraints_combine_and_missing_fields_never_match():
    recs = _campaign_log("run-a")
    # run records carry no task/status/attempt fields: never match those
    both = RunLog.filter(recs, record="task", status="ok")
    assert [r["task"] for r in both] == ["simulate", "evaluate"]
    assert RunLog.filter(recs, attempt=1, status="ok") == both[1:]


def test_filter_no_match_and_order_preserved():
    recs = _campaign_log("run-a")
    assert RunLog.filter(recs, task="nope") == []
    assert RunLog.filter(recs, record="task") == recs[1:5]


def test_filter_accepts_path_and_records(tmp_path):
    recs = _campaign_log("run-a")
    path = _write_log(tmp_path, "a", recs)
    assert RunLog.filter(path, record="task") == RunLog.filter(recs, record="task")


def test_filter_rejects_other_input_types():
    with pytest.raises(TypeError, match="log path or a record list"):
        RunLog.filter(42)


# ---------------------------------------------------------------- #
# summarize — the compact account
# ---------------------------------------------------------------- #
def test_summarize_full_run(tmp_path):
    path = _write_log(tmp_path, "a", _campaign_log("run-a"))
    out = RunLog.summarize(path)
    assert out["flow"] == "campaign"
    assert out["run_id"] == "run-a"
    assert out["status"] == "ok"
    assert [t["task"] for t in out["tasks"]] == ["simulate", "evaluate", "report"]
    simulate = out["tasks"][0]
    assert simulate["attempts"] == 2
    assert simulate["statuses"] == ["error", "ok"]
    assert simulate["status"] == "ok"
    assert simulate["duration_ms"] == 20  # both attempts, backoff excluded


def test_summarize_skips_are_not_attempts():
    out = RunLog.summarize(_campaign_log("run-a"))
    report = out["tasks"][2]
    assert report["attempts"] == 0
    assert report["statuses"] == ["skipped"]
    assert report["status"] == "skipped"
    assert report["duration_ms"] == 0


def test_summarize_interrupted_run_has_no_verdict():
    out = RunLog.summarize(_campaign_log("run-a")[:4])  # no run_end
    assert "status" not in out
    assert out["tasks"]  # what did happen is still accounted


def test_summarize_empty_log(tmp_path):
    assert RunLog.summarize(_write_log(tmp_path, "empty", [])) == {"tasks": []}


def test_summarize_output_is_jsonable():
    out = RunLog.summarize(_campaign_log("run-a"))
    assert json.loads(json.dumps(out)) == out


# ---------------------------------------------------------------- #
# diff — the determinism check (synthetic logs)
# ---------------------------------------------------------------- #
def test_diff_timing_and_identity_never_count():
    report = RunLog.diff(_campaign_log("run-a"), _retime(_campaign_log("run-a")))
    assert report == {"equal": True, "only_left": [], "only_right": [], "changed": []}


def test_diff_changed_outcome_is_pinpointed():
    left = _campaign_log("run-a")
    right = [
        _run_start("run-b"),
        _task("run-b", "simulate", 1, "ok", seq=2, result={"score": 1.0}),
        _task("run-b", "evaluate", 1, "ok", seq=3, result={"passed": True}),
        _skip("run-b", "report", seq=4),
        _run_end("run-b", seq=5, result={"passed": True}),
    ]
    report = RunLog.diff(left, right)
    assert report["equal"] is False
    assert report["only_left"] == [
        {
            "record": "task",
            "task": "simulate",
            "attempt": 2,
            "args": ["a.csv"],
            "kwargs": {},
        }
    ]
    assert report["only_right"] == []
    assert len(report["changed"]) == 1
    changed = report["changed"][0]
    assert changed["task"] == "simulate" and changed["attempt"] == 1
    assert changed["fields"]["status"] == {"left": "error", "right": "ok"}
    assert changed["fields"]["result"] == {"left": None, "right": {"score": 1.0}}
    assert changed["fields"]["error"] == {
        "left": {"type": "RuntimeError", "message": "solver crashed"},
        "right": None,
    }


def test_diff_extra_work_is_listed():
    right = _campaign_log("run-b")
    right.append(
        _task("run-b", "evaluate", 1, "ok", seq=50, args=("b.csv",), result={"passed": False})
    )
    right.insert(3, _skip("run-b", "late", seq=51))
    report = RunLog.diff(_campaign_log("run-a"), right)
    assert report["equal"] is False
    assert report["only_left"] == []
    assert report["only_right"] == [
        {
            "record": "task",
            "task": "evaluate",
            "attempt": 1,
            "args": ["b.csv"],
            "kwargs": {},
        },
        {"record": "task", "task": "late", "attempt": 0, "args": None, "kwargs": None},
    ]


def test_diff_run_level_change_is_flagged():
    report = RunLog.diff(_campaign_log("run-a"), _campaign_log("run-b", args=("other-cases/",)))
    assert report["only_left"] == [] and report["only_right"] == []
    assert report["changed"] == [
        {
            "record": "run_start",
            "fields": {"args": {"left": ["cases/"], "right": ["other-cases/"]}},
        }
    ]


def test_diff_interrupted_run_lists_missing_verdict():
    report = RunLog.diff(_campaign_log("run-a"), _campaign_log("run-b")[:5])
    assert report["only_left"] == [{"record": "run_end"}]
    assert report["equal"] is False


def test_diff_exclude_override_brings_timing_back():
    report = RunLog.diff(
        _campaign_log("run-a"),
        _retime(_campaign_log("run-a")),
        exclude=DIFF_EXCLUDE - {"duration_ms"},
    )
    # every record that carries a duration now differs
    assert len(report["changed"]) == 4
    assert all("duration_ms" in c["fields"] for c in report["changed"])


def test_diff_duplicate_identity_last_wins():
    left = [
        _run_start("run-a"),
        _task("run-a", "simulate", 1, "error", seq=2, error={"type": "E", "message": "one"}),
        _task("run-a", "simulate", 1, "ok", seq=3, result={"score": 1.0}),
        _run_end("run-a"),
    ]
    right = [
        _run_start("run-b"),
        _task("run-b", "simulate", 1, "ok", seq=2, result={"score": 1.0}),
        _run_end("run-b"),
    ]
    assert RunLog.diff(left, right) == {
        "equal": True,
        "only_left": [],
        "only_right": [],
        "changed": [],
    }


def test_diff_future_done_snapshot_is_ignored():
    left = [
        _run_start("run-a"),
        _task(
            "run-a",
            "evaluate",
            1,
            "ok",
            seq=2,
            args=({"node": "simulate", "done": False},),
            result=1,
        ),
        _run_end("run-a"),
    ]
    right = [
        _run_start("run-b"),
        _task(
            "run-b",
            "evaluate",
            1,
            "ok",
            seq=2,
            args=({"node": "simulate", "done": True},),
            result=1,
        ),
        _run_end("run-b"),
    ]
    assert RunLog.diff(left, right)["equal"] is True


def test_diff_output_is_jsonable_and_stably_ordered():
    right = _campaign_log("run-b")
    right[1] = _task("run-b", "simulate", 1, "ok", seq=2, result={"score": 2.0})
    right.pop(2)
    report = RunLog.diff(_campaign_log("run-a"), right)
    assert json.loads(json.dumps(report)) == report
    fields = list(report["changed"][0]["fields"])
    assert fields == sorted(fields)


def test_diff_accepts_paths_and_record_lists(tmp_path):
    left = _write_log(tmp_path, "a", _campaign_log("run-a"))
    right = _write_log(tmp_path, "b", _campaign_log("run-b"))
    via_paths = RunLog.diff(left, right)
    via_lists = RunLog.diff(RunLog.records(left), RunLog.records(right))
    assert via_paths == via_lists


# ---------------------------------------------------------------- #
# Real runs: the toolkit over logs the engine actually wrote
# ---------------------------------------------------------------- #
def _run_campaign(runs_dir, *, fail_first=False):
    """A two-stage fan-out with dependency edges; returns (log, result)."""
    from sequence_extensions.flow import flow, task

    seen = {}

    @task(retries=1, retry_delay_seconds=0.0)
    def stage(x):
        if fail_first and x == 1:
            seen[x] = seen.get(x, 0) + 1
            if seen[x] == 1:
                raise RuntimeError("boom")
        return x + 1

    @task
    def combine(x, bias):
        return x + bias

    @flow(name="mini", log=str(runs_dir))
    def mini(items):
        firsts = [stage.submit(x) for x in items]
        return [combine.submit(f, 10).result() for f in firsts]

    result = mini([1, 2, 3])
    logs = list(Path(runs_dir).glob("*.jsonl"))
    assert len(logs) == 1
    return logs[0], result


def test_two_real_runs_diff_equal(tmp_path):
    log_a, result_a = _run_campaign(tmp_path / "a")
    log_b, result_b = _run_campaign(tmp_path / "b")
    assert result_a == result_b == [12, 13, 14]
    assert RunLog.diff(log_a, log_b) == {
        "equal": True,
        "only_left": [],
        "only_right": [],
        "changed": [],
    }


def test_real_run_with_a_flaky_difference_is_pinpointed(tmp_path):
    log_a, _ = _run_campaign(tmp_path / "a", fail_first=True)
    log_b, _ = _run_campaign(tmp_path / "b")
    report = RunLog.diff(log_a, log_b)
    assert report["equal"] is False
    # the retry attempt exists only in the flaky run
    assert len(report["only_left"]) == 1
    assert report["only_left"][0]["task"] == "stage"
    assert report["only_left"][0]["attempt"] == 2
    assert report["only_left"][0]["args"] == [1]
    # the first attempt of the same invocation changed outcome
    assert len(report["changed"]) == 1
    assert report["changed"][0]["task"] == "stage"
    assert report["changed"][0]["attempt"] == 1
    assert report["changed"][0]["fields"]["status"] == {"left": "error", "right": "ok"}


def test_real_run_summarizes(tmp_path):
    log_a, _ = _run_campaign(tmp_path / "a")
    out = RunLog.summarize(log_a)
    assert out["flow"] == "mini"
    assert out["status"] == "ok"
    assert [t["task"] for t in out["tasks"]] == ["stage", "combine"]
    assert out["tasks"][0]["attempts"] == 3  # three invocations, one attempt each
    assert out["tasks"][0]["statuses"] == ["ok"] * 3
    assert out["tasks"][1]["attempts"] == 3
    assert json.loads(json.dumps(out)) == out


def test_real_run_filters(tmp_path):
    log_a, _ = _run_campaign(tmp_path / "a")
    errors = RunLog.filter(log_a, status="error")
    assert errors == []
    attempts = RunLog.filter(log_a, record="task", attempt=1)
    assert len(attempts) == 6  # both stages, three invocations each
    assert all(r["task"] in ("stage", "combine") for r in attempts)
