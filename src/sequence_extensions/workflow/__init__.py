"""
V&V workflow layer: node schema, function registry, and execution engine.

Built on top of the :mod:`sequence_extensions.graph` substrate.  The
semantics follow the paper "Automation Nation: Taming Complex V&V Workflows"
(16th International Modelica & FMI Conference, September 2025, Lucerne,
Switzerland; DOI 10.3384/ecp12076741).

Modules:

* :mod:`~sequence_extensions.workflow.schema` — ``Action`` / ``Sequential``
  / ``Parallel`` node classes, the ``Template`` reuse mechanism, and the XML
  parser (``parse_workflow``).
* :mod:`~sequence_extensions.workflow.registry` — ``FunctionRegistry`` and
  the empty ``DEFAULT_REGISTRY``, plus the ``workflow_function``
  registration decorator.
* :mod:`~sequence_extensions.workflow.params` — parameter normalization
  (XML string form -> Python form).
* :mod:`~sequence_extensions.workflow.engine` — the execution engine
  (``run_workflow`` / ``Test_Framework``) and the dynamic-adaptation scope
  check (``check_splice_scope``).
* :mod:`~sequence_extensions.workflow.adaptation` — the scoped DAG handle
  (``DAGHandle``) handed to functions that declare a ``dag`` parameter:
  scoped reads, validated write ops and the transactional commit protocol.
"""

from sequence_extensions.workflow.adaptation import ADAPTATION_BOUND, AdaptationOp, DAGHandle
from sequence_extensions.workflow.engine import (
    Test_Framework,
    check_splice_scope,
    run_workflow,
)
from sequence_extensions.workflow.registry import (
    DEFAULT_REGISTRY,
    FunctionRegistry,
    workflow_function,
)
from sequence_extensions.workflow.schema import (
    Action,
    Parallel,
    Sequential,
    Template,
    parse_workflow,
)

__all__ = [
    "ADAPTATION_BOUND",
    "DEFAULT_REGISTRY",
    "Action",
    "AdaptationOp",
    "DAGHandle",
    "FunctionRegistry",
    "Parallel",
    "Sequential",
    "Template",
    "Test_Framework",
    "check_splice_scope",
    "parse_workflow",
    "run_workflow",
    "workflow_function",
]
