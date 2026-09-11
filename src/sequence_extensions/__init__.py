"""sequence_extensions: higher-order function extensions for sequences."""

from sequence_extensions import graph_future
from sequence_extensions.dict_ext import KeyValueTuple, dict_ext
from sequence_extensions.gen_ext import gen_ext
from sequence_extensions.graph_future import GraphFuture, GraphPool
from sequence_extensions.list_ext import list_ext

__version__ = "0.2.0"

__all__ = [
    "GraphFuture",
    "GraphPool",
    "KeyValueTuple",
    "dict_ext",
    "gen_ext",
    "graph_future",
    "list_ext",
]
