"""sequence_extensions: higher-order function extensions for sequences."""

from sequence_extensions.ext import KeyValueTuple, dict_ext, gen_ext, list_ext
from sequence_extensions.graph import GraphFuture, GraphPool, graph_future
from sequence_extensions.workflow import (
    DEFAULT_REGISTRY,
    Action,
    FunctionRegistry,
    Parallel,
    Sequential,
    Test_Framework,
    parse_workflow,
    run_workflow,
    workflow_function,
)

__version__ = "0.2.0"

__all__ = [
    "DEFAULT_REGISTRY",
    "Action",
    "FunctionRegistry",
    "GraphFuture",
    "GraphPool",
    "KeyValueTuple",
    "Parallel",
    "Sequential",
    "Test_Framework",
    "dict_ext",
    "gen_ext",
    "graph_future",
    "list_ext",
    "parse_workflow",
    "run_workflow",
    "workflow_function",
]
