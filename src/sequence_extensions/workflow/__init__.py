"""
V&V workflow layer: node schema, function registry, and execution engine.

Built on top of the :mod:`sequence_extensions.graph` substrate.  The
semantics follow the paper "Automation Nation: Taming Complex V&V Workflows"
(16th International Modelica & FMI Conference, September 2025, Lucerne,
Switzerland; DOI 10.3384/ecp12076741).

Modules:

* :mod:`~sequence_extensions.workflow.schema` — ``Action`` / ``Sequential``
  / ``Parallel`` node classes and the XML parser (``parse_workflow``).
* :mod:`~sequence_extensions.workflow.registry` — ``FunctionRegistry`` and
  the empty ``DEFAULT_REGISTRY``, plus the ``workflow_function``
  registration decorator.
* :mod:`~sequence_extensions.workflow.params` — parameter normalization
  (XML string form -> Python form).
* :mod:`~sequence_extensions.workflow.engine` — the execution engine
  (``run_workflow`` / ``Test_Framework``) and the dynamic-adaptation scope
  check (``check_splice_scope``).
"""

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
from sequence_extensions.workflow.schema import Action, Parallel, Sequential, parse_workflow

__all__ = [
    "DEFAULT_REGISTRY",
    "Action",
    "FunctionRegistry",
    "Parallel",
    "Sequential",
    "Test_Framework",
    "check_splice_scope",
    "parse_workflow",
    "run_workflow",
    "workflow_function",
]
