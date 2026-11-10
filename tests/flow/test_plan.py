"""Tests for ``plan`` — the pre-execution DAG pass.

``plan(node, ...)`` runs the root body once (so synchronous fan-out sources
like ``sorted(...)`` execute) but schedules nothing: every ``submit`` /
``gather`` builds and binds its edges with no node body running and no run
log written.  These tests lock the shape the user's campaign example
discovers.
"""

from __future__ import annotations

from pathlib import Path

from sequence_extensions.flow import FlowPlan, RunOptions, gather, node, plan


def _make_campaign():
    """The supported inline fan-out shape from the design discussion."""

    ran = {"simulate": 0, "evaluate": 0, "verdict": 0}

    @node
    def simulate(case: Path, out_dir: Path) -> Path:
        ran["simulate"] += 1
        return out_dir / (case.stem + ".sim")

    @node
    def evaluate(sim: Path, tolerance: float, out_dir: Path) -> Path:
        ran["evaluate"] += 1
        return out_dir / (sim.stem + ".eval")

    @node
    def verdict(evals: list[Path], out_dir: Path) -> Path:
        ran["verdict"] += 1
        return out_dir / "verdict.txt"

    @node
    def campaign(cases_dir: Path, tolerance: float, out_dir: Path) -> Path:
        """Fan-out over the cases, dependency edges into evaluate, one verdict."""
        cases = sorted(cases_dir.glob("*.csv"))
        sims = [simulate.submit(c, out_dir) for c in cases]
        evals = [evaluate.submit(s, tolerance, out_dir) for s in sims]
        return verdict.submit(gather(evals), out_dir)

    return campaign, ran


def test_plan_discovers_the_campaign_dag_without_running_it(tmp_path):
    """plan() returns the DAG a real run would execute, without side effects."""
    for name in ("a.csv", "b.csv", "c.csv"):
        (tmp_path / name).write_text("x")

    campaign, ran = _make_campaign()
    out_dir = tmp_path / "out"

    fplan = plan(campaign, tmp_path, 0.5, out_dir)

    assert isinstance(fplan, FlowPlan)
    assert fplan.root == "campaign"
    # One entry per submitted/gathered node, in bind order (the order the
    # body built them: each simulate/evaluate pair, then gather, then verdict).
    assert fplan.names() == (
        "simulate",
        "evaluate",
        "simulate",
        "evaluate",
        "simulate",
        "evaluate",
        "gather",
        "verdict",
    )
    # Nothing ran: fan-out width is discovered, not executed.
    assert ran == {"simulate": 0, "evaluate": 0, "verdict": 0}
    # The DAG is complete: verdict -> gather -> evaluate -> simulate edges.
    # indices: 0,2,4 simulate; 1,3,5 evaluate; 6 gather; 7 verdict.
    assert fplan.edges == (
        (1, 0),
        (3, 2),
        (5, 4),
        (6, 1),
        (6, 3),
        (6, 5),
        (7, 6),
    )


def test_plan_supports_single_case_fan_out(tmp_path):
    (tmp_path / "only.csv").write_text("x")
    campaign, ran = _make_campaign()

    fplan = plan(campaign, tmp_path, 0.5, tmp_path / "out")

    assert fplan.names() == ("simulate", "evaluate", "gather", "verdict")
    assert fplan.edges == ((1, 0), (2, 1), (3, 2))
    assert fplan.nodes[0][2] == 1  # single occurrence
    assert fplan.nodes[1][2] == 1
    assert ran == {"simulate": 0, "evaluate": 0, "verdict": 0}


def test_plan_is_deterministic_across_calls(tmp_path):
    for name in ("a.csv", "b.csv"):
        (tmp_path / name).write_text("x")
    campaign, _ran = _make_campaign()

    p1 = plan(campaign, tmp_path, 0.5, tmp_path / "out")
    p2 = plan(campaign, tmp_path, 0.5, tmp_path / "out")

    assert p1 == p2


def test_plan_is_pure_and_leaves_no_run_log(tmp_path, monkeypatch):
    for name in ("a.csv", "b.csv"):
        (tmp_path / name).write_text("x")
    campaign, _ran = _make_campaign()

    logs_dir = tmp_path / "logs"
    fplan = plan(campaign, tmp_path, 0.5, tmp_path / "out", options=RunOptions(log=logs_dir))

    assert not logs_dir.exists()
    assert fplan.nodes  # a non-trivial plan
