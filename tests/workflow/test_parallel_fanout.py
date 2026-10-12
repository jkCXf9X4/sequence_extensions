"""
Tests for PARALLEL FAN-OUT (Finding 1 / 6b of
``docs/critical_review_simulation_workflows.md``): the concurrent map
pattern.

``TreeHandle.fan_out_parallel`` clones the declared downstream scope's
children once per override set, in place, so the clones run as direct
children of the declared group; the workflow's ``DAGHandle`` requires
that group to be a ``Parallel`` scope, and the engine then walks the
clones concurrently.  ``parameter_sweep`` / ``find_files`` expose it as
``parallel=True``.

Coverage:

* **Concurrency without wall-clock flakiness** — the parallel-mode sims
  meet at a ``threading.Barrier`` sized to the clone count: the barrier
  only trips when every clone is inside the function at once, so
  ``max concurrency == N`` is a structural fact, not a timing race.
  The sequential default needs no barrier: the engine strictly
  serializes the clones (one finishes before the next starts), so
  ``max concurrency == 1`` holds by construction.
* **Data plane** — the clones' results flow downstream exactly as the
  sequential fan-out's do (``sim``, ``sim_2``, ...), because the clones
  are direct children of the parallel group, not wrapped in a new
  group (a wrapper would hit the engine's parallel information
  barrier and the results would never reach a following action).
* **Backward compatibility** — the default is unchanged: the same XML
  without ``parallel`` runs the clones one after another, and
  ``fan_out``'s op shape is untouched.
* **The dynamic-node bound** — ``fan_out_parallel``'s clones count
  against the bound exactly as ``fan_out``'s do (one op per declared
  child, each carrying its clones), so a large parallel sweep fails
  loudly at the bound instead of silently exceeding it.
* **Replay** — a recorded parallel sweep replays to the same result
  (the ``ReplayHandle`` inherits the pattern; its writes are no-ops).
* **Errors** — a non-parallel declared body, an empty override list,
  and a non-mapping override each raise ``ValueError``.
"""

from __future__ import annotations

import threading

import pytest

from sequence_extensions import Parallel, Sequential, run_workflow
from sequence_extensions.workflow.adaptation import ADAPTATION_BOUND, DAGHandle
from sequence_extensions.workflow.history import RunHistory, replay
from sequence_extensions.workflow.library import register_library
from sequence_extensions.workflow.registry import FunctionRegistry, workflow_function
from sequence_extensions.workflow.schema import Action


# --------------------------------------------------------------------------- #
# Fixtures: a registry whose `sim` tracks max observed concurrency
# --------------------------------------------------------------------------- #


class _ConcurrencyTracker:
    """
    Thread-safe max-concurrency probe (no wall-clock timing involved).

    ``barrier`` — when set, every ``sim`` call meets at the barrier
    before returning: the barrier has exactly as many parties as there
    are clones, so it trips only when ALL clones are inside their calls
    at once.  A broken barrier (a clone missing) raises, so a
    non-concurrent engine fails loudly instead of flaking.
    """

    def __init__(self, barrier: threading.Barrier | None = None) -> None:
        self._lock = threading.Lock()
        self._current = 0
        self.max_concurrency = 0
        self.barrier = barrier
        self.seen_p: list = []

    def enter(self, p) -> None:
        with self._lock:
            self._current += 1
            self.max_concurrency = max(self.max_concurrency, self._current)
            self.seen_p.append(p)
        if self.barrier is not None:
            self.barrier.wait(timeout=30.0)

    def exit(self) -> None:
        with self._lock:
            self._current -= 1


def _tracker_registry(tracker: _ConcurrencyTracker) -> FunctionRegistry:
    """A registry with the library plus a concurrency-tracking ``sim``."""
    registry = FunctionRegistry()
    register_library(registry)

    @workflow_function(registry=registry)
    def sim(**kwargs):
        tracker.enter(kwargs.get("p", kwargs.get("file")))
        try:
            # `p` at the top level: aggregate(upstream="sim", field="p")
            # reads it from each clone's result.
            return {"p": kwargs.get("p", kwargs.get("file")), "sim": True}
        finally:
            tracker.exit()

    return registry


def _sweep_xml(parallel: bool, values: str = "1, 2, 3, 4") -> str:
    """A parameter_sweep over a parallel body, with or without parallel."""
    flag = '<argument key="parallel" value="true"/>' if parallel else ""
    return (
        "<VerificationWorkflow><scope type=\"sequential\">"
        "<action function=\"parameter_sweep\">"
        "<argument key=\"parameter_name\" value=\"p\"/>"
        f"<argument key=\"values\" value=\"{values}\"/>"
        f"{flag}"
        "</action>"
        "<scope type=\"parallel\"><action function=\"sim\"/></scope>"
        "</scope></VerificationWorkflow>"
    )


