"""Unit tests for @node: decoration, retry, timeout, submit semantics."""

from __future__ import annotations

import pickle
import threading
import time

import pytest

from sequence_extensions.flow import (
    UNSET,
    FlowFuture,
    NodeFunction,
    NodePolicy,
    NodeTimeoutError,
    RunLog,
    RunOptions,
    current_run,
    execute_flow,
    gather,
    node,
)


# ---------------------------------------------------------------- #
# Decoration
# ---------------------------------------------------------------- #
def test_node_bare_decoration():
    @node
    def f(x):
        return x * 2

    assert isinstance(f, NodeFunction)
    assert f(21) == 42
    assert f.name == "f"
    assert f.__node__ == "f"


def test_node_empty_parentheses():
    @node()
    def f():
        return 1

    assert f() == 1


def test_node_parameterized_and_named():
    @node(retries=1, name="worker")
    def f():
        return "v"

    assert f.name == "worker"
    assert f.retries == 1
    assert f.__node__ == "worker"


def test_node_metadata_preserved():
    @node
    def documented():
        """Doc."""

    assert documented.__doc__ == "Doc."
    assert documented.__name__ == "documented"
    assert documented.__wrapped__ is not None


def test_node_rejects_negative_retries():
    with pytest.raises(ValueError, match="retries"):
        node(lambda: 1, retries=-1)


def test_node_rejects_negative_delay():
    with pytest.raises(ValueError, match="retry_delay_seconds"):
        node(lambda: 1, retry_delay_seconds=-0.5)


def test_node_rejects_nonpositive_timeout():
    with pytest.raises(ValueError, match="timeout"):
        node(lambda: 1, timeout=0)


def test_node_repr_mentions_policy():
    n = node(lambda: 1, retries=2, timeout=5.0)
    assert "retries=2" in repr(n)
    assert "timeout=5.0" in repr(n)


# ---------------------------------------------------------------- #
# Plain call: sequential, inline
# ---------------------------------------------------------------- #
def test_node_call_runs_in_caller_thread():
    seen = {}

    @node
    def where():
        seen["thread"] = threading.current_thread().name
        return 1

    assert where() == 1
    assert seen["thread"] == threading.current_thread().name


def test_node_call_outside_run_works_unlogged():
    @node
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    assert current_run() is None


# ---------------------------------------------------------------- #
# Retry
# ---------------------------------------------------------------- #
def test_node_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    @node(retries=2, retry_delay_seconds=0.01)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    t0 = time.perf_counter()
    assert flaky() == "ok"
    assert calls["n"] == 3
    assert time.perf_counter() - t0 >= 0.02


def test_node_retry_exhausted_raises_last_error():
    calls = {"n": 0}

    @node(retries=2)
    def always_fails():
        calls["n"] += 1
        raise ValueError(f"failure {calls['n']}")

    with pytest.raises(ValueError, match="failure 3"):
        always_fails()
    assert calls["n"] == 3


def test_node_zero_delay_default_is_fast():
    calls = {"n": 0}

    @node(retries=5)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 6:
            raise RuntimeError("no")
        return "ok"

    t0 = time.perf_counter()
    assert flaky() == "ok"
    assert time.perf_counter() - t0 < 0.5


def test_node_success_first_try_has_single_attempt():
    calls = {"n": 0}

    @node(retries=3)
    def stable():
        calls["n"] += 1
        return 1

    assert stable() == 1
    assert calls["n"] == 1


def test_node_baseexception_wrapped_to_runtime_error():
    class Boom(BaseException):
        pass

    @node
    def exits():
        raise Boom("system")

    with pytest.raises(RuntimeError, match="Boom"):
        exits()


# ---------------------------------------------------------------- #
# Timeout
# ---------------------------------------------------------------- #
def test_node_timeout_raises_named_error():
    @node(timeout=0.1)
    def slow():
        time.sleep(2.0)

    t0 = time.perf_counter()
    with pytest.raises(NodeTimeoutError) as excinfo:
        slow()
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5
    assert excinfo.value.node == "slow"
    assert excinfo.value.timeout == 0.1
    assert excinfo.value.attempt == 1
    assert isinstance(excinfo.value, TimeoutError)
    assert "slow" in str(excinfo.value)


