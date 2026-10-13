"""
Tests for the per-scope error-capture policy (finding 3c): the
``on_error="capture"`` scope attribute and the ``CapturedError`` record.

A V&V campaign must treat a scenario failure as DATA, not a crash (paper
P3: branch on failures): a scope declaring ``on_error="capture"`` turns an
exception raised by one of its direct action children into that action's
RESULT — a :class:`~sequence_extensions.workflow.engine.CapturedError`
record — and the walk continues.  Without the attribute the historical
behavior is unchanged (the exception propagates and the run fails).

Composition (each policy keeps its own contract):

* retry / fallback — they run INSIDE the action's function call, so they
  exhaust themselves before the engine sees the exception: capture is the
  last resort.  A captured result carries the ``ok``/``error`` keys, so
  ``retry(on="error")`` reads it like a ``try_action`` outcome.
* fail_fast — a captured failure is a result, not an error: siblings are
  NOT skipped and the group does not abandon them.
* action_timeout — a timed-out action inside a capture scope is captured
  (``timeout=True``), not fatal; the hung worker is still abandoned.

The tests are structural (call logs, result shapes, error types) — no
wall-clock assertions beyond the one timeout test, which sleeps a
fraction of a second and releases its worker on teardown (the suite's
only wall-clock tests live in ``test_action_timeout.py``; this file
follows the same convention for its single timeout case).
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
from sequence_extensions.workflow.engine import (
    ActionTimeoutError,
    CapturedError,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _recording_registry(*specs):
    """
    Build ``(registry, calls)`` from ``specs`` of ``(name, result)``.

    A ``result`` that is an ``Exception`` instance is RAISED when the
    function runs (a failing scenario); anything else is returned.  The
    shared ``calls`` list records every invocation, lock-protected
    (parallel siblings may run concurrently).
    """
    calls: list[str] = []
    lock = threading.Lock()

    def make(name, result):
        def fn(**kwargs):
            with lock:
                calls.append(name)
            if isinstance(result, Exception):
                raise result
            return result

        fn.__name__ = name
        return fn

    registry = FunctionRegistry()
    for name, result in specs:
        registry.register(name, make(name, result))
    return registry, calls


class _Hung:
    """A hung-simulator stand-in: blocks until released (or duration passes)."""

    def __init__(self, name="sleepy", duration=30.0):
        self.name = name
        self.duration = duration
        self.release = threading.Event()
        self.registry = FunctionRegistry()
        self.registry.register(name, self._hung_function)

    def _hung_function(self, **kwargs):
        self.release.wait(self.duration)
        return self.name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release.set()
        return False


# --------------------------------------------------------------------------- #
# The core policy: a failing action becomes data
# --------------------------------------------------------------------------- #


def test_capture_scope_turns_failure_into_result():
    """A failing action inside a capture scope: run completes, result is the record."""
    registry, calls = _recording_registry(
        ("boom", ValueError("scenario 7 diverged")),
        ("after", "after-ok"),
    )
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="boom"/>'
        '<action function="after"/>'
        "</scope>"
    )
    result = run_workflow(xml, registry=registry)
    # The walk continued past the failure.
    assert calls == ["boom", "after"]
    # The final result is the last action's result (the run completed).
    assert result == "after-ok"


def test_captured_result_shape():
    """The capture record carries the action identity and the exception data."""
    registry, _ = _recording_registry(
        ("boom", ValueError("scenario 7 diverged")),
        ("inspect", None),
    )

    def inspect(boom=None, **kwargs):
        return boom

    registry.register("inspect", inspect)
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="boom"/>'
        '<action function="inspect"/>'
        "</scope>"
    )
    result = run_workflow(xml, registry=registry)
    assert isinstance(result, CapturedError)
    # The documented shape: plain, comparable data.
    assert result["is_error"] is True
    assert result["ok"] is False
    assert result["function"] == "boom"
    assert result["error_type"] == "ValueError"
    assert result["error"] == "scenario 7 diverged"
    assert result["timeout"] is False
    # The same fields read as attributes.
    assert result.is_error is True
    assert result.function == "boom"
    # A dict: the existing driver vocabulary (guard/fallback/aggregate)
    # reads fields from it like from any mapping.
    assert isinstance(result, dict)


def test_downstream_action_sees_the_capture():
    """A downstream action receives the capture through the data plane."""
    registry, _ = _recording_registry(("boom", RuntimeError("solver crashed")))

    seen = {}

    def downstream(boom=None, **kwargs):
        seen["result"] = boom
        return "downstream-ok"

    registry.register("downstream", downstream)
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="boom"/>'
        '<action function="downstream"/>'
        "</scope>"
    )
    result = run_workflow(xml, registry=registry)
    assert result == "downstream-ok"
    assert isinstance(seen["result"], CapturedError)
    assert seen["result"]["error_type"] == "RuntimeError"
    assert seen["result"]["error"] == "solver crashed"


def test_capture_scope_group_result_contains_the_record():
    """The group's own result list carries the capture (the data plane)."""
    registry, _ = _recording_registry(("boom", ValueError("nope")))

    def collect(boom=None, **kwargs):
        # The capture scope's direct action child contributed its pair to
        # the parent's chain (one-level flattening), so the record is
        # keyed by the action's function name downstream.
        return ("collected", boom["is_error"], boom["function"])

    registry.register("collect", collect)
    xml = (
        "<sequential>"
        '<scope type="sequential" on_error="capture">'
        '<action function="boom"/>'
        "</scope>"
        '<action function="collect"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry)
    # The capture flowed through the data plane to the sibling AFTER the
    # scope (the scope's direct action children's pairs are flattened
    # into the parent chain).
    assert result == ("collected", True, "boom")


# --------------------------------------------------------------------------- #
# Backward compatibility: without the attribute nothing changes
# --------------------------------------------------------------------------- #


def test_without_policy_the_same_workflow_fails():
    """The same workflow without on_error: the exception propagates (historical)."""
    registry, calls = _recording_registry(
        ("boom", ValueError("scenario 7 diverged")),
        ("after", "after-ok"),
    )
    xml = (
        '<scope type="sequential">'
        '<action function="boom"/>'
        '<action function="after"/>'
        "</scope>"
    )
    with pytest.raises(ValueError, match="scenario 7 diverged"):
        run_workflow(xml, registry=registry)
    # The walk stopped at the failure: the downstream action never ran.
    assert calls == ["boom"]


def test_default_scope_attribute_is_none():
    """A parsed scope without the attribute carries on_error=None (inert)."""
    from sequence_extensions.workflow.schema import parse_workflow

    group = parse_workflow(
        '<scope type="sequential"><action function="a"/></scope>'
    )
    assert group.on_error is None
    group = parse_workflow(
        '<scope type="sequential" on_error="capture">'
        "<action function=\"a\"/></scope>"
    )
    assert group.on_error == "capture"


def test_invalid_on_error_value_rejected():
    """An unknown on_error value is a parse error naming the valid values."""
    from sequence_extensions.workflow.schema import parse_workflow

    with pytest.raises(ValueError, match="on_error"):
        parse_workflow(
            '<scope type="sequential" on_error="explode">'
            "<action function=\"a\"/></scope>"
        )


def test_capture_applies_only_to_direct_children():
    """A nested scope without the policy still fails: capture is per-scope."""
    registry, _ = _recording_registry(("boom", ValueError("inner boom")))

    def outer(boom=None, **kwargs):
        return "never-reached"

    registry.register("outer", outer)
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<scope type="sequential">'
        '<action function="boom"/>'
        "</scope>"
        '<action function="outer"/>'
        "</scope>"
    )
    # The inner scope has no policy, so its child's failure propagates out
    # of it — and then out of the OUTER scope too: the outer policy only
    # captures the failures of its DIRECT action children, not the
    # failures a nested group's walk raises.
    with pytest.raises(ValueError, match="inner boom"):
        run_workflow(xml, registry=registry)


