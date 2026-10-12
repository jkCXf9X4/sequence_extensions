"""
Tests for the per-action timeout (finding 3d): ``run_workflow`` /
``Test_Framework`` option ``action_timeout`` and ``ActionTimeoutError``.

A hung simulator action must not deadlock an unattended campaign: with
``action_timeout`` set, an action whose function call outlives the budget
raises a contextual error naming the action, the timeout and the option;
with the default (``None``) the wait is unbounded and nothing changes.

NOTE — these are the suite's only wall-clock tests: the feature IS a
wall-clock bound, so each test sleeps for a fraction of a second and
asserts error type and message content, never exact timings.  The "hung"
functions block on a release event the test sets on teardown, so the
worker threads a timed-out run abandons exit promptly (the suite's
determinism and speed conventions are otherwise preserved).
"""

import threading
import time

import pytest

from sequence_extensions import (
    Action,
    FunctionRegistry,
    Parallel,
    Sequential,
    Test_Framework,
    run_workflow,
)
from sequence_extensions.workflow.engine import ActionTimeoutError


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _Hung:
    """
    A hung-simulator stand-in: blocks until released (or ``duration`` passes).

    Used as a context manager so the abandoned worker is ALWAYS released on
    teardown — a timed-out run abandons its worker thread (threads cannot
    be killed), and releasing it keeps the test process fast.
    """

    def __init__(self, name="sleepy", duration=30.0):
        self.name = name
        self.duration = duration
        self.release = threading.Event()
        self.registry = FunctionRegistry()
        self.registry.register(name, self._hung_function)

    def _hung_function(self, **kwargs):
        """Block until released (or ``duration`` passes); a hung simulator."""
        self.release.wait(self.duration)
        return self.name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        # Always release the abandoned worker (threads cannot be killed).
        self.release.set()
        return False

    def __exit__(self, *_exc):
        self.release.set()
        return False

    def stub(self, name, fn):
        """Register one more (healthy) function under this registry."""
        self.registry.register(name, fn)
        return self


def _quick_registry(*names):
    """A registry of instant recording stubs sharing one call log."""
    calls = []
    lock = threading.Lock()

    def make(name):
        def stub(**kwargs):
            with lock:
                calls.append(name)
            return name

        stub.__name__ = name
        return stub

    registry = FunctionRegistry()
    for name in names:
        registry.register(name, make(name))
    return registry, calls


# --------------------------------------------------------------------------- #
# The timeout fires: type, message, promptness
# --------------------------------------------------------------------------- #


def test_hung_action_raises_action_timeout_error():
    """A sleeping action with a short timeout raises ActionTimeoutError promptly."""
    with _Hung() as hung:
        xml = '<sequential><action function="sleepy"/></sequential>'
        started = time.monotonic()
        with pytest.raises(ActionTimeoutError) as excinfo:
            run_workflow(xml, registry=hung.registry, action_timeout=0.25)
        elapsed = time.monotonic() - started
        # Prompt: bounded by the timeout plus teardown slack, NOT the hang.
        assert elapsed < 5.0
        # The error is a TimeoutError subclass (catchable as TimeoutError).
        assert isinstance(excinfo.value, TimeoutError)
        # The message names the action, the timeout and the option.
        message = str(excinfo.value)
        assert "sleepy" in message
        assert "0.25" in message
        assert "action_timeout" in message
        assert "per-action" in message


def test_timeout_error_is_catchable_as_builtin_timeout_error():
    """ActionTimeoutError subclasses the builtin TimeoutError."""
    with _Hung() as hung:
        xml = '<sequential><action function="sleepy"/></sequential>'
        with pytest.raises(TimeoutError):  # the builtin, not just the subclass
            run_workflow(xml, registry=hung.registry, action_timeout=0.2)


def test_timeout_names_the_hung_action_in_a_sequence():
    """The error names the action that hung, not a sibling or the group."""
    quick, calls = _quick_registry("quick")
    with _Hung() as hung:
        hung.stub("quick", quick.get("quick"))
        xml = (
            "<sequential>"
            '<action function="quick"/>'
            '<action function="sleepy"/>'
            "</sequential>"
        )
        with pytest.raises(ActionTimeoutError, match="sleepy"):
            run_workflow(xml, registry=hung.registry, action_timeout=0.25)
    # The action before the hung one ran and completed.
    assert calls == ["quick"]