def test_node_timeout_within_budget_returns_value():
    @node(timeout=2.0)
    def quick():
        time.sleep(0.05)
        return "value"

    assert quick() == "value"


def test_node_timeout_counts_as_attempt_failure_and_retries():
    attempts = {"n": 0}

    @node(timeout=0.05, retries=2)
    def slow():
        attempts["n"] += 1
        time.sleep(2.0)

    with pytest.raises(NodeTimeoutError) as excinfo:
        slow()
    assert attempts["n"] == 3
    assert excinfo.value.attempt == 3


def test_node_timeout_budget_is_per_attempt():
    attempts = {"n": 0}

    @node(timeout=0.1, retries=1)
    def slow():
        attempts["n"] += 1
        time.sleep(0.15)

    t0 = time.perf_counter()
    with pytest.raises(NodeTimeoutError):
        slow()
    assert attempts["n"] == 2
    assert time.perf_counter() - t0 >= 0.2


# ---------------------------------------------------------------- #
# submit()
# ---------------------------------------------------------------- #
def test_submit_requires_active_run():
    @node
    def f():
        return 1

    with pytest.raises(RuntimeError, match="active run"):
        f.submit()


def test_submit_returns_named_graph_future():
    @node(name="unit")
    def f():
        return 1

    @node
    def campaign():
        future = f.submit()
        assert isinstance(future, FlowFuture)
        assert future.name == "unit"
        return future

    run = execute_flow(campaign, options=RunOptions(log=None))
    assert run.result == 1


def test_flow_exports_future_types_and_gather():
    import sequence_extensions.flow as flow

    for name in ("gather", "FlowFuture", "FlowOutcome", "execute_flow"):
        assert name in flow.__all__


def test_node_can_return_an_incomplete_plain_future(tmp_path):
    from concurrent.futures import Future

    @node
    def external():
        future = Future()
        timer = threading.Timer(0.05, future.set_result, args=(5,))
        timer.start()
        return future

    @node
    def leaf():
        return "leaf"

    @node
    def campaign():
        return gather([external.submit(), leaf.submit()])

    run = execute_flow(campaign, options=RunOptions(log=tmp_path, max_workers=1))
    assert run.result == [5, "leaf"]
    records = RunLog.records(next(tmp_path.glob("*.jsonl")))
    external_record = next(r for r in records if r["node"] == "external")
    assert external_record["result"] == 5
    assert external_record["duration_ms"] >= 30


def test_plain_future_argument_becomes_dependency(tmp_path):
    from concurrent.futures import Future

    @node
    def add(x, y):
        return x + y

    @node
    def campaign():
        future = Future()
        future.set_result(10)
        return add.submit(future, 5)

    run = execute_flow(campaign, options=RunOptions(log=tmp_path))
    assert run.result == 15


def test_submit_future_argument_becomes_dependency():
    @node
    def double(x):
        return x * 2

    @node
    def campaign():
        a = double.submit(21)
        b = double.submit(a)
        return b.result()

    assert execute_flow(campaign, options=RunOptions(log=None)).result == 84


def test_submit_future_as_keyword_argument():
    @node
    def combine(x, y):
        return x + y

    @node
    def one():
        return 1

    @node
    def campaign():
        a = one.submit()
        return combine.submit(y=a, x=10).result()

    assert execute_flow(campaign, options=RunOptions(log=None)).result == 11


def test_submit_runs_concurrently():
    @node
    def sleepish(i):
        time.sleep(0.15)
        return i

    @node
    def campaign():
        futures = [sleepish.submit(i) for i in range(6)]
        return [f.result() for f in futures]

    t0 = time.perf_counter()
    result = execute_flow(campaign, options=RunOptions(log=None, max_workers=8))
    assert result.result == list(range(6))
    assert time.perf_counter() - t0 < 0.6


def test_submit_inside_a_worker_fans_out_without_deadlocking():
    @node
    def inner(x):
        return x + 1

    @node
    def outer(x):
        return inner.submit(x)

    @node
    def campaign():
        return outer.submit(1)

    t0 = time.perf_counter()
    run = execute_flow(campaign, options=RunOptions(log=None, max_workers=1))
    assert run.result == 2
    assert time.perf_counter() - t0 < 2.0


