"""Hand-written oracles for the e2e golden — independent of the engine.

The golden is evidence only if something other than the implementation that
produced it checks it.  Nothing in this module imports ``sequence_extensions``:
the log is parsed with :mod:`json` and compared field by field here, so a bug
in the engine's own reader or in ``RunLog.diff`` cannot hide in the gate.

``RunLog.diff`` stays in the suite as a *second, weaker* gate — its semantic
report is easier to read once these checks have failed — but it is not the
oracle.

Three checks, all returning a list of problem strings (empty means green):

* :func:`load_log` — the file is JSON lines: one object per line, no blanks.
* :func:`validate_log` — structure: required keys per record kind, contiguous
  ``seq``, ``run_start`` first / ``run_end`` last, the status vocabulary, the
  ``result``/``error`` pairing, and pinned timing.
* :func:`compare_records` — the golden comparison itself: positional,
  field by field, with an explicit exclusion set (:data:`EXCLUDED`).

The constants below restate the log contract on purpose.  If the engine
changes its schema, these restatements fail and the change becomes a reviewed
decision instead of an incidental one.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Status vocabulary.  A new status must be added here deliberately.
RUN_STATUSES = frozenset({"ok", "error", "timeout"})
NODE_STATUSES = frozenset({"ok", "error", "timeout", "skipped"})

#: Timing / identity fields and the sentinel reference mode must pin them to.
#: A live reading in a golden file would make the golden churn between runs.
PINNED = {
    "started": "1970-01-01T00:00:00+00:00",
    "start": "1970-01-01T00:00:00+00:00",
    "end": "1970-01-01T00:00:00+00:00",
    "ended": "1970-01-01T00:00:00+00:00",
    "duration_ms": 0,
    "worker": "fixed",
}

#: Fields the golden deliberately does not compare, each with its reason.
#: Adding a field here is a protocol change;
#: ``test_version_is_excluded_from_comparison_on_purpose`` in ``test_flows.py``
#: pins the set so it cannot grow unnoticed.
EXCLUDED = {
    "seq": "record position: canonical order in reference mode, not an execution fact",
    "run_id": "run identity: pinned by reference mode, a name, not behavior",
    "start": "wall clock",
    "end": "wall clock",
    "started": "wall clock",
    "ended": "wall clock",
    "duration_ms": "wall clock",
    "worker": "worker identity: which thread ran a node is not behavior",
    "version": "package version: metadata, a release bump must not redden the golden",
}

_COMMON = ("seq", "schema", "record", "run_id")

#: Keys every record of a kind carries, whatever its status.
_REQUIRED = {
    "run_start": _COMMON + ("node", "attempt", "started", "version", "args", "kwargs"),
    "node": _COMMON + ("node", "path", "attempt", "parent_attempt", "status"),
    "run_end": _COMMON + ("status", "ended", "duration_ms"),
}

#: Keys a node record carries only when the node actually executed.
_EXECUTED = ("args", "kwargs", "start", "end", "duration_ms", "worker")


def load_log(path) -> tuple[list, list[str]]:
    """Parse a JSON-lines log: ``(records, problems)``."""
    path = Path(path)
    problems: list[str] = []
    records: list = []
    if not path.exists():
        return [], [f"{path}: missing"]
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        problems.append(f"{path.name}: last line has no trailing newline")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            problems.append(f"{path.name}:{number}: blank line")
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}:{number}: not JSON ({exc.msg})")
            continue
        if not isinstance(record, dict):
            problems.append(f"{path.name}:{number}: not a JSON object")
            continue
        records.append(record)
    return records, problems


def _error_problems(record, at, problems) -> None:
    """``error`` must be an object with a type name and a message."""
    error = record.get("error")
    if not isinstance(error, dict):
        problems.append(f"{at}: missing an 'error' object")
        return
    for field in ("type", "message"):
        if not isinstance(error.get(field), str) or not error[field]:
            problems.append(f"{at}: error.{field} is not a non-empty string")


def validate_log(records, *, where: str = "log") -> list[str]:
    """Structural validation of one run log; ``[]`` means well-formed."""
    problems: list[str] = []
    if not records:
        return [f"{where}: no records"]

    kinds = [record.get("record") for record in records]
    if kinds[0] != "run_start":
        problems.append(f"{where}: first record is {kinds[0]!r}, expected 'run_start'")
    if kinds[-1] != "run_end":
        problems.append(f"{where}: last record is {kinds[-1]!r}, expected 'run_end'")
    if kinds.count("run_start") != 1 or kinds.count("run_end") != 1:
        problems.append(f"{where}: expected exactly one run_start and one run_end")

    seqs = [record.get("seq") for record in records]
    if seqs != list(range(1, len(records) + 1)):
        problems.append(f"{where}: seq is not contiguous from 1: {seqs}")

    run_ids = {record.get("run_id") for record in records}
    if len(run_ids) != 1:
        problems.append(f"{where}: records from more than one run: {sorted(map(str, run_ids))}")
    schemas = {record.get("schema") for record in records}
    if len(schemas) != 1:
        problems.append(f"{where}: mixed schema versions: {sorted(map(str, schemas))}")
    elif not all(isinstance(schema, int) and not isinstance(schema, bool) for schema in schemas):
        problems.append(f"{where}: schema is not an integer: {sorted(map(str, schemas))}")

    for number, record in enumerate(records, start=1):
        kind = record.get("record")
        at = f"{where}:{number} ({kind})"
        if kind not in _REQUIRED:
            problems.append(f"{at}: unknown record kind")
            continue
        for field in _REQUIRED[kind]:
            if field not in record:
                problems.append(f"{at}: missing {field!r}")

        if "args" in record and not isinstance(record["args"], list):
            problems.append(f"{at}: args is not a list")
        if "kwargs" in record and not isinstance(record["kwargs"], dict):
            problems.append(f"{at}: kwargs is not an object")
        if kind == "run_start":
            if record.get("attempt") != 1:
                problems.append(f"{at}: run attempt is {record.get('attempt')!r}, expected 1")
            if not isinstance(record.get("version"), str) or not record.get("version"):
                problems.append(f"{at}: version is not a non-empty string")
        elif kind == "node":
            _validate_node(record, at, problems)
        else:
            _validate_run_end(record, at, problems)

        for field, sentinel in PINNED.items():
            if field in record and record[field] != sentinel:
                problems.append(
                    f"{at}: {field} is {record[field]!r}; a golden must pin it to {sentinel!r}"
                )
    return problems


def _validate_node(record, at, problems) -> None:
    """One node record: status vocabulary and the shape that status implies."""
    status = record.get("status")
    if status not in NODE_STATUSES:
        problems.append(f"{at}: status {status!r} outside {sorted(NODE_STATUSES)}")
    path = record.get("path")
    if not isinstance(path, list) or not path or path[-1] != record.get("node"):
        problems.append(f"{at}: path {path!r} does not end at node {record.get('node')!r}")

    attempt = record.get("attempt")
    if status == "skipped":
        if attempt != 0:
            problems.append(f"{at}: skipped with attempt {attempt!r}, expected 0")
        if not record.get("reason"):
            problems.append(f"{at}: skipped without a reason")
        for field in _EXECUTED:
            if field in record:
                problems.append(f"{at}: a skipped record carries {field!r}")
        return

    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        problems.append(f"{at}: attempt {attempt!r} is not a positive integer")
    for field in _EXECUTED:
        if field not in record:
            problems.append(f"{at}: missing {field!r}")
    if status == "ok":
        if "result" not in record:
            problems.append(f"{at}: an ok attempt carries no result")
        if "error" in record:
            problems.append(f"{at}: an ok attempt carries an error")
    else:
        _error_problems(record, at, problems)


def _validate_run_end(record, at, problems) -> None:
    """The closing bookend: a verdict, and the payload that goes with it."""
    status = record.get("status")
    if status not in RUN_STATUSES:
        problems.append(f"{at}: status {status!r} outside {sorted(RUN_STATUSES)}")
    if status == "ok":
        if "result" not in record:
            problems.append(f"{at}: an ok run carries no result")
        if "error" in record:
            problems.append(f"{at}: an ok run carries an error")
    else:
        _error_problems(record, at, problems)
    failed = record.get("failed_nodes")
    if failed is not None and (
        not isinstance(failed, list)
        or not failed
        or not all(isinstance(path, list) and path for path in failed)
    ):
        problems.append(f"{at}: failed_nodes is not a non-empty list of node paths")


def compare_records(reference, produced, *, where: str = "log") -> list[str]:
    """Compare two logs positionally, field by field, excluding :data:`EXCLUDED`.

    Positional is legitimate here and stricter than an identity-keyed diff:
    reference mode writes records in canonical order, so the nth line must be
    the nth line.  Every field outside :data:`EXCLUDED` must match exactly.
    """
    problems: list[str] = []
    if len(reference) != len(produced):
        problems.append(f"{where}: {len(reference)} reference records, {len(produced)} produced")
    for number, (ref, run) in enumerate(zip(reference, produced, strict=False), start=1):
        at = f"{where}:{number} ({ref.get('record')})"
        for field in sorted(set(ref) | set(run)):
            if field in EXCLUDED:
                continue
            if field not in run:
                problems.append(f"{at}: {field} is missing from the run")
            elif field not in ref:
                problems.append(f"{at}: {field} is new in the run")
            elif ref[field] != run[field]:
                problems.append(f"{at}: {field}: reference {ref[field]!r} != run {run[field]!r}")
    return problems