# --------------------------------------------------------------------------- #
# Default None: behavior unchanged
# --------------------------------------------------------------------------- #


def test_default_none_leaves_behavior_unchanged():
    """Without action_timeout a long sleep completes (the historical behavior)."""
    with _Hung(duration=0.5) as hung:
        xml = '<sequential><action function="sleepy"/></sequential>'
        started = time.monotonic()
        result = run_workflow(xml, registry=hung.registry)  # no action_timeout
        assert result == "sleepy"
        assert time.monotonic() - started >= 0.5  # the sleep really ran


def test_explicit_none_matches_the_default():
    """action_timeout=None is the same as omitting it."""
    with _Hung(duration=0.3) as hung:
        xml = '<sequential><action function="sleepy"/></sequential>'
        assert run_workflow(xml, registry=hung.registry, action_timeout=None) == "sleepy"


def test_a_run_after_a_timed_out_run_is_unaffected():
    """A timed-out run leaves nothing behind: the next run behaves normally."""
    with _Hung(duration=0.4) as hung:
        xml = '<sequential><action function="sleepy"/></sequential>'
        # First a run WITH a timeout that fires (the worker is abandoned)...
        with pytest.raises(ActionTimeoutError):
            run_workflow(xml, registry=hung.registry, action_timeout=0.05)
        # ...then a normal run: the engine's state is per-run, nothing sticks.
        assert run_workflow(xml, registry=hung.registry) == "sleepy"


# --------------------------------------------------------------------------- #
# Composition with a parallel scope
# --------------------------------------------------------------------------- #


def test_timeout_composes_with_parallel_scope():
    """A hung action inside <parallel> times out and fails the run."""
    quick, calls = _quick_registry("quick_a", "quick_b")
    with _Hung() as hung:
        hung.stub("quick_a", quick.get("quick_a"))
        hung.stub("quick_b", quick.get("quick_b"))
        xml = (
            "<parallel>"
            '<action function="quick_a"/>'
            '<action function="sleepy"/>'
            '<action function="quick_b"/>'
            "</parallel>"
        )
        started = time.monotonic()
        with pytest.raises(ActionTimeoutError) as excinfo:
            run_workflow(xml, registry=hung.registry, action_timeout=0.25)
        assert time.monotonic() - started < 5.0  # prompt, not the hang
        assert "sleepy" in str(excinfo.value)
    # The healthy siblings ran (concurrently with the hung one).
    assert set(calls) == {"quick_a", "quick_b"}


def test_parallel_group_without_hung_action_completes_under_timeout():
    """A parallel group of fast actions completes with a timeout set."""
    registry, calls = _quick_registry("a", "b", "c")
    xml = (
        "<parallel>"
        '<action function="a"/>'
        '<action function="b"/>'
        '<action function="c"/>'
        "</parallel>"
    )
    result = run_workflow(xml, registry=registry, action_timeout=5.0)
    assert sorted(calls) == ["a", "b", "c"]
    assert result is not None


def test_timeout_in_nested_parallel_branch():
    """A hung action nested in a group child of a parallel scope times out."""
    quick, calls = _quick_registry("ok")
    with _Hung() as hung:
        hung.stub("ok", quick.get("ok"))
        xml = (
            "<parallel>"
            "<sequential>"
            '<action function="ok"/>'
            "</sequential>"
            "<sequential>"
            '<action function="sleepy"/>'
            "</sequential>"
            "</parallel>"
        )
        with pytest.raises(ActionTimeoutError, match="sleepy"):
            run_workflow(xml, registry=hung.registry, action_timeout=0.25)
    assert calls == ["ok"]


# --------------------------------------------------------------------------- #
# Python API parity (Test_Framework)
# --------------------------------------------------------------------------- #


