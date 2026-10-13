"""
Tests for the fail-fast parallel failure policy (finding 3e): the
``run_workflow`` / ``Test_Framework`` option ``fail_fast``.

A runtime-sized unattended campaign must not pay for every remaining
sibling after the first failure.  With ``fail_fast=True`` a ``Parallel``
group stops at the FIRST action failure: not-yet-run siblings skip their
function call entirely (a queued action costs nothing — the abort event
makes the guard return a ``_SKIPPED`` sentinel before calling the
function), in-flight siblings are abandoned (threads cannot be killed —
the pool is torn down without waiting), and the first error in child order
is raised promptly.  With the default (``fail_fast=False``) the historical
drain-then-report behavior is kept: every sibling settles, then the first
error in child order is raised.

NOTE — most of these tests use COUNTERS (shared call logs with a lock)
instead of wall-clock assertions: the skip/drain distinction is a
structural fact (did the sibling's function run or not), not a timing
race.  Where the feature IS timing (the ``action_timeout`` composition),
each test sleeps for a fraction of a second and asserts error type and
promptness bounds, never exact timings.  "Hung" / "slow" functions block
on a release event the test sets on teardown, so the worker threads an
abandoned run leaves behind exit promptly (the suite's determinism and
speed conventions are otherwise preserved).
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
    teardown — a fail-fast / timed-out run abandons its worker thread
    (threads cannot be killed), and releasing it keeps the test process fast.
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

    def stub(self, name, fn):
        """Register one more (healthy) function under this registry."""
        self.registry.register(name, fn)
        return self


class _Release:
    """A release event that is ALWAYS set on teardown (context manager)."""

    def __init__(self):
        self.event = threading.Event()

    def __enter__(self):
        return self.event

    def __exit__(self, *_exc):
        self.event.set()
        return False


def _call_log():
    """A shared call log with a lock: ``(calls, lock)``."""
    return [], threading.Lock()


def _fast_fail(name, message):
    """A function that raises ``RuntimeError(message)`` immediately."""

    def fn(**kwargs):
        raise RuntimeError(message)

    fn.__name__ = name
    return fn


def _slow(name, calls, lock, release, duration=0.3):
    """
    A slow sibling: appends ``name`` to the call log, then blocks until
    released (or ``duration`` passes).

    In the fail-fast skip case the sibling is never called (skipped via the
    abort event), so the block is a safety net; in the drain case the
    sibling completes after the block.
    """

    def fn(**kwargs):
        with lock:
            calls.append(name)
        release.wait(duration)
        return name

    fn.__name__ = name
    return fn


def _recording(name, calls, lock):
    """A healthy sibling: appends ``name`` to the call log and returns it."""

    def fn(**kwargs):
        with lock:
            calls.append(name)
        return name

    fn.__name__ = name
    return fn


def _keyboard_interrupt(name):
    """A function that raises ``KeyboardInterrupt`` immediately."""

    def fn(**kwargs):
        raise KeyboardInterrupt("interrupted")

    fn.__name__ = name
    return fn


# --------------------------------------------------------------------------- #
# Fail-fast skips a slow sibling after a fast failure
# --------------------------------------------------------------------------- #


def test_fail_fast_skips_slow_sibling_after_fast_failure():
    """fail_fast=True: a queued slow sibling is skipped (its function never runs)."""
    calls, lock = _call_log()
    with _Release() as release:
        registry = FunctionRegistry()
        registry.register("fast_fail", _fast_fail("fast_fail", "boom"))
        registry.register("slow", _slow("slow", calls, lock, release))
        xml = (
            "<parallel>"
            '<action function="fast_fail"/>'
            '<action function="slow"/>'
            "</parallel>"
        )
        with pytest.raises(RuntimeError) as excinfo:
            run_workflow(xml, registry=registry, fail_fast=True, max_workers=1)
        # The first error (the original exception) is raised.
        assert str(excinfo.value) == "boom"
    # The slow sibling's function NEVER ran (skipped via the abort event).
    assert "slow" not in calls


def test_fail_fast_failing_child_not_first_position():
    """fail_fast=True: the first error in child order is raised promptly, even
    when the failing child is not the first (the in-flight sibling is abandoned)."""
    calls, lock = _call_log()
    with _Release() as release:
        registry = FunctionRegistry()
        registry.register("slow", _slow("slow", calls, lock, release))
        registry.register("fast_fail", _fast_fail("fast_fail", "boom"))
        xml = (
            "<parallel>"
            '<action function="slow"/>'
            '<action function="fast_fail"/>'
            "</parallel>"
        )
        started = time.monotonic()
        with pytest.raises(RuntimeError) as excinfo:
            run_workflow(xml, registry=registry, fail_fast=True)
        elapsed = time.monotonic() - started
        # The first error in child order (the fast failure) is raised promptly.
        assert str(excinfo.value) == "boom"
        # Prompt: bounded by teardown slack, NOT the slow sibling's block.
        assert elapsed < 5.0


# --------------------------------------------------------------------------- #
# Default (fail_fast omitted) drains
# --------------------------------------------------------------------------- #


def test_default_drains_slow_sibling():
    """fail_fast omitted: the slow sibling COMPLETES before the error is raised."""
    calls, lock = _call_log()
    with _Release() as release:
        registry = FunctionRegistry()
        registry.register("fast_fail", _fast_fail("fast_fail", "boom"))
        registry.register("slow", _slow("slow", calls, lock, release))
        xml = (
            "<parallel>"
            '<action function="fast_fail"/>'
            '<action function="slow"/>'
            "</parallel>"
        )
        with pytest.raises(RuntimeError) as excinfo:
            run_workflow(xml, registry=registry, max_workers=1)  # fail_fast omitted
        assert str(excinfo.value) == "boom"
    # The slow sibling COMPLETED (drain-then-report: every sibling settles).
    assert "slow" in calls


# --------------------------------------------------------------------------- #
# First error raised in BOTH modes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fail_fast", [True, False])
def test_first_error_raised_in_both_modes(fail_fast):
    """Both fail_fast modes raise the original error (type + message)."""
    calls, lock = _call_log()
    with _Release() as release:
        registry = FunctionRegistry()
        registry.register("first_fail", _fast_fail("first_fail", "first error"))
        registry.register("second_ok", _slow("second_ok", calls, lock, release))
        xml = (
            "<parallel>"
            '<action function="first_fail"/>'
            '<action function="second_ok"/>'
            "</parallel>"
        )
        with pytest.raises(RuntimeError) as excinfo:
            run_workflow(
                xml, registry=registry, fail_fast=fail_fast, max_workers=1
            )
        # The original error (type + message) is raised in both modes.
        assert isinstance(excinfo.value, RuntimeError)
        assert str(excinfo.value) == "first error"


# --------------------------------------------------------------------------- #
# KeyboardInterrupt in a child is NOT swallowed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fail_fast", [True, False])
def test_keyboard_interrupt_not_swallowed(fail_fast):
    """A child raising KeyboardInterrupt is re-raised to the caller (both modes)."""
    calls, lock = _call_log()
    with _Release() as release:
        registry = FunctionRegistry()
        registry.register("interrupt", _keyboard_interrupt("interrupt"))
        registry.register("ok", _slow("ok", calls, lock, release))
        xml = (
            "<parallel>"
            '<action function="interrupt"/>'
            '<action function="ok"/>'
            "</parallel>"
        )
        with pytest.raises(KeyboardInterrupt) as excinfo:
            run_workflow(
                xml, registry=registry, fail_fast=fail_fast, max_workers=1
            )
        # The ORIGINAL KeyboardInterrupt (not the carrier wrapper) is raised.
        assert str(excinfo.value) == "interrupted"


# --------------------------------------------------------------------------- #
# fail_fast composes with action_timeout
# --------------------------------------------------------------------------- #


def test_fail_fast_composes_with_action_timeout_fast_failure_wins():
    """A fast failure beats a 0.3s ActionTimeoutError (first error in time)."""
    with _Hung() as hung:
        hung.stub("fast_fail", _fast_fail("fast_fail", "fast"))
        xml = (
            "<parallel>"
            '<action function="sleepy"/>'
            '<action function="fast_fail"/>'
            "</parallel>"
        )
        with pytest.raises(RuntimeError) as excinfo:
            run_workflow(
                xml, registry=hung.registry, fail_fast=True, action_timeout=0.3
            )
        # The fast failure wins (RuntimeError, not ActionTimeoutError).
        assert str(excinfo.value) == "fast"
        assert not isinstance(excinfo.value, ActionTimeoutError)


def test_fail_fast_composes_with_action_timeout_hung_wins():
    """A 0.3s ActionTimeoutError beats a slow sibling's completion."""
    with _Hung() as hung:
        # A slow, healthy sibling: blocks until released (abandoned in-flight).
        def slow_ok(**kwargs):
            hung.release.wait(0.5)
            return "slow_ok"

        slow_ok.__name__ = "slow_ok"
        hung.stub("slow_ok", slow_ok)
        xml = (
            "<parallel>"
            '<action function="sleepy"/>'
            '<action function="slow_ok"/>'
            "</parallel>"
        )
        started = time.monotonic()
        with pytest.raises(ActionTimeoutError) as excinfo:
            run_workflow(
                xml, registry=hung.registry, fail_fast=True, action_timeout=0.3
            )
        elapsed = time.monotonic() - started
        # Prompt: bounded by the timeout plus teardown slack, NOT the hang.
        assert elapsed < 5.0
        # The error names the hung action.
        assert "sleepy" in str(excinfo.value)


