"""Unit tests for @task: decoration, retry, timeout, submit semantics."""

from __future__ import annotations

import threading
import time

import pytest

from sequence_extensions.flow import TaskTimeoutError, current_run, flow, task
from sequence_extensions.graph import GraphFuture


# ---------------------------------------------------------------- #
# Decoration
# ---------------------------------------------------------------- #
def test_task_bare_decoration():
    @task
    def f(x):
        return x * 2

    assert f(21) == 42
    assert f.name == "f"


def test_task_empty_parentheses():
    @task()
    def f():
        return 1

    assert f() == 1


def test_task_parameterized_and_named():
    @task(retries=1, name="worker")
    def f():
        return "v"

    assert f.name == "worker"
    assert f.retries == 1


def test_task_metadata_preserved():
    @task
    def documented():
        """Doc."""

    assert documented.__doc__ == "Doc."
    assert documented.__name__ == "documented"


def test_task_rejects_negative_retries():
    with pytest.raises(ValueError, match="retries"):
        task(lambda: 1, retries=-1)


def test_task_rejects_negative_delay():
    with pytest.raises(ValueError, match="retry_delay_seconds"):
        task(lambda: 1, retry_delay_seconds=-0.5)


def test_task_rejects_nonpositive_timeout():
    with pytest.raises(ValueError, match="timeout"):
        task(lambda: 1, timeout=0)


def test_task_repr_mentions_policy():
    t = task(lambda: 1, retries=2, timeout=5.0)
    assert "retries=2" in repr(t)
    assert "timeout=5.0" in repr(t)


# ---------------------------------------------------------------- #
# Plain call: sequential, inline
# ---------------------------------------------------------------- #
def test_task_call_runs_in_caller_thread():
    seen = {}

    @task
    def where():
        seen["thread"] = threading.current_thread().name
        return 1

    assert where() == 1
    assert seen["thread"] == threading.current_thread().name


def test_task_call_outside_flow_works_unlogged():
    @task
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    assert current_run() is None


# ---------------------------------------------------------------- #
# Retry
# ---------------------------------------------------------------- #
def test_task_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    @task(retries=2, retry_delay_seconds=0.01)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    t0 = time.perf_counter()
    assert flaky() == "ok"
    assert calls["n"] == 3
    # two backoff sleeps of 0.01s
    assert time.perf_counter() - t0 >= 0.02


def test_task_retry_exhausted_raises_last_error():
    calls = {"n": 0}

    @task(retries=2)
    def always_fails():
        calls["n"] += 1
        raise ValueError(f"failure {calls['n']}")

    with pytest.raises(ValueError, match="failure 3"):
        always_fails()
    assert calls["n"] == 3


def test_task_zero_delay_default_is_fast():
    calls = {"n": 0}

    @task(retries=5)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 6:
            raise RuntimeError("no")
        return "ok"

    t0 = time.perf_counter()
    assert flaky() == "ok"
    assert time.perf_counter() - t0 < 0.5


def test_task_success_first_try_has_single_attempt():
    calls = {"n": 0}

    @task(retries=3)
    def stable():
        calls["n"] += 1
        return 1

    assert stable() == 1
    assert calls["n"] == 1


def test_task_baseexception_wrapped_to_runtime_error():
    class Boom(BaseException):
        pass

    @task
    def exits():
        raise Boom("system")

    with pytest.raises(RuntimeError, match="Boom"):
        exits()


# ---------------------------------------------------------------- #
# Timeout
# ---------------------------------------------------------------- #
def test_task_timeout_raises_named_error():
    @task(timeout=0.1)
    def slow():
        time.sleep(2.0)

    t0 = time.perf_counter()
    with pytest.raises(TaskTimeoutError) as excinfo:
        slow()
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5  # returned promptly, did not wait out the sleep
    assert excinfo.value.task == "slow"
    assert excinfo.value.timeout == 0.1
    assert excinfo.value.attempt == 1
    assert isinstance(excinfo.value, TimeoutError)
    assert "slow" in str(excinfo.value)


def test_task_timeout_within_budget_returns_value():
    @task(timeout=2.0)
    def quick():
        time.sleep(0.05)
        return "value"

    assert quick() == "value"


def test_task_timeout_counts_as_attempt_failure_and_retries():
    attempts = {"n": 0}

    @task(timeout=0.05, retries=2, retry_delay_seconds=0.0)
    def slow():
        attempts["n"] += 1
        time.sleep(2.0)

    with pytest.raises(TaskTimeoutError) as excinfo:
        slow()
    assert attempts["n"] == 3  # every attempt was launched and timed out
    assert excinfo.value.attempt == 3


