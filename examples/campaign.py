"""A small simulation campaign — the core flow shape.

Shows the flow engine end to end:

* ``@node`` functions with retry and timeout policy;
* a plain call for sequential work, ``.submit()`` for concurrent work;
* futures passed as arguments become dependency edges;
* ``gather(...)`` fans in and keeps the container shape;
* ``RunOptions`` (workers, log directory, node defaults);
* the returned ``Run`` and the JSON-lines log it points at.

The simulation is deliberately fake and deterministic, but the structure is
the real one: discover cases, fan out simulations, evaluate each result, and
fan in one verdict.  Every case fails its first attempt, so the log contains
one error and one success per case.

Run::

    python examples/campaign.py --out /tmp/campaign
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sequence_extensions.flow import (
    NodePolicy,
    RunLog,
    RunOptions,
    execute_flow,
    gather,
    node,
)

#: case name -> score; the first two pass a 0.75 tolerance.
CASES = {"c1": 0.82, "c2": 0.91, "c3": 0.74, "c4": 0.65}


def _write_cases(cases_dir: Path) -> list[Path]:
    """Create the input files so the example is runnable on its own."""
    cases_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, value in CASES.items():
        path = cases_dir / f"{name}.csv"
        path.write_text(f"name,value\n{name},{value}\n", encoding="utf-8")
        paths.append(path)
    return paths


def _load_case(case_path: Path) -> dict:
    """Read the tiny csv: a header line, then ``name,value``."""
    name, value = case_path.read_text(encoding="utf-8").strip().splitlines()[1].split(",")
    return {"case": name, "value": float(value)}


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@node(retries=1, retry_delay_seconds=0.01, timeout=5.0)
def simulate(case_path: Path, out_dir: Path) -> Path:
    """Run one case and return the path to its result file.

    Returning a ``Path`` (not the payload) is the convention for bulky
    results: the run log records the path and its sha256, not the contents.
    """
    marker = out_dir / "markers" / f"{case_path.stem}.failed-once"
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        raise RuntimeError(f"transient failure for {case_path.name}")

    case = _load_case(case_path)
    return _write_json(
        out_dir / "sims" / f"{case_path.stem}.json",
        {"case": case["case"], "score": case["value"]},
    )


@node
def evaluate(sim_path: Path, tolerance: float) -> dict:
    """Read one simulation artifact; return a small payload for the log."""
    sim = json.loads(sim_path.read_text(encoding="utf-8"))
    return {
        "case": sim["case"],
        "score": sim["score"],
        "passed": sim["score"] >= tolerance,
    }


@node
def summarize(payload: dict) -> dict:
    """Fan-in node: ``gather`` preserved the dict shape around the list."""
    evaluations = payload["evaluations"]
    return {
        "cases": payload["cases"],
        "passed": sum(1 for evaluation in evaluations if evaluation["passed"]),
        "mean_score": round(
            sum(evaluation["score"] for evaluation in evaluations) / len(evaluations), 3
        ),
    }


@node(timeout=None)
def count_cases(cases_dir: Path) -> int:
    """Sequential helper: a plain call runs inline in the caller's thread."""
    return len(sorted(cases_dir.glob("*.csv")))


@node
def campaign(cases_dir: Path, out_dir: Path, tolerance: float = 0.75) -> dict:
    """Discover cases, fan out, chain evaluate, fan in with ``gather``.

    ``count_cases(cases_dir)`` is a plain call: it runs inline, before the
    fan-out.  ``simulate.submit(...)`` runs on the run's bounded pool;
    passing the returned future to ``evaluate.submit`` creates a dependency
    edge, so an evaluate starts only when its simulation is ready.
    """
    case_count = count_cases(cases_dir)  # plain call: sequential
    cases = sorted(cases_dir.glob("*.csv"))
    sims = [simulate.submit(case, out_dir) for case in cases]
    evaluations = [evaluate.submit(sim, tolerance) for sim in sims]
    return summarize.submit(gather({"evaluations": evaluations, "cases": case_count}))


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("examples/_out/campaign"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    cases_dir = args.out / "cases"
    _write_cases(cases_dir)

    # Reset the retry markers so rerunning the example demonstrates retries
    # again (the --out directory is scratch by contract).
    markers = args.out / "markers"
    if markers.exists():
        for marker in markers.iterdir():
            marker.unlink()

    run = execute_flow(
        campaign,
        cases_dir,
        args.out,
        0.75,
        options=RunOptions(
            max_workers=args.workers,
            log=args.out / "runs",
            # Nodes that left policy unset inherit this; simulate's explicit
            # retries=1 / timeout=5.0 win over it.
            node_defaults=NodePolicy(retries=0, timeout=10.0),
        ),
    )

    summary = RunLog.summarize(run.log)
    retried = RunLog.filter(run.log, record="node", node="simulate", status="error")

    print(f"status:  {run.status}")
    print(f"result:  {run.result}")
    print(f"attempt: {run.attempt}, duration_ms: {run.duration_ms}")
    print(f"retried: {len(retried)} simulate attempts (one per case)")
    print(f"log:     {run.log}")
    print("nodes:  ", [entry["path"] for entry in summary["nodes"]])

    return {"run": run, "summary": summary, "retried": len(retried)}


if __name__ == "__main__":
    main()
