"""
Execution history and deterministic replay for the V&V workflow layer.

The vision (docs/breakdown/00-intent/vision.md) requires that workflows are
"traceable and reproducible: the full history of verification activities is
preserved and results can be replayed".  The engine itself returns only the
final result; this module supplies the missing evidence layer:

* :class:`ExecutionRecord` — per-action evidence: the action's registry
  name, the resolved function, the parameters the function was ACTUALLY
  called with, its return value (or exception), start/end timestamps, a
  deterministic completion-order index, and the action's path in the
  workflow tree (e.g. ``root/parallel[1]/action[0]``).
* :class:`RunHistory` — a thread-safe collector the engine appends to as
  each action's function call completes.  Because records are added at
  call completion, the history captures what ACTUALLY executed — including
  actions spliced in at runtime by dynamic adaptation (marked
  ``dynamic=True``) — in true completion order.
* :func:`replay` / :func:`replay_records` — deterministic re-execution of
  a recorded run: every recorded action is re-resolved through the function
  registry and called again with its recorded parameters, sequentially, in
  recorded order.  :func:`replay` returns the same final result as the
  original run (the replayed value of the run's final action, which the
  engine marks on the history), proving reproducibility rather than
  echoing stored results.  A function that adapted through a ``dag``
  handle is re-invoked with the recorded ``dag`` kwarg stripped and a
  :class:`ReplayHandle` re-injected: reads are served from a fake tree
  materialized from the record's ``scope`` snapshot and write ops are
  no-ops, so replaying an adapting run is deterministic and never mutates
  the live tree.

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

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Union

from .registry import DEFAULT_REGISTRY, FunctionRegistry
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
      own parameters, merged in the engine's precedence order).
    * ``result`` — the function's return value; a dynamic-adaptation
      return (workflow node(s)) is stored as the plain descriptor produced
      by :func:`recordable_result`.  ``None`` when the function raised.
    * ``exception`` — the exception the function raised, if any.
    * ``started_at`` / ``ended_at`` — wall-clock timestamps
      (``time.time()``) taken around the function call.
    * ``order`` — deterministic completion-order index, assigned by
      :meth:`RunHistory.add` (records are numbered 0, 1, 2, ... in the
      order their function calls completed).
    * ``group_path`` — the action's path in the workflow tree at call
      completion, e.g. ``"root/parallel[1]/action[0]"``.
    * ``dynamic`` — ``True`` when the action was spliced into the workflow
      at runtime by dynamic adaptation.
    * ``adaptations`` — the committed dynamic-adaptation ops (plain
      descriptors; empty when the function adapted nothing).
    * ``scope`` — snapshot of the acting action's sibling list and index,
      recorded at handle injection (``None`` for non-adapting actions).
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
    """

    def __init__(self) -> None:
        """Create an empty history."""
        self._records: list[ExecutionRecord] = []
        self._lock = threading.Lock()
        self._next_order = 0
        # Order index of the run's final action; None until the engine
        # marks it (and for an empty or failed run).
        self.final_order: int | None = None

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
    placeholders = [Action(_REPLAY_PLACEHOLDER) for _ in range(count)]
    if kind == "parallel":
        return Parallel(*placeholders)
    return Sequential(*placeholders)


def _clone_node(node: _Node, overrides: dict[str, Any]) -> _Node:
    """
    Deep-clone a (fake) node, applying parameter overrides to its actions.

    Mirrors the engine's clone: every ``Action`` gets a fresh ``params``
    dict with ``overrides`` merged in; groups are rebuilt with cloned
    children.  Used by :meth:`ReplayHandle.copy` so an adapting function's
    clone-based logic runs against the materialized fake tree.
    """
    if isinstance(node, Action):
        params = dict(node.params)
        params.update(overrides)
        return Action(node.function, **params)
    children = [_clone_node(child, overrides) for child in node.children]
    clone = Sequential(*children) if isinstance(node, Sequential) else Parallel(*children)
    clone.globals = dict(node.globals)
    return clone