def test_fail_fast_no_failure_completes_under_timeout():
    """A no-failure fail_fast run with action_timeout set completes normally."""
    calls, lock = _call_log()
    registry = FunctionRegistry()
    registry.register("a", _recording("a", calls, lock))
    registry.register("b", _recording("b", calls, lock))
    xml = (
        "<parallel>"
        '<action function="a"/>'
        '<action function="b"/>'
        "</parallel>"
    )
    result = run_workflow(xml, registry=registry, fail_fast=True, action_timeout=5.0)
    # All siblings completed.
    assert sorted(calls) == ["a", "b"]
    # The final result is the last action's result.
    assert result == "b"


# --------------------------------------------------------------------------- #
# Python API parity (Test_Framework)
# --------------------------------------------------------------------------- #


def test_python_api_fail_fast_parity():
    """Test_Framework(fail_fast=True) mirrors run_workflow (skips the slow sibling)."""
    calls, lock = _call_log()
    with _Release() as release:
        registry = FunctionRegistry()
        registry.register("fast_fail", _fast_fail("fast_fail", "boom"))
        registry.register("slow", _slow("slow", calls, lock, release))
        seq = Parallel(Action("fast_fail"), Action("slow"))
        with pytest.raises(RuntimeError) as excinfo:
            Test_Framework(seq, registry=registry, fail_fast=True, max_workers=1)
        assert str(excinfo.value) == "boom"
    # The slow sibling's function NEVER ran (skipped via the abort event).
    assert "slow" not in calls