def test_task_timeout_budget_is_per_attempt():
    attempts = {"n": 0}

    @task(timeout=0.1, retries=1)
    def slow():
        attempts["n"] += 1
        time.sleep(0.15)  # exceeds the budget but returns on its own

    t0 = time.perf_counter()
    with pytest.raises(TaskTimeoutError):
        slow()
    elapsed = time.perf_counter() - t0
    # two full attempt budgets: join timed out at ~0.1, but the thread
    # finished at ~0.15; retry ran the same way
    assert attempts["n"] == 2
    assert elapsed >= 0.2


# ---------------------------------------------------------------- #
# submit()
# ---------------------------------------------------------------- #
def test_submit_requires_active_flow():
    @task
    def f():
        return 1

    with pytest.raises(RuntimeError, match="active flow"):
        f.submit()


def test_submit_returns_named_graph_future():
    @task(name="unit")
    def f():
        return 1

    @flow(log=None)
    def run():
        return f.submit()

    gf = run()
    assert isinstance(gf, GraphFuture)
    assert gf.name == "unit"


def test_submit_future_argument_becomes_dependency():
    @flow(log=None)
    def run():
        a = double.submit(21)
        b = double.submit(a)  # future as argument = edge
        return b.result()

    @task
    def double(x):
        return x * 2

    assert run() == 84


def test_submit_future_as_keyword_argument():
    @task
    def combine(x, y):
        return x + y

    @flow(log=None)
    def run():
        a = one.submit()
        return combine.submit(y=a, x=10).result()

    @task
    def one():
        return 1

    assert run() == 11


def test_submit_runs_concurrently():
    @task
    def sleepish(i):
        time.sleep(0.15)
        return i

    @flow(max_workers=8, log=None)
    def run():
        futures = [sleepish.submit(i) for i in range(6)]
        return [f.result() for f in futures]

    t0 = time.perf_counter()
    assert run() == list(range(6))
    assert time.perf_counter() - t0 < 0.6  # sequential would be >= 0.9


def test_submit_from_inside_a_task_joins_the_run():
    @task
    def inner(x):
        return x + 1

    @task
    def outer(x):
        f = inner.submit(x)  # submit from within a task
        return f.result() * 10

    @flow(log=None)
    def run():
        return outer.submit(1).result()

    assert run() == 20


def test_plain_call_inside_flow_is_logged_sequentially(tmp_path):
    @task
    def inline(x):
        return x * 2

    @flow(log=tmp_path)
    def run(x):
        return inline(x) + 1

    assert run(3) == 7
    from sequence_extensions.flow import RunLog

    recs = RunLog.records(next(tmp_path.glob("*.jsonl")))
    task_records = [r for r in recs if r["record"] == "task"]
    assert len(task_records) == 1
    assert task_records[0]["status"] == "ok"
    assert task_records[0]["worker"] == "MainThread"
    assert task_records[0]["result"] == 6


def test_submit_task_records_logged_with_attempts(tmp_path):
    @task(retries=1, retry_delay_seconds=0.0)
    def flaky_once():
        if not flaky_once.ran:
            flaky_once.ran = True
            raise RuntimeError("transient")
        return "ok"

    flaky_once.ran = False

    @flow(log=tmp_path)
    def run():
        return flaky_once.submit().result()

    assert run() == "ok"
    from sequence_extensions.flow import RunLog

    recs = RunLog.records(next(tmp_path.glob("*.jsonl")))
    attempts = [r for r in recs if r["record"] == "task"]
    assert [a["status"] for a in attempts] == ["error", "ok"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert attempts[0]["error"]["type"] == "RuntimeError"
    assert attempts[1]["result"] == "ok"


def test_submit_timeout_status_in_log(tmp_path):
    @task(timeout=0.05)
    def slow():
        time.sleep(2.0)

    @flow(log=tmp_path)
    def run():
        with pytest.raises(TaskTimeoutError):
            return slow.submit().result()

    run()
    from sequence_extensions.flow import RunLog

    recs = RunLog.records(next(tmp_path.glob("*.jsonl")))
    task_records = [r for r in recs if r["record"] == "task"]
    assert task_records[0]["status"] == "timeout"
    assert task_records[0]["error"]["type"] == "TaskTimeoutError"