class ReplayHandle:
    """
    A read-only, no-op stand-in for :class:`~.adaptation.DAGHandle` in replay.

    When a recorded run's function declared a ``dag`` parameter, replay
    re-injects a :class:`ReplayHandle` (instead of a live handle) so the
    function re-executes deterministically:

    * **Reads** (``following`` / ``preceding`` / ``following_group`` and
      node traversal) are served from a FAKE tree materialized from the
      record's ``scope`` snapshot — the acting action's sibling list and
      index as they stood at injection.
    * **Write ops** (``replace`` / ``adjust`` / ``append``) are NO-OPS:
      they are recorded nowhere and applied nowhere, so replay never
      mutates the live tree and never diverges from the original run's
      committed structure.
    * **Clone ops** (``copy`` / ``adjusted``) are functional: they clone
      the materialized fake target, so an adapting function's clone-based
      logic runs (the clone is of the fake tree — the closest the snapshot
      allows).

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
        self._parent = Sequential(*siblings)
        self._index = index

    # ------------------------------------------------------------ #
    # Reads (served from the materialized fake tree)
    # ------------------------------------------------------------ #
    @property
    def scope(self) -> _Group:
        """The materialized fake grouping scope (the acting action's parent)."""
        return self._parent

    @property
    def index(self) -> int:
        """The acting action's recorded position in its parent's children."""
        return self._index

    @property
    def read_only(self) -> bool:
        """Always ``True`` in replay: writes are no-ops, never applied."""
        return True

    def following(self) -> list[_Node]:
        """The fake siblings after the acting action, in order."""
        return list(self._parent.children[self._index + 1 :])

    def preceding(self) -> list[_Node]:
        """The fake siblings before the acting action, in order."""
        return list(self._parent.children[: self._index])

    def following_group(self) -> _Group:
        """The first following fake sibling, which must be a group."""
        following = self.following()
        if not following:
            raise ValueError(
                "dynamic adaptation: no following sibling in this scope to adapt"
            )
        first = following[0]
        if not isinstance(first, (Sequential, Parallel)):
            raise ValueError(
                "dynamic adaptation: the first following sibling is an action, "
                "not a group; use dag.following() to read it or dag.replace() "
                "to substitute nodes for it"
            )
        return first

    # ------------------------------------------------------------ #
    # Clone ops (functional: clone the materialized fake target)
    # ------------------------------------------------------------ #
    def copy(self, target: _Node, **param_overrides: Any) -> _Node:
        """Clone the (fake) ``target`` subtree with parameter overrides."""
        return _clone_node(target, param_overrides)

    def adjusted(self, **param_overrides: Any) -> _Node:
        """Clone the first following fake sibling with parameter overrides."""
        return self.copy(self.following()[0], **param_overrides)

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


# --------------------------------------------------------------------------- #
# Deterministic replay
# --------------------------------------------------------------------------- #


def replay_records(
    history: RunHistory,
    registry: FunctionRegistry | None = None,
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
    """
    reg = registry if registry is not None else DEFAULT_REGISTRY
    replayed: list[Any] = []
    for record in history.records:
        params = dict(record.params)
        if "dag" in params:
            params.pop("dag")
            params["dag"] = ReplayHandle(record.scope)
        replayed.append(recordable_result(reg.get(record.name)(**params)))
    return replayed


def replay(history: RunHistory, registry: FunctionRegistry | None = None) -> Any:
    """
    Replay a recorded run and return the same final result.

    Re-executes the recorded actions (see :func:`replay_records`) and
    returns the replayed value of the run's FINAL action — the action the
    engine marked in ``history.final_order`` — which is the value
    ``run_workflow`` / ``Test_Framework`` returned for the original run.
    Returns ``None`` for an empty workflow.  This proves reproducibility:
    the result is recomputed by re-running the recorded function calls,
    not echoed from the history.
    """
    results = replay_records(history, registry)
    if history.final_order is None:
        return None
    return results[history.final_order]
