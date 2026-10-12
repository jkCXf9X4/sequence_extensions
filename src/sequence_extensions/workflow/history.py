"""
Execution history and deterministic replay for the V&V workflow layer.

The vision (docs/breakdown/00-intent/vision.md) requires that workflows are
"traceable and reproducible: the full history of verification activities is
preserved and results can be replayed".  The engine itself returns only the
final result; this module supplies the missing evidence layer:

* :class:`ExecutionRecord` — per-action evidence: the action's registry
  name, the resolved function, the parameters the function was ACTUALLY
  called with (globals, upstream results and the action's own parameters,
  merged in the engine's precedence order, minus the engine's reserved
  kwarg names — their evidence lives in dedicated fields), its return
  value (or exception), start/end timestamps, a monotonic duration, the
  run's id, a deterministic completion-order index, and the action's path
  in the workflow tree (e.g. ``root/parallel[1]/action[0]``).
* :class:`RunHistory` — a thread-safe collector the engine appends to as
  each action's function call completes.  Because records are added at
  call completion, the history captures what ACTUALLY executed — including
  actions spliced in at runtime by dynamic adaptation (marked
  ``dynamic=True``) — in true completion order.  The collector carries the
  run's identity: a fresh ``run_id`` per history, and the ``source``
  workflow digest the engine stamps at run start.  ``final_order`` is set
  by the engine after a successful run to the ``order`` of the workflow's
  final action, which is the value :func:`replay` returns.
* :func:`replay` / :func:`replay_records` — deterministic re-execution of
  a recorded run: every recorded action is re-resolved through the function
  registry and called again with its recorded parameters, sequentially, in
  recorded order.  :func:`replay` returns the same final result as the
  original run (the replayed value of the run's final action, which the
  engine marks on the history), proving reproducibility rather than
  echoing stored results.  A function whose signature declares a ``dag``
  parameter (the registry's cached flag — the same signal the engine used
  at run time) is re-invoked with a :class:`ReplayHandle` re-injected:
  reads are served from a fake tree
  materialized from the record's ``scope`` snapshot and write ops are
  no-ops, so replaying an adapting run is deterministic and never mutates
  the live tree.
* :meth:`RunHistory.to_json` / :meth:`RunHistory.from_json` — plain-data
  persistence: the run's identity (``run_id``, ``source``,
  ``params_mode``, ``seed``, ``final_order``) and every record serialize
  to a JSON document and back, so a finished run can be analyzed or
  audited OFFLINE (traceability that lives only in process memory is not
  traceability for regression campaigns).  Non-JSON-serializable values
  (a live ``dag`` handle that a user function kept in its params, an
  exception object, a workflow node) become typed placeholder dicts —
  the serializer never crashes and never drops data that IS plain
  (see :meth:`RunHistory.to_json` for the full policy).

Recording is opt-in: ``run_workflow`` / ``Test_Framework`` accept a
``history`` argument (default ``None``); when no history is requested the
engine behaves exactly as before.

Semantics worth knowing:

* A record's ``params`` are the RESOLVED keyword arguments of the call —
  global parameters, upstream results and the action's own parameters
  already merged in the engine's precedence order.
* A function that returns workflow node(s) (dynamic adaptation) has its
  return value stored as a plain, comparable descriptor (see
  :func:`recordable_result`); the spliced-in actions appear as their own
  records immediately after it.
* ``group_path`` is computed when the action's function call completes, so
  it reflects the workflow tree as it stood at that moment (splices mutate
  the tree concurrently).
* Replaying a run whose action raised re-raises that exception at the same
  point in the sequence.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
import json
import warnings
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Union

from ..graph.handle import TreeHandle
from .artifacts import ArtifactStore, ReplayArtifacts
from .registry import DEFAULT_REGISTRY, FunctionRegistry, wants_artifacts
from .schema import Action, Parallel, Sequential

__all__ = [
    "ExecutionRecord",
    "ReplayHandle",
    "RunHistory",
    "recordable_result",
    "replay",
    "replay_records",
    "resolve_group_path",
]

_Node = Union[Action, Sequential, Parallel]
_Group = Union[Sequential, Parallel]


# --------------------------------------------------------------------------- #
# Per-action evidence
# --------------------------------------------------------------------------- #


@dataclass
class ExecutionRecord:
    """
    Evidence for one executed action: the unit of traceability.

    Fields:

    * ``name`` — the action's registry name (``Action.function``); the key
      :func:`replay` re-resolves the function through.
    * ``function`` — the name of the resolved callable (``fn.__name__``).
    * ``params`` — the resolved keyword arguments the function was
      actually called with (globals, upstream results and the action's
      own parameters, merged in the engine's precedence order), minus the
      engine's reserved kwarg names (``dag`` / ``walk_context``) when the
      engine injected them — their evidence lives in ``scope`` and the
      store's manifest, so the record holds plain, comparable data.
    * ``result`` — the function's return value; a dynamic-adaptation
      return (workflow node(s)) is stored as the plain descriptor produced
      by :func:`recordable_result`.  ``None`` when the function raised.
    * ``exception`` — the exception the function raised, if any.
    * ``started_at`` / ``ended_at`` — wall-clock timestamps
      (``time.time()``) taken around the function call (the audit stamps).
    * ``duration`` — the call's duration (``time.monotonic()``, so it is
      immune to wall-clock adjustments between the stamps).
    * ``order`` — deterministic completion-order index, assigned by
      :meth:`RunHistory.add` (records are numbered 0, 1, 2, ... in the
      order their function calls completed).
    * ``run_id`` — the run's identity: the run history's ``run_id`` (a
      fresh uuid4 hex per history), so a record can be matched to its run.
    * ``group_path`` — the action's path in the workflow tree at call
      completion, e.g. ``"root/parallel[1]/action[0]"``.
    * ``dynamic`` — ``True`` when the action was spliced into the workflow
      at runtime by dynamic adaptation.
    * ``adaptations`` — the committed dynamic-adaptation ops (plain
      descriptors; empty when the function adapted nothing).
    * ``scope`` — snapshot of the acting action's sibling list and index,
      recorded at handle injection (``None`` for non-adapting actions).
    * ``artifacts`` — the action's minted artifact-store address (the
      root-relative node directory, the join key into the run's manifest
      entries); ``None`` when the run had no artifact store (IMP-005).
    * ``description`` — the action node's plain-data ``description`` label
      (set from the XML ``description`` attribute, or by assignment from the
      Python API); ``None`` unless labeled.  It does not execute.
    * ``run_id`` — the run's identity: the run history's ``run_id`` (a
      fresh uuid4 hex per history), so a record can be matched to its run.
    * ``duration`` — the call's duration (``time.monotonic()``); immune to
      wall-clock adjustments between the ``started_at`` / ``ended_at``
      stamps.
    """

    name: str
    function: str
    params: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    exception: BaseException | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    order: int = -1
    group_path: str = ""
    dynamic: bool = False
    adaptations: list[dict] = field(default_factory=list)
    scope: dict | None = None
    artifacts: str | None = None
    description: str | None = None
    run_id: str = ""
    duration: float = 0.0


# --------------------------------------------------------------------------- #
# Plain-data serialization (to_json / from_json)
# --------------------------------------------------------------------------- #

#: The key a serialized non-JSON value's placeholder dict carries.
_PLACEHOLDER_KEY = "__placeholder__"


class _Placeholder:
    """
    The deserialized form of a serialized non-JSON value.

    A live object that cannot be JSON-serialized (a ``dag`` handle, an
    exception, a workflow node) serializes to a typed placeholder dict
    (``{"__placeholder__": "<type>", "repr": ...}``); :meth:`RunHistory.from_json`
    restores it as a :class:`_Placeholder` — the type name and repr
    survive the round-trip, the live object does not (a serialized
    handle is a reference, not a handle).  The class is private: it is
    the serializer's contract, not a public API.
    """

    __slots__ = ("type_name", "repr", "message")

    def __init__(self, type_name: str, repr: str, message: str | None = None) -> None:
        """Bind the placeholder to the serialized value's type and repr."""
        self.type_name = type_name
        self.repr = repr
        self.message = message

    def __repr__(self) -> str:
        """The ORIGINAL value's repr (so a re-serialization of a
        restored history is byte-identical to the first one)."""
        return self.repr

    def __eq__(self, other: Any) -> bool:
        """Structural equality (type name, repr, message)."""
        if not isinstance(other, _Placeholder):
            return NotImplemented
        return (
            self.type_name == other.type_name
            and self.repr == other.repr
            and self.message == other.message
        )


