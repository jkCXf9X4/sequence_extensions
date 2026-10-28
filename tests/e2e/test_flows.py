"""End-to-end golden: two deterministic mock flows against the committed reference.

The protocol is two phases that never share an invocation (see :mod:`e2e.golden`
and ``README.md``):

* **verify** (default) — run the flow, compare the produced log and artifact
  tree against ``ref/``.  The primary gate is the hand-written oracle in
  :mod:`e2e.oracle`, which parses the JSON lines itself; ``RunLog.diff`` is a
  second, weaker gate kept for its report.
* **regenerate** (``UPDATE_REF=1``) — write ``ref/`` and skip verification, so a
  regeneration run cannot report a passing comparison in the same invocation.

Scratch (``tests/e2e/out/``) is git-ignored: recorded paths stay
repository-relative and stable, and a run — or a crash mid-run — cannot leave a
tracked file modified.

Regenerate the reference::

    UPDATE_REF=1 python -m pytest tests/e2e

Then review the diff under ``tests/e2e/ref/`` and re-run without ``UPDATE_REF``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from e2e import golden, oracle
from e2e.flows import campaign, failing_campaign
from sequence_extensions.flow import RunOptions, execute_flow


@pytest.fixture(autouse=True)
def _from_repo_root(monkeypatch):
    """Run from the repository root (paths end up in the logs)."""
    monkeypatch.chdir(golden.REPO_ROOT)


# ---------------------------------------------------------------- #
# The two flows — one producer each
# ---------------------------------------------------------------- #
def _run_campaign(out: Path) -> None:
    run = execute_flow(
        campaign,
        golden.CASES,
        100.0,
        out,
        options=RunOptions(log=golden.OUT / "logs", fixed_clock=True),
    )
    assert json.loads(run.result.read_text(encoding="utf-8")) == {
        "cases": 4,
        "passed": 4,
        "all_passed": True,
    }


def _run_failing_campaign(out: Path) -> None:
    with pytest.raises(ValueError, match="bad.csv"):
        execute_flow(
            failing_campaign,
            golden.CASES,
            out,
            options=RunOptions(log=golden.OUT / "logs", fixed_clock=True),
        )


PRODUCERS = {"campaign": _run_campaign, "failing_campaign": _run_failing_campaign}


def _check(flow_name: str, produce, *, ref_root: Path = golden.REF) -> None:
    """The one per-flow body: clean, run, then regenerate *or* verify."""
    out = Path("tests/e2e/out") / flow_name
    golden.clean(out)
    produce(out)
    if golden.UPDATE_REF:
        # Generation stops here.  Falling through to verify() would make this
        # run green by construction — the failure the split exists to prevent.
        pytest.skip(golden.save_reference(flow_name, out) + " — re-run without UPDATE_REF")
    problems = golden.verify(flow_name, out, ref_root=ref_root)
    assert not problems, f"{flow_name} differs from the reference:\n" + "\n".join(problems)


# ---------------------------------------------------------------- #
# The golden
# ---------------------------------------------------------------- #
@pytest.mark.parametrize(("flow_name", "produce"), list(PRODUCERS.items()))
def test_flow_matches_the_committed_reference(flow_name, produce):
    """A fresh run must reproduce the committed log and artifact bytes."""
    _check(flow_name, produce)


def test_the_same_flow_gives_the_same_bytes_twice():
    """Determinism: reference mode pins the run id, the timing, the record
    order, and the worker name, so a repeated run rewrites the same bytes —
    not merely an equal verdict."""
    out = Path("tests/e2e/out/campaign")
    runs = []
    for _ in range(2):
        golden.clean(out)
        _run_campaign(out)
        runs.append((golden.log_path("campaign").read_bytes(), golden.snapshot(out)))
    assert runs[0][0] == runs[1][0], "a repeated run changed the reference log bytes"
    assert runs[0][1] == runs[1][1], "a repeated run changed the artifact bytes"
    assert golden.compare_artifacts(golden.REF / "campaign", out) == []


def test_version_is_excluded_from_comparison_on_purpose():
    """``version`` is metadata, not behavior: a release bump must not redden the
    golden.  The exclusion set is pinned, so widening it is a reviewed change,
    and the oracle is shown not to be blind to a behavioral field."""
    assert set(oracle.EXCLUDED) == {
        "seq",
        "run_id",
        "start",
        "end",
        "started",
        "ended",
        "duration_ms",
        "worker",
        "version",
    }
    records, problems = oracle.load_log(golden.REF / "campaign.jsonl")
    assert not problems
    bumped = [
        {**record, "version": "999.0.0"} if "version" in record else record for record in records
    ]
    assert oracle.compare_records(records, bumped) == []
    changed = [
        {**record, "status": "timeout"} if record.get("status") == "ok" else record
        for record in records
    ]
    assert oracle.compare_records(records, changed), "the oracle ignores a status change"


def test_the_structural_oracle_rejects_a_broken_log():
    """The validator is not vacuous: a ``seq`` gap, a missing bookend, an
    unknown status, and a live timing reading are each caught."""
    good, problems = oracle.load_log(golden.REF / "campaign.jsonl")
    assert not problems
    assert oracle.validate_log(good) == []

    gap = [dict(record) for record in good]
    gap[1]["seq"] = 99
    assert any("seq" in problem for problem in oracle.validate_log(gap))

    truncated = good[:-1]
    assert any("run_end" in problem for problem in oracle.validate_log(truncated))

    unknown = [dict(record) for record in good]
    unknown[1]["status"] = "maybe"
    assert any("status" in problem for problem in oracle.validate_log(unknown))

    live = [dict(record) for record in good]
    live[1]["duration_ms"] = 12
    assert any("duration_ms" in problem for problem in oracle.validate_log(live))

    assert oracle.compare_records(good, good[:1]), "a dropped record must be a difference"


# ---------------------------------------------------------------- #
# The protocol itself
# ---------------------------------------------------------------- #
def _flip_first_hash_digit(ref_root: Path) -> None:
    """Change one hex digit of a result hash: still structurally valid JSON."""
    log = ref_root / "campaign.jsonl"
    data = log.read_bytes()
    marker = b'"sha256": "'
    start = data.index(marker) + len(marker)
    old = data[start : start + 1]
    assert old and old.decode() in "0123456789abcdef"
    new = b"0" if old != b"0" else b"1"
    log.write_bytes(data[:start] + new + data[start + 1 :])


def _change_artifact_byte(ref_root: Path) -> None:
    """Change one digit of the committed verdict artifact."""
    artifact = ref_root / "campaign" / "verdict.json"
    data = artifact.read_bytes()
    assert b"4" in data
    artifact.write_bytes(data.replace(b"4", b"5", 1))


@pytest.mark.parametrize(
    "mutate", [_flip_first_hash_digit, _change_artifact_byte], ids=["log-field", "artifact-byte"]
)
def test_a_changed_reference_byte_turns_the_golden_red(tmp_path, mutate):
    """The golden must be falsifiable.  The mutation happens in a ``tmp_path``
    copy — a test never touches the real reference."""
    copy = tmp_path / "ref"
    shutil.copytree(golden.REF, copy)
    out = Path("tests/e2e/out/campaign")
    golden.clean(out)
    _run_campaign(out)
    assert golden.verify("campaign", out, ref_root=copy) == [], "the untouched copy must be green"

    mutate(copy)
    problems = golden.verify("campaign", out, ref_root=copy)
    assert problems, f"{mutate.__name__} left the golden green"


def test_regeneration_writes_without_verifying(monkeypatch):
    """``UPDATE_REF=1`` writes the reference and stops: a regeneration run must
    not fall through to the comparison, or it would certify itself."""
    monkeypatch.setattr(golden, "UPDATE_REF", True)
    written = []

    def write(flow_name, out):
        written.append(flow_name)
        return f"wrote the reference for {flow_name!r}"

    def forbid(*args, **kwargs):
        raise AssertionError("a regeneration run must not compare")

    monkeypatch.setattr(golden, "save_reference", write)
    monkeypatch.setattr(golden, "verify", forbid)

    for flow_name in PRODUCERS:
        with pytest.raises(pytest.skip.Exception) as skipped:
            _check(flow_name, lambda out: None)
        assert "re-run without UPDATE_REF" in str(skipped.value)
    assert written == list(PRODUCERS)


def test_scratch_output_is_ignored_and_untracked():
    """``out/`` is scratch: git ignores it and tracks nothing below it, so a
    run cannot leave a modified tracked file behind — crash or not."""
    git = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=golden.REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if git.returncode != 0:
        pytest.skip("not a git work tree")

    scratch = golden.log_path("campaign").relative_to(golden.REPO_ROOT)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(scratch)],
        cwd=golden.REPO_ROOT,
        check=False,
    )
    assert ignored.returncode == 0, "tests/e2e/out is not git-ignored"
    tracked = subprocess.run(
        ["git", "ls-files", "tests/e2e/out"],
        cwd=golden.REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.stdout.strip() == "", f"scratch is tracked by git: {tracked.stdout}"