# --------------------------------------------------------------------------- #
# Composition: retry / fallback run FIRST (capture is the last resort)
# --------------------------------------------------------------------------- #


def test_compose_retry_exhausts_then_capture():
    """retry re-runs the body; when it exhausts, the capture is the data."""
    from sequence_extensions.workflow.library import retry

    attempts: list[int] = []

    def body(**kwargs):
        attempts.append(1)
        raise ValueError("flaky solver")

    registry = FunctionRegistry()
    registry.register("body", body)
    registry.register("retry", retry)
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="body"/>'
        '<action function="retry">'
        '<argument key="upstream" value="body"/>'
        '<argument key="max_attempts" value="3"/>'
        '<argument key="on" value="error"/>'
        "</action>"
        "</scope>"
    )
    result = run_workflow(xml, registry=registry)
    # The body ran once, then retry re-ran it up to the cap (copy-to-end).
    assert len(attempts) == 4
    # The retry summary reports exhaustion.
    assert result["ok"] is False
    assert result["attempts"] == 4
    assert result["max_attempts"] == 3


def test_compose_retry_success_after_capture():
    """retry(on='error') recognizes a captured result and re-runs the body."""
    from sequence_extensions.workflow.library import retry

    attempts: list[int] = []

    def body(**kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise ValueError("transient")
        return "converged"

    registry = FunctionRegistry()
    registry.register("body", body)
    registry.register("retry", retry)
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="body"/>'
        '<action function="retry">'
        '<argument key="upstream" value="body"/>'
        '<argument key="max_attempts" value="5"/>'
        '<argument key="on" value="error"/>'
        "</action>"
        "</scope>"
    )
    result = run_workflow(xml, registry=registry)
    # The captured failure (ok falsy) was unacceptable to retry, so the
    # body was re-run until it succeeded.  The body runs once per
    # attempt plus the initial run; the copy-to-end re-splice means the
    # successful attempt's result is what retry sees as latest.
    assert result["ok"] is True
    assert len(attempts) >= 3


