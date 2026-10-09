"""
Concurrency stability-under-scaling tests (unit U7).

Verifies vision.md success criterion 3: "parallelization of slow activities
yields major speed-ups, with stable behavior under scaling".

The engine runs ``<parallel>`` children concurrently on a bounded thread pool
(``GraphPool``, default ``max_workers=16`` — see ``workflow/engine.py``).
These tests prove, at scale:

* **true concurrency** — a ``threading.Barrier`` that only releases when a
  full wave of workers is in flight simultaneously (a sequential engine would
  time the barrier out and fail the test);
* **exactly-once execution** — every action runs exactly once;
* **correct, complete results** — all N results are present and deterministic;
* **no deadlock** — every wait is bounded by a generous barrier timeout;
* **deterministic final result** — the final result is a fixed, reproducible
  value;
* **speed-up vs sequential** — parallel wall-time is meaningfully below the
  sequential baseline.

Design notes (determinism / flakiness):

* The pool is bounded to 16 workers, so at most 16 actions can be in flight
  at once. A single ``Barrier(N)`` is therefore only satisfiable for
  ``N <= 16``. For ``N > 16`` we use a ``Barrier(16)`` (one full wave of
  workers); it releases in waves of 16 and still proves >= 16 concurrent
  threads. To keep every wave full (so the barrier is always satisfiable and
  the test cannot deadlock on a short final wave), the scaling sizes are
  multiples of 16.
* All barrier waits use a generous 30 s timeout so a loaded machine cannot
  cause a spurious ``BrokenBarrierError``, while a real deadlock is still
  caught (the wait times out and the test fails).
* The speed-up assertion uses a generous margin (``parallel < sequential *
  0.5``, i.e. at least a 2x speed-up). With 16 workers the ideal speed-up is
  ~16x, so even a 3x slowdown on a heavily loaded machine still clears the
  2x bar comfortably.
"""

from __future__ import annotations

import threading
import time

from sequence_extensions import (
    Action,
    FunctionRegistry,
    Parallel,
    Sequential,
    Test_Framework,
    run_workflow,
)

# The engine's GraphPool default (see workflow/engine.py: ``GraphPool()``).
POOL_WORKERS = 16
# Generous barrier timeout: a loaded machine must not cause a spurious
# BrokenBarrierError, but a real deadlock must still be caught.
BARRIER_TIMEOUT = 30.0
# Speed-up margin: parallel wall-time must be < sequential * this factor.
# 0.5 = at least a 2x speed-up (ideal is ~16x with 16 workers).
SPEEDUP_MARGIN = 0.5


def _work(i: int) -> int:
    """Small deterministic per-action workload (pure computation)."""
    return sum(range(i * 100, i * 100 + 100))


def _expected(i: int) -> int:
    """The deterministic result action ``i`` must produce."""
    return _work(i)


def _make_work(barrier: threading.Barrier | None, sleep: float = 0.0):
    """
    Build a workload that (optionally) joins a barrier, (optionally) sleeps,
    and does a small deterministic computation.

    Returns ``(work, calls)`` where ``work`` is the registered function and
    ``calls`` is a shared list of ``(index, result)`` pairs appended (under a
    lock) by each execution — used to assert exactly-once execution and
    result correctness.
    """
    calls: list[tuple[int, int]] = []
    lock = threading.Lock()

    def work(i, **kwargs) -> int:
        # XML argument values arrive as strings; the Python API passes ints.
        # Coerce so both paths behave identically.
        i = int(i)
        if barrier is not None:
            barrier.wait(timeout=BARRIER_TIMEOUT)
        if sleep:
            time.sleep(sleep)
        result = _work(i)
        with lock:
            calls.append((i, result))
        return result

    work.__name__ = "work"
    return work, calls


def _registry_with(fn) -> FunctionRegistry:
    registry = FunctionRegistry()
    registry.register("work", fn)
    return registry


def _parallel_xml(n: int) -> str:
    actions = "".join(
        f'<action function="work"><argument key="i" value="{i}"/></action>' for i in range(n)
    )
    return f"<parallel>{actions}</parallel>"


def _parallel_seq(n: int) -> Parallel:
    return Parallel(*(Action("work", i=i) for i in range(n)))


