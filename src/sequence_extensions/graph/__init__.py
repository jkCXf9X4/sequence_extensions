"""
Dependency-graph execution substrate: a small thread-pool future DAG.

Modules:

* :mod:`~sequence_extensions.graph.graph_future` — ``GraphFuture`` nodes
  form a DAG whose functions run on a bounded ``ThreadPoolExecutor`` once
  their dependencies complete; ``GraphPool`` drives the scheduling and
  evaluation of such a graph.
"""

from sequence_extensions.graph.graph_future import GraphFuture, GraphPool

__all__ = [
    "GraphFuture",
    "GraphPool",
]
