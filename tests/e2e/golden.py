"""The committed golden of the e2e suite: layout, generation, verification.

The protocol has two phases, and they never share an invocation:

* **generate** (``UPDATE_REF=1``) — run the flow, write ``ref/``.  It does not
  compare, so a regeneration run can never certify its own output.
* **verify** (a normal run) — run the flow, compare against ``ref/``.  It never
  writes, so a red run cannot move the goalposts.

Scratch lives in ``tests/e2e/out/`` and is git-ignored.  The run log records
the paths it was given, so a fixed repository-relative scratch path keeps the
golden stable between runs; being ignored keeps ``git status`` clean, even
after a crash in the middle of a run.

The comparison itself lives in :mod:`e2e.oracle` (hand-written, independent of
the engine); this module owns the file layout and the two phases.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from e2e import oracle
from sequence_extensions.flow import RunLog

E2E = Path(__file__).resolve().parent
REPO_ROOT = E2E.parent.parent

#: Scratch output — git-ignored, one stable subtree per flow, cleaned per run.
OUT = E2E / "out"

#: The committed golden: one log per flow plus one artifact tree per flow.
REF = E2E / "ref"

#: Repository-relative on purpose: these paths end up in the run log.
CASES = Path("tests/e2e/cases")

#: Regenerate instead of verify.  Read once at import; the tests monkeypatch it.
UPDATE_REF = bool(os.environ.get("UPDATE_REF"))


def fixed_run_id(flow_name: str) -> str:
    """The id ``fixed_clock`` mode pins: same flow, same id, every run."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", flow_name).strip("-") or "flow"
    return f"{safe}-fixed"


def log_path(flow_name: str) -> Path:
    """The run log of a flow — a stable filename, from the pinned id."""
    return OUT / "logs" / f"{fixed_run_id(flow_name)}.jsonl"


def clean(out: Path) -> None:
    """Reset one flow's scratch subtree (retry markers included)."""
    shutil.rmtree(out, ignore_errors=True)


def snapshot(root: Path) -> dict[Path, bytes]:
    """Every file below ``root``, keyed by its relative path."""
    root = Path(root)
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def compare_artifacts(reference_dir: Path, run_dir: Path) -> list[str]:
    """Byte-for-byte artifact comparison: same file set, same bytes."""
    reference = snapshot(reference_dir)
    produced = snapshot(run_dir)
    problems = [
        f"artifact missing from the run: {rel}" for rel in sorted(set(reference) - set(produced))
    ]
    problems += [
        f"artifact new in the run: {rel}" for rel in sorted(set(produced) - set(reference))
    ]
    problems += [
        f"artifact bytes changed: {rel}"
        for rel in sorted(set(reference) & set(produced))
        if reference[rel] != produced[rel]
    ]
    return problems


def verify(flow_name: str, out: Path, *, ref_root: Path = REF) -> list[str]:
    """Compare one finished run against the golden; ``[]`` means green.

    Read-only.  The gates, strongest first:

    1. both logs are well-formed JSON lines with a valid record structure;
    2. the logs match positionally, field by field, outside :data:`oracle.EXCLUDED`;
    3. the artifact trees match byte for byte;
    4. ``RunLog.diff`` agrees — a second, weaker gate, kept for its report.
    """
    ref_log = Path(ref_root) / f"{flow_name}.jsonl"
    run_log = log_path(flow_name)
    if not ref_log.exists():
        return [
            f"no reference at {ref_log} — regenerate with UPDATE_REF=1 python -m pytest tests/e2e"
        ]

    reference, reference_problems = oracle.load_log(ref_log)
    produced, produced_problems = oracle.load_log(run_log)
    problems = [f"reference: {problem}" for problem in reference_problems]
    problems += [f"run: {problem}" for problem in produced_problems]
    problems += oracle.validate_log(reference, where="reference")
    problems += oracle.validate_log(produced, where="run")
    # ``run_id`` is excluded from the field comparison (it is an identity, not
    # behavior), so the pin itself is asserted here: reference mode must name
    # every record of this flow ``<flow>-fixed``.
    pinned = fixed_run_id(flow_name)
    for label, records in (("reference", reference), ("run", produced)):
        if records and records[0].get("run_id") != pinned:
            problems.append(
                f"{label}: run_id is {records[0].get('run_id')!r}, expected the pinned {pinned!r}"
            )
    problems += oracle.compare_records(reference, produced, where=flow_name)
    problems += compare_artifacts(Path(ref_root) / flow_name, out)

    report = RunLog.diff(ref_log, run_log, exclude=frozenset(oracle.EXCLUDED))
    if not report["equal"]:
        problems.append(
            f"{flow_name}: RunLog.diff (second gate) disagrees: "
            + json.dumps(report, sort_keys=True)
        )
    return problems


def save_reference(flow_name: str, out: Path) -> str:
    """Write the golden for one flow.  Generation only — it never compares.

    The produced log must pass the structural oracle first: a structurally
    invalid run is not a reference, however recently it was generated.  The
    caller must stop after this call (``pytest.skip``); falling through to
    :func:`verify` would make a regeneration run green by construction.
    """
    log = log_path(flow_name)
    records, problems = oracle.load_log(log)
    problems += oracle.validate_log(records, where=f"generated {flow_name}")
    if problems:
        raise AssertionError("refusing to write an invalid reference:\n" + "\n".join(problems))

    ref_log = REF / f"{flow_name}.jsonl"
    REF.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(log, ref_log)
    ref_dir = REF / flow_name
    if ref_dir.exists():
        shutil.rmtree(ref_dir)
    shutil.copytree(out, ref_dir)
    return (
        f"wrote the reference for {flow_name!r}: "
        f"{ref_log.relative_to(REPO_ROOT)} and {ref_dir.relative_to(REPO_ROOT)}"
    )