def _assert_all_ran_once_and_correct(calls, n: int) -> None:
    """Assert every action ran exactly once and produced the correct result."""
    indices = sorted(i for i, _ in calls)
    assert indices == list(range(n)), (
        f"expected each of {n} actions to run exactly once, got {len(calls)} calls"
    )
    for i, result in calls:
        assert result == _expected(i), f"action {i} returned {result}, expected {_expected(i)}"


# --------------------------------------------------------------------------- #
# 1. TRUE CONCURRENCY — barrier of size N (N == pool size)
# --------------------------------------------------------------------------- #


def test_barrier_proves_true_concurrency():
    """N=16 actions on a Barrier(16) only complete if all 16 run concurrently."""
    n = POOL_WORKERS
    barrier = threading.Barrier(n)
    work, calls = _make_work(barrier)
    result = run_workflow(_parallel_xml(n), registry=_registry_with(work))
    # A sequential engine would leave the first waiter alone -> the barrier
    # times out (BrokenBarrierError) and the test fails. Reaching here proves
    # all 16 were in flight at once.
    _assert_all_ran_once_and_correct(calls, n)
    assert result == _expected(n - 1)  # deterministic final result


# --------------------------------------------------------------------------- #
# 2. STABLE BEHAVIOR UNDER SCALING — barrier waves across several sizes
# --------------------------------------------------------------------------- #


def test_scaling_curve_stable():
    """A full wave of workers (Barrier(16)) is satisfied at every size."""
    for n in (POOL_WORKERS, 64, 128, 192):
        barrier = threading.Barrier(POOL_WORKERS)
        work, calls = _make_work(barrier)
        result = run_workflow(_parallel_xml(n), registry=_registry_with(work))
        _assert_all_ran_once_and_correct(calls, n)
        assert result == _expected(n - 1), f"n={n}: wrong final result"


# --------------------------------------------------------------------------- #
# 3. SPEED-UP VS SEQUENTIAL
# --------------------------------------------------------------------------- #


def test_speedup_vs_sequential():
    """Parallel wall-time is meaningfully below the sequential baseline."""
    n = 64
    sleep = 0.01  # 10 ms of simulated slow work per action

    # Parallel run (no barrier; the sleep is the parallelized slow work).
    work_p, calls_p = _make_work(None, sleep=sleep)
    t0 = time.perf_counter()
    result_p = Test_Framework(_parallel_seq(n), registry=_registry_with(work_p))
    parallel_wall = time.perf_counter() - t0

    # Sequential baseline (same work, strict order, no barrier).
    work_s, calls_s = _make_work(None, sleep=sleep)
    t0 = time.perf_counter()
    result_s = Test_Framework(
        Sequential(*(Action("work", i=i) for i in range(n))),
        registry=_registry_with(work_s),
    )
    sequential_wall = time.perf_counter() - t0

    _assert_all_ran_once_and_correct(calls_p, n)
    _assert_all_ran_once_and_correct(calls_s, n)
    assert result_p == result_s == _expected(n - 1)
    # Robust margin: at least a 2x speed-up (ideal is ~16x with 16 workers).
    assert parallel_wall < sequential_wall * SPEEDUP_MARGIN, (
        f"no speed-up: parallel={parallel_wall:.3f}s sequential={sequential_wall:.3f}s"
    )


# --------------------------------------------------------------------------- #
# 4. NESTED SCALING — parallel groups inside parallel groups
# --------------------------------------------------------------------------- #


def test_nested_parallel_scaling():
    """Nested Parallel groups (4 outer x 8 inner = 32 actions) stay stable."""
    outer, inner = 4, 8
    n = outer * inner
    barrier = threading.Barrier(POOL_WORKERS)
    work, calls = _make_work(barrier)
    root = Parallel(
        *(
            Parallel(*(Action("work", i=i) for i in range(g * inner, (g + 1) * inner)))
            for g in range(outer)
        )
    )
    result = Test_Framework(root, registry=_registry_with(work))
    _assert_all_ran_once_and_correct(calls, n)
    # Final result = last action of the last inner group (index n-1).
    assert result == _expected(n - 1)
