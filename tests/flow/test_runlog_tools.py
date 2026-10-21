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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _run_start(run_id, *, seq=1, node="campaign", args=("cases/",), version="3.0.0"):
    return {
        "seq": seq,
        "schema": SCHEMA_VERSION,
        "record": "run_start",
        "run_id": run_id,
        "node": node,
        "attempt": 1,
        "started": "2026-10-14T10:00:00+00:00",
        "version": version,
        "args": list(args),
        "kwargs": {},
    }


def _node(
    run_id,
    name,
    attempt,
    status,
    *,
    seq,
    path=None,
    parent_attempt=None,
    duration_ms=10,
    worker="w1",
    args=("a.csv",),
    result=_UNSET,
    error=_UNSET,
):
    rec = {
        "seq": seq,
        "schema": SCHEMA_VERSION,
        "record": "node",
        "run_id": run_id,
        "node": name,
        "path": list(path or [name]),
        "attempt": attempt,
        "parent_attempt": parent_attempt,
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


def _skip(run_id, name, *, seq, path=None, parent_attempt=None, reason="dependency failed"):
    return {
        "seq": seq,
        "schema": SCHEMA_VERSION,
        "record": "node",
        "run_id": run_id,
        "node": name,
        "path": list(path or [name]),
        "attempt": 0,
        "parent_attempt": parent_attempt,
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
    """A small realistic log: bookends, a root, one retried node, one skip."""
    return [
        _run_start(run_id, args=args),
        _node(
            run_id,
            "simulate",
            1,
            "error",
            seq=2,
            path=["campaign", "simulate"],
            parent_attempt=1,
            error={"type": "RuntimeError", "message": "solver crashed"},
        ),
        _node(
            run_id,
            "simulate",
            2,
            "ok",
            seq=3,
            path=["campaign", "simulate"],
            parent_attempt=1,
            result={"score": 1.0},
        ),
        _node(
            run_id,
            "evaluate",
            1,
            "ok",
            seq=4,
            path=["campaign", "evaluate"],
            parent_attempt=1,
            result={"passed": True},
        ),
        _skip(
            run_id,
            "report",
            seq=5,
            path=["campaign", "report"],
            parent_attempt=1,
        ),
        _node(
            run_id,
            "campaign",
            1,
            "ok",
            seq=6,
            path=["campaign"],
            result={"passed": True},
        ),
        _run_end(run_id, seq=7, result={"passed": True}),
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
    assert [r["node"] for r in RunLog.filter(path, record="node")] == [
        "simulate",
        "simulate",
        "evaluate",
        "report",
        "campaign",
    ]
    assert RunLog.filter(recs, record="run_start")[0]["node"] == "campaign"
    assert RunLog.filter(recs, record="run_end")[0]["status"] == "ok"


def test_filter_by_node_status_attempt_and_path():
    recs = _campaign_log("run-a")
    assert [r["attempt"] for r in RunLog.filter(recs, node="simulate")] == [1, 2]
    skips = RunLog.filter(recs, status="skipped")
    assert len(skips) == 1 and skips[0]["node"] == "report"
    errors = RunLog.filter(recs, record="node", status="error")
    assert len(errors) == 1 and errors[0]["node"] == "simulate"
    second = RunLog.filter(recs, node="simulate", attempt=2)
    assert len(second) == 1 and second[0]["status"] == "ok"
    by_path = RunLog.filter(recs, path=["campaign", "evaluate"])
    assert [r["node"] for r in by_path] == ["evaluate"]


def test_filter_constraints_combine_and_missing_fields_never_match():
    recs = _campaign_log("run-a")
    both = RunLog.filter(recs, record="node", status="ok")
    assert [r["node"] for r in both] == ["simulate", "evaluate", "campaign"]
    assert RunLog.filter(recs, attempt=1, status="ok") == [
        r for r in recs if r.get("attempt") == 1 and r.get("status") == "ok"
    ]


def test_filter_no_match_and_order_preserved():
    recs = _campaign_log("run-a")
    assert RunLog.filter(recs, node="nope") == []
    assert RunLog.filter(recs, record="node") == recs[1:6]


def test_filter_accepts_path_and_records(tmp_path):
    recs = _campaign_log("run-a")
    path = _write_log(tmp_path, "a", recs)
    assert RunLog.filter(path, record="node") == RunLog.filter(recs, record="node")


def test_filter_rejects_other_input_types():
    with pytest.raises(TypeError, match="log path or a record list"):
        RunLog.filter(42)


# ---------------------------------------------------------------- #
# summarize — the compact account
# ---------------------------------------------------------------- #
def test_summarize_full_run(tmp_path):
    path = _write_log(tmp_path, "a", _campaign_log("run-a"))
    out = RunLog.summarize(path)
    assert out["node"] == "campaign"
    assert out["run_id"] == "run-a"
    assert out["status"] == "ok"
    assert [n["node"] for n in out["nodes"]] == [
        "simulate",
        "evaluate",
        "report",
        "campaign",
    ]
    simulate = out["nodes"][0]
    assert simulate["path"] == ["campaign", "simulate"]
    assert simulate["attempts"] == 2
    assert simulate["statuses"] == ["error", "ok"]
    assert simulate["status"] == "ok"
    assert simulate["duration_ms"] == 20


def test_summarize_skips_are_not_attempts():
    out = RunLog.summarize(_campaign_log("run-a"))
    report = next(n for n in out["nodes"] if n["node"] == "report")
    assert report["attempts"] == 0
    assert report["statuses"] == ["skipped"]
    assert report["status"] == "skipped"
    assert report["duration_ms"] == 0


def test_summarize_interrupted_run_has_no_verdict():
    out = RunLog.summarize(_campaign_log("run-a")[:4])
    assert "status" not in out
    assert out["nodes"]


def test_summarize_empty_log(tmp_path):
    assert RunLog.summarize(_write_log(tmp_path, "empty", [])) == {"nodes": []}


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
        _node(
            "run-b",
            "simulate",
            1,
            "ok",
            seq=2,
            path=["campaign", "simulate"],
            parent_attempt=1,
            result={"score": 1.0},
        ),
        _node(
            "run-b",
            "evaluate",
            1,
            "ok",
            seq=3,
            path=["campaign", "evaluate"],
            parent_attempt=1,
            result={"passed": True},
        ),
        _skip("run-b", "report", seq=4, path=["campaign", "report"], parent_attempt=1),
        _node(
            "run-b",
            "campaign",
            1,
            "ok",
            seq=5,
            path=["campaign"],
            result={"passed": True},
        ),
        _run_end("run-b", seq=6, result={"passed": True}),
    ]
    report = RunLog.diff(left, right)
    assert report["equal"] is False
    assert report["only_left"] == [
        {
            "record": "node",
            "node": "simulate",
            "path": ["campaign", "simulate"],
            "parent_attempt": 1,
            "attempt": 2,
            "args": ["a.csv"],
            "kwargs": {},
        }
    ]
    assert report["only_right"] == []
    assert len(report["changed"]) == 1
    changed = report["changed"][0]
    assert changed["node"] == "simulate" and changed["attempt"] == 1
    assert changed["fields"]["status"] == {"left": "error", "right": "ok"}
    assert changed["fields"]["result"] == {"left": None, "right": {"score": 1.0}}
    assert changed["fields"]["error"] == {
        "left": {"type": "RuntimeError", "message": "solver crashed"},
        "right": None,
    }


def test_diff_extra_work_is_listed():
    right = _campaign_log("run-b")
    right.append(
        _node(
            "run-b",
            "evaluate",
            1,
            "ok",
            seq=50,
            path=["campaign", "evaluate"],
            parent_attempt=1,
            args=("b.csv",),
            result={"passed": False},
        )
    )
    right.insert(3, _skip("run-b", "late", seq=51, path=["campaign", "late"], parent_attempt=1))
    report = RunLog.diff(_campaign_log("run-a"), right)
    assert report["equal"] is False
    assert report["only_left"] == []
    assert len(report["only_right"]) == 2


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
    report = RunLog.diff(_campaign_log("run-a"), _campaign_log("run-b")[:-1])
    assert report["only_left"] == [{"record": "run_end"}]
    assert report["equal"] is False


def test_diff_exclude_override_brings_timing_back():
    report = RunLog.diff(
        _campaign_log("run-a"),
        _retime(_campaign_log("run-a")),
        exclude=DIFF_EXCLUDE - {"duration_ms"},
    )
    assert len(report["changed"]) == 5
    assert all("duration_ms" in c["fields"] for c in report["changed"])


def test_diff_duplicate_identity_last_wins():
    left = [
        _run_start("run-a"),
        _node(
            "run-a",
            "simulate",
            1,
            "error",
            seq=2,
            path=["campaign", "simulate"],
            parent_attempt=1,
            error={"type": "E", "message": "one"},
        ),
        _node(
            "run-a",
            "simulate",
            1,
            "ok",
            seq=3,
            path=["campaign", "simulate"],
            parent_attempt=1,
            result={"score": 1.0},
        ),
        _run_end("run-a"),
    ]
    right = [
        _run_start("run-b"),
        _node(
            "run-b",
            "simulate",
            1,
            "ok",
            seq=2,
            path=["campaign", "simulate"],
            parent_attempt=1,
            result={"score": 1.0},
        ),
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
        _node(
            "run-a",
            "evaluate",
            1,
            "ok",
            seq=2,
            path=["campaign", "evaluate"],
            parent_attempt=1,
            args=({"node": "simulate", "done": False},),
            result=1,
        ),
        _run_end("run-a"),
    ]
    right = [
        _run_start("run-b"),
        _node(
            "run-b",
            "evaluate",
            1,
            "ok",
            seq=2,
            path=["campaign", "evaluate"],
            parent_attempt=1,
            args=({"node": "simulate", "done": True},),
            result=1,
        ),
        _run_end("run-b"),
    ]
    assert RunLog.diff(left, right)["equal"] is True


def test_diff_output_is_jsonable_and_stably_ordered():
    right = _campaign_log("run-b")
    right[1] = _node(
        "run-b",
        "simulate",
        1,
        "ok",
        seq=2,
        path=["campaign", "simulate"],
        parent_attempt=1,
        result={"score": 2.0},
    )
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
    from sequence_extensions.flow import RunOptions, execute_flow, node

    seen = {}

    @node(retries=1)
    def stage(x):
        if fail_first and x == 1:
            seen[x] = seen.get(x, 0) + 1
            if seen[x] == 1:
                raise RuntimeError("boom")
        return x + 1

    @node
    def combine(x, bias):
        return x + bias

    @node
    def mini(items):
        firsts = [stage.submit(x) for x in items]
        return [combine.submit(f, 10).result() for f in firsts]

    run = execute_flow(
        mini, [1, 2, 3], options=RunOptions(log=str(runs_dir), name="mini")
    )
    logs = list(Path(runs_dir).glob("*.jsonl"))
    assert len(logs) == 1
    return logs[0], run.result


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
    assert len(report["only_left"]) == 1
    assert report["only_left"][0]["node"] == "stage"
    assert report["only_left"][0]["attempt"] == 2
    assert report["only_left"][0]["args"] == [1]
    assert len(report["changed"]) == 1
    assert report["changed"][0]["node"] == "stage"
    assert report["changed"][0]["attempt"] == 1
    assert report["changed"][0]["fields"]["status"] == {"left": "error", "right": "ok"}


def test_real_run_summarizes(tmp_path):
    log_a, _ = _run_campaign(tmp_path / "a")
    out = RunLog.summarize(log_a)
    assert out["node"] == "mini"
    assert out["status"] == "ok"
    assert [n["node"] for n in out["nodes"]] == ["stage", "combine", "mini"]
    assert out["nodes"][0]["attempts"] == 3
    assert out["nodes"][0]["statuses"] == ["ok"] * 3
    assert out["nodes"][1]["attempts"] == 3
    assert json.loads(json.dumps(out)) == out


def test_real_run_filters(tmp_path):
    log_a, _ = _run_campaign(tmp_path / "a")
    errors = RunLog.filter(log_a, status="error")
    assert errors == []
    attempts = RunLog.filter(log_a, record="node", attempt=1)
    assert len(attempts) == 7  # 3 stage + 3 combine + the root
    assert all(r["node"] in ("stage", "combine", "mini") for r in attempts)
