"""
flow — the mini flow engine: parallel, deterministic, audited.

``@node`` wraps a function with retry / backoff / timeout policy and a
``.submit()``; ``execute_flow(node, ...)`` opens a run — identity, a bounded
pool, and a JSON-lines audit log (the executed truth of a run).  Built
directly on :mod:`sequence_extensions.graph.graph_future` — futures passed
as submit arguments become dependency edges, so runs express general DAGs.

A node may return a value or a future.  Future-returning bodies fan out
without blocking; ``gather`` resolves the futures inside a value and keeps
its shape.
``execute_flow`` is the top-level boundary: it waits once, on the driver,
and materializes the result.

Typical shape::

    from sequence_extensions.flow import execute_flow, gather, node, RunOptions

    @node(retries=2, retry_delay_seconds=0.1, timeout=30.0)
    def simulate(case): ...

    @node
    def campaign(cases_dir):
        cases = discover(cases_dir)                    # plain call: sequential
        sims = [simulate.submit(c) for c in cases]     # concurrent map
        return merge.submit(gather(sims))              # no .result() wait

    run = execute_flow(campaign, cases_dir="cases")    # returns a Run
    run.result, run.run_id, run.status, run.log
"""

from ._config.context import RunContext, current_run
from ._config.options import (
    DEFAULT_LOG_DIR,
    DEFAULT_MAX_WORKERS,
    UNSET,
    NodePolicy,
    RunOptions,
    validate_node_policy,
)
from ._execution.futures import FlowFuture, FlowOutcome, NodeTimeoutError
from ._execution.gather import gather
from ._execution.node import NodeFunction, node
from ._execution.process_pool import ProcessDispatchError, ProcessGraphPool
from ._execution.run import Run, execute_flow
from ._planning.document import (
    apply_override,
    diff_plans,
    execute_plan,
    plan_document,
    plan_manifest,
)
from ._recording.runlog import DIFF_EXCLUDE, SCHEMA_VERSION, RunLog, jsonable

__all__ = [
    "DEFAULT_LOG_DIR",
    "DEFAULT_MAX_WORKERS",
    "DIFF_EXCLUDE",
    "FlowFuture",
    "FlowOutcome",
    "NodeFunction",
    "NodePolicy",
    "NodeTimeoutError",
    "ProcessDispatchError",
    "ProcessGraphPool",
    "Run",
    "RunContext",
    "RunLog",
    "RunOptions",
    "SCHEMA_VERSION",
    "UNSET",
    "apply_override",
    "current_run",
    "diff_plans",
    "execute_flow",
    "execute_plan",
    "gather",
    "jsonable",
    "node",
    "plan_document",
    "plan_manifest",
    "validate_node_policy",
]
