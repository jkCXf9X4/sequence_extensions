"""sequence_extensions: higher-order function extensions for sequences."""

from sequence_extensions import graph_future
from sequence_extensions.dict_ext import KeyValueTuple, dict_ext
from sequence_extensions.gen_ext import gen_ext
from sequence_extensions.graph_future import GraphFuture, GraphPool
from sequence_extensions.list_ext import list_ext
from sequence_extensions.workflow_engine import (
    DEFAULT_REGISTRY,
    FunctionRegistry,
    Test_Framework,
    run_workflow,
)
from sequence_extensions.workflow_schema import Action, Parallel, Sequential, parse_workflow

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
]