# --------------------------------------------------------------------------- #
# Composition: fail_fast — a captured failure is a result, not an error
# --------------------------------------------------------------------------- #


def test_compose_fail_fast_siblings_not_skipped():
    """fail_fast + capture: every sibling still runs (nothing failed)."""
    registry, calls = _recording_registry(
        ("a", "a-ok"),
        ("bad", RuntimeError("sibling failure")),
        ("b", "b-ok"),
        ("c", "c-ok"),
    )
    xml = (
        '<scope type="parallel" on_error="capture">'
        '<action function="a"/>'
        '<action function="bad"/>'
        '<action function="b"/>'
        '<action function="c"/>'
        "</scope>"
    )
    result = run_workflow(xml, registry=registry, fail_fast=True)
    # No sibling was skipped: the captured failure is a result, so the
    # fail-fast abort never fired.
    assert sorted(calls) == ["a", "b", "bad", "c"]
    # The run completed and returned the FINAL action's result (the last
    # child's), not an error.
    assert result == "c-ok"


def test_compose_fail_fast_capture_reaches_downstream():
    """fail_fast + capture: the record flows to a sibling after the group."""
    registry, _ = _recording_registry(
        ("a", "a-ok"),
        ("bad", RuntimeError("sibling failure")),
    )

    def collect(a=None, bad=None, **kwargs):
        return (a, isinstance(bad, CapturedError), bad["error_type"])

    registry.register("collect", collect)
    xml = (
        "<sequential>"
        '<scope type="parallel" on_error="capture">'
        '<action function="a"/>'
        '<action function="bad"/>'
        "</scope>"
        '<action function="collect"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry, fail_fast=True)
    assert result == ("a-ok", True, "RuntimeError")


def test_compose_fail_fast_without_capture_still_fails_fast():
    """fail_fast without capture: unchanged (the first error is raised)."""
    registry, _ = _recording_registry(
        ("a", "a-ok"),
        ("bad", RuntimeError("sibling failure")),
    )
    xml = (
        '<scope type="parallel">'
        '<action function="a"/>'
        '<action function="bad"/>'
        "</scope>"
    )
    with pytest.raises(RuntimeError, match="sibling failure"):
        run_workflow(xml, registry=registry, fail_fast=True)


# --------------------------------------------------------------------------- #
# Composition: action_timeout — a timed-out action is captured, not fatal
# --------------------------------------------------------------------------- #


def test_compose_action_timeout_captured():
    """A timed-out action inside a capture scope: captured, run completes."""
    with _Hung() as hung:
        hung.registry.register("after", lambda **kwargs: "after-ok")
        xml = (
            '<scope type="sequential" on_error="capture">'
            '<action function="sleepy"/>'
            '<action function="after"/>'
            "</scope>"
        )
        result = run_workflow(
            xml, registry=hung.registry, action_timeout=0.3
        )
    # The run completed: the timeout became the action's result.
    assert result == "after-ok"


def test_compose_action_timeout_capture_record_marks_timeout():
    """The capture record from a timeout carries timeout=True."""
    with _Hung() as hung:
        seen = {}

        def inspect(sleepy=None, **kwargs):
            seen["result"] = sleepy
            return "inspected"

        hung.registry.register("inspect", inspect)
        xml = (
            '<scope type="sequential" on_error="capture">'
            '<action function="sleepy"/>'
            '<action function="inspect"/>'
            "</scope>"
        )
        result = run_workflow(
            xml, registry=hung.registry, action_timeout=0.3
        )
    assert result == "inspected"
    record = seen["result"]
    assert isinstance(record, CapturedError)
    assert record["timeout"] is True
    assert record["error_type"] == "ActionTimeoutError"
    assert record["function"] == "sleepy"


def test_compose_action_timeout_without_capture_still_fatal():
    """action_timeout without capture: unchanged (ActionTimeoutError raised)."""
    with _Hung() as hung:
        xml = (
            '<scope type="sequential">'
            '<action function="sleepy"/>'
            "</scope>"
        )
        with pytest.raises(ActionTimeoutError, match="sleepy"):
            run_workflow(xml, registry=hung.registry, action_timeout=0.3)


# --------------------------------------------------------------------------- #
# XML surface and the Python API
# --------------------------------------------------------------------------- #


def test_xml_on_error_on_sequential_and_parallel_aliases():
    """The attribute is accepted on <scope>, <sequential> and <parallel>."""
    from sequence_extensions.workflow.schema import parse_workflow

    for tag in ("scope", "sequential", "parallel"):
        attrs = 'type="parallel"' if tag == "scope" else ""
        group = parse_workflow(
            f'<{tag} {attrs} on_error="capture"><action function="a"/></{tag}>'
        )
        assert group.on_error == "capture", tag


def test_python_api_on_error():
    """Sequential/Parallel accept on_error= (the Python API surface)."""
    registry, _ = _recording_registry(("boom", ValueError("py boom")))

    def after(boom=None, **kwargs):
        return ("saw", boom["error_type"])

    registry.register("after", after)
    seq = Sequential(
        Action("boom"),
        Action("after"),
        on_error="capture",
    )
    result = Test_Framework(seq, registry=registry)
    assert result == ("saw", "ValueError")

    par = Parallel(Action("boom"), on_error="capture")
    result = Test_Framework(par, registry=registry)
    # The run's final result is the LAST action's result: the capture
    # record itself (the failing action is the group's only child).
    assert isinstance(result, CapturedError)
    assert result["function"] == "boom"
    assert result["error_type"] == "ValueError"


def test_python_api_default_unchanged():
    """Without on_error= the Python API keeps the historical behavior."""
    registry, _ = _recording_registry(("boom", ValueError("py boom")))
    seq = Sequential(Action("boom"))
    with pytest.raises(ValueError, match="py boom"):
        Test_Framework(seq, registry=registry)


def test_keyboard_interrupt_is_never_captured():
    """A KeyboardInterrupt propagates even inside a capture scope."""
    registry = FunctionRegistry()

    def interrupt(**kwargs):
        raise KeyboardInterrupt()

    registry.register("interrupt", interrupt)
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="interrupt"/>'
        "</scope>"
    )
    with pytest.raises(KeyboardInterrupt):
        run_workflow(xml, registry=registry)


