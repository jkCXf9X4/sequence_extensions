"""
Dynamic adaptation: the workflow's DAG handle policy over the generic
tree handle.

The paper (section 4.2) hands "the full DAG" to each action and merges the
modified DAG back "when returned".  This module implements that mechanism
in a deterministic, scoped form (the investigation's option 2, section
4.2 of ``docs/breakdown/06-evolution/investigation/dynamic_adaptation.md``):

* **Injection** — the engine passes a ``dag=`` keyword argument to a
  function only when the function's signature declares one (the registry
  caches the ``wants_dag`` flag at registration time).  ``dag`` is a
  reserved kwarg name for adapting functions: the injected handle wins
  over any same-named parameter.
* **Reads** — the handle exposes the action's OWN grouping scope: the
  following siblings and their whole subtrees (so an outer action can
  alter inner actions, the paper's Listing 7), and the preceding siblings
  (so an end-of-body check can copy them to the end, the paper's section 5
  iteration workaround).
* **Writes** — ``replace``, ``adjust``, ``copy`` and ``append`` are
  validated EAGERLY (scope rules, read-only parallel scopes, the
  dynamic-node bound) and recorded as plain data (:class:`AdaptationOp`).
  Functions never build nodes: ``dag.copy(target, **overrides)`` clones a
  declared subtree with parameter overrides, and the intent-level
  combinators (``fan_out`` / ``select`` / ``skip`` / ``skip_following`` /
  ``repeat``) cover the recurring driver patterns — map, branch, skip,
  skip-rest, copy-to-end iteration — each recording the same primitive
  ops the drivers used to record by hand.
* **Commit** — at function return, on the same thread, under ONE engine
  lock acquisition: the recorded ops are re-validated, applied as tree
  surgery, bounded, recorded on the action's ``ExecutionRecord`` and the
  inserted nodes are marked dynamic.  If the function raised, the op log
  is discarded — nothing is applied (atomic).

The manipulation flows themselves live in the generic
:class:`~sequence_extensions.graph.handle.TreeHandle` (see
:mod:`sequence_extensions.graph.handle`); this module supplies the
workflow's POLICY on top of them: the validation rules (an adaptable
target is a workflow node that has not started, inside the action's own
scope), the op recording (:class:`AdaptationOp` plus the dynamic-node
bound), the empty ``Sequential()`` skip sentinel, and ``adjust`` (the
parameter-retuning op, which is workflow-specific).

Parallel safety (finding F4): children of a ``Parallel`` scope get a
READ-ONLY handle — every write op raises ``ValueError`` — because inside a
parallel scope the sequential invariant ("every following position is
unwalked") does not hold: siblings may already be running.

Termination (decision D5): the engine counts dynamic nodes added; exceeding
the bound (default 10 000) raises a deterministic ``ValueError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

from sequence_extensions.graph.handle import TreeHandle

from .schema import Action, Parallel, Sequential

__all__ = [
    "ADAPTATION_BOUND",
    "AdaptationOp",
    "DAGHandle",
]

_Node = Union[Action, Sequential, Parallel]
_Group = Union[Sequential, Parallel]

#: The default dynamic-node bound (decision D5): a run may add at most this
#: many nodes through dynamic adaptation before the engine raises a
#: deterministic ``ValueError`` (a runaway adaptation terminates instead of
#: hanging).
ADAPTATION_BOUND = 10_000


# --------------------------------------------------------------------------- #
# The op descriptor (plain data)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AdaptationOp:
    """
    A validated dynamic-adaptation write, recorded as plain data.

    The handle never mutates the tree directly: each write op is validated
    eagerly and stored as an :class:`AdaptationOp`; the engine applies the
    recorded ops at commit time (function return, under the engine lock).
    If the function raises, the op log is discarded and nothing is applied.

    Fields:

    * ``kind`` — one of ``"replace"``, ``"adjust"``, ``"copy"``,
      ``"append"``.
    * ``target`` — the node the op acts on (``None`` for ``append``).
    * ``nodes`` — the replacement/inserted nodes (``replace`` / ``append``).
    * ``params`` — the parameter overrides (``adjust`` / ``copy``).
    """

    kind: str
    target: _Node | None = None
    nodes: tuple = ()
    params: dict[str, Any] = field(default_factory=dict)
    scope: _Group | None = None

    def describe(self) -> dict[str, Any]:
        """A plain, comparable descriptor of the op (for history records)."""
        return {
            "kind": self.kind,
            "target": _describe_target(self.target),
            "nodes": [_describe_target(node) for node in self.nodes],
            "params": dict(self.params),
        }


def _describe_target(node: _Node | None) -> Any:
    """A plain descriptor of a node: its kind, function name and params."""
    if node is None:
        return None
    if isinstance(node, Action):
        return {"kind": "action", "function": node.function, "params": dict(node.params)}
    kind = "sequential" if isinstance(node, Sequential) else "parallel"
    descriptor = {"kind": kind, "children": len(node.children)}
    # A named group's label is part of its declared identity — recorded
    # so the op descriptor names the branch it selected.
    if node.name is not None:
        descriptor["name"] = node.name
    return descriptor


# --------------------------------------------------------------------------- #
# The scoped handle (the workflow policy over the generic tree handle)
# --------------------------------------------------------------------------- #


class DAGHandle(TreeHandle):
    """
    A scoped, read-mostly view of the workflow tree handed to a function
    that declares a ``dag`` parameter.

    The handle is constructed by the engine for one action call.  It knows
    the action's parent group and the action's index in it, so the scope
    rules are structural rather than conventional:

    * ``following()`` — the siblings AFTER the action (and their whole
      subtrees): an outer action can alter inner actions (Listing 7).
    * ``preceding()`` — the siblings BEFORE the action: an end-of-body
      check can copy them to the end (the paper's section 5 iteration).
    * writes — only onto nodes that provably have not started: later
      siblings when the parent scope is sequential, the subtree of a
      following scope, and fresh appends at the scope end.

    The manipulation flows — scoped reads, the clone ops, the write
    primitives and the intent-level combinators — are inherited from
    :class:`~sequence_extensions.graph.handle.TreeHandle`; this class
    supplies the workflow's policy:

    * ``_check_writable`` — children of a ``Parallel`` scope get a
      READ-ONLY handle: every write op raises ``ValueError`` (finding F4 —
      inside a parallel scope the sequential invariant does not hold, so
      writes are designed out rather than negotiated).
    * ``_check_target`` — a target must be a workflow node that has not
      started (``_engine_executed``), inside the action's own scope.
    * ``_check_nodes`` — replacement nodes must be workflow nodes
      (``Action`` / ``Sequential`` / ``Parallel``).
    * ``_emit`` — writes are recorded as :class:`AdaptationOp` data and
      checked against the dynamic-node bound; the engine applies them at
      commit time (function return).  The handle is NOT thread-safe by
      itself: the engine serializes commits under its lock.
    * ``_empty_group`` — the skip sentinel is an empty ``Sequential()``.
    """

    def __init__(
        self,
        parent: _Group,
        index: int,
        *,
        read_only: bool = False,
        bound: int = ADAPTATION_BOUND,
    ) -> None:
        """
        Create a handle for the action at ``parent.children[index]``.

        ``read_only`` marks a parallel-scope child (all writes raise).
        ``bound`` is the remaining dynamic-node budget this handle's ops
        may consume; the engine applies the recorded ops at commit time.
        """
        super().__init__(parent, index, read_only=read_only)
        self._bound = bound
        self._ops: list[AdaptationOp] = []

    # ------------------------------------------------------------ #
    # The workflow policy (hooks over the generic flows)
    # ------------------------------------------------------------ #
    def _check_writable(self) -> None:
        """Reject writes on a read-only (parallel-scope) handle (F4)."""
        if self._read_only:
            raise ValueError(
                "dynamic adaptation: this action runs inside a parallel "
                "scope, whose handle is read-only; parallel siblings may "
                "already be executing, so the tree cannot be adapted here"
            )

    def _check_target(self, target: _Node, *, allow_preceding: bool) -> None:
        """
        Validate that ``target`` is inside this action's own scope.

        A writable target is a following sibling or a node inside a
        following sibling's subtree (every following position is unwalked
        while the action's function runs — the sequential invariant).  With
        ``allow_preceding`` (the copy-to-end iteration form) a preceding
        sibling is also acceptable as a COPY SOURCE: it is only read, never
        replaced.  Targets that already ran (``_engine_executed``) are
        rejected: an executed node is not adaptable.
        """
        if not isinstance(target, (Action, Sequential, Parallel)):
            raise ValueError(
                f"dynamic adaptation: target must be a workflow node, "
                f"got {type(target).__name__}"
            )
        if getattr(target, "_engine_executed", False):
            raise ValueError(
                "dynamic adaptation: target has already executed; only "
                "nodes that have not started may be adapted"
            )
        if not self._in_scope(target, allow_preceding=allow_preceding):
            raise ValueError(
                "dynamic adaptation: target is outside this action's grouping "
                "scope; an action may only adapt its following siblings and "
                "their subtrees (or copy preceding siblings to the scope end)"
            )

    def _check_nodes(self, nodes: Any) -> tuple[_Node, ...]:
        """Normalize and validate replacement/appended nodes."""
        if isinstance(nodes, (Action, Sequential, Parallel)):
            nodes = [nodes]
        if not isinstance(nodes, (list, tuple)):
            raise ValueError(
                "dynamic adaptation: nodes must be a workflow node or a "
                "list of them"
            )
        for node in nodes:
            if not isinstance(node, (Action, Sequential, Parallel)):
                raise ValueError(
                    "dynamic adaptation: nodes must be workflow nodes "
                    f"(Action/Sequential/Parallel), got {type(node).__name__}"
                )
        return tuple(nodes)

    def _empty_group(self) -> _Group:
        """The skip sentinel: an empty ``Sequential``."""
        return Sequential()

    def _emit(
        self,
        *,
        kind: str,
        target: _Node | None = None,
        nodes: tuple = (),
        params: dict[str, Any] | None = None,
        scope: _Group | None = None,
    ) -> None:
        """Record one write op as :class:`AdaptationOp` data."""
        op = AdaptationOp(
            kind,
            target=target,
            nodes=nodes,
            params=params if params is not None else {},
            scope=scope,
        )
        self._ops.append(op)
        added = sum(len(op.nodes) for op in self._ops)
        if added > self._bound:
            raise ValueError(
                f"dynamic adaptation: the dynamic-node bound ({self._bound}) "
                f"was exceeded; a runaway adaptation is terminated "
                f"deterministically instead of hanging"
            )

    # ------------------------------------------------------------ #
    # The parameter op (workflow-specific)
    # ------------------------------------------------------------ #
    def adjust(self, target: _Node, **params: Any) -> None:
        """
        Retune ``target``'s parameters in place at commit time.

        ``target`` must be an adaptable node in this action's scope; its
        ``params`` dict is updated with ``params`` (existing keys are
        overwritten, missing keys added).  This is the paper's "adjust
        existing downstream actions" capability.
        """
        self._check_writable()
        self._check_target(target, allow_preceding=False)
        if not params:
            raise ValueError("dynamic adaptation: adjust() needs at least one parameter")
        self._emit(kind="adjust", target=target, params=dict(params))

    # ------------------------------------------------------------ #
    # The op log (read by the engine at commit time)
    # ------------------------------------------------------------ #
    @property
    def ops(self) -> list[AdaptationOp]:
        """The recorded ops, in issue order (empty when nothing was written)."""
        return list(self._ops)
