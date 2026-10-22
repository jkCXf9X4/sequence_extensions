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

import json
import os
import threading
from pathlib import Path

from sequence_extensions.flow._diff import _diff_records, _path_of
from sequence_extensions.flow._serialize import _canon, _json_bytes, _sort_nested, jsonable

try:  # POSIX advisory locks for fixed-clock reference files
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

#: Bumped whenever the record format changes in a way readers must know about.
SCHEMA_VERSION = 2

__all__ = [
    "DIFF_EXCLUDE",
    "FIXED_CLOCK",
    "FIXED_WORKER",
    "SCHEMA_VERSION",
    "RunLog",
    "jsonable",
]

#: Fixed-clock runs own one path per node name.  The in-process registry makes
#: a second concurrent writer fail loudly instead of truncating the first log;
#: on POSIX an advisory file lock extends the same guarantee across processes.
_FIXED_LOG_LOCKS: dict[str, bool] = {}
_FIXED_LOG_LOCKS_GUARD = threading.Lock()


def _acquire_fixed_log_lock(path: Path) -> str:
    key = str(path.resolve())
    with _FIXED_LOG_LOCKS_GUARD:
        if key in _FIXED_LOG_LOCKS:
            raise RuntimeError(
                f"fixed_clock log is already open by another run: {path} "
                "(reference mode pins one file per node name)"
            )
        _FIXED_LOG_LOCKS[key] = True
    return key


def _release_fixed_log_lock(key: str | None) -> None:
    if key is None:
        return
    with _FIXED_LOG_LOCKS_GUARD:
        _FIXED_LOG_LOCKS.pop(key, None)

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


def _as_records(source) -> list:
    """A log path (``str`` / ``Path``) is read via ``RunLog.records``; a
    list or tuple of records passes through as a list."""
    if isinstance(source, (str, Path)):
        return RunLog.records(source)
    if isinstance(source, (list, tuple)):
        return list(source)
    raise TypeError(f"expected a log path or a record list, got {type(source).__name__}")


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
        self._fixed_lock_key = None
        # Reference mode buffers records; canonical flush happens on close.
        self._buffer: list[tuple[int, dict]] | None = [] if fixed_clock else None

    # ------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------ #
    def open(self) -> None:
        """Create the parent directory and open the file for writing.

        A fixed-clock path is exclusive: a second concurrent run with the same
        pinned node name fails instead of truncating the first run's log.  On
        POSIX the lock also covers separate processes.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.fixed_clock:
            self._fh = self.path.open("wb")
            return
        key = _acquire_fixed_log_lock(self.path)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o666)
        except BaseException:
            _release_fixed_log_lock(key)
            raise
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(fd)
                _release_fixed_log_lock(key)
                raise RuntimeError(
                    f"fixed_clock log is already open by another process: {self.path}"
                ) from exc
        try:
            os.ftruncate(fd, 0)
            self._fh = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            _release_fixed_log_lock(key)
            raise
        self._fixed_lock_key = key

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
        try:
            if self._fh is not None:
                try:
                    if self._buffer is not None:
                        self._flush_canonical()
                finally:
                    self._fh.close()
                    self._fh = None
        finally:
            _release_fixed_log_lock(self._fixed_lock_key)
            self._fixed_lock_key = None

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
            line = {"seq": self._seq, "schema": SCHEMA_VERSION}
            line.update(record)
            # Engine fields win: a record cannot spoof its own sequence.
            line["seq"] = self._seq
            line["schema"] = SCHEMA_VERSION
            self._fh.write(_json_bytes(line))
            self._fh.flush()

    def _flush_canonical(self) -> None:
        """Reference-mode flush: pinned records in canonical order, renumbered.

        Nested mapping keys are sorted as well, so a result dict whose
        insertion order came from a set is byte-identical across processes.
        """
        for _arrival, record in sorted(self._buffer, key=_canonical_order):
            self._seq += 1
            pinned = _pin_timing(record)
            line = {"seq": self._seq, "schema": SCHEMA_VERSION}
            for key, value in pinned.items():
                line[key] = _sort_nested(value)
            line["seq"] = self._seq
            line["schema"] = SCHEMA_VERSION
            self._fh.write(_json_bytes(line))
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

        Note: ``run_start`` also has a ``node`` field, so ``node=...`` alone
        selects it too.  Pass ``record="node"`` when only attempts are wanted.
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
        (``seq``).  Repeated executions with the same identity are compared as
        a multiset: the nth copy carries ``"occurrence": n`` (the first copy
        omits it), so a changed fan-out count is visible.  Fields named in
        ``exclude`` (default :data:`DIFF_EXCLUDE`: record order, run identity,
        wall-clock and worker fields) are dropped before comparing, and a
        future argument's ``done`` snapshot is ignored — wall time is not an
        execution fact.

        Returns a jsonable report, stably ordered: ``equal``; records
        ``only_left`` / ``only_right``; one ``changed`` entry per shared
        identity that differs, carrying each differing field with its
        left and right values.
        """
        left_recs = _as_records(left)
        right_recs = _as_records(right)
        return _diff_records(left_recs, right_recs, exclude)