def _to_plain(value: Any) -> Any:
    """
    Recursively turn ``value`` into plain JSON data (the serializer's
    policy — see :meth:`RunHistory.to_json`).

    Plain JSON data (``None`` / bool / int / float / str / list / dict)
    passes through unchanged (dicts keep their key order; non-str keys
    are stringified, the one case ``json`` itself would reject).  A
    value that is not JSON-serializable becomes a typed placeholder
    dict: ``{"__placeholder__": "<type>", "repr": "<repr>"}`` — for an
    exception, plus ``"message"`` (``str(exc)``).  Never raises, never
    drops plain data.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, _Placeholder):
        # A restored placeholder re-serializes to its own dict (the
        # round-trip is a fixed point: the type name and repr are the
        # ORIGINAL value's, not the placeholder's).
        placeholder = {
            _PLACEHOLDER_KEY: value.type_name,
            "repr": value.repr,
        }
        if value.message is not None:
            placeholder["message"] = value.message
        return placeholder
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {
            key if isinstance(key, str) else str(key): _to_plain(item)
            for key, item in value.items()
        }
    placeholder: dict[str, Any] = {
        _PLACEHOLDER_KEY: type(value).__name__,
        "repr": repr(value),
    }
    if isinstance(value, BaseException):
        placeholder["message"] = str(value)
    return placeholder


def _from_plain(value: Any) -> Any:
    """
    Recursively restore a :func:`_to_plain` value (the deserializer's
    policy — see :meth:`RunHistory.from_json`).

    Plain data comes back unchanged; a placeholder dict comes back as a
    :class:`_Placeholder` (its type name and repr preserved).
    """
    if isinstance(value, list):
        return [_from_plain(item) for item in value]
    if isinstance(value, dict):
        if _PLACEHOLDER_KEY in value:
            return _Placeholder(
                value[_PLACEHOLDER_KEY],
                value.get("repr", ""),
                value.get("message"),
            )
        return {key: _from_plain(item) for key, item in value.items()}
    return value


def _record_to_plain(record: ExecutionRecord) -> dict[str, Any]:
    """One record as a plain JSON object (every field, policy-applied)."""
    return {
        "name": record.name,
        "function": record.function,
        "params": _to_plain(record.params),
        "result": _to_plain(record.result),
        "exception": _to_plain(record.exception),
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "order": record.order,
        "group_path": record.group_path,
        "dynamic": record.dynamic,
        "adaptations": _to_plain(record.adaptations),
        "scope": _to_plain(record.scope),
        "artifacts": record.artifacts,
        "description": record.description,
        "run_id": record.run_id,
        "duration": record.duration,
    }


def _record_from_plain(data: dict[str, Any]) -> ExecutionRecord:
    """Rebuild one record from its plain JSON object (policy-applied)."""
    return ExecutionRecord(
        name=data["name"],
        function=data["function"],
        params=_from_plain(data.get("params", {})),
        result=_from_plain(data.get("result")),
        exception=_from_plain(data.get("exception")),
        started_at=data.get("started_at", 0.0),
        ended_at=data.get("ended_at", 0.0),
        order=data.get("order", -1),
        group_path=data.get("group_path", ""),
        dynamic=data.get("dynamic", False),
        adaptations=_from_plain(data.get("adaptations", [])),
        scope=_from_plain(data.get("scope")),
        artifacts=data.get("artifacts"),
        description=data.get("description"),
        run_id=data.get("run_id", ""),
        duration=data.get("duration", 0.0),
    )


# --------------------------------------------------------------------------- #
# Thread-safe collector
# --------------------------------------------------------------------------- #


class RunHistory:
    """
    A thread-safe, ordered collector of :class:`ExecutionRecord` s.

    The engine appends one record per action as the action's function call
    completes, so the history is what ACTUALLY executed — including
    actions spliced in at runtime by dynamic adaptation — in true
    completion order.  ``final_order`` is set by the engine after a
    successful run to the ``order`` of the workflow's final action, which
    is the value :func:`replay` returns.

    Run identity (IMP-011): ``run_id`` is a fresh uuid4 hex created with
    the history and stamped on every record the engine appends to it;
    ``source`` is the workflow digest (sha256 of the XML source, or of the
    Python-API root tree's repr) the engine stamps at run start (``None``
    until then, and for a history never used for a run); ``params_mode``
    is the recorded-params shape the run used (``"full"`` /
    ``"summary"``), ``"full"`` by default — the serializer preserves it
    so a deserialized history records the shape its params were
    recorded in.

    Randomization identity (finding 4e / paper P16-UC2): ``seed`` is the
    campaign's randomization seed (``None`` for a run that used no
    randomization).  The engine does not stamp it — the seed is caller
    knowledge, not engine-derivable — so the caller sets it when running
    a randomized campaign (``history.seed = seed``); the per-action
    evidence (the driver's declared ``seed`` parameter) is recorded by
    the engine in each record's ``params``.  The serializer preserves the
    run-level seed so a deserialized history still names the seed its
    scenarios were drawn from.
    """

    def __init__(self) -> None:
        """Create an empty history with its run identity."""
        self._records: list[ExecutionRecord] = []
        self._lock = threading.Lock()
        self._next_order = 0
        # Order index of the run's final action; None until the engine
        # marks it (and for an empty or failed run).
        self.final_order: int | None = None
        # Run identity: a fresh uuid4 hex per history, and the workflow
        # digest stamped by the engine at run start.
        self.run_id: str = uuid.uuid4().hex
        self.source: str | None = None
        # The recorded-params shape the run used ("full" / "summary");
        # stamped by the engine at run start, "full" until then.
        self.params_mode: str = "full"
        # The campaign's randomization seed (finding 4e / paper P16-UC2):
        # the seed a randomized run drew its scenarios from, so the run is
        # reproducible.  ``None`` for a run that used no randomization.
        # The engine does not stamp it (it is caller knowledge, not
        # engine-derivable), so the caller sets it when running a
        # randomized campaign (``history.seed = seed``); the per-action
        # evidence also lands in each record's ``params`` (the driver's
        # declared ``seed`` parameter is recorded by the engine).
        self.seed: int | None = None

    def add(self, record: ExecutionRecord) -> ExecutionRecord:
        """
        Append ``record``, assigning its deterministic ``order`` index.

        Thread-safe: the index assignment and the append happen under one
        lock, so concurrent action completions produce a gapless 0..n-1
        numbering with no lost or duplicated records.  Returns ``record``
        (for the engine's final-action bookkeeping).
        """
        with self._lock:
            record.order = self._next_order
            self._next_order += 1
            self._records.append(record)
        return record

    @property
    def records(self) -> list[ExecutionRecord]:
        """A snapshot list of the records, in completion order."""
        with self._lock:
            return list(self._records)

    def __len__(self) -> int:
        """The number of recorded actions."""
        return len(self.records)

    def __iter__(self) -> Iterator[ExecutionRecord]:
        """Iterate the records in completion order."""
        return iter(self.records)

    def __getitem__(self, index: int | slice) -> Any:
        """Index (or slice) the completion-ordered records."""
        return self.records[index]

    # ------------------------------------------------------------ #
    # Persistence (plain-data JSON round-trip)
    # ------------------------------------------------------------ #
    def to_json(self) -> str:
        """
        Serialize the run history to a JSON document (a string).

        The document is a plain JSON object:

        * ``"run_id"`` — the run's identity (a uuid4 hex).
        * ``"source"`` — the workflow digest the engine stamped at run
          start (``null`` for a history never used for a run).
        * ``"params_mode"`` — the recorded-params shape the run used
          (``"full"`` / ``"summary"``).
        * ``"seed"`` — the campaign's randomization seed (``null`` for a
          run that used no randomization; finding 4e / paper P16-UC2).
        * ``"final_order"`` — the completion-order index of the run's
          final action (``null`` for an empty or failed run).
        * ``"records"`` — the records, in completion order, each a plain
          object with the record's fields (``name``, ``function``,
          ``params``, ``result``, ``exception``, ``started_at``,
          ``ended_at``, ``order``, ``group_path``, ``dynamic``,
          ``adaptations``, ``scope``, ``artifacts``, ``description``,
          ``run_id``, ``duration``).

        **Non-JSON-serializable policy.**  The serializer walks every
        value recursively.  Plain JSON data (``None`` / bool / int /
        float / str / list / dict) passes through UNCHANGED — plain data
        is never dropped or altered.  A value that is not JSON-
        serializable becomes a typed placeholder dict
        ``{"__placeholder__": "<type>", "repr": "<repr>"}`` — a
        reference to what was there, never a crash and never a silent
        drop.  The known cases:

        * a live ``dag`` handle (the engine strips the INJECTED one from
          recorded params, but a user function that keeps a handle under
          its own parameter name — the known IMP-010 issue — records it)
          serializes as ``{"__placeholder__": "DAGHandle", ...}`` (or the
          handle's concrete type name);
        * a recorded ``exception`` object serializes as
          ``{"__placeholder__": "<ExcType>", "repr": ..., "message": ...}``
          (the exception's type name and ``str(exc)`` — enough to audit
          what failed without re-raising it);
        * a workflow node (an adapting function's return value that was
          not normalized by :func:`recordable_result`) serializes as
          ``{"__placeholder__": "<NodeType>", ...}``.

        The placeholder is deterministic for a given value (its type
        name and repr), so two serializations of the same history
        produce the same document.  :meth:`from_json` restores the
        placeholders as :class:`_Placeholder` objects (the type name and
        repr survive the round-trip; the live object does not — a
        serialized handle is a reference, not a handle).
        """
        return json.dumps(
            {
                "run_id": self.run_id,
                "source": self.source,
                "params_mode": self.params_mode,
                "seed": self.seed,
                "final_order": self.final_order,
                "records": [_record_to_plain(record) for record in self.records],
            }
        )

    @classmethod
    def from_json(cls, document: str) -> "RunHistory":
        """
        Rebuild a :class:`RunHistory` from a :meth:`to_json` document.

        The rebuilt history carries the same ``run_id``, ``source``,
        ``params_mode``, ``seed``, ``final_order`` and records (in
        completion order, with their ``order`` indices) as the serialized
        one.
        Plain data round-trips exactly; a serialized placeholder comes
        back as a :class:`_Placeholder` (its type name and repr
        preserved), so a round-trip of a history whose params held a
        live ``dag`` handle yields a history whose params hold the
        handle's PLACEHOLDER — the reference survives, the live object
        does not (it cannot: a serialized handle is not a handle).

        Raises ``ValueError`` when the document is not a valid
        :meth:`to_json` document (not a JSON object, or missing the
        ``run_id`` / ``records`` keys).
        """
        try:
            data = json.loads(document)
        except json.JSONDecodeError as exc:
            raise ValueError(f"RunHistory.from_json: not a JSON document: {exc}") from None
        if not isinstance(data, dict) or "run_id" not in data or "records" not in data:
            raise ValueError(
                "RunHistory.from_json: not a RunHistory.to_json document "
                "(expected a JSON object with 'run_id' and 'records')"
            )
        history = cls()
        history.run_id = data["run_id"]
        history.source = data.get("source")
        history.params_mode = data.get("params_mode", "full")
        history.seed = data.get("seed")
        history.final_order = data.get("final_order")
        for record_data in data["records"]:
            record = _record_from_plain(record_data)
            # Rebuild the completion-order numbering exactly (the
            # serialized order indices are authoritative; add() would
            # renumber from 0, which is the same sequence, but the
            # explicit assignment keeps the invariant visible).
            history._records.append(record)
            history._next_order = max(history._next_order, record.order + 1)
        return history


# --------------------------------------------------------------------------- #
# Tree paths and dynamic-adaptation descriptors
# --------------------------------------------------------------------------- #


def resolve_group_path(root: _Group, node: _Node) -> str:
    """
    Return ``node``'s path in the workflow tree rooted at ``root``.

    The path starts at ``"root"`` and adds one ``kind[index]`` segment per
    level (``sequential`` / ``parallel`` for groups, ``action`` for
    actions), e.g. ``"root/parallel[1]/action[0]"`` for the first action of
    the root's second child when that child is a ``Parallel`` group.
    Indices are positions in ``children`` at call time, so a tree mutated
    by a splice yields the post-splice path.  Returns ``"root"`` when
    ``node`` is the root itself and ``""`` when it is not in the tree.
    """
    if node is root:
        return "root"
    segments = _find_segments(root, node, [])
    if segments is None:
        return ""
    return "/".join(["root", *segments])


def _find_segments(group: _Group, node: _Node, prefix: list[str]) -> list[str] | None:
    """Depth-first search for ``node``; returns its path segments or ``None``."""
    for index, child in enumerate(group.children):
        segment = f"{_kind(child)}[{index}]"
        if child is node:
            return [*prefix, segment]
        if isinstance(child, (Sequential, Parallel)):
            found = _find_segments(child, node, [*prefix, segment])
            if found is not None:
                return found
    return None


def _kind(node: _Node) -> str:
    """The path-segment kind of a node: action / sequential / parallel."""
    if isinstance(node, Action):
        return "action"
    if isinstance(node, Sequential):
        return "sequential"
    return "parallel"


def recordable_result(value: Any) -> Any:
    """
    Normalize a function return value for storage in a record.

    A dynamic-adaptation return (an ``Action`` / ``Sequential`` /
    ``Parallel`` node, or a non-empty list/tuple of them) becomes a plain,
    comparable descriptor — nested dicts/lists of function names and
    parameters — because the engine splices the nodes into the workflow
    (their execution appears as the following records) and node objects do
    not compare structurally.  Any other value is returned unchanged.
    """
    if _is_node_return(value):
        return _describe(value)
    return value


def _is_node_return(value: Any) -> bool:
    """
    True when ``value`` is a workflow node or a non-empty list/tuple of
    them (the engine's dynamic-adaptation return shape).
    """
    if isinstance(value, (Action, Sequential, Parallel)):
        return True
    if isinstance(value, (list, tuple)):
        return bool(value) and all(
            isinstance(item, (Action, Sequential, Parallel)) for item in value
        )
    return False


def _describe(value: Any) -> Any:
    """Recursively turn workflow node(s) into a plain descriptor."""
    if isinstance(value, Action):
        return {"function": value.function, "params": dict(value.params)}
    if isinstance(value, Sequential):
        return {"sequential": [_describe(child) for child in value.children]}
    if isinstance(value, Parallel):
        return {"parallel": [_describe(child) for child in value.children]}
    if isinstance(value, (list, tuple)):
        return [_describe(item) for item in value]
    return value


# --------------------------------------------------------------------------- #
# Replay handle (deterministic re-execution of adapting runs)
# --------------------------------------------------------------------------- #

#: Sentinel function name for placeholder children of a materialized fake
#: group sibling.  The scope snapshot records a group sibling's child COUNT
#: but not the children's identities, so the fake group is filled with
#: placeholders that preserve the count (and are clearly not real actions).
_REPLAY_PLACEHOLDER = "__replay_placeholder__"


def _materialize_sibling(descriptor: dict[str, Any]) -> _Node:
    """
    Materialize one fake sibling node from a scope-snapshot descriptor.

    An action descriptor becomes an ``Action`` with the recorded function
    name (no parameters — the snapshot does not record them).  A group
    descriptor becomes a ``Sequential`` / ``Parallel`` with the recorded
    number of placeholder children, so the child COUNT is preserved even
    though the snapshot does not record the children's identities.
    """
    kind = descriptor.get("kind")
    if kind == "action":
        return Action(descriptor.get("function", ""))
    count = int(descriptor.get("children", 0))
    # A recorded child name (position-aligned, None for unnamed) becomes
    # a named empty group; unnamed positions stay placeholder actions.
    # The child COUNT is preserved either way.
    child_names = descriptor.get("child_names")
    if child_names is not None:
        children = [
            Sequential(name=name) if name is not None else Action(_REPLAY_PLACEHOLDER)
            for name in child_names
        ]
        children = children[:count] + [Action(_REPLAY_PLACEHOLDER)] * (
            count - len(children)
        )
    else:
        children = [Action(_REPLAY_PLACEHOLDER) for _ in range(count)]
    if kind == "parallel":
        group: Sequential | Parallel = Parallel(*children)
    else:
        group = Sequential(*children)
    # A named group's label is part of its declared identity — recorded
    # in the snapshot, materialized here so a replayed branching driver
    # (``ReplayHandle.select``) can find its named alternatives.
    group.name = descriptor.get("name")
    return group


class ReplayHandle(TreeHandle):
    """
    A read-only, no-op stand-in for :class:`~.adaptation.DAGHandle` in replay.

    When a recorded run's function declared a ``dag`` parameter, replay
    re-injects a :class:`ReplayHandle` (instead of a live handle) so the
    function re-executes deterministically:

    * **Reads** (``following`` / ``preceding`` / ``following_group`` and
      node traversal) are served from a FAKE tree materialized from the
      record's ``scope`` snapshot — the acting action's sibling list and
      index as they stood at injection.
    * **Write ops** (``replace`` / ``adjust`` / ``append`` and the
      write-only patterns ``fan_out`` / ``skip`` / ``skip_following`` /
      ``repeat``) are NO-OPS: they are recorded nowhere and applied
      nowhere, so replay never mutates the live tree and never diverges
      from the original run's committed structure.
    * **Clone ops** (``copy`` / ``adjusted`` / ``copy_self``) and the
      value-returning branch pattern (``select``) are functional: they
      clone or resolve the materialized fake target, so an adapting
      function's clone-based and branching logic runs (against the fake
      tree — the closest the snapshot allows).

    The handle is a thin specialization of the generic
    :class:`~sequence_extensions.graph.handle.TreeHandle`: the
    value-returning flows (reads, clone ops, ``select``) are inherited and
    served from the fake tree, and this class supplies only the replay
    policy — the fake-tree construction, the silenced write-permission
    check, the no-op op recording and the short-circuited write-only
    patterns.  An inherited flow therefore cannot drift from the live
    handle's; only a write-only pattern needs an explicit no-op here.

    The handle is constructed per replayed record and holds no reference
    to the live workflow tree.
    """

    def __init__(self, scope: dict | None) -> None:
        """Materialize the fake parent group from ``scope`` (or empty)."""
        siblings: list[_Node] = []
        index = 0
        if scope is not None:
            index = int(scope.get("index", 0))
            siblings = [_materialize_sibling(s) for s in scope.get("siblings", [])]
        super().__init__(Sequential(*siblings), index, read_only=True)

    # ------------------------------------------------------------ #
    # The replay policy (hooks over the generic flows)
    # ------------------------------------------------------------ #
    def _check_writable(self) -> None:
        """Writes are silent no-ops in replay: the permission check passes."""
        return None

    def _emit(
        self,
        *,
        kind: str,
        target: _Node | None = None,
        nodes: tuple = (),
        params: dict[str, Any] | None = None,
        scope: _Group | None = None,
    ) -> None:
        """Record nothing: replay never mutates and never diverges."""
        return None

    # ------------------------------------------------------------ #
    # Write ops (NO-OPS: recorded nowhere, applied nowhere)
    # ------------------------------------------------------------ #
    def replace(self, target: _Node, nodes: Any) -> None:
        """No-op in replay: the replacement is not applied to any tree."""
        return None

    def adjust(self, target: _Node, **params: Any) -> None:
        """No-op in replay: the parameter overrides are not applied."""
        return None

    def append(self, nodes: Any) -> None:
        """No-op in replay: the nodes are not appended to any tree."""
        return None

    # ------------------------------------------------------------ #
    # Write-only patterns (no-ops: their only effect is a write)
    # ------------------------------------------------------------ #
    # The value-returning flows (select / copy / adjusted / copy_self)
    # are inherited and run functionally against the fake tree.  The
    # patterns below have no return value: their whole effect is a
    # write, so they are short-circuited — nothing is recorded, nothing
    # is applied, and no clone is computed only to be discarded.
    # ------------------------------------------------------------ #
    def fan_out(self, overrides: Any) -> None:
        """No-op in replay: the fan-out clones are not applied to any tree."""
        return None

    def skip(self) -> None:
        """No-op in replay: the following group is not skipped."""
        return None

    def skip_following(self) -> None:
        """No-op in replay: the following siblings are not skipped."""
        return None

    def repeat(self, **param_overrides: Any) -> None:
        """No-op in replay: the copy-to-end append is not applied."""
        return None


# --------------------------------------------------------------------------- #
# Deterministic replay
# --------------------------------------------------------------------------- #


def replay_records(
    history: RunHistory,
    registry: FunctionRegistry | None = None,
    artifacts: ArtifactStore | None = None,
) -> list[Any]:
    """
    Re-execute every recorded action and return the replayed values.

    Actions are re-executed strictly sequentially, in recorded
    (completion) order: each record's function is re-resolved through
    ``registry`` (default ``DEFAULT_REGISTRY``) and called with the
    record's resolved ``params``.  The returned list is positionally
    aligned with ``history.records``; a replayed dynamic-adaptation return
    is normalized with :func:`recordable_result` so it compares equal to
    the stored descriptor.  A recorded failure re-raises at the same point
    in the sequence.

    Adapting functions (whose recorded ``params`` contain the injected
    ``dag`` kwarg) are re-invoked with the ``dag`` kwarg STRIPPED and a
    :class:`ReplayHandle` re-injected instead: reads are served from a
    fake tree materialized from the record's ``scope`` snapshot and write
    ops are no-ops, so replay is deterministic and never mutates the live
    tree.  Non-adapting records are replayed byte-for-byte as before.

    The engine's injected ``walk_context`` kwarg (present in a recorded
    store run, where every call went through the store's registry
    wrapper) is engine plumbing, never replayed: it is stripped.  A
    record whose run minted an artifact address, whose function
    declares an ``artifacts`` parameter, is re-invoked with the
    ``artifacts`` kwarg stripped and a
    :class:`~.artifacts.ReplayArtifacts` handle re-injected instead:
    reads are served from the run's manifest and ``out_dir()`` returns
    the ORIGINAL node directory, so a deterministic function rewrites
    identical content and the replayed result — returned pointers
    included — matches the recorded one.  Pass the run's
    :class:`~.artifacts.ArtifactStore` as ``artifacts``; a record that
    needs one when no store was given raises ``ValueError``.
    """
    reg = registry if registry is not None else DEFAULT_REGISTRY
    replayed: list[Any] = []
    for record in history.records:
        params = dict(record.params)
        params.pop("walk_context", None)
        fn = reg.get(record.name)
        # Registry drift check (IMP-010): the record stores the resolved
        # function's name, so a re-registration between run and replay (the
        # same registry name now resolving to a different callable) is
        # visible instead of silently diverging the replay.
        resolved_name = getattr(fn, "__name__", type(fn).__name__)
        if resolved_name != record.function:
            warnings.warn(
                f"replay: record {record.order} ({record.name!r}) resolves to "
                f"{resolved_name!r} but was recorded as {record.function!r}; "
                "the registry changed between run and replay",
                UserWarning,
                stacklevel=2,
            )
        if reg.adapts(record.name):
            # The engine injects the handle for a dag-declaring function
            # (the registry's cached flag, the same signal the engine used
            # at run time); replay re-injects a read-only stand-in.  A
            # record whose params still carry a ``dag`` kwarg (user data
            # under the reserved name) keeps it.
            params["dag"] = ReplayHandle(record.scope)
        if record.artifacts is not None and wants_artifacts(fn):
            params.pop("artifacts", None)
            if artifacts is None:
                raise ValueError(
                    f"replay: record {record.order} ({record.name!r}) was "
                    f"recorded with an artifact store; pass the run's "
                    f"ArtifactStore as artifacts= to replay it"
                )
            params["artifacts"] = ReplayArtifacts(artifacts, record.artifacts)
        replayed.append(recordable_result(fn(**params)))
    return replayed


def replay(
    history: RunHistory,
    registry: FunctionRegistry | None = None,
    artifacts: ArtifactStore | None = None,
) -> Any:
    """
    Replay a recorded run and return the same final result.

    Re-executes the recorded actions (see :func:`replay_records`) and
    returns the replayed value of the run's FINAL action — the action the
    engine marked in ``history.final_order`` — which is the value
    ``run_workflow`` / ``Test_Framework`` returned for the original run.
    Returns ``None`` for an empty workflow.  This proves reproducibility:
    the result is recomputed by re-running the recorded function calls,
    not echoed from the history.

    When the recorded run used an artifact store, pass it as
    ``artifacts`` so artifacts-declaring functions replay with a
    :class:`~.artifacts.ReplayArtifacts` handle (reads from the recorded
    manifest; writes re-derive the original node directory).
    """
    results = replay_records(history, registry, artifacts)
    if history.final_order is None:
        return None
    return results[history.final_order]


def _workflow_digest(
    xml_source: str | bytes | None = None, root: _Group | None = None
) -> str:
    """
    The run's workflow digest (sha256 hex): of the XML source when given
    (the ``run_workflow`` path), else of the root tree's repr (the
    ``Test_Framework`` path, where no XML exists — the repr of a tree built
    the same way is stable, so identical trees digest identically).
    """
    if xml_source is not None:
        data = (
            xml_source if isinstance(xml_source, bytes) else xml_source.encode("utf-8")
        )
    else:
        data = repr(root).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
