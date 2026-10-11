"""
Generic tree nodes: structure and identity-based tree operations.

This module is the structural substrate of the package: a :class:`Node`
is an ordered list of children plus an optional name, and a :class:`Group`
is the container specialization.  The module knows nothing about any
domain built on top of it (the workflow layer subclasses these classes):

* :class:`Node` — a tree node.  ``children`` is the ordered list of child
  nodes (the empty list for a leaf); ``name`` is an optional label that is
  part of a node's declared identity.
* :class:`Group` — a node whose children are its content (the container
  specialization).  Domain trees distinguish branch nodes from leaf nodes
  by subclassing :class:`Group`.

Operations:

* :meth:`Node.contains` — identity-based subtree containment.
* :meth:`Node.locate` — depth-first search for a node's (parent, index).
* :meth:`Node.clone` — deep copy.  ``overrides`` are passed through
  opaquely to the per-class :meth:`Node._copy` hook, so a domain decides
  what a copy carries (the generic layer only rebuilds the shape).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "Group",
    "Node",
]


class Node:
    """
    A tree node: an ordered list of children and an optional name.

    ``children`` is stored as a plain list (a copy of the constructor's
    arguments); a leaf node keeps it empty and never grows it.  ``name``
    is an optional label; it is part of a node's declared identity, so
    :meth:`clone` preserves it.
    """

    def __init__(self, *children: Node, name: str | None = None) -> None:
        """Create a node with the given children, in order, and a name."""
        self.children = list(children)
        self.name = name

    def __repr__(self) -> str:
        """One-liner with the node type and its children."""
        return f"{type(self).__name__}({self.children!r})"

    def contains(self, target: Node) -> bool:
        """
        True when ``target`` is this node or a node in its subtree.

        Containment is by IDENTITY (``is``), not equality: two equal-looking
        nodes are different tree positions.
        """
        if self is target:
            return True
        return any(child.contains(target) for child in self.children)

    def locate(self, target: Node) -> tuple[Node | None, int]:
        """
        Depth-first search for ``target``; return its ``(parent, index)``.

        Children are visited in order and each subtree fully before the
        next sibling, so the first match is the shallowest-leftmost one.
        Returns ``(None, -1)`` when ``target`` is not in this subtree
        (including when ``target`` is ``self`` — a root has no parent
        here).
        """
        for index, child in enumerate(self.children):
            if child is target:
                return self, index
            found_parent, found_index = child.locate(target)
            if found_parent is not None:
                return found_parent, found_index
        return None, -1

    def clone(self, /, **overrides: Any) -> Node:
        """
        Return a deep copy of this subtree.

        Every child is cloned first (recursively); the per-class
        :meth:`_copy` hook then rebuilds THIS node around the cloned
        children.  ``overrides`` are opaque to the generic layer — they
        travel down to every :meth:`_copy` call, and the domain decides
        what they mean (e.g. parameter overrides merged into every
        copied action).  No node object is shared with the original
        subtree.
        """
        children = [child.clone(**overrides) for child in self.children]
        return self._copy(children, overrides)

    def _copy(self, children: list[Node], overrides: dict[str, Any]) -> Node:
        """
        Rebuild this node around already-cloned ``children`` (the hook).

        The default reconstructs the same type with the same name and the
        cloned children.  Subclasses whose constructor or payload differs
        override this — ``overrides`` is whatever :meth:`clone` received.
        """
        return type(self)(*children, name=self.name)


class Group(Node):
    """
    A container node: its children are its content.

    Domains that distinguish branch nodes from leaf nodes subclass
    :class:`Group` for the branches (and plain :class:`Node` for the
    leaves), so "is a container" is a structural check
    (``isinstance(node, Group)``), not a convention.
    """
