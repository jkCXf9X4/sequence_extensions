"""Run-log record construction — the one place record shapes live.

Every writer (run boundary, attempt loop, settle phase) builds records
through these functions, so schema fields, their order, and the jsonable
policy stay in one place.  Writers decide *when* to record; this module
decides *what* a record looks like.
"""

from __future__ import annotations

from sequence_extensions.flow._serialize import jsonable


def error_field(error: BaseException) -> dict:
    """The ``error`` field shared by node, skip, and run_end records."""
    return {"type": type(error).__qualname__, "message": str(error)}


def arguments_fields(args, kwargs, *, summary: bool) -> dict:
    """The ``args`` / ``kwargs`` fields, converted under the log policy."""
    return {
        "args": [jsonable(a, summary=summary) for a in args],
        "kwargs": {k: jsonable(v, summary=summary) for k, v in kwargs.items()},
    }


def run_start_record(*, run_id, node, attempt, started, version, args, kwargs, summary) -> dict:
    """The ``run_start`` bookend record."""
    return {
        "record": "run_start",
        "run_id": run_id,
        "node": node,
        "attempt": attempt,
        "started": started,
        "version": version,
        **arguments_fields(args, kwargs, summary=summary),
    }


def run_end_record(
    *,
    run_id,
    status,
    ended,
    duration_ms,
    failed_nodes=(),
    result=None,
    error=None,
    summary=False,
) -> dict:
    """The ``run_end`` bookend record for an ok, error, or timeout run."""
    record = {
        "record": "run_end",
        "run_id": run_id,
        "status": status,
        "ended": ended,
        "duration_ms": duration_ms,
    }
    if failed_nodes:
        record["failed_nodes"] = [list(path) for path in failed_nodes]
    if status == "ok":
        record["result"] = jsonable(result, summary=summary)
    else:
        record["error"] = error_field(error)
    return record


def node_record(
    *,
    run_id,
    node,
    path,
    attempt,
    parent_attempt,
    status,
    args,
    kwargs,
    started,
    ended,
    duration_ms,
    worker,
    value=None,
    error=None,
    summary=False,
) -> dict:
    """One executed attempt: ``status`` is ``ok``, ``error``, or ``timeout``."""
    record = {
        "record": "node",
        "run_id": run_id,
        "node": node,
        "path": list(path),
        "attempt": attempt,
        "parent_attempt": parent_attempt,
        "status": status,
        **arguments_fields(args, kwargs, summary=summary),
        "start": started,
        "end": ended,
        "duration_ms": duration_ms,
        "worker": worker,
    }
    if status == "ok":
        record["result"] = jsonable(value, summary=summary)
    else:
        record["error"] = error_field(error)
    return record


def skipped_record(*, run_id, node, path, parent_attempt, reason, error=None) -> dict:
    """A node that never executed (``attempt`` 0) and why."""
    record = {
        "record": "node",
        "run_id": run_id,
        "node": node,
        "path": list(path),
        "attempt": 0,
        "parent_attempt": parent_attempt,
        "status": "skipped",
        "reason": reason,
    }
    if error is not None:
        record["error"] = error_field(error)
    return record
