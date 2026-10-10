"""
Dynamic adaptation: the scoped DAG handle and its commit protocol.

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
  declared subtree with parameter overrides.
* **Commit** — at function return, on the same thread, under ONE engine
  lock acquisition: the recorded ops are re-validated, applied as tree
  surgery, bounded, recorded on the action's ``ExecutionRecord`` and the
  inserted nodes are marked dynamic.  If the function raised, the op log
  is discarded — nothing is applied (atomic).

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
    return {"kind": kind, "children": len(node.children)}


# --------------------------------------------------------------------------- #
# The scoped handle
# --------------------------------------------------------------------------- #


class DAGHandle:
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

    Children of a ``Parallel`` scope get a READ-ONLY handle: every write
    op raises ``ValueError`` (finding F4 — inside a parallel scope the
    sequential invariant does not hold, so writes are designed out rather
    than negotiated).

    Write ops are validated eagerly and recorded as :class:`AdaptationOp`
    data; the engine applies them at commit time (function return).  The
    handle is NOT thread-safe by itself: the engine serializes commits
    under its lock.
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
        self._parent = parent
        self._index = index
        self._read_only = read_only
        self._bound = bound
        self._ops: list[AdaptationOp] = []

    # ------------------------------------------------------------ #
    # Reads (served from the live tree)
    # ------------------------------------------------------------ #
    @property
    def scope(self) -> _Group:
        """The action's own grouping scope (its parent group)."""
        return self._parent

    @property
    def index(self) -> int:
        """The action's position in its parent's children list."""
        return self._index

    @property
    def read_only(self) -> bool:
        """True when the handle rejects writes (a parallel-scope child)."""
        return self._read_only

    def following(self) -> list[_Node]:
        """The siblings after this action, in order (outermost first)."""
        return list(self._parent.children[self._index + 1 :])

    def preceding(self) -> list[_Node]:
        """The siblings before this action, in order."""
        return list(self._parent.children[: self._index])

    def following_group(self) -> _Group:
        """
        The first following sibling, which must be a group.

        This is the declared downstream scope a driver action adapts (the
        paper's Listings 5 and 7: the driver is followed by the group it
        clones per file / per value).
        """
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
        for sibling in self._parent.children[self._index + 1 :]:
            if _contains(sibling, target):
                return
        if allow_preceding:
            for sibling in self._parent.children[: self._index]:
                if _contains(sibling, target):
                    return
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

    def _record(self, op: AdaptationOp) -> None:
        """Validate the running op count against the dynamic-node bound."""
        self._ops.append(op)
        added = sum(len(op.nodes) for op in self._ops)
        if added > self._bound:
            raise ValueError(
                f"dynamic adaptation: the dynamic-node bound ({self._bound}) "
                f"was exceeded; a runaway adaptation is terminated "
                f"deterministically instead of hanging"
            )

    # ------------------------------------------------------------ #
    # Write ops (validated eagerly, applied at commit)
    # ------------------------------------------------------------ #
    def replace(self, target: _Node, nodes: Any) -> None:
        """
        Replace ``target`` with ``nodes`` in the live tree at commit time.

        ``target`` must be a following sibling (or a node inside a following
        sibling's subtree) that has not started.  The replaced subtree never
        runs; the replacement nodes run in its place, and their results fan
        in downstream keyed by their OWN action names.
        """
        self._check_writable()
        self._check_target(target, allow_preceding=False)
        replacement = self._check_nodes(nodes)
        if not replacement:
            raise ValueError(
                "dynamic adaptation: replace() needs at least one node"
            )
        self._record(AdaptationOp("replace", target=target, nodes=replacement))

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
        self._record(AdaptationOp("adjust", target=target, params=dict(params)))

    def copy(self, target: _Node, **param_overrides: Any) -> _Node:
        """
        Clone ``target``'s subtree with parameter overrides.

        Returns the cloned node(s) — the caller then ``append``s or
        ``replace``s with them.  Functions never build nodes for iteration:
        they clone the DECLARED downstream scope once per file / per value
        (the paper's Listing 5).  ``param_overrides`` are applied to every
        ``Action`` in the clone (existing keys overwritten).
        """
        self._check_writable()
        self._check_target(target, allow_preceding=True)
        return _clone(target, param_overrides)

    def adjusted(self, **param_overrides: Any) -> _Node:
        """
        Clone the first following sibling with parameter overrides.

        Shorthand for ``dag.copy(dag.following()[0], **overrides)`` — the
        common "clone the declared downstream scope" form.
        """
        self._check_writable()
        return self.copy(self.following()[0], **param_overrides)

    def append(self, nodes: Any) -> None:
        """
        Append ``nodes`` at the END of this action's scope at commit time.

        This is the paper's section 5 iteration workaround ("copy the
        desired actions to the end when a condition is triggered"): each
        appended copy is a fresh node, so at-most-once holds and the
        workflow stays strictly downstream (a DAG).
        """
        self._check_writable()
        appended = self._check_nodes(nodes)
        if not appended:
            raise ValueError("dynamic adaptation: append() needs at least one node")
        self._record(
            AdaptationOp("append", nodes=appended, scope=self._parent)
        )

    # ------------------------------------------------------------ #
    # The op log (read by the engine at commit time)
    # ------------------------------------------------------------ #
    @property
    def ops(self) -> list[AdaptationOp]:
        """The recorded ops, in issue order (empty when nothing was written)."""
        return list(self._ops)


def _clone(node: _Node, overrides: dict[str, Any]) -> _Node:
    """
    Deep-clone ``node``'s subtree, applying parameter overrides to actions.

    Every ``Action`` in the clone gets a fresh ``params`` dict with
    ``overrides`` merged in (existing keys overwritten); groups are rebuilt
    with cloned children.  The clone carries no engine state, so it is a
    fresh, never-executed node.
    """
    if isinstance(node, Action):
        params = dict(node.params)
        params.update(overrides)
        return Action(node.function, **params)
    children = [_clone(child, overrides) for child in node.children]
    clone = Sequential(*children) if isinstance(node, Sequential) else Parallel(*children)
    clone.globals = dict(node.globals)
    return clone
    @staticmethod
    def _contains_any(node: _Node, targets: tuple[_Node, ...]) -> bool:
        """True when any target is ``node`` itself or inside its subtree."""
        return any(_contains(node, target) for target in targets)


def _contains(root: _Node, target: _Node) -> bool:
    """True when ``target`` is ``root`` itself or a node in its subtree."""
    if root is target:
        return True
    if isinstance(root, (Sequential, Parallel)):
        return any(_contains(child, target) for child in root.children)
    return False
