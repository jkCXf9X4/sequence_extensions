"""Unit tests for the run log: serialization policy and the writer."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime

import pytest

from sequence_extensions.flow.runlog import (
    _SUMMARY_CONTAINER_LIMIT,
    FIXED_CLOCK,
    FIXED_WORKER,
    SCHEMA_VERSION,
    RunLog,
    jsonable,
)


# ---------------------------------------------------------------- #
# jsonable: the serialization policy
# ---------------------------------------------------------------- #
def test_jsonable_primitives_passthrough():
    assert jsonable(None) is None
    assert jsonable("s") == "s"
    assert jsonable(3) == 3
    assert jsonable(2.5) == 2.5
    assert jsonable(True) is True


def test_jsonable_path_with_sha256(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("value\n30\n")
    out = jsonable(f)
    assert out["path"] == str(f)
    assert out["sha256"] == hashlib.sha256(b"value\n30\n").hexdigest()


def test_jsonable_missing_path_has_no_hash(tmp_path):
    out = jsonable(tmp_path / "nope.csv")
    assert out == {"path": str(tmp_path / "nope.csv"), "sha256": None}


def test_jsonable_containers_nested():
    out = jsonable([{"a": (1, 2)}, ["x"]])
    assert out == [{"a": [1, 2]}, ["x"]]


def test_jsonable_set_becomes_sorted_list():
    assert jsonable({3, 1, 2}) == [1, 2, 3]


def test_jsonable_unorderable_set_falls_back():
    out = jsonable({"b", "a"}) == ["a", "b"]
    assert out


def test_jsonable_datetime_iso():
    stamp = datetime(2026, 10, 13, 12, 0, 0)
    assert jsonable(stamp) == "2026-10-13T12:00:00"


def test_jsonable_bytes_len_and_sha256():
    out = jsonable(b"payload")
    assert out == {
        "len": 7,
        "sha256": hashlib.sha256(b"payload").hexdigest(),
    }


def test_jsonable_graph_future_shape():
    from sequence_extensions.graph import GraphFuture

    gf = GraphFuture(lambda: 1).set_name("node_x")
    out = jsonable(gf)
    assert out == {"node": "node_x", "done": False}


def test_jsonable_unknown_falls_back_to_str():
    class Opaque:
        def __str__(self):
            return "opaque!"

    assert jsonable(Opaque()) == "opaque!"


def test_jsonable_non_string_dict_keys_become_strings():
    assert jsonable({1: "a"}) == {"1": "a"}


# ---------------------------------------------------------------- #
# jsonable: summary mode
# ---------------------------------------------------------------- #
def test_summary_long_list_becomes_count():
    items = list(range(_SUMMARY_CONTAINER_LIMIT + 1))
    out = jsonable(items, summary=True)
    assert out == {"type": "list", "len": len(items)}


def test_summary_short_list_kept():
    out = jsonable([1, 2], summary=True)
    assert out == [1, 2]


def test_summary_long_dict_becomes_count():
    items = {f"k{i}": i for i in range(_SUMMARY_CONTAINER_LIMIT + 1)}
    assert jsonable(items, summary=True) == {"type": "dict", "len": len(items)}


def test_summary_does_not_change_scalars_or_paths(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"z")
    out = jsonable(f, summary=True)
    assert out["sha256"] == hashlib.sha256(b"z").hexdigest()


# ---------------------------------------------------------------- #
# RunLog writer
# ---------------------------------------------------------------- #
def test_runlog_write_adds_seq_and_schema(tmp_path):
    log = RunLog(tmp_path / "run.jsonl")
    log.open()
    log.write({"record": "run_start"})
    log.write({"record": "run_end"})
    log.close()
    recs = RunLog.records(tmp_path / "run.jsonl")
    assert [r["seq"] for r in recs] == [1, 2]
    assert all(r["schema"] == SCHEMA_VERSION for r in recs)


def test_runlog_abandon_drops_later_records(tmp_path):
    log = RunLog(tmp_path / "run.jsonl")
    log.open()
    log.write({"record": "run_start"})
    log.abandon()
    log.write({"record": "node", "node": "late"})
    log.close()
    assert [r["record"] for r in RunLog.records(tmp_path / "run.jsonl")] == ["run_start"]


def test_runlog_write_closed_raises(tmp_path):
    log = RunLog(tmp_path / "run.jsonl")
    log.open()
    log.close()
    with pytest.raises(RuntimeError, match="closed"):
        log.write({"record": "x"})


# ---------------------------------------------------------------- #
# RunLog writer: reference mode (fixed_clock)
# ---------------------------------------------------------------- #
def test_reference_mode_buffers_until_close(tmp_path):
    path = tmp_path / "ref.jsonl"
    log = RunLog(path, fixed_clock=True)
    log.open()
    log.write({"record": "run_start"})
    assert path.read_text(encoding="utf-8") == ""  # nothing until close
    log.close()
    assert len(RunLog.records(path)) == 1


def test_reference_mode_pins_timing_and_orders_canonically(tmp_path):
    path = tmp_path / "ref.jsonl"
    log = RunLog(path, fixed_clock=True)
    log.open()
    # Deliberately out of canonical order, with real-looking timing.
    log.write(
        {
            "record": "node",
            "run_id": "f-fixed",
            "node": "beta",
            "path": ["f", "beta"],
            "attempt": 1,
            "parent_attempt": 1,
            "status": "ok",
            "args": [2],
            "kwargs": {},
            "start": "2026-10-19T06:00:00+00:00",
            "end": "2026-10-19T06:00:01+00:00",
            "duration_ms": 7,
            "worker": "graph-worker_3",
            "result": 4,
        }
    )
    log.write(
        {
            "record": "run_end",
            "run_id": "f-fixed",
            "status": "ok",
            "ended": "2026-10-19T06:00:02+00:00",
            "duration_ms": 9,
            "result": 4,
        }
    )
    log.write({"record": "run_start", "run_id": "f-fixed", "started": "2026-10-19T06:00:00+00:00"})
    log.close()

    recs = RunLog.records(path)
    assert [r["record"] for r in recs] == ["run_start", "node", "run_end"]
    assert [r["seq"] for r in recs] == [1, 2, 3]  # renumbered in canonical order
    run_start, node_rec, run_end = recs
    assert run_start["started"] == FIXED_CLOCK
    assert run_end["ended"] == FIXED_CLOCK
    assert run_end["duration_ms"] == 0
    assert node_rec["start"] == FIXED_CLOCK
    assert node_rec["end"] == FIXED_CLOCK
    assert node_rec["duration_ms"] == 0
    assert node_rec["worker"] == FIXED_WORKER
    assert node_rec["result"] == 4  # execution facts untouched


def test_reference_mode_orders_nodes_by_path_and_attempt(tmp_path):
    path = tmp_path / "ref.jsonl"
    log = RunLog(path, fixed_clock=True)
    log.open()
    for node_name, path_names, attempt in [
        ("b", ["a", "b"], 1),
        ("a", ["a"], 2),
        ("a", ["a"], 1),
        ("b", ["a", "b"], 2),
    ]:
        log.write(
            {
                "record": "node",
                "node": node_name,
                "path": path_names,
                "attempt": attempt,
                "parent_attempt": None,
                "status": "ok",
            }
        )
    log.close()
    recs = RunLog.records(path)
    assert [(r["path"], r["attempt"]) for r in recs] == [
        (["a"], 1),
        (["a"], 2),
        (["a", "b"], 1),
        (["a", "b"], 2),
    ]


def test_runlog_records_roundtrip(tmp_path):
    log = RunLog(tmp_path / "run.jsonl")
    log.open()
    log.write({"record": "node", "nested": {"a": [1, 2]}})
    log.close()
    assert RunLog.records(tmp_path / "run.jsonl") == [
        {"seq": 1, "schema": SCHEMA_VERSION, "record": "node", "nested": {"a": [1, 2]}}
    ]


def test_runlog_open_creates_parent_dirs(tmp_path):
    log = RunLog(tmp_path / "deep" / "nested" / "run.jsonl")
    log.open()
    log.write({"record": "run_start"})
    log.close()
    assert (tmp_path / "deep" / "nested" / "run.jsonl").exists()


def test_runlog_concurrent_writes_are_unique_and_valid(tmp_path):
    log = RunLog(tmp_path / "run.jsonl")
    log.open()
    n_threads, n_writes = 8, 25

    def _pound():
        for _ in range(n_writes):
            log.write({"record": "node", "node": threading.current_thread().name})

    threads = [threading.Thread(target=_pound) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log.close()

    lines = (tmp_path / "run.jsonl").read_text().splitlines()
    assert len(lines) == n_threads * n_writes
    seqs = [json.loads(line)["seq"] for line in lines]
    assert sorted(seqs) == list(range(1, n_threads * n_writes + 1))
