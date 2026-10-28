"""Cancellation paths: submission and attempts after abandonment.

These tests drive the boundaries with events, never sleeps: the abandoned
body is released explicitly once the run has returned.
"""

from __future__ import annotations

import threading

import pytest

from sequence_extensions.flow import NodeTimeoutError, RunOptions, execute_flow, node
from sequence_extensions.flow._context import AttemptToken, RunContext, execution_scope
from sequence_extensions.graph import GraphPool


def test_submit_after_a_timed_out_attempt_is_rejected(tmp_path):
    """A body that outlives its attempt cannot schedule more work."""
    started = threading.Event()
    gate = threading.Event()
    caught = []
    done = threading.Event()

    @node
    def leaf():
        return 1

    @node(timeout=0.05)
    def root():
        started.set()
        gate.wait(5)
        try:
            leaf.submit()
        except BaseException as exc:  # noqa: BLE001 - asserted below
            caught.append(exc)
            done.set()

    with pytest.raises(NodeTimeoutError):
        execute_flow(root, options=RunOptions(log=tmp_path))

    assert started.wait(5), "root body never started"
    gate.set()
    assert done.wait(5), "abandoned body did not reach submit()"
    assert len(caught) == 1
    assert isinstance(caught[0], RuntimeError)
    assert "abandoned attempt" in str(caught[0])


def test_attempt_with_an_abandoned_parent_token_is_rejected():
    """A child attempt under an abandoned parent settles abandoned, not pending."""
    from sequence_extensions.flow._attempt import _AttemptRunner
    from sequence_extensions.flow._context import AttemptToken

    @node
    def leaf():
        return 1

    parent = AttemptToken()
    parent.abandoned.set()
    runner = _AttemptRunner(
        leaf,
        (),
        {},
        None,
        parent_token=parent,
        run_attempt_token=None,
        retries=0,
        delay=0.0,
        timeout=None,
    )

    with pytest.raises(RuntimeError, match="is abandoned"):
        runner.run().result()


def test_attempt_after_a_cancelled_run_is_rejected(tmp_path):
    """Run-level cancellation is visible before a node attempt starts."""
    started = threading.Event()
    gate = threading.Event()
    caught = []
    done = threading.Event()

    @node
    def leaf(x):
        return x

    @node
    def root():
        started.set()
        gate.wait(5)
        try:
            leaf(1)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            caught.append(exc)
            done.set()

    with pytest.raises(NodeTimeoutError):
        execute_flow(root, options=RunOptions(log=tmp_path, timeout=0.05))

    assert started.wait(5), "root body never started"
    gate.set()
    assert done.wait(5), "abandoned body did not reach the leaf call"
    assert len(caught) == 1
    assert isinstance(caught[0], RuntimeError)
    assert "run cancelled before node 'leaf' attempt 1" in str(caught[0])


def test_submit_on_a_cancelled_run_is_rejected():
    """A cancelled run rejects submission even when the attempt token is live."""
    pool = GraphPool(max_workers=1)
    ctx = RunContext(run_id="r", node_name="r", runlog=None, pool=pool, options=RunOptions())
    ctx.cancelled.set()

    @node
    def leaf():
        return 1

    with execution_scope(
        ctx=ctx,
        path=(),
        attempt=None,
        token=AttemptToken(),
        run_token=None,
        worker=False,
        process_worker=False,
    ):
        with pytest.raises(RuntimeError, match="cancelled run"):
            leaf.submit()