# --------------------------------------------------------------------------- #
# fail_fast=True with NO failure
# --------------------------------------------------------------------------- #


def test_fail_fast_no_failure_all_complete():
    """fail_fast=True with no failure: all siblings complete, correct final result."""
    calls, lock = _call_log()
    registry = FunctionRegistry()
    registry.register("a", _recording("a", calls, lock))
    registry.register("b", _recording("b", calls, lock))
    registry.register("c", _recording("c", calls, lock))
    xml = (
        "<parallel>"
        '<action function="a"/>'
        '<action function="b"/>'
        '<action function="c"/>'
        "</parallel>"
    )
    result = run_workflow(xml, registry=registry, fail_fast=True)
    # All siblings completed.
    assert sorted(calls) == ["a", "b", "c"]
    # The final result is the last action's result.
    assert result == "c"


# --------------------------------------------------------------------------- #
# A skipped sibling does not corrupt downstream data-plane pairing
# --------------------------------------------------------------------------- #


def test_skipped_sibling_no_downstream_pair():
    """With fail_fast, the error propagates so the downstream consumer never runs."""
    calls, lock = _call_log()
    with _Release() as release:
        registry = FunctionRegistry()
        registry.register("fail", _fast_fail("fail", "boom"))
        registry.register("slow", _slow("slow", calls, lock, release))
        registry.register("consumer", _recording("consumer", calls, lock))
        xml = (
            "<sequential>"
            "<parallel>"
            '<action function="fail"/>'
            '<action function="slow"/>'
            "</parallel>"
            '<action function="consumer"/>'
            "</sequential>"
        )
        with pytest.raises(RuntimeError) as excinfo:
            run_workflow(xml, registry=registry, fail_fast=True, max_workers=1)
        assert str(excinfo.value) == "boom"
    # The consumer never ran (the error propagated out of the Parallel group).
    assert "consumer" not in calls
    # The slow sibling was skipped (never called).
    assert "slow" not in calls
