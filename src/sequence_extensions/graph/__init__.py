"""
Dependency-graph layer: the thread-pool execution substrate.

``GraphFuture`` nodes form a DAG whose functions run on a bounded
``ThreadPoolExecutor`` once their dependencies complete; ``GraphPool``
drives the scheduling and evaluation of such a graph.  ``iter_postorder``
exposes the deterministic dependency walk (leaves first) that the pool's
bind uses and the flow layer's plan passes duplicate.  The flow layer
(:mod:`sequence_extensions.flow`) builds on this substrate unchanged.
"""

from sequence_extensions.graph.graph_future import (
    GraphFuture,
    GraphPool,
    is_dependency,
    iter_postorder,
)

__all__ = [
    "GraphFuture",
    "GraphPool",
    "is_dependency",
    "iter_postorder",
]
