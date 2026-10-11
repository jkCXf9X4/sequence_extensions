"""
A scoped handle over a node tree, with intent-level manipulation patterns.

This module is the generic manipulation surface of the package: given a
scope (a parent :class:`~sequence_extensions.graph.node.Group` and a
position in it), :class:`TreeHandle` offers scoped reads, clone ops,
write primitives and the recurring manipulation patterns — map
(:meth:`~TreeHandle.fan_out`), branch (:meth:`~TreeHandle.select`),
skip (:meth:`~TreeHandle.skip`), skip-rest
(:meth:`~TreeHandle.skip_following`) and iterate
(:meth:`~TreeHandle.repeat`).  It knows nothing about any domain built
on top of it: the domain supplies its policy through small hooks:

* :meth:`TreeHandle._emit` — record one write op.  The generic layer
  never mutates anything itself; a domain subclass turns the emitted
  writes into its own op log / commit protocol (or into no-ops).
* :meth:`TreeHandle._check_writable` — the write-permission rule.
* :meth:`TreeHandle._check_target` — which nodes a write may act on.
* :meth:`TreeHandle._check_nodes` — what counts as a valid node.
* :meth:`TreeHandle._empty_group` — the empty group substituted for a
  skipped scope.

The workflow layer's :class:`~sequence_extensions.workflow.adaptation.DAGHandle`
(dynamic adaptation) and
:class:`~sequence_extensions.workflow.history.ReplayHandle`
(deterministic replay) are both thin subclasses of this class: they
share the manipulation flows by construction instead of mirroring
them by hand.
"""

from __future__ import annotations

from typing import Any

from sequence_extensions.graph.node import Group, Node

__all__ = ["TreeHandle"]


