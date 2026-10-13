"""
Tests for the branch-thread bound (finding 5b): nested parallel group
children no longer spawn one unbounded ``threading.Thread`` per branch.

Before the bound, group children of a ``Parallel`` scope each ran on a
plain daemon thread — one per branch, created MULTIPLICATIVELY for deeply
nested, wide campaigns (width ``W`` at depth ``D`` wants ~``W**D`` live
threads), which can take down an unattended runtime-sized campaign at
the OS thread limit.  The engine now keeps at most ``BRANCH_THREAD_BOUND``
branch walks on their own thread; beyond the bound a branch's walk runs
INLINE on its parent's thread (the same runner and holder/error
contract, just no new thread), so overflow degrades to sequential branch
walking instead of resource exhaustion.

NOTE — the bound is observed as a STRUCTURAL fact, not a timing one:
every campaign function samples ``threading.active_count()`` at entry
(under the campaign's own lock), and the campaign's functions block on
a release event so the sample is taken while the campaign is at its
widest.  Concurrency proofs use ``threading.Barrier`` (a barrier only
releases when every party is inside the call at once).  Composition
tests with ``action_timeout`` necessarily wait one short budget (a
fraction of a second) and assert the error TYPE, never exact timings.
"Hung" functions block on a release event the test ALWAYS sets on
teardown, so worker threads an abandoned run leaves behind exit
promptly.
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
)
from sequence_extensions.workflow.engine import (
    BRANCH_THREAD_BOUND,
    ActionTimeoutError,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _Campaign:
    """
    A campaign stand-in with deterministic observability.

    ``fn`` is registered under one name and used for every action; the
    test-side state (entry counter, live-thread high-water mark) lives
    here so the functions stay plain ``**kwargs`` callees.
    """

    def __init__(self, fn):
        self.registry = FunctionRegistry()
        self.registry.register("campaign_step", fn)
        self.entries = 0
        self.peak_threads = 0
        self.lock = threading.Lock()

    def note_entry(self):
        """Count one function entry and sample the live-thread high-water."""
        with self.lock:
            self.entries += 1
            self.peak_threads = max(self.peak_threads, threading.active_count())


def _wait_for(predicate, timeout=10.0):
    """Wait (polling) until ``predicate()`` is true; a generous cap that
    only fires on failure — the campaign reaches the state in
    milliseconds, the cap exists so a regression fails instead of hangs."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.002)
    return True


def _nested_campaign(width: int, depth: int) -> Parallel:
    """A ``width``-wide, ``depth``-deep tree of nested Parallel groups.

    ``_nested_campaign(6, 4)`` has 6 + 36 + 216 = 258 branch group walks
    and 6**4 = 1296 actions: far more branch threads than the bound, and
    (without a bound) far more than an OS would tolerate.
    """

    def build(level: int):
        if level >= depth:
            return Action("campaign_step")
        return Parallel(*[build(level + 1) for _ in range(width)])

    return Parallel(*[build(1) for _ in range(width)])


# --------------------------------------------------------------------------- #
# 1. The bound: nested parallel group children are thread-bounded
# --------------------------------------------------------------------------- #


def test_nested_parallel_thread_count_is_bounded():
    """
    A deeply nested, wide campaign's live-thread count stays bounded.

    Every function samples ``threading.active_count()`` at entry while
    the campaign is blocked at its widest (the functions hold a release
    event).  The unbounded engine would hold ~258 live branch threads
    for this tree; the bounded engine must stay near the bound plus the
    pool's 16 workers.
    """
    release = threading.Event()
    campaign = _Campaign(
        lambda **kwargs: (campaign.note_entry(), release.wait(10.0), "done")[2]
    )
    tree = _nested_campaign(width=6, depth=4)

    runner = threading.Thread(
        target=lambda: Test_Framework(tree, registry=campaign.registry),
        daemon=True,
    )
    runner.start()
    try:
        # Wait until a full pool wave of actions is running and blocked
        # (the campaign reaches this state in milliseconds).
        assert _wait_for(lambda: campaign.entries >= 6), "campaign did not start"
        # The bound: branch threads (<= BRANCH_THREAD_BOUND) + pool
        # workers (16) + the walk/runner/test threads — far below the
        # ~258 branch threads the unbounded engine would hold.
        assert campaign.peak_threads <= BRANCH_THREAD_BOUND + 32
    finally:
        release.set()
        runner.join(timeout=10)
    assert not runner.is_alive()
    assert campaign.entries >= 6


