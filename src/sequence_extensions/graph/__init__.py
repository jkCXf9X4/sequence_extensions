"""
Dependency-graph layer: generic nodes, scoped manipulation, and the
thread-pool execution substrate.

Modules:

* :mod:`~sequence_extensions.graph.node` — ``Node`` / ``Group``: the
  generic tree nodes (an ordered child list plus an optional name) with
  identity-based tree operations (containment, location, deep clone).
  Domain trees subclass these.
* :mod:`~sequence_extensions.graph.handle` — ``TreeHandle``: a scoped,
  read-mostly view over a node tree with the intent-level manipulation
  patterns (map / branch / skip / skip-rest / iterate).  Domain handles
  subclass it and supply validation, op recording and empty-group
  policy through small hooks.
* :mod:`~sequence_extensions.graph.graph_future` — ``GraphFuture`` nodes
  form a DAG whose functions run on a bounded ``ThreadPoolExecutor`` once
  their dependencies complete; ``GraphPool`` drives the scheduling and
  evaluation of such a graph.
"""

from sequence_extensions.graph.graph_future import GraphFuture, GraphPool
from sequence_extensions.graph.handle import TreeHandle
from sequence_extensions.graph.node import Group, Node

__all__ = [
    "GraphFuture",
    "GraphPool",
    "Group",
    "Node",
    "TreeHandle",
]