def test_system_exit_is_never_captured():
    """A SystemExit propagates even inside a capture scope."""
    registry = FunctionRegistry()

    def bail(**kwargs):
        raise SystemExit(3)

    registry.register("bail", bail)
    xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="bail"/>'
        "</scope>"
    )
    with pytest.raises(SystemExit):
        run_workflow(xml, registry=registry)


def test_compose_fallback_reads_a_captured_alternative():
    """fallback(field='ok') reads a captured result like any mapping.

    The chain convention: one fallback check after each alternative.
    The first alternative raises (captured, ok=False), so its check
    fails and the second alternative runs; the second succeeds, so its
    check empties the rest of the chain.
    """
    from sequence_extensions.workflow.library import fallback

    ran: list[str] = []

    def solver_a(**kwargs):
        ran.append("a")
        raise ValueError("solver A diverged")

    def solver_b(**kwargs):
        ran.append("b")
        return {"ok": True, "value": 7}

    def collect(solver_a=None, solver_b=None, **kwargs):
        # The capture scope's direct action children's pairs flatten into
        # the parent chain, so both alternatives' results are keyed by
        # their function names downstream.
        return (
            solver_a["is_error"],
            solver_a["error"],
            solver_b["ok"],
            solver_b["value"],
        )

    registry = FunctionRegistry()
    registry.register("solver_a", solver_a)
    registry.register("solver_b", solver_b)
    registry.register("fallback", fallback)
    registry.register("collect", collect)
    xml = (
        "<sequential>"
        '<scope type="sequential" on_error="capture">'
        '<action function="solver_a"/>'
        '<action function="fallback">'
        '<argument key="upstream" value="solver_a"/>'
        '<argument key="field" value="ok"/>'
        '<argument key="ok_value" value="True"/>'
        "</action>"
        '<action function="solver_b"/>'
        '<action function="fallback">'
        '<argument key="upstream" value="solver_b"/>'
        '<argument key="field" value="ok"/>'
        '<argument key="ok_value" value="True"/>'
        "</action>"
        "</scope>"
        '<action function="collect"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry)
    # Both alternatives ran: the captured failure of A (ok falsy) failed
    # its check, so B ran.  B's check succeeded and emptied the rest of
    # the CHAIN INSIDE the scope (collect sits outside it, after the
    # scope, so it still runs and reads the flattened pairs).
    assert ran == ["a", "b"]
    assert result == (True, "solver A diverged", True, 7)


# --------------------------------------------------------------------------- #
# try_action: deprecated in favor of on_error="capture"
# --------------------------------------------------------------------------- #


def test_try_action_still_works():
    """try_action keeps its documented behavior (deprecated, not removed)."""
    from sequence_extensions.workflow.library import try_action

    registry = FunctionRegistry()
    registry.register("inner", lambda **kwargs: 42)
    outcome = try_action("inner", registry=registry)
    assert outcome == {"ok": True, "result": 42, "error": None}

    def failing(**kwargs):
        raise ValueError("inner failure")

    registry.register("failing", failing)
    outcome = try_action("failing", registry=registry)
    assert outcome["ok"] is False
    assert outcome["result"] is None
    assert outcome["error"] == "inner failure"


def test_try_action_migration_equivalence():
    """The migration: the engine policy covers the wrapper's use case."""
    registry, _ = _recording_registry(("boom", ValueError("migrate me")))

    def read(try_action=None, boom=None, **kwargs):
        # The wrapper's outcome shape and the capture record shape share
        # the ok/error keys, so one reader works with either.  Only the
        # kwarg KEY differs: results arrive keyed by the producing
        # action's function name — "try_action" for the wrapper, "boom"
        # for the action inside the capture scope.
        outcome = try_action if try_action is not None else boom
        return (outcome["ok"], outcome["error"])

    registry.register("read", read)

    # Old style: the try_action wrapper (static params, one function).
    # The wrapper resolves its target from its ``registry`` parameter
    # (default DEFAULT_REGISTRY); from XML the parameter is a string, so
    # the old style is shown here through the Python API, where the
    # registry object can be passed as a global parameter (globals reach
    # every action's kwargs).
    from sequence_extensions.workflow.library import try_action

    registry.register("try_action", try_action)
    old = Test_Framework(
        Sequential(
            Action(
                "try_action",
                name="boom",
            ),
            Action("read"),
        ),
        registry=registry,
        parameters={"registry": registry},
    )
    assert old == (False, "migrate me")

    # New style: the action itself inside a capture scope.
    new_xml = (
        '<scope type="sequential" on_error="capture">'
        '<action function="boom"/>'
        '<action function="read"/>'
        "</scope>"
    )
    new = run_workflow(new_xml, registry=registry)
    # The capture record's ok/error keys match the wrapper's outcome
    # shape, so the same downstream reader works with either.
    assert new == (False, "migrate me")