def test_python_api_supports_action_timeout():
    """Test_Framework accepts action_timeout and raises the same error."""
    with _Hung() as hung:
        seq = Sequential(Action("sleepy"))
        with pytest.raises(ActionTimeoutError) as excinfo:
            Test_Framework(seq, registry=hung.registry, action_timeout=0.25)
        assert "sleepy" in str(excinfo.value)


def test_python_api_default_none_completes():
    """Test_Framework without action_timeout completes a slow action."""
    with _Hung(duration=0.3) as hung:
        seq = Sequential(Action("sleepy"))
        assert Test_Framework(seq, registry=hung.registry) == "sleepy"


# --------------------------------------------------------------------------- #
# Validation and semantics
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [0, -1, -0.5])
def test_non_positive_timeout_is_rejected(bad):
    """A non-positive action_timeout raises ValueError before anything runs."""
    with _Hung(duration=0.0) as hung:
        xml = '<sequential><action function="sleepy"/></sequential>'
        with pytest.raises(ValueError, match="action_timeout"):
            run_workflow(xml, registry=hung.registry, action_timeout=bad)


def test_timeout_composes_with_history():
    """A timed-out run still records the actions that completed."""
    from sequence_extensions.workflow.history import RunHistory

    quick, calls = _quick_registry("quick")
    with _Hung() as hung:
        hung.stub("quick", quick.get("quick"))
        xml = (
            "<sequential>"
            '<action function="quick"/>'
            '<action function="sleepy"/>'
            "</sequential>"
        )
        history = RunHistory()
        with pytest.raises(ActionTimeoutError):
            run_workflow(
                xml, registry=hung.registry, history=history, action_timeout=0.25
            )
        names = [record.name for record in history.records]
    assert "quick" in names  # the completed action is recorded
    assert "sleepy" not in names  # the hung one never completed


def test_caller_owned_executor_is_not_shut_down_by_a_timeout():
    """A caller-owned executor survives a timed-out run (caller keeps ownership)."""
    from sequence_extensions.graph import GraphFuture, GraphPool

    with _Hung() as hung:
        xml = '<sequential><action function="sleepy"/></sequential>'
        pool = GraphPool(max_workers=2)
        try:
            with pytest.raises(ActionTimeoutError):
                run_workflow(
                    xml, registry=hung.registry, executor=pool, action_timeout=0.25
                )
            # The caller's pool is still usable for a fresh graph (one worker
            # is still inside the hung call; the other serves the probe).
            probe = GraphFuture(lambda: "alive")
            assert pool.result(probe) == "alive"
        finally:
            # Release the abandoned worker BEFORE the pool's blocking exit:
            # GraphPool.__exit__ waits for running workers, and the hung
            # call only returns once released (caller-owned teardown order
            # is the caller's responsibility — the engine never touches it).
            hung.release.set()
            pool.__exit__(None, None, None)


def test_budget_measured_from_call_start_not_submission():
    """A queued action keeps its full budget (measured from call start)."""
    # One worker, two slow actions in a parallel group, then a fast one: the
    # second slow action QUEUES behind the first, and the fast action waits
    # for the group.  A submission-based budget would consume the queued
    # action's budget while it waited; a call-start budget does not.
    def slow(**kwargs):
        time.sleep(0.4)
        return "slow"

    def fast(**kwargs):
        return "fast"

    slow.__name__ = "slow"
    fast.__name__ = "fast"
    registry = FunctionRegistry()
    registry.register("slow", slow)
    registry.register("fast", fast)
    xml = (
        "<sequential>"
        "<parallel>"
        '<action function="slow"/>'
        '<action function="slow"/>'
        "</parallel>"
        '<action function="fast"/>'
        "</sequential>"
    )
    # Timeline on one worker: slow#1 runs 0.0-0.4 s, slow#2 (queued) runs
    # 0.4-0.8 s, fast runs from 0.8 s.  A 0.6 s per-action budget measured
    # from call start lets every action finish (slow#2's deadline is
    # 0.4+0.6=1.0 s > 0.8 s); measured from submission it would not
    # (0.0+0.6=0.6 s < 0.8 s).
    result = run_workflow(xml, registry=registry, max_workers=1, action_timeout=0.6)
    assert result == "fast"