def _with_sink(xml: str, sink_xml: str) -> str:
    """Insert ``sink_xml`` before the outer scope's closing tags."""
    return xml.replace("</scope></VerificationWorkflow>",
                       f"{sink_xml}</scope></VerificationWorkflow>")


# --------------------------------------------------------------------------- #
# Concurrency (the Finding-1 headline)
# --------------------------------------------------------------------------- #


def test_parallel_sweep_runs_clones_concurrently():
    """parallel=True walks the clones concurrently (max concurrency == 4).

    The barrier has 4 parties — one per clone — so it trips only when
    all four clones are inside their ``sim`` calls at the same time.
    """
    tracker = _ConcurrencyTracker(barrier=threading.Barrier(4))
    registry = _tracker_registry(tracker)
    run_workflow(_sweep_xml(parallel=True), registry=registry)
    assert tracker.max_concurrency == 4


def test_sequential_sweep_default_runs_clones_one_after_another():
    """Without parallel, the default fan_out runs the clones serially.

    No barrier: the engine strictly serializes the clones (each finishes
    before the next starts), so max concurrency is 1 by construction.
    """
    tracker = _ConcurrencyTracker()
    registry = _tracker_registry(tracker)
    run_workflow(_sweep_xml(parallel=False), registry=registry)
    assert tracker.max_concurrency == 1


def test_parallel_find_files_runs_clones_concurrently(tmp_path):
    """find_files(parallel=True) fans the per-file clones out concurrently."""
    for name in ("a.csv", "b.csv", "c.csv"):
        (tmp_path / name).write_text("x")
    tracker = _ConcurrencyTracker(barrier=threading.Barrier(3))
    registry = _tracker_registry(tracker)
    xml = (
        "<VerificationWorkflow><scope type=\"sequential\">"
        "<action function=\"find_files\">"
        f"<argument key=\"path\" value=\"{tmp_path}\"/>"
        "<argument key=\"parallel\" value=\"true\"/>"
        "</action>"
        "<scope type=\"parallel\"><action function=\"sim\"/></scope>"
        "</scope></VerificationWorkflow>"
    )
    run_workflow(xml, registry=registry)
    assert tracker.max_concurrency == 3


# --------------------------------------------------------------------------- #
# The data plane (why clones are spliced as direct children)
# --------------------------------------------------------------------------- #


def test_parallel_sweep_results_flow_downstream():
    """The clones' results reach a following action, exactly as sequential."""
    tracker = _ConcurrencyTracker(barrier=threading.Barrier(4))
    registry = _tracker_registry(tracker)
    seen: dict[str, list] = {}

    @workflow_function(registry=registry)
    def sink(**kwargs):
        seen["upstream"] = sorted(k for k in kwargs if k.startswith("sim"))
        return {"sink": True}

    xml = _with_sink(_sweep_xml(parallel=True), '<action function="sink"/>')
    run_workflow(xml, registry=registry)
    assert seen["upstream"] == ["sim", "sim_2", "sim_3", "sim_4"]


def test_parallel_sweep_aggregates_downstream():
    """aggregate() over a parallel sweep sees every per-value result."""
    tracker = _ConcurrencyTracker(barrier=threading.Barrier(4))
    registry = _tracker_registry(tracker)
    xml = _with_sink(
        _sweep_xml(parallel=True),
        "<action function=\"aggregate\">"
        "<argument key=\"upstream\" value=\"sim\"/>"
        "<argument key=\"field\" value=\"p\"/>"
        "<argument key=\"op\" value=\"sum\"/>"
        "</action>",
    )
    result = run_workflow(xml, registry=registry)
    # 1 + 2 + 3 + 4 over the four clones' p values
    assert result == {"aggregate": {"op": "sum", "count": 4, "value": 10}}


def test_parallel_and_sequential_sweeps_run_the_same_clones():
    """Both modes run one sim per sweep value, with that value injected."""
    seq_tracker = _ConcurrencyTracker()
    par_tracker = _ConcurrencyTracker(barrier=threading.Barrier(4))
    seq_registry = _tracker_registry(seq_tracker)
    par_registry = _tracker_registry(par_tracker)
    run_workflow(_sweep_xml(parallel=False), registry=seq_registry)
    run_workflow(_sweep_xml(parallel=True), registry=par_registry)
    # The same clone set with the same per-clone overrides — only the
    # scheduling (and therefore the kwargs each clone sees of its
    # siblings) differs between the modes.
    assert sorted(seq_tracker.seen_p, key=str) == sorted(par_tracker.seen_p, key=str)
    assert set(seq_tracker.seen_p) == {1, 2, 3, 4}


# --------------------------------------------------------------------------- #
# Backward compatibility
# --------------------------------------------------------------------------- #


