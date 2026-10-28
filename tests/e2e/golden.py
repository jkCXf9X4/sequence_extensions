"""The committed golden of the e2e suite: layout, generation, verification.

The protocol has two phases, and they never share an invocation:

* **generate** (``UPDATE_REF=1``) — run the flow, write ``ref/``.  It does not
  compare, so a regeneration run can never certify its own output.
* **verify** (a normal run) — run the flow, compare against ``ref/``.  It never
  writes, so a red run cannot move the goalposts.

Scratch lives in ``tests/e2e/out/<worker>/`` — one root per pytest worker, so
two workers never share a run tree — and is git-ignored.  The run log records
the paths it was given, and the committed golden records them
repository-relative, so the flows are handed the stable alias
``tests/e2e/out/<flow>`` and run from a per-worker view directory
(:func:`scratch_view`) where that alias resolves into this worker's root.  The
log bytes therefore do not depend on which worker ran the flow, while the
files on disk do.

The comparison itself lives in :mod:`e2e.oracle` (hand-written, independent of
the engine); this module owns the file layout and the two phases.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from e2e import oracle
from sequence_extensions.flow import RunLog

E2E = Path(__file__).resolve().parent
REPO_ROOT = E2E.parent.parent

#: Which pytest worker owns this process: two workers may never share scratch.
WORKER_ID = re.sub(r"[^A-Za-z0-9_.-]+", "-", os.environ.get("PYTEST_XDIST_WORKER", "main"))
WORKER_ID = WORKER_ID.strip("-") or "main"

#: Scratch output — git-ignored, one root per worker, cleaned per run.
OUT = E2E / "out" / WORKER_ID

#: cwd-relative name for the scratch root.  It appears in the golden, so it is
#: stable across workers; :func:`scratch_view` resolves it into :data:`OUT`.
ALIAS = Path("tests/e2e/out")

#: The committed golden: one log per flow plus one artifact tree per flow.
REF = E2E / "ref"

#: Repository-relative on purpose: these paths end up in the run log.
CASES = Path("tests/e2e/cases")

#: Regenerate instead of verify.  Read once at import; the tests monkeypatch it.
UPDATE_REF = bool(os.environ.get("UPDATE_REF"))

#: Provenance note inside each ``ref/<flow>/`` tree: documentation, not an artifact.
CASE_NOTE = "case.md"


def flow_out(flow_name: str) -> Path:
    """The out argument handed to a flow: the stable, repo-relative alias.

    The flows are given repository-relative paths on purpose — those strings
    are recorded in the golden — so the caller must run from
    :func:`scratch_view` for the alias to reach this worker's :data:`OUT`.
    """
    return ALIAS / flow_name


def _link(link: Path, target: Path) -> None:
    """Make ``link`` point at ``target`` (idempotent, replaces a wrong link)."""
    target = Path(target).resolve()
    if link.is_symlink() and link.resolve() == target:
        return
    if link.is_symlink() or link.exists():
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)


def scratch_view() -> Path:
    """This worker's cwd for the flows: where :data:`ALIAS` and ``CASES`` resolve.

    The flows record the paths they are handed, and the committed golden holds
    repository-relative ones, so the alias and the case path must resolve from
    here: the alias into this worker's :data:`OUT`, the case path into the
    committed inputs.  Both are symlinks — the inputs stay single-sourced and
    scratch stays per-worker.
    """
    view = OUT / "cwd"
    _link(view / ALIAS, OUT)
    _link(view / CASES, E2E / "cases")
    return view



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


def _artifacts(root: Path) -> dict[Path, bytes]:
    """Every artifact below ``root``: :func:`snapshot` minus the provenance note."""
    return {
        rel: data for rel, data in snapshot(root).items() if rel.name != CASE_NOTE
    }


def compare_artifacts(reference_dir: Path, run_dir: Path) -> list[str]:
    """Byte-for-byte artifact comparison: same file set, same bytes.

    ``case.md`` is provenance, not an artifact, so it is excluded: the flow
    does not write it and regenerating the reference must not delete it.
    """
    reference = _artifacts(reference_dir)
    produced = _artifacts(run_dir)
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

    CI is refused outright: a reference rewrite is a reviewed, human act, and a
    CI job must never be able to move the goalposts it reports against.

    The produced log must pass the structural oracle first: a structurally
    invalid run is not a reference, however recently it was generated.  The
    caller must stop after this call (``pytest.skip``); falling through to
    :func:`verify` would make a regeneration run green by construction.
    """
    if UPDATE_REF and os.environ.get("CI"):
        pytest.fail("refusing to update the e2e reference in CI")
    log = log_path(flow_name)
    records, problems = oracle.load_log(log)
    problems += oracle.validate_log(records, where=f"generated {flow_name}")
    if problems:
        raise AssertionError("refusing to write an invalid reference:\n" + "\n".join(problems))

    ref_log = REF / f"{flow_name}.jsonl"
    REF.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(log, ref_log)
    ref_dir = REF / flow_name
    note = ref_dir / CASE_NOTE
    note_bytes = note.read_bytes() if note.is_file() else None
    if ref_dir.exists():
        shutil.rmtree(ref_dir)
    shutil.copytree(out, ref_dir)
    if note_bytes is not None:
        note.write_bytes(note_bytes)
    return (
        f"wrote the reference for {flow_name!r}: "
        f"{ref_log.relative_to(REPO_ROOT)} and {ref_dir.relative_to(REPO_ROOT)}"
    )
