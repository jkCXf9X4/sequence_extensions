"""End-to-end version comparison: run the two mock flows, compare against the reference.

The committed reference (``tests/e2e/ref/``) holds one run log and one
artifact tree per flow.  Each test runs its flow fresh and requires the
run to compare equal to the reference — ``RunLog.diff`` over the logs
(the package's own determinism check) and byte-for-byte artifact
comparison.  The package-version field in ``run_start`` is excluded in
addition to ``DIFF_EXCLUDE``: it is metadata, not behavior.

The run id is pinned (a fixed id per flow), so the log filename and the
id inside every record are constant between runs.  The scratch tree
(``tests/e2e/out/`` — versioned, one stable subtree per flow) keeps its
shape across runs: repeated runs leave only timing-field differences in
the logs and no file churn at all.

A failure means behavior changed between versions.  Intended changes
regenerate the reference; unintended ones are regressions.

Regenerate the reference::

    UPDATE_REF=1 python -m pytest tests/e2e
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from e2e.flows import campaign, failing_campaign
from sequence_extensions.flow import DIFF_EXCLUDE, RunLog

E2E = Path(__file__).resolve().parent
REPO_ROOT = E2E.parent.parent
OUT = E2E / "out"  # scratch — versioned; one stable subtree per flow
REF = E2E / "ref"  # committed reference logs and artifacts
CASES = Path("tests/e2e/cases")

#: The package-version field is metadata, not behavior — excluded on top
#: of ``DIFF_EXCLUDE`` so the gate fires only on real drift.
_E2E_EXCLUDE = DIFF_EXCLUDE | {"version"}

#: The module that builds run ids.  Imported through importlib because
#: the ``flow`` package re-exports the ``flow`` *decorator*, shadowing
#: the submodule attribute a plain ``import ... as`` would resolve to.
_FLOW_MODULE = importlib.import_module("sequence_extensions.flow.flow")


def _fixed_run_id(flow_name: str) -> str:
    """A stable run id: same flow, same id, every run.

    The log filename (``<run_id>.jsonl``) and the id inside every record
    stay constant, so repeated runs leave the versioned ``out/`` tree
    with only timing-field differences — no file churn.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", flow_name).strip("-") or "flow"
    return f"{safe}-fixed"


@pytest.fixture(autouse=True)
def _from_repo_root_with_pinned_run_id(monkeypatch):
    """Run from the repository root (paths end up in the logs) with the
    run id pinned, so scratch and reference paths stay stable."""
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(_FLOW_MODULE, "_new_run_id", _fixed_run_id)


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
    """Clean one flow's scratch, run it, then save and/or compare."""
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
        verdict = campaign(CASES, 100.0, out)
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
            failing_campaign(CASES, out)

    _run_and_check("failing_campaign", out, run)