def test_fan_out_op_shape_is_unchanged():
    """fan_out still records ONE replace op carrying the flat clones."""
    root = Sequential(Action("driver"), Sequential(Action("work")))
    handle = DAGHandle(root, 0)
    handle.fan_out([{}, {}, {}])
    (op,) = handle.ops
    assert op.kind == "replace"
    assert len(op.nodes) == 3  # flat clones, no wrapper node


def test_fan_out_parallel_records_one_op_per_declared_child():
    """fan_out_parallel records one replace op per declared child, each
    carrying that child's clones — so the dynamic-node count is exactly
    the number of clones, never a wrapper node."""
    root = Sequential(
        Action("driver"), Parallel(Action("a"), Action("b"))
    )
    handle = DAGHandle(root, 0)
    handle.fan_out_parallel([{}, {}, {}])
    assert len(handle.ops) == 2
    assert all(op.kind == "replace" for op in handle.ops)
    assert [len(op.nodes) for op in handle.ops] == [3, 3]


def test_fan_out_parallel_requires_a_parallel_body():
    """A sequential declared body is rejected with a clear error."""
    root = Sequential(Action("driver"), Sequential(Action("work")))
    handle = DAGHandle(root, 0)
    with pytest.raises(ValueError, match="Parallel"):
        handle.fan_out_parallel([{}])


def test_fan_out_parallel_rejects_empty_and_non_mapping_overrides():
    """The same input rules as fan_out: non-empty, mappings only."""
    root = Sequential(Action("driver"), Parallel(Action("work")))
    handle = DAGHandle(root, 0)
    with pytest.raises(ValueError, match="at least one override"):
        handle.fan_out_parallel([])
    with pytest.raises(ValueError, match="mappings"):
        handle.fan_out_parallel(["not-a-mapping"])


def test_parallel_option_from_xml_string_is_normalized():
    """The parallel option accepts XML strings ('true'/'false', any case)."""
    from sequence_extensions.workflow.library import _as_bool

    assert _as_bool(True, "parameter_sweep") is True
    assert _as_bool(False, "parameter_sweep") is False
    assert _as_bool("true", "parameter_sweep") is True
    assert _as_bool("TRUE", "parameter_sweep") is True
    assert _as_bool("false", "parameter_sweep") is False
    assert _as_bool("False", "parameter_sweep") is False
    with pytest.raises(ValueError, match="parallel"):
        _as_bool("maybe", "parameter_sweep")


# --------------------------------------------------------------------------- #
# The dynamic-node bound
# --------------------------------------------------------------------------- #


def test_fan_out_parallel_clones_count_against_the_bound():
    """fan_out_parallel's clones count against the dynamic-node bound."""
    root = Sequential(Action("driver"), Parallel(Action("work")))
    handle = DAGHandle(root, 0, bound=3)
    handle.fan_out_parallel([{}, {}, {}])  # exactly at the bound
    with pytest.raises(ValueError, match="bound"):
        handle.fan_out_parallel([{}, {}])


def test_large_parallel_sweep_fails_loudly_at_the_engine_bound():
    """A parallel sweep past ADAPTATION_BOUND terminates deterministically."""
    tracker = _ConcurrencyTracker()
    registry = _tracker_registry(tracker)
    values = ",".join(str(v) for v in range(ADAPTATION_BOUND + 10))
    xml = (
        "<VerificationWorkflow><scope type=\"sequential\">"
        "<action function=\"parameter_sweep\">"
        "<argument key=\"parameter_name\" value=\"p\"/>"
        f"<argument key=\"values\" value=\"{values}\"/>"
        "<argument key=\"parallel\" value=\"true\"/>"
        "</action>"
        "<scope type=\"parallel\"><action function=\"sim\"/></scope>"
        "</scope></VerificationWorkflow>"
    )
    with pytest.raises(ValueError, match="bound"):
        run_workflow(xml, registry=registry)


# --------------------------------------------------------------------------- #
# Replay (the history layer must stay compatible)
# --------------------------------------------------------------------------- #


def test_parallel_sweep_replays_to_the_same_result():
    """A recorded parallel sweep replays deterministically (no-op writes).

    No barrier here: replay re-executes the functions against the fake
    tree with no-op writes, so the declared body runs once as declared —
    the point is that the recorded result is reproduced exactly, not
    that replay is concurrent.
    """
    tracker = _ConcurrencyTracker()
    registry = _tracker_registry(tracker)
    history = RunHistory()
    result = run_workflow(_sweep_xml(parallel=True), registry=registry, history=history)
    assert replay(history, registry) == result


def test_parallel_sweep_records_adaptations_as_plain_data():
    """The parallel sweep's ops are recorded as plain, comparable data."""
    tracker = _ConcurrencyTracker(barrier=threading.Barrier(4))
    registry = _tracker_registry(tracker)
    history = RunHistory()
    run_workflow(_sweep_xml(parallel=True), registry=registry, history=history)
    driver = history.records[0]
    assert driver.adaptations
    kinds = {op["kind"] for op in driver.adaptations}
    assert kinds == {"replace"}
