"""
flow — the mini flow engine: parallel, deterministic, audited.

``@task`` wraps a function with retry / backoff / timeout policy;
``@flow`` adds run identity, a bounded pool, and a JSON-lines audit log
(the executed truth of a run).  Built directly on
:mod:`sequence_extensions.graph.graph_future` — futures passed as submit
arguments become dependency edges, so flows express general DAGs.

Typical shape::

    from sequence_extensions.flow import flow, task

    @task(retries=2, retry_delay_seconds=0.1, timeout=30.0)
    def simulate(case): ...

    @flow
    def campaign(cases_dir):
        cases = discover(cases_dir)                    # plain call: sequential
        sims = [simulate.submit(c) for c in cases]     # concurrent map
        return aggregate([evaluate(s).result() ...])   # gather
"""

from sequence_extensions.flow._context import RunContext, current_run
from sequence_extensions.flow.flow import DEFAULT_LOG_DIR, flow
from sequence_extensions.flow.process_pool import ProcessDispatchError, ProcessGraphPool
from sequence_extensions.flow.runlog import SCHEMA_VERSION, RunLog, jsonable
from sequence_extensions.flow.task import TaskFunction, TaskTimeoutError, task

__all__ = [
    "DEFAULT_LOG_DIR",
    "ProcessDispatchError",
    "ProcessGraphPool",
    "RunContext",
    "RunLog",
    "SCHEMA_VERSION",
    "TaskFunction",
    "TaskTimeoutError",
    "current_run",
    "flow",
    "jsonable",
    "task",
]