class TreeHandle:
    """
    A scoped, read-mostly view of a node tree.

    The handle is constructed for one position: the node at
    ``parent.children[index]`` (the *acting node*).  The scope rules are
    structural rather than conventional:

    * ``following()`` — the siblings AFTER the acting node (and their
      whole subtrees): the positions a write may act on, because they
      have not been reached yet.
    * ``preceding()`` — the siblings BEFORE the acting node: readable,
      and usable as a COPY SOURCE (the copy-to-end iteration form).
    * writes — through the :meth:`_emit` hook, so the domain owns
      validation, recording and application.

    A ``read_only`` handle rejects writes in :meth:`_check_writable`
    (the generic rule; a domain subclass may replace it with its own —
    or silence it, when writes are no-ops by design).
    """

    def __init__(self, parent: Group, index: int, *, read_only: bool = False) -> None:
        """
        Create a handle for the node at ``parent.children[index]``.

        ``read_only`` marks a scope whose writes are rejected (the
        generic rule: the scope's siblings may be running concurrently,
        so the tree cannot be adapted there).
        """
        self._parent = parent
        self._index = index
        self._read_only = read_only

    # ------------------------------------------------------------ #
    # Reads (served from the live tree)
    # ------------------------------------------------------------ #
    @property
    def scope(self) -> Group:
        """The acting node's own grouping scope (its parent group)."""
        return self._parent

    @property
    def index(self) -> int:
        """The acting node's position in its parent's children list."""
        return self._index

    @property
    def read_only(self) -> bool:
        """True when this handle rejects writes (see ``_check_writable``)."""
        return self._read_only

    def following(self) -> list[Node]:
        """The siblings after the acting node, in order (outermost first)."""
        return list(self._parent.children[self._index + 1 :])

    def preceding(self) -> list[Node]:
        """The siblings before the acting node, in order."""
        return list(self._parent.children[: self._index])

    def following_group(self) -> Group:
        """
        The first following sibling, which must be a group.

        This is the declared downstream scope a driver node adapts: the
        group that is cloned once per item, branched over, or skipped.
        """
        following = self.following()
        if not following:
            raise ValueError(
                "no following sibling in this scope to adapt; the acting "
                "node must be followed by the group it adapts"
            )
        first = following[0]
        if not isinstance(first, Group):
            raise ValueError(
                "the first following sibling is not a group; use "
                "following() to read it or replace() to substitute "
                "nodes for it"
            )
        return first

    # ------------------------------------------------------------ #
    # Validation (generic rules; domain subclasses override)
    # ------------------------------------------------------------ #
    def _in_scope(self, target: Node, *, allow_preceding: bool) -> bool:
        """
        True when ``target`` is a following sibling or in one's subtree.

        With ``allow_preceding`` (the copy-to-end iteration form) a
        preceding sibling is also acceptable as a COPY SOURCE: it is
        only read, never replaced.  Containment is by identity.
        """
        for sibling in self._parent.children[self._index + 1 :]:
            if sibling.contains(target):
                return True
        if allow_preceding:
            for sibling in self._parent.children[: self._index]:
                if sibling.contains(target):
                    return True
        return False

    def _check_writable(self) -> None:
        """Reject writes on a read-only handle (the generic rule)."""
        if self._read_only:
            raise ValueError(
                "this handle is read-only; the scope's siblings may be "
                "running concurrently, so the tree cannot be adapted here"
            )

    def _check_target(self, target: Node, *, allow_preceding: bool) -> None:
        """
        Validate that ``target`` is a node inside the acting node's scope.

        A writable target is a following sibling or a node inside a
        following sibling's subtree; with ``allow_preceding`` a preceding
        sibling is also acceptable as a copy source.
        """
        if not isinstance(target, Node):
            raise ValueError(f"target must be a node, got {type(target).__name__}")
        if not self._in_scope(target, allow_preceding=allow_preceding):
            raise ValueError(
                "target is outside this handle's scope; only following "
                "siblings and their subtrees are adaptable (preceding "
                "siblings only as a copy source)"
            )

    def _check_nodes(self, nodes: Any) -> tuple[Node, ...]:
        """Normalize and validate replacement/appended nodes."""
        if isinstance(nodes, Node):
            nodes = [nodes]
        if not isinstance(nodes, (list, tuple)):
            raise ValueError("nodes must be a node or a list of them")
        for node in nodes:
            if not isinstance(node, Node):
                raise ValueError(f"nodes must be nodes, got {type(node).__name__}")
        return tuple(nodes)

    # ------------------------------------------------------------ #
    # Hooks (the domain policy)
    # ------------------------------------------------------------ #
    def _emit(
        self,
        *,
        kind: str,
        target: Node | None = None,
        nodes: tuple = (),
        params: dict[str, Any] | None = None,
        scope: Group | None = None,
    ) -> None:
        """
        Record one write op (the hook; a domain subclass implements it).

        ``kind`` names the structural edit (``"replace"`` / ``"append"``;
        a domain may add its own kinds), ``target`` the node acted on,
        ``nodes`` the replacement/inserted nodes, ``params`` any payload
        the domain attaches, and ``scope`` the group an append extends.
        The generic layer calls this INSTEAD of mutating anything, so
        the domain owns validation, recording and application.
        """
        raise NotImplementedError("a TreeHandle subclass must implement _emit to record writes")

    def _empty_group(self) -> Group:
        """
        The empty group substituted for a skipped scope (the hook).

        The generic default is a plain
        :class:`~sequence_extensions.graph.node.Group`; a domain whose
        groups carry semantics substitutes its own empty group.
        """
        return Group()

    # ------------------------------------------------------------ #
    # Write ops (validated eagerly, emitted through the hook)
    # ------------------------------------------------------------ #
    def replace(self, target: Node, nodes: Any) -> None:
        """
        Replace ``target`` with ``nodes`` (emitted as a ``"replace"`` op).

        ``target`` must be a following sibling (or a node inside a
        following sibling's subtree).  What replacement means at
        application time is the domain's commit protocol's business.
        """
        self._check_writable()
        self._check_target(target, allow_preceding=False)
        replacement = self._check_nodes(nodes)
        if not replacement:
            raise ValueError("replace() needs at least one node")
        self._emit(kind="replace", target=target, nodes=replacement)

    def append(self, nodes: Any) -> None:
        """
        Append ``nodes`` at the END of the acting node's scope.

        Emitted as an ``"append"`` op carrying the scope group: the
        copy-to-end iteration form — each appended copy is a fresh node,
        so nothing runs twice.
        """
        self._check_writable()
        appended = self._check_nodes(nodes)
        if not appended:
            raise ValueError("append() needs at least one node")
        self._emit(kind="append", nodes=appended, scope=self._parent)

    # ------------------------------------------------------------ #
    # Clone ops (functional: return the clone)
    # ------------------------------------------------------------ #
    def copy(self, target: Node, **overrides: Any) -> Node:
        """
        Clone ``target``'s subtree with overrides.

        Returns the cloned node — the caller then ``append``s or
        ``replace``s with it.  ``overrides`` are passed through to the
        per-class copy hook opaquely; the domain decides what they mean
        (e.g. parameter overrides merged into every copied action).
        """
        self._check_writable()
        self._check_target(target, allow_preceding=True)
        return target.clone(**overrides)

    def adjusted(self, **overrides: Any) -> Node:
        """
        Clone the first following sibling with overrides.

        Shorthand for ``copy(following()[0], **overrides)`` — the common
        "clone the declared downstream scope" form.
        """
        self._check_writable()
        return self.copy(self.following()[0], **overrides)

    def copy_self(self, **overrides: Any) -> Node:
        """
        Clone the ACTING NODE itself with overrides.

        The copy-to-end iteration form needs a fresh copy of the acting
        node alongside the body copies, so the check re-arms at the end
        of the scope.  The clone carries no runtime state, so it is a
        fresh, never-executed node.
        """
        self._check_writable()
        return self._parent.children[self._index].clone(**overrides)

    # ------------------------------------------------------------ #
    # Intent-level patterns (sugar over the write ops)
    # ------------------------------------------------------------ #
    def fan_out(self, overrides: Any) -> None:
        """
        Clone the declared downstream scope once per override set and
        replace it with the clones (the MAP pattern).

        ``overrides`` is a non-empty iterable of mappings; each mapping
        is the overrides for one clone.  The clones run in place of the
        declared scope, in iterable order.  An empty iterable raises
        ``ValueError`` — "run nothing" is not a map; a driver that wants
        the declared scope to run once when its collection is empty
        keeps its own ``if`` guard.
        """
        self._check_writable()
        items = list(overrides)
        if not items:
            raise ValueError(
                "fan_out() needs at least one override set (an empty map is not a body)"
            )
        body = self.following_group()
        clones = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"fan_out() overrides must be mappings, got {type(item).__name__}")
            clones.append(self.copy(body, **item))
        self.replace(body, clones)

    def select(self, name: Any, default: Any = None) -> Node:
        """
        Pick the named child of the declared downstream group and replace
        the group with it (the BRANCH pattern).

        The alternatives scope's children are the named branches (each
        a NAMED group — the node's optional ``name`` label; unnamed
        children are not alternatives).  The child whose name equals
        ``name`` is moved into place of the scope, so the unselected
        alternatives never run.  When no child matches, the ``default``
        child is used; when there is no default (or it matches no child
        either), a ``ValueError`` is raised.  Returns the chosen child.
        """
        self._check_writable()
        group = self.following_group()
        named = [child for child in group.children if getattr(child, "name", None)]
        names = [child.name for child in named]
        if name in names:
            chosen = next(child for child in named if child.name == name)
        elif default is not None:
            if default in names:
                chosen = next(child for child in named if child.name == default)
            else:
                raise ValueError(
                    f"select() default {default!r} is not a named child of "
                    f"the alternatives scope (named alternatives: {names})"
                )
        else:
            raise ValueError(
                f"no alternative named {name!r} in the alternatives scope "
                f"(named alternatives: {names}) and no default alternative "
                f"was given"
            )
        self.replace(group, [chosen])
        return chosen

    def skip(self) -> None:
        """
        Replace the declared downstream scope with an empty group (the
        SKIP pattern): the body never runs, and the group's result is an
        empty list.
        """
        self.replace(self.following_group(), [self._empty_group()])

    def skip_following(self) -> None:
        """
        Replace every following sibling with an empty group (the
        SKIP-REST pattern, first-success): the rest of the scope never
        runs.
        """
        for node in self.following():
            self.replace(node, self._empty_group())

    def repeat(self, **overrides: Any) -> None:
        """
        Append a copy of the preceding body plus a fresh copy of the
        acting node itself at the scope end (the ITERATE pattern, the
        copy-to-end workaround).

        ``overrides`` are applied to every copied node (the domain
        decides what that means — e.g. parameter overrides computed from
        the latest upstream result).  Every appended copy is a fresh
        node, so nothing runs twice and the workflow stays strictly
        downstream (a DAG).

        Raises ``ValueError`` when the acting node has no preceding
        siblings — it must be preceded by the iteration body in its
        scope.
        """
        self._check_writable()
        body = self.preceding()
        if not body:
            raise ValueError(
                "repeat() has no body to repeat; the acting node must be "
                "preceded by the iteration body in its scope"
            )
        copies = [self.copy(node, **overrides) for node in body]
        copies.append(self.copy_self(**overrides))
        self._emit(kind="append", nodes=tuple(copies), scope=self._parent)
