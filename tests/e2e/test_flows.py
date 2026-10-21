"""End-to-end version comparison: run the two mock flows, compare against the reference.

The committed reference (``tests/e2e/ref/``) holds one run log and one
artifact tree per flow.  Each test runs its flow fresh and requires the
run to compare equal to the reference — ``RunLog.diff`` over the logs
(the package's own determinism check) and byte-for-byte artifact
comparison.  The package-version field in ``run_start`` is excluded in
addition to ``DIFF_EXCLUDE``: it is metadata, not behavior.

The runs use the engine's reference mode (``fixed_clock``): the run id
is pinned (a fixed id per flow, so the log filename and the id inside
every record are constant) and the log comes out byte-identical for an
identical run — timing pinned, records in canonical order.  The
scratch tree (``tests/e2e/out/`` — versioned, one stable subtree per
flow) therefore never churns in git: repeated runs rewrite the same
bytes.

A failure means behavior changed between versions.  Intended changes
regenerate the reference; unintended ones are regressions.

Regenerate the reference::

    UPDATE_REF=1 python -m pytest tests/e2e
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from e2e.flows import campaign, failing_campaign
from sequence_extensions.flow import DIFF_EXCLUDE, RunLog, RunOptions, execute_flow

E2E = Path(__file__).resolve().parent
REPO_ROOT = E2E.parent.parent
OUT = E2E / "out"  # scratch — versioned; one stable subtree per flow
REF = E2E / "ref"  # committed reference logs and artifacts
CASES = Path("tests/e2e/cases")

#: The package-version field is metadata, not behavior — excluded on top
#: of ``DIFF_EXCLUDE`` so the gate fires only on real drift.
_E2E_EXCLUDE = DIFF_EXCLUDE | {"version"}

def _fixed_run_id(flow_name: str) -> str:
    """The id ``fixed_clock`` mode pins: same flow, same id, every run."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", flow_name).strip("-") or "flow"
    return f"{safe}-fixed"


@pytest.fixture(autouse=True)
def _from_repo_root(monkeypatch):
    """Run from the repository root (paths end up in the logs)."""
    monkeypatch.chdir(REPO_ROOT)


def _clean(out: Path) -> None:
    """Reset one flow's scratch subtree (retry markers included)."""
    if out.exists():
        shutil.rmtree(out)


def _log_path(flow_name: str) -> Path:
    """The run log of a flow — a stable filename, from the pinned id."""
    return OUT / "logs" / f"{_fixed_run_id(flow_name)}.jsonl"


def _save_reference(flow_name: str, out: Path) -> None:
    REF.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_log_path(flow_name), REF / f"{flow_name}.jsonl")
    if (REF / flow_name).exists():
        shutil.rmtree(REF / flow_name)
    shutil.copytree(out, REF / flow_name)


def _assert_artifacts_match(ref_dir: Path, run_dir: Path) -> None:
    ref_files = sorted(p.relative_to(ref_dir) for p in ref_dir.rglob("*") if p.is_file())
    run_files = sorted(p.relative_to(run_dir) for p in run_dir.rglob("*") if p.is_file())
    assert run_files == ref_files, "the artifact set changed between versions"
    for rel in ref_files:
        assert (run_dir / rel).read_bytes() == (ref_dir / rel).read_bytes(), (
            f"artifact changed: {rel}"
        )


def _compare_with_reference(flow_name: str, out: Path) -> None:
    ref_log = REF / f"{flow_name}.jsonl"
    if not ref_log.exists():
        pytest.fail(
            f"no reference for {flow_name!r} — regenerate with "
            f"UPDATE_REF=1 python -m pytest tests/e2e"
        )
    report = RunLog.diff(ref_log, _log_path(flow_name), exclude=_E2E_EXCLUDE)
    assert report == {"equal": True, "only_left": [], "only_right": [], "changed": []}, json.dumps(
        report, indent=2
    )
    _assert_artifacts_match(REF / flow_name, out)


def _run_and_check(flow_name: str, out: Path, run_flow) -> None:
    """Clean one flow's scratch, run it in reference mode, then save and/or compare."""
    _clean(out)
    run_flow()
    if os.environ.get("UPDATE_REF"):
        _save_reference(flow_name, out)
    _compare_with_reference(flow_name, out)


# ---------------------------------------------------------------- #
# The two flows, one per test
# ---------------------------------------------------------------- #
def test_campaign_end_to_end_matches_the_reference():
    out = Path("tests/e2e/out/campaign")

    def run():
        run = execute_flow(
            campaign,
            CASES,
            100.0,
            out,
            options=RunOptions(log=OUT / "logs", fixed_clock=True),
        )
        verdict = run.result
        assert json.loads(verdict.read_text(encoding="utf-8")) == {
            "cases": 4,
            "passed": 4,
            "all_passed": True,
        }

    _run_and_check("campaign", out, run)


def test_failing_campaign_end_to_end_matches_the_reference():
    out = Path("tests/e2e/out/failing_campaign")

    def run():
        with pytest.raises(ValueError, match="bad.csv"):
            execute_flow(
                failing_campaign,
                CASES,
                out,
                options=RunOptions(log=OUT / "logs", fixed_clock=True),
            )

    _run_and_check("failing_campaign", out, run)
