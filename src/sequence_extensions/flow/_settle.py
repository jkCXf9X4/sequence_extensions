"""The run's settle phase: drain every node, settle the pool, close records.

The run boundary (:mod:`sequence_extensions.flow.run`) owns identity,
execution, and retries; this module owns what happens once the root has
returned or failed — waiting for submitted work, cancelling the owned pool,
replaying process-worker records, and writing one skip record per node that
never executed.
"""

from __future__ import annotations

import concurrent.futures

from sequence_extensions.flow._context import RunContext
from sequence_extensions.flow._records import skipped_record
from sequence_extensions.flow.process_pool import ProcessDispatchError
from sequence_extensions.graph.graph_future import GraphPool


def settle(pool: GraphPool) -> None:
    """Cancel pending nodes and shut the executor down, waiting for running."""
    pool.__exit__(None, None, None)


def drain(ctx: RunContext) -> None:
    """Wait for every submitted node and deferred outcome.

    Outcomes are part of the drain because a returned future can settle
    after its GraphFuture is cancelled; waiting for the outcome guarantees
    the attempt record is in the log before ``run_end``.  Failures are
    swallowed here on purpose: every attempt is already in the audit log,
    and the exception surfaces through whichever future the caller
    gathers.  A cancelled node must not crash the return path.
    """
    seen_nodes = set()
    seen_outcomes = set()
    while True:
        pending_nodes = [node for node in ctx.nodes if node not in seen_nodes]
        pending_outcomes = [outcome for outcome in ctx.outcomes if outcome not in seen_outcomes]
        if not pending_nodes and not pending_outcomes:
            return
        for node in pending_nodes:
            seen_nodes.add(node)
            try:
                node.result()
            except Exception:
                pass
        for outcome in pending_outcomes:
            seen_outcomes.add(outcome)
            try:
                outcome.result()
            except Exception:
                pass


def failed_node_paths(ctx: RunContext) -> tuple[tuple[str, ...], ...]:
    """Paths of submitted nodes whose settled future carries an exception.

    This includes a fire-and-forget child the root never gathered: the log
    already records its error, and ``Run.failed_nodes`` makes it visible
    without changing the root verdict.
    """
    out = set()
    for node in ctx.nodes:
        if node.cancelled() or not node.done():
            continue
        try:
            exc = node.exception()
        except concurrent.futures.CancelledError:
            continue
        if exc is not None:
            out.add(tuple(node.path))
    return tuple(sorted(out))


def _write_skip(ctx: RunContext, node, *, reason: str, error=None) -> None:
    ctx.runlog.write(
        skipped_record(
            run_id=ctx.run_id,
            node=node.name,
            path=node.path,
            parent_attempt=node.parent_attempt,
            reason=reason,
            error=error,
        )
    )


def write_settle_records(ctx: RunContext, *, run_failed: bool) -> None:
    """Every settle-time record, written by the run thread before run_end.

    Replayed worker records first (process pools), then one skip record
    per node that never executed: cancelled by the run's failure, or
    failed because its dependency or process dispatch failed.  Never
    called from a done-callback — ``set_result`` wakes drain waiters
    before callbacks finish, so a callback-side write could race
    ``run_end`` closing the log.
    """
    if ctx.runlog is None:
        return
    for node in ctx.nodes:
        for record in node.process_records or ():
            ctx.runlog.write(record)
    for node in ctx.nodes:
        if node.attempted:
            continue
        if node.cancelled():
            if run_failed:
                _write_skip(ctx, node, reason="cancelled (run failed)")
            continue
        if not node.done():
            # A run-level timeout deliberately skips the drain.  A
            # caller-owned pool may still have pending nodes here; never
            # block on their exception just to write a settle record.
            if run_failed:
                _write_skip(ctx, node, reason="pending at run end")
            continue
        try:
            exc = node.exception()
        except concurrent.futures.CancelledError:
            continue
        if exc is None:
            continue
        _write_skip(
            ctx,
            node,
            reason=(
                "dispatch failed" if isinstance(exc, ProcessDispatchError) else "dependency failed"
            ),
            error=exc,
        )
