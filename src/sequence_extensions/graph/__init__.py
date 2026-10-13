"""
Dependency-graph layer: the thread-pool execution substrate.

``GraphFuture`` nodes form a DAG whose functions run on a bounded
``ThreadPoolExecutor`` once their dependencies complete; ``GraphPool``
drives the scheduling and evaluation of such a graph.  The flow layer
(:mod:`sequence_extensions.flow`) builds on this substrate unchanged.
"""

from sequence_extensions.graph.graph_future import GraphFuture, GraphPool

__all__ = [
    "GraphFuture",
    "GraphPool",
]
