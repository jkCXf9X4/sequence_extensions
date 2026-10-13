"""sequence_extensions: higher-order function extensions for sequences."""

from sequence_extensions.ext import KeyValueTuple, dict_ext, gen_ext, list_ext
from sequence_extensions.graph import (
    GraphFuture,
    GraphPool,
    graph_future,
)

__version__ = "1.0.0"

__all__ = [
    "GraphFuture",
    "GraphPool",
    "KeyValueTuple",
    "dict_ext",
    "gen_ext",
    "graph_future",
    "list_ext",
]
