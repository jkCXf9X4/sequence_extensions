"""Position independence: a flow behaves the same at the root and as a child.

A flow must not depend on whether it runs at the root or as a child node — the
fixtures cannot rely on a position the engine does not guarantee.  This is
composition semantics, so it lives with the other flow tests rather than in
``tests/e2e``, whose golden asserts the committed bytes of a run.  (The suite's
directory policy in ``tests/markers.py`` derives the level marker from the
directory; this file carries no marker of its own.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from e2e.flows import campaign, failing_campaign
from sequence_extensions.flow import RunOptions, execute_flow, node

#: The e2e fixtures; absolute on purpose (no run log is written here, and the
#: test must not depend on the invocation directory).
CASES = Path(__file__).resolve().parents[1] / "e2e" / "cases"


@node
def _wrapped_campaign(cases_dir: Path, tolerance: float, out_dir: Path):
    """``campaign`` as a child node — it must behave exactly as at the root."""
    return campaign.submit(cases_dir, tolerance, out_dir)


@node
def _wrapped_failing_campaign(cases_dir: Path, out_dir: Path):
    """``failing_campaign`` as a child node."""
    return failing_campaign.submit(cases_dir, out_dir)


def _outcome(flow, out_dir: Path, *extra):
    """Execute ``flow`` into ``out_dir`` and describe what it did."""
    try:
        run = execute_flow(flow, CASES, *extra, out_dir, options=RunOptions(log=None))
    except Exception as exc:  # the failure path raises on purpose
        return "error", type(exc).__name__, str(exc)
    return "ok", run.status, Path(run.result).name


def _assert_same_artifacts(left: Path, right: Path) -> None:
    left_files = sorted(p.relative_to(left) for p in left.rglob("*") if p.is_file())
    right_files = sorted(p.relative_to(right) for p in right.rglob("*") if p.is_file())
    assert left_files == right_files, "the artifact set depends on the position"
    for relative in left_files:
        assert (left / relative).read_bytes() == (right / relative).read_bytes(), relative


@pytest.mark.parametrize(
    ("flow", "wrapped", "extra"),
    [
        (campaign, _wrapped_campaign, (100.0,)),
        (failing_campaign, _wrapped_failing_campaign, ()),
    ],
    ids=["campaign", "failing_campaign"],
)
def test_flow_behaves_the_same_when_wrapped(tmp_path, flow, wrapped, extra):
    root_out = tmp_path / "root"
    wrapped_out = tmp_path / "wrapped"

    root = _outcome(flow, root_out, *extra)
    child = _outcome(wrapped, wrapped_out, *extra)

    assert child == root
    _assert_same_artifacts(root_out, wrapped_out)