def test_blocking_on_a_future_inside_a_worker_raises():
    @node
    def inner(x):
        return x + 1

    @node
    def outer(x):
        return inner.submit(x).result()

    @node
    def campaign():
        return outer.submit(1)

    with pytest.raises(RuntimeError, match="incomplete future inside a pool worker"):
        execute_flow(campaign, options=RunOptions(log=None, max_workers=1))


def test_plain_call_inside_run_is_logged_sequentially(tmp_path):
    @node
    def inline(x):
        return x * 2

    @node
    def campaign(x):
        return inline(x) + 1

    run = execute_flow(campaign, 3, options=RunOptions(log=tmp_path))
    assert run.result == 7
    records = RunLog.records(run.log)
    nodes = [r for r in records if r["record"] == "node"]
    assert len(nodes) == 2
    assert nodes[0]["node"] == "inline"
    assert nodes[0]["path"] == ["campaign", "inline"]
    assert nodes[0]["status"] == "ok"
    assert nodes[0]["worker"] == "MainThread"
    assert nodes[0]["result"] == 6
    assert nodes[1]["node"] == "campaign"
    assert nodes[1]["path"] == ["campaign"]


def test_submit_node_records_logged_with_attempts(tmp_path):
    @node(retries=1, retry_delay_seconds=0.0)
    def flaky_once():
        if not flaky_once.ran:
            flaky_once.ran = True
            raise RuntimeError("transient")
        return "ok"

    flaky_once.ran = False

    @node
    def campaign():
        return flaky_once.submit().result()

    run = execute_flow(campaign, options=RunOptions(log=tmp_path))
    assert run.result == "ok"
    records = RunLog.records(run.log)
    attempts = [r for r in records if r["record"] == "node" and r["node"] == "flaky_once"]
    assert [a["status"] for a in attempts] == ["error", "ok"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert attempts[0]["error"]["type"] == "RuntimeError"
    assert attempts[1]["result"] == "ok"


def test_submit_timeout_status_in_log(tmp_path):
    @node(timeout=0.05)
    def slow():
        time.sleep(2.0)

    @node
    def campaign():
        with pytest.raises(NodeTimeoutError):
            return slow.submit().result()

    run = execute_flow(campaign, options=RunOptions(log=tmp_path))
    assert run.status == "ok"
    records = RunLog.records(run.log)
    nodes = [r for r in records if r["record"] == "node" and r["node"] == "slow"]
    assert nodes[0]["status"] == "timeout"
    assert nodes[0]["error"]["type"] == "NodeTimeoutError"


# ---------------------------------------------------------------- #
# Policy from RunOptions.node_defaults
# ---------------------------------------------------------------- #
def test_node_defaults_apply_to_unset_decorator_values(tmp_path):
    calls = {"n": 0}

    @node
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("first")
        return "ok"

    @node
    def campaign():
        return flaky.submit().result()

    run = execute_flow(
        campaign,
        options=RunOptions(log=None, node_defaults=NodePolicy(retries=1)),
    )
    assert run.result == "ok"
    assert calls["n"] == 2


def test_explicit_node_keyword_beats_node_defaults():
    calls = {"n": 0}

    @node(retries=0)
    def strict():
        calls["n"] += 1
        raise ValueError("always")

    @node(retries=0)
    def campaign():
        return strict()

    with pytest.raises(ValueError, match="always"):
        execute_flow(
            campaign,
            options=RunOptions(log=None, node_defaults=NodePolicy(retries=5)),
        )
    assert calls["n"] == 1


def test_node_defaults_reach_timeout_attempt_threads():
    state = {"n": 0}

    @node
    def flaky():
        state["n"] += 1
        if state["n"] < 2:
            raise ValueError("first")
        return "ok"

    @node(timeout=5.0)
    def outer():
        return flaky()

    run = execute_flow(outer, options=RunOptions(log=None, node_defaults=NodePolicy(retries=1)))
    assert run.result == "ok"
    assert state["n"] == 2


def test_pickle_roundtrips_policy_values():
    strict = node(lambda: "ok", retries=2, retry_delay_seconds=0.25, timeout=12.0)
    clone = pickle.loads(pickle.dumps(strict))
    assert (clone.retries, clone.retry_delay_seconds, clone.timeout) == (2, 0.25, 12.0)

    bare = node(lambda: "ok")
    clone = pickle.loads(pickle.dumps(bare))
    assert clone.retries is UNSET



