"""Two mock flows for end-to-end version comparison — the e2e reference pair.

``campaign`` is the happy path: a fan-out of ``simulate`` over the case
files, a dependency edge into ``evaluate``, and one aggregated verdict
artifact.  ``failing_campaign`` is the failure path: one case always fails
validation, its dependent work is skipped, and the flow records
``run_end`` with ``status: "error"``.

Everything is deliberately deterministic — same code, same inputs, same
execution.  The only nondeterminism is what ``RunLog.diff`` excludes by
default: record order, the run's identity, wall-clock, and worker names.
``simulate`` fails the first attempt of every case once per run (a marker
file under the run's output directory — the e2e tests clean the scratch
directory first), so the reference log exercises the retry policy on
every invocation.

All paths are repository-relative because they end up in the run log;
call the flows from the repository root (the e2e tests chdir there).
"""

from __future__ import annotations

import json
from pathlib import Path

from sequence_extensions.flow import node


def _load_case(case_path: Path) -> dict:
    """Parse a two-line csv: header, then ``name,value``."""
    name, value = case_path.read_text(encoding="utf-8").strip().splitlines()[1].split(",")
    return {"case": case_path.name, "value": int(value)}


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- #
# campaign — the happy path
# ---------------------------------------------------------------- #
@node(retries=1, retry_delay_seconds=0.0)
def simulate(case_path: Path, out_dir: Path) -> Path:
    """Mock solver: doubles the case value; the first attempt of every
    case fails once per run (marker file), exercising the retry policy."""
    marker = out_dir / "markers" / f"{case_path.stem}.failed-once"
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        raise RuntimeError(f"transient solver failure: {case_path.name}")
    case = _load_case(case_path)
    return _write_json(
        out_dir / "sims" / f"{case_path.stem}.json",
        {"case": case["case"], "value": case["value"] * 2},
    )


@node
def evaluate(sim_path: Path, tolerance: float, out_dir: Path) -> Path:
    """Mock evaluation: reads the sim artifact, writes one pass/fail."""
    sim = json.loads(sim_path.read_text(encoding="utf-8"))
    return _write_json(
        out_dir / "evals" / f"{sim_path.stem}.json",
        {
            "case": sim["case"],
            "value": sim["value"],
            "tolerance": tolerance,
            "passed": sim["value"] <= tolerance,
        },
    )


def _verdict(eval_paths: list[Path], out_dir: Path) -> Path:
    """Plain helper: one verdict artifact from the evaluations."""
    evaluations = [json.loads(p.read_text(encoding="utf-8")) for p in eval_paths]
    return _write_json(
        out_dir / "verdict.json",
        {
            "cases": len(evaluations),
            "passed": sum(1 for e in evaluations if e["passed"]),
            "all_passed": all(e["passed"] for e in evaluations),
        },
    )


@node
def campaign(cases_dir: Path, tolerance: float, out_dir: Path) -> Path:
    """Fan-out over the cases, dependency edges into evaluate, one verdict."""
    cases = sorted(cases_dir.glob("*.csv"))
    sims = [simulate.submit(c, out_dir) for c in cases]
    evals = [evaluate.submit(s, tolerance, out_dir) for s in sims]
    return _verdict([e.result() for e in evals], out_dir)


# ---------------------------------------------------------------- #
# failing_campaign — the failure path
# ---------------------------------------------------------------- #
@node(retries=1, retry_delay_seconds=0.0)
def validate(case_path: Path) -> dict:
    """Mock gate: a negative value fails validation (``bad.csv``)."""
    case = _load_case(case_path)
    if case["value"] < 0:
        raise ValueError(f"case {case['case']}: value {case['value']} is negative")
    return case


@node
def transform(validated: dict, out_dir: Path) -> Path:
    """Mock consumer of validation; never runs for a failed case."""
    return _write_json(
        out_dir / "transformed" / f"{Path(validated['case']).stem}.json",
        {"case": validated["case"], "value": validated["value"]},
    )


def _summary(transformed_paths: list[Path], out_dir: Path) -> Path:
    """Plain helper: the summary this run never produces (the gather raises)."""
    return _write_json(
        out_dir / "summary.json",
        {"transformed": [p.name for p in transformed_paths]},
    )


@node
def failing_campaign(cases_dir: Path, out_dir: Path) -> Path:
    """Always fails: ``bad.csv`` fails validation, its dependent transform
    is recorded skipped, and the flow raises the first failure — but only
    after every submitted node has settled, so the run's record and
    artifacts are complete and deterministic (no timing-dependent
    cancellations)."""
    cases = sorted(cases_dir.glob("*.csv"))
    validated = [validate.submit(c) for c in cases]
    transformed = [transform.submit(v, out_dir) for v in validated]
    results, failure = [], None
    for t in transformed:  # drain everything first: gate on the full picture
        try:
            results.append(t.result())
        except Exception as error:  # collect every failure, raise the first
            failure = failure or error
    if failure is not None:
        raise failure
    return _summary(results, out_dir)
