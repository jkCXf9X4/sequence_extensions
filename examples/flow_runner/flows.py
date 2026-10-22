"""Nodes driven by ``campaign.toml`` — the flow-runner example.

Run from this directory::

    flow-runner campaign.toml
    python -m sequence_extensions.flow_runner campaign.toml --list

The runner imports this module, discovers the ``@node`` functions, and runs
the one selected by ``[run].flow``.  Inputs come from ``[inputs]``; the
``[node]`` table supplies retry/timeout defaults for decorators that left a
value unset.
"""

from __future__ import annotations

import json
from pathlib import Path

from sequence_extensions.flow import gather, node


def _load_case(case_path: Path) -> dict:
    name, value = case_path.read_text(encoding="utf-8").strip().splitlines()[1].split(",")
    return {"case": name, "value": float(value)}


@node
def simulate(case_path: Path, out_dir: Path) -> Path:
    """Double the case value; fail once per case to exercise retries."""
    marker = out_dir / "markers" / f"{case_path.stem}.failed-once"
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        raise RuntimeError(f"transient failure for {case_path.name}")

    case = _load_case(case_path)
    out_path = out_dir / "sims" / f"{case_path.stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"case": case["case"], "value": case["value"] * 2}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


@node
def evaluate(sim_path: Path, tolerance: float) -> dict:
    """Compare one simulated value to the tolerance."""
    sim = json.loads(sim_path.read_text(encoding="utf-8"))
    return {"case": sim["case"], "value": sim["value"], "passed": sim["value"] >= tolerance}


@node
def summarize(evaluations: list[dict]) -> dict:
    """Fan in the evaluations into one verdict."""
    return {
        "cases": len(evaluations),
        "passed": sum(1 for evaluation in evaluations if evaluation["passed"]),
        "mean": round(sum(evaluation["value"] for evaluation in evaluations) / len(evaluations), 3),
    }


@node
def campaign(cases_dir: Path, out_dir: Path, tolerance: float = 1.5) -> dict:
    """Run every case through simulate and evaluate; return one verdict."""
    # TOML values arrive as strings; normalize paths at the run boundary.
    cases_dir = Path(cases_dir)
    out_dir = Path(out_dir)
    cases = sorted(cases_dir.glob("*.csv"))
    sims = [simulate.submit(case, out_dir) for case in cases]
    evaluations = [evaluate.submit(sim, tolerance) for sim in sims]
    return summarize.submit(gather(evaluations))


if __name__ == "__main__":  # pragma: no cover - the runner is the entry point
    raise SystemExit("run this module through the runner: flow-runner campaign.toml")
