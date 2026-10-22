"""Phase-2 acceptance test: the benchmark campaign, ported to the flow layer.

Campaign (identical semantics to the four-engine benchmark of
2026-10-13): discover 6 case files at runtime, simulate each in
parallel (0.15 s of work, deterministic score, ``case_3`` fails its
first attempt), evaluate against tolerance 0.5, aggregate one verdict.

Expected verdict::

    {"count": 6, "mean_score": 0.35, "passed": 2, "all_passed": False}

and a run log that is the executed truth: 7 simulate attempts
(6 cases + 1 retry of case_3), 6 evaluations, attempt numbering
correct, one run_start/run_end pair.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sequence_extensions.flow import RunLog, RunOptions, execute_flow, gather, node

#: case name -> csv value; score = value / 100
CASE_VALUES = {
    "case_1": 10,
    "case_2": 20,
    "case_3": 30,
    "case_4": 40,
    "case_5": 50,
    "case_6": 60,
}
TOLERANCE = 0.5
EXPECTED_VERDICT = {
    "count": 6,
    "mean_score": pytest.approx(0.35),
    "passed": 2,
    "all_passed": False,
}

#: transient-crash marker: case_3 fails its first attempt per process
_FLAKED: set = set()


def _write_cases(cases_dir: Path) -> Path:
    cases_dir.mkdir(parents=True, exist_ok=True)
    for name, value in CASE_VALUES.items():
        (cases_dir / f"{name}.csv").write_text(f"value\n{value}\n")
    return cases_dir


# ---------------------------------------------------------------- #
# The campaign
# ---------------------------------------------------------------- #
@node(retries=2, retry_delay_seconds=0.05)
def simulate(case: Path) -> dict:
    """Simulate one case; score = value / 100."""
    time.sleep(0.15)
    if case.stem == "case_3" and case.stem not in _FLAKED:
        _FLAKED.add(case.stem)
        raise RuntimeError(f"transient simulator crash on {case.stem}")
    value = int(case.read_text().splitlines()[-1])
    return {"case": case.stem, "score": value / 100}


@node
def evaluate(sim: dict, tolerance: float) -> dict:
    """Evaluate one simulation against the tolerance."""
    return {
        "case": sim["case"],
        "score": sim["score"],
        "passed": sim["score"] >= tolerance,
    }


def discover(cases_dir: Path) -> list:
    """Plain function: sequential discovery, no decorator needed."""
    return sorted(cases_dir.glob("*.csv"))


@node
def aggregate(evaluations: list) -> dict:
    """Fan-in: one verdict from the evaluations (a node, so the composite
    hands on a future instead of waiting)."""
    return {
        "count": len(evaluations),
        "mean_score": sum(e["score"] for e in evaluations) / len(evaluations),
        "passed": sum(1 for e in evaluations if e["passed"]),
        "all_passed": all(e["passed"] for e in evaluations),
    }


@node
def campaign(cases_dir: Path, tolerance: float = TOLERANCE) -> dict:
    cases = discover(cases_dir)  # sequential
    sims = [simulate.submit(c) for c in cases]  # concurrent map
    evals = [evaluate.submit(s, tolerance=tolerance) for s in sims]  # edges
    return aggregate.submit(gather(evals))  # fan-in, no .result() wait


# ---------------------------------------------------------------- #
# The test
# ---------------------------------------------------------------- #
def test_campaign_verdict_and_audit_log(tmp_path):
    _FLAKED.clear()
    cases_dir = _write_cases(tmp_path / "cases")

    t0 = time.perf_counter()
    run = execute_flow(
        campaign,
        cases_dir,
        options=RunOptions(log=tmp_path / "logs", name="campaign"),
    )
    verdict = run.result
    wall = time.perf_counter() - t0

    # 1. identical verdict to the benchmark (all four engines agreed)
    assert verdict["count"] == EXPECTED_VERDICT["count"]
    assert verdict["mean_score"] == EXPECTED_VERDICT["mean_score"]
    assert verdict["passed"] == EXPECTED_VERDICT["passed"]
    assert verdict["all_passed"] is False

    # 2. parallelism: 6 x 0.15s of work plus one 0.05s retry backoff;
    #    sequential execution would need >= 1.0s
    assert wall < 0.6, f"campaign took {wall:.2f}s — not parallel"

    # 3. the audit log is the executed truth
    log_path = next((tmp_path / "logs").glob("*.jsonl"))
    recs = RunLog.records(log_path)

    assert [r["seq"] for r in recs] == list(range(1, len(recs) + 1))
    assert recs[0]["record"] == "run_start"
    assert recs[0]["node"] == "campaign"
    assert recs[0]["args"][0]["path"] == str(cases_dir)
    assert recs[-1]["record"] == "run_end"
    assert recs[-1]["status"] == "ok"
    assert recs[-1]["result"]["count"] == 6
    assert recs[-1]["result"]["passed"] == 2

    task_records = [r for r in recs if r["record"] == "node"]
    sim_records = [r for r in task_records if r["node"] == "simulate"]
    eval_records = [r for r in task_records if r["node"] == "evaluate"]

    # 7 simulate attempts: 6 cases + 1 retry of case_3
    assert len(sim_records) == 7
    assert len(eval_records) == 6

    # one error (case_3 attempt 1), six successes
    assert [r["status"] for r in sim_records].count("error") == 1
    assert [r["status"] for r in sim_records].count("ok") == 6
    assert all(r["status"] == "ok" for r in eval_records)

    def case_of(record):
        return Path(record["args"][0]["path"]).stem

    flaked = [r for r in sim_records if case_of(r) == "case_3"]
    assert [r["attempt"] for r in flaked] == [1, 2]  # attempt numbering
    assert flaked[0]["error"]["message"] == "transient simulator crash on case_3"
    assert flaked[1]["result"] == {"case": "case_3", "score": 0.3}

    # every case simulated exactly once except case_3 (twice)
    per_case = {}
    for r in sim_records:
        per_case.setdefault(case_of(r), []).append(r["attempt"])
    assert per_case["case_1"] == [1]
    assert per_case["case_6"] == [1]
    assert per_case["case_3"] == [1, 2]

    # evaluate received the RESOLVED simulation results (dependency edges)
    eval_args = {(r["args"][0]["case"]): r for r in eval_records}
    assert eval_args["case_5"]["args"][0]["score"] == 0.5
    assert eval_args["case_5"]["result"]["passed"] is True
    assert eval_args["case_1"]["result"]["passed"] is False
    assert eval_args["case_3"]["kwargs"] == {"tolerance": 0.5}

    # simulate really simulated (0.15s of work per attempt)
    assert all(r["duration_ms"] >= 150 for r in sim_records)
    # and ran on pool workers
    assert all(r["worker"].startswith("graph-worker") for r in sim_records)