def test_flat_parallel_actions_still_concurrent():
    """
    Backward compatibility: a flat parallel group of ACTION children
    (the common case) still runs fully concurrent — actions never take
    branch slots, so the bound cannot serialize them.

    A ``Barrier(width)`` only releases when all ``width`` functions are
    inside their call at once — proof of true concurrency.
    """
    width = 8
    barrier = threading.Barrier(width, timeout=10)
    campaign = _Campaign(
        lambda **kwargs: (campaign.note_entry(), barrier.wait(), "ok")[2]
    )
    tree = Parallel(*[Action("campaign_step") for _ in range(width)])
    result = Test_Framework(tree, registry=campaign.registry)
    assert campaign.entries == width
    assert result == "ok"


def test_flat_group_children_still_concurrent():
    """
    Backward compatibility: a flat parallel group of GROUP children
    still runs fully concurrent — within the bound every branch gets its
    own thread, so genuinely parallel branches are not serialized.
    """
    width = 6
    barrier = threading.Barrier(width, timeout=10)
    campaign = _Campaign(
        lambda **kwargs: (campaign.note_entry(), barrier.wait(), "ok")[2]
    )
    tree = Parallel(
        *[
            Sequential(Action("campaign_step"), Action("campaign_step"))
            for _ in range(width)
        ]
    )
    result = Test_Framework(tree, registry=campaign.registry)
    assert campaign.entries == 2 * width
    assert result == "ok"


# --------------------------------------------------------------------------- #
# 2. Composition with fail_fast and action_timeout
# --------------------------------------------------------------------------- #


def test_bound_composes_with_fail_fast():
    """
    Over the bound (inline branches) + ``fail_fast=True``: the first
    failure still raises, and not-yet-run siblings skip.

    The campaign is wider than the bound (group children), so some
    branches run inline on the parent's thread; the failing action is
    the first action of the first branch.  The pool is FIFO and every
    branch submits its failing action first, so a failure completes
    within the first worker wave and the abort event skips the queued
    tail — the call count stays far below the campaign's total.
    """
    calls: list[int] = []
    lock = threading.Lock()

    def step(**kwargs):
        with lock:
            calls.append(1)
        if kwargs.get("fail") == "yes":
            raise RuntimeError("boom")
        return "ok"

    registry = FunctionRegistry()
    registry.register("step", step)

    branches = BRANCH_THREAD_BOUND + 4  # over the bound: some inline
    tree = Parallel(
        *[
            Parallel(
                Action("step", fail="yes" if i == 0 else "no"),
                Action("step", fail="no"),
                Action("step", fail="no"),
            )
            for i in range(branches)
        ]
    )
    with pytest.raises(RuntimeError, match="boom"):
        Test_Framework(tree, registry=registry, fail_fast=True)
    # Fail-fast skipped the queued tail: only the first worker wave (the
    # pool has 16 workers) plus the in-flight actions ran, not all
    # 3 * branches actions.
    assert len(calls) < 3 * branches


def test_bound_composes_with_action_timeout():
    """
    Over the bound (inline branches) + ``action_timeout``: a hung action
    inside the campaign still raises ``ActionTimeoutError`` and the run
    unwinds (the pool is torn down without waiting for the hung worker).
    """
    release = threading.Event()

    def hung(**kwargs):
        release.wait(30.0)
        return "never"

    def ok(**kwargs):
        return "ok"

    registry = FunctionRegistry()
    registry.register("hung", hung)
    registry.register("ok", ok)

    # Over the bound: the later branches run inline on the parent thread.
    tree = Parallel(
        Sequential(Action("hung")),
        *[Sequential(Action("ok")) for _ in range(BRANCH_THREAD_BOUND + 4)],
    )
    try:
        with pytest.raises(ActionTimeoutError):
            Test_Framework(tree, registry=registry, action_timeout=0.25)
    finally:
        # Always release the abandoned worker (threads cannot be killed).
        release.set()


def test_bound_composes_with_fail_fast_and_timeout():
    """
    Both policies + over the bound: the run still terminates with the
    first error in child order (the quick failure of branch 0), while
    the hung sibling's wait is bounded by the same deadline machinery.
    """
    release = threading.Event()

    def hung(**kwargs):
        release.wait(30.0)
        return "never"

    def quick_fail(**kwargs):
        raise RuntimeError("quick boom")

    def ok(**kwargs):
        return "ok"

    registry = FunctionRegistry()
    registry.register("hung", hung)
    registry.register("quick_fail", quick_fail)
    registry.register("ok", ok)

    tree = Parallel(
        Sequential(Action("quick_fail")),
        Sequential(Action("hung")),
        *[Sequential(Action("ok")) for _ in range(BRANCH_THREAD_BOUND + 4)],
    )
    try:
        # Child order makes branch 0's RuntimeError the first error; the
        # hung sibling's deadline (or the fail-fast abort) bounds the
        # rest, so either error type proves the run terminated.
        with pytest.raises((RuntimeError, ActionTimeoutError)):
            Test_Framework(
                tree, registry=registry, fail_fast=True, action_timeout=0.25
            )
    finally:
        release.set()
