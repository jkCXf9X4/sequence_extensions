"""
flow — the mini flow engine: parallel, deterministic, audited.

``@node`` wraps a function with retry / backoff / timeout policy and a
``.submit()``; ``execute_flow(node, ...)`` opens a run — identity, a bounded
pool, and a JSON-lines audit log (the executed truth of a run).  Built
directly on :mod:`sequence_extensions.graph.graph_future` — futures passed
as submit arguments become dependency edges, so runs express general DAGs.

A node may return a value or a future.  Future-returning bodies fan out
without blocking; ``gather`` combines several futures into one.
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

from sequence_extensions.flow._context import RunContext, current_run
from sequence_extensions.flow._options import (
    DEFAULT_LOG_DIR,
    DEFAULT_MAX_WORKERS,
    UNSET,
    NodePolicy,
    RunOptions,
    validate_node_policy,
)
from sequence_extensions.flow.node import (
    FlowFuture,
    FlowOutcome,
    NodeFunction,
    NodeTimeoutError,
    gather,
    node,
)
from sequence_extensions.flow.process_pool import ProcessDispatchError, ProcessGraphPool
from sequence_extensions.flow.run import Run, execute_flow
from sequence_extensions.flow.runlog import DIFF_EXCLUDE, SCHEMA_VERSION, RunLog, jsonable

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
    "current_run",
    "execute_flow",
    "gather",
    "jsonable",
    "node",
    "validate_node_policy",
]
