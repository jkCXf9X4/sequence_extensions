"""JSON-lines audit log — the executed truth of a flow run.

One file per run, one JSON object per line, written while things happen
(attempt granularity for nodes).  The log is the product: diffable,
greppable, and language-neutral.  Large payloads are never inlined; by
convention a node returns a :class:`~pathlib.Path` for anything bulky, and
paths are logged as path plus content hash.

Record kinds (all get ``seq`` and ``schema`` added on write):

* ``run_start`` — written by ``execute_flow`` at entry (identity, args).
* ``node`` — one record per node attempt: ``status`` is ``ok`` (with
  ``result``), ``error``, ``timeout``, or ``skipped`` (``attempt`` 0 —
  the node never executed because a dependency failed or the run failed
  and cancelled it).  ``path`` is the node-name chain that executed and
  ``parent_attempt`` is the enclosing node's attempt number.
* ``run_end`` — written at exit (``status`` ok/error/timeout, result or
  error).

Reading side: :meth:`RunLog.records` reads a log back whole;
:meth:`RunLog.filter` selects records; :meth:`RunLog.summarize`
condenses one run to its per-node account and verdict; and
:meth:`RunLog.diff` compares two runs semantically — the determinism
check.  Comparison identifies records by what ran, never by position,
and drops wall-clock and worker fields by default
(:data:`DIFF_EXCLUDE`): wall time is not an execution fact.

Reference mode (``RunLog(..., fixed_clock=True)``) serves the other
kind of determinism: identical runs produce byte-identical files, for
storing logs as reference artifacts (golden files in git).  Records
are buffered and written at close, in canonical order, with timing
pinned (:data:`FIXED_CLOCK`, ``duration_ms`` 0) and workers constant
(:data:`FIXED_WORKER`).
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from sequence_extensions.graph.graph_future import GraphFuture

#: Bumped whenever the record format changes in a way readers must know about.
SCHEMA_VERSION = 2

#: Containers longer than this are replaced by a count in summary mode.
_SUMMARY_CONTAINER_LIMIT = 8

#: Fields :meth:`RunLog.diff` drops before comparing: record order
#: (``seq``), run identity (``run_id``), and wall-clock / worker timing —
#: none of them are determinism claims.  Pass a replacement set to
#: ``exclude=`` to compare more (or less).
DIFF_EXCLUDE = frozenset(
    {
        "seq",
        "run_id",
        "start",
        "end",
        "started",
        "ended",
        "duration_ms",
        "worker",
    }
)

#: The instant ``fixed_clock`` mode stamps on every engine-written
#: timing field (the epoch — obvious, and never a real reading).
FIXED_CLOCK = "1970-01-01T00:00:00+00:00"

#: What ``fixed_clock`` mode writes instead of the executing worker's
#: thread name: worker identity is not an execution fact.
FIXED_WORKER = "fixed"

#: Engine-written timing fields ``fixed_clock`` mode pins.
_FIXED_TIMING_FIELDS = ("start", "end", "started", "ended")


def _pin_timing(record: dict) -> dict:
    """Reference-mode copy of a record: timing pinned, worker constant."""
    out = dict(record)
    for field in _FIXED_TIMING_FIELDS:
        if field in out:
            out[field] = FIXED_CLOCK
    if "duration_ms" in out:
        out["duration_ms"] = 0
    if "worker" in out:
        out["worker"] = FIXED_WORKER
    return out


def _canonical_order(item) -> tuple:
    """Sort key for a buffered ``(arrival, record)`` pair.

    ``run_start`` first, ``run_end`` last, node records between — by
    what ran (path, parent attempt, attempt, inputs), never by completion
    order: on a frozen clock, completion order carries no information.
    Arrival index only breaks exact ties.
    """
    arrival, rec = item
    kind = rec.get("record")
    if kind == "run_start":
        return (0, "", -1, -1, "", "", arrival)
    if kind == "run_end":
        return (2, "", -1, -1, "", "", arrival)
    parent_attempt = rec.get("parent_attempt")
    parent_attempt = parent_attempt if isinstance(parent_attempt, int) else -1
    attempt = rec.get("attempt")
    attempt = attempt if isinstance(attempt, int) else -1
    return (
        1,
        "\x00".join(str(part) for part in (rec.get("path") or [rec.get("node")])),
        parent_attempt,
        attempt,
        _canon(rec.get("args")),
        _canon(rec.get("kwargs")),
        arrival,
    )


def _file_sha256(path: Path):
    """Hex sha256 of a file's contents, or None if it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def jsonable(value: Any, *, summary: bool = False) -> Any:
    """Convert a value to a JSON-serializable structure.

    * primitives pass through unchanged
    * :class:`~pathlib.Path` -> ``{"path": ..., "sha256": ...}`` (hash only
      when the file exists and is readable)
    * ``datetime`` -> ISO 8601 string (as-is, no timezone guessing)
    * ``bytes`` -> ``{"len": n, "sha256": ...}``
    * ``set`` -> sorted list (items converted)
    * :class:`~sequence_extensions.graph.GraphFuture` -> ``{"node": name,
      "done": bool}``
    * anything else JSON does not know -> ``str(value)``

    In ``summary`` mode, containers longer than
    ``_SUMMARY_CONTAINER_LIMIT`` items are replaced by
    ``{"type": ..., "len": ...}`` — item counts, not items.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return {"path": str(value), "sha256": _file_sha256(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return {"len": len(value), "sha256": hashlib.sha256(bytes(value)).hexdigest()}
    if isinstance(value, (list, tuple)):
        if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
            return {"type": type(value).__name__, "len": len(value)}
        return [jsonable(item, summary=summary) for item in value]
    if isinstance(value, (set, frozenset)):
        if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
            return {"type": type(value).__name__, "len": len(value)}
        try:
            items = sorted(value)
        except TypeError:
            items = list(value)
        return [jsonable(item, summary=summary) for item in items]
    if isinstance(value, dict):
        if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
            return {"type": "dict", "len": len(value)}
        return {str(key): jsonable(item, summary=summary) for key, item in value.items()}
    if isinstance(value, GraphFuture):
        return {"node": value.name, "done": value.done()}
    return str(value)


def _as_records(source) -> list:
    """A log path (``str`` / ``Path``) is read via ``RunLog.records``; a
    list or tuple of records passes through as a list."""
    if isinstance(source, (str, Path)):
        return RunLog.records(source)
    if isinstance(source, (list, tuple)):
        return list(source)
    raise TypeError(f"expected a log path or a record list, got {type(source).__name__}")


def _drop_future_done(value):
    """Recursively drop ``done`` from future-shaped dicts.

    ``jsonable`` gives a :class:`~sequence_extensions.graph.GraphFuture`
    the shape ``{"node": ..., "done": ...}``; the done-snapshot is a
    serialization-time accident, not an execution fact, so diff must
    not see it.
    """
    if isinstance(value, dict):
        out = {k: _drop_future_done(v) for k, v in value.items()}
        if "done" in out and "node" in out:
            out.pop("done")
        return out
    if isinstance(value, list):
        return [_drop_future_done(v) for v in value]
    return value


def _canon(value) -> str:
    """Canonical string of a jsonable value (sort-keys JSON)."""
    return json.dumps(value, sort_keys=True, default=str)


def _path_of(rec) -> tuple:
    """The node-name path of a record, as a hashable tuple."""
    path = rec.get("path")
    if isinstance(path, (list, tuple)) and path:
        return tuple(str(item) for item in path)
    node = rec.get("node")
    return (str(node),) if node is not None else ()


def _diff_identity(rec) -> tuple:
    """The identity of a record for comparison.

    Node records: (path, parent attempt, attempt, args, kwargs) — an
    attempt is what ran, where in the node tree, on which inputs, for the
    which time, so a fan-out (many attempts of one node) compares case by
    case and a retried composite's re-executed descendants stay distinct.
    Run records: their kind (one per run).  Never the record's position.
    """
    if rec.get("record") == "node":
        parent_attempt = rec.get("parent_attempt")
        parent_attempt = parent_attempt if isinstance(parent_attempt, int) else -1
        attempt = rec.get("attempt")
        attempt = attempt if isinstance(attempt, int) else -1
        return (
            "node",
            _path_of(rec),
            parent_attempt,
            attempt,
            _canon(rec.get("args")),
            _canon(rec.get("kwargs")),
        )
    return (str(rec.get("record")),)


def _identity_out(key) -> dict:
    """The jsonable, printable form of a diff identity."""
    if key[0] == "node":
        path = list(key[1])
        return {
            "record": "node",
            "node": path[-1] if path else None,
            "path": path,
            "parent_attempt": key[2],
            "attempt": key[3],
            "args": json.loads(key[4]),
            "kwargs": json.loads(key[5]),
        }
    return {"record": key[0]}


def _diff_side(records, exclude) -> dict:
    """One side of a comparison: ``{identity: normalized record}``.

    Excluded fields are dropped and future ``done`` snapshots ignored
    before the identity is taken, so both come from the same
    normalization.  Duplicate identities: the last record wins.
    """
    side = {}
    for rec in records:
        normalized = _drop_future_done({f: v for f, v in rec.items() if f not in exclude})
        side[_diff_identity(normalized)] = normalized
    return side


class RunLog:
    """Thread-safe JSON-lines writer; one file per run.

    ``write`` is safe from any thread (nodes log their attempts from pool
    workers).  ``seq`` (per-run monotonic record number) and ``schema`` are
    added to every record on write.  Writing to a closed (or never opened)
    log raises — the flow layer closes the log only after every record is
    in, so a late write is a bug, not a dropped line.

    ``fixed_clock=True`` opts the log into reference mode: records are
    buffered and written at :meth:`close`, in canonical order (``run_start``,
    node records by path / parent attempt / attempt / inputs, ``run_end``) with ``seq``
    assigned in that order; engine-written timing fields are pinned to
    :data:`FIXED_CLOCK`, ``duration_ms`` to ``0``, and ``worker`` to
    :data:`FIXED_WORKER`.  The log of an identical run comes out
    byte-identical — for reference-file storage (golden files in git).
    The trade: a reference-mode file holds nothing until close.
    """

    def __init__(self, path, *, summary: bool = False, fixed_clock: bool = False):
        self.path = Path(path)
        self.summary = bool(summary)
        self.fixed_clock = bool(fixed_clock)
        self._lock = threading.Lock()
        self._seq = 0
        self._fh = None
        self._abandoned = False
        # Reference mode buffers records; canonical flush happens on close.
        self._buffer: list[tuple[int, dict]] | None = [] if fixed_clock else None

    # ------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------ #
    def open(self) -> None:
        """Create the parent directory and open the file for writing."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")

    def abandon(self) -> None:
        """Drop every later record.

        A run-level timeout cannot preempt the abandoned attempt thread;
        it may keep producing records after ``run_end``.  Those records
        describe work that is still running and must not corrupt the log,
        so writes after this call are no-ops.
        """
        self._abandoned = True

    def close(self) -> None:
        """Close the file (idempotent).  Reference mode flushes here."""
        if self._fh is not None:
            if self._buffer is not None:
                self._flush_canonical()
            self._fh.close()
            self._fh = None

    # ------------------------------------------------------------ #
    # Writing / reading
    # ------------------------------------------------------------ #
    def write(self, record: dict) -> None:
        """Append one record as a JSON line (thread-safe, flushed).

        Reference mode (``fixed_clock``) buffers the record instead; the
        canonical, pinned lines reach the file at :meth:`close`.  Records
        arriving after :meth:`abandon` are dropped.
        """
        if self._abandoned:
            return
        if self._fh is None:
            raise RuntimeError(f"RunLog.write on a closed log: {self.path}")
        with self._lock:
            if self._abandoned:
                return
            if self._buffer is not None:
                self._buffer.append((len(self._buffer), dict(record)))
                return
            self._seq += 1
            line = {"seq": self._seq, "schema": SCHEMA_VERSION, **record}
            self._fh.write(json.dumps(line, default=str, ensure_ascii=False) + "\n")
            self._fh.flush()

    def _flush_canonical(self) -> None:
        """Reference-mode flush: pinned records in canonical order, renumbered."""
        for _arrival, record in sorted(self._buffer, key=_canonical_order):
            self._seq += 1
            line = {"seq": self._seq, "schema": SCHEMA_VERSION, **_pin_timing(record)}
            self._fh.write(json.dumps(line, default=str, ensure_ascii=False) + "\n")
        self._fh.flush()

    @staticmethod
    def records(path) -> list:
        """Read a run log back as a list of dicts, in file order."""
        out = []
        with open(Path(path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    # ------------------------------------------------------------ #
    # Reading: selection, summary, comparison
    # ------------------------------------------------------------ #
    @staticmethod
    def filter(
        records, *, record=None, node=None, status=None, attempt=None, path=None
    ) -> list:
        """Records matching every given field; ``None`` means no constraint.

        ``record`` selects the record kind (``"run_start"`` / ``"node"``
        / ``"run_end"``); ``node``, ``status``, ``attempt`` and ``path``
        select the same-named fields.  A record without a constrained
        field never matches.  Input order is preserved.
        """
        out = []
        wanted_path = None if path is None else list(path)
        for rec in _as_records(records):
            if record is not None and rec.get("record") != record:
                continue
            if node is not None and rec.get("node") != node:
                continue
            if status is not None and rec.get("status") != status:
                continue
            if attempt is not None and rec.get("attempt") != attempt:
                continue
            if wanted_path is not None and list(rec.get("path") or []) != wanted_path:
                continue
            out.append(rec)
        return out

    @staticmethod
    def summarize(records) -> dict:
        """A compact, jsonable account of a run.

        Run level: ``node`` and ``run_id`` (from ``run_start``) and
        ``status`` — the verdict (from ``run_end``; absent when the log
        has none — an interrupted run).  Per node path, in first-appearance
        order: ``attempts`` (executions — a skip is not an attempt),
        ``statuses`` in record order, the last recorded ``status``, and
        ``duration_ms`` summed over executions (backoff sleeps excluded).
        """
        run = {}
        nodes = {}
        for rec in _as_records(records):
            kind = rec.get("record")
            if kind == "run_start":
                run["node"] = rec.get("node")
                run["run_id"] = rec.get("run_id")
            elif kind == "run_end":
                run["status"] = rec.get("status")
            elif kind == "node":
                path = _path_of(rec)
                detail = nodes.setdefault(
                    path,
                    {
                        "node": path[-1] if path else rec.get("node"),
                        "path": list(path),
                        "attempts": 0,
                        "statuses": [],
                        "duration_ms": 0,
                    },
                )
                detail["statuses"].append(rec.get("status"))
                if rec.get("attempt", 0):
                    detail["attempts"] += 1
                    detail["duration_ms"] += rec.get("duration_ms") or 0
        for detail in nodes.values():
            detail["status"] = detail["statuses"][-1]
        return {**run, "nodes": list(nodes.values())}

    @staticmethod
    def diff(left, right, *, exclude=DIFF_EXCLUDE) -> dict:
        """Compare two runs semantically — the determinism check.

        Records are identified by what ran — node path, parent attempt,
        attempt, inputs (run records by kind) — never by position
        (``seq``).  Fields named in ``exclude`` (default
        :data:`DIFF_EXCLUDE`: record order, run identity, wall-clock and
        worker fields) are dropped before comparing, and a future
        argument's ``done`` snapshot is ignored — wall time is not an
        execution fact.  With duplicate identities, the last record wins.

        Returns a jsonable report, stably ordered: ``equal``; records
        ``only_left`` / ``only_right``; one ``changed`` entry per shared
        identity that differs, carrying each differing field with its
        left and right values.
        """
        left_recs = _as_records(left)
        right_recs = _as_records(right)
        return _diff_records(left_recs, right_recs, exclude)


def _diff_records(left_records, right_records, exclude) -> dict:
    """The flat comparison of two record lists."""
    left_side = _diff_side(left_records, exclude)
    right_side = _diff_side(right_records, exclude)
    only_left = sorted(left_side.keys() - right_side.keys())
    only_right = sorted(right_side.keys() - left_side.keys())
    changed = []
    for key in sorted(left_side.keys() & right_side.keys()):
        lrec, rrec = left_side[key], right_side[key]
        differing = {}
        for field in sorted(set(lrec) | set(rrec)):
            if lrec.get(field) != rrec.get(field):
                differing[field] = {
                    "left": lrec.get(field),
                    "right": rrec.get(field),
                }
        if differing:
            changed.append({**_identity_out(key), "fields": differing})
    return {
        "equal": not (only_left or only_right or changed),
        "only_left": [_identity_out(k) for k in only_left],
        "only_right": [_identity_out(k) for k in only_right],
        "changed": changed,
    }
