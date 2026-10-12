"""
Tests for execution history and deterministic replay
(``sequence_extensions.workflow.history``) and the engine's opt-in
``history`` hooks (``run_workflow`` / ``Test_Framework``).

Coverage:

* sequential / parallel / nested / dynamically-spliced workflows record
  what ACTUALLY executed, in true completion order, with deterministic
  gapless order indices and group paths;
* resolved parameters (globals, upstream results, own parameters) are
  captured per action;
* the collector is thread-safe under parallelism (no lost or duplicated
  records, gapless numbering) both directly and through the engine;
* ``replay`` re-executes the recorded actions (call counters double) and
  returns the same final result AND the same per-action results;
* the default-off contract: without a ``history`` argument the engine
  behaves exactly as before (same result, nothing recorded anywhere).
"""

import inspect
import threading

import pytest

from sequence_extensions import (
    Action,
    FunctionRegistry,
    Parallel,
    Sequential,
    Test_Framework,
    run_workflow,
)
from sequence_extensions.workflow.history import (
    ExecutionRecord,
    RunHistory,
    recordable_result,
    replay,
    replay_records,
    resolve_group_path,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _registry(**functions):
    """Build a per-test registry mapping names to callables (no shared state)."""
    registry = FunctionRegistry()
    for name, fn in functions.items():
        registry.register(name, fn)
    return registry


def _counter_registry():
    """A registry of counting stubs: ``a``/``b``/``c`` return their name."""
    counts = {}
    lock = threading.Lock()
    registry = FunctionRegistry()

    def make(name):
        def stub(**kwargs):
            with lock:
                counts[name] = counts.get(name, 0) + 1
            return name.upper()

        stub.__name__ = name
        return stub

    for name in ("a", "b", "c"):
        registry.register(name, make(name))
    return registry, counts


def _names(history):
    """The recorded action names, in completion order."""
    return [record.name for record in history]


def _orders(history):
    """The recorded order indices, in completion order."""
    return [record.order for record in history]


# --------------------------------------------------------------------------- #
# 1. SEQUENTIAL WORKFLOWS
# --------------------------------------------------------------------------- #


def test_sequential_records_every_action_in_completion_order():
    """A sequential run records one record per action, in execution order."""
    registry, _ = _counter_registry()
    history = RunHistory()
    result = run_workflow(
        "<sequential><action function='a'/><action function='b'/></sequential>",
        registry=registry,
        history=history,
    )
    assert result == "B"
    assert _names(history) == ["a", "b"]
    assert _orders(history) == [0, 1]


def test_sequential_record_fields_capture_the_call_evidence():
    """Each record carries name, function, resolved params, result and timing."""
    registry = FunctionRegistry()

    def add(**kwargs):
        return kwargs["x"] + kwargs["y"]

    registry.register("add", add)
    history = RunHistory()
    run_workflow(
        "<sequential><action function='add'>"
        "<argument key='x' value='2'/><argument key='y' value='3'/>"
        "</action></sequential>",
        registry=registry,
        history=history,
    )
    (record,) = history.records
    assert isinstance(record, ExecutionRecord)
    assert record.name == "add"
    assert record.function == "add"
    # XML argument values stay strings (params.py only normalizes 'values').
    assert record.params == {"x": "2", "y": "3"}
    assert record.result == "23"
    assert record.exception is None
    assert record.dynamic is False
    assert 0.0 < record.started_at <= record.ended_at


def test_sequential_group_paths_and_deterministic_indices():
    """Group paths locate each action in the tree; indices are 0..n-1."""
    registry, _ = _counter_registry()
    history = RunHistory()
    run_workflow(
        "<sequential><action function='a'/><action function='b'/></sequential>",
        registry=registry,
        history=history,
    )
    assert [record.group_path for record in history] == [
        "root/action[0]",
        "root/action[1]",
    ]
    assert sorted(_orders(history)) == [0, 1]


def test_records_capture_resolved_params_globals_and_upstream():
    """Params are the RESOLVED call kwargs: globals, upstream results, own."""
    registry = FunctionRegistry()

    def echo(**kwargs):
        return dict(kwargs)

    registry.register("echo", echo)
    history = RunHistory()
    result = run_workflow(
        "<VerificationWorkflow><argument key='model' value='./m1'/>"
        "<sequential><action function='echo'>"
        "<argument key='x' value='1'/></action>"
        "<action function='echo'/></sequential></VerificationWorkflow>",
        registry=registry,
        history=history,
    )
    first, second = history.records
    # Own parameters win over globals; globals are passed to every function.
    # (XML argument values stay strings; params.py only normalizes 'values'.)
    assert first.params == {"model": "./m1", "x": "1"}
    # Upstream results are keyed by the producing action's function name.
    assert second.params == {"model": "./m1", "echo": {"model": "./m1", "x": "1"}}
    assert result == second.result


# --------------------------------------------------------------------------- #
# 2. PARALLEL AND NESTED WORKFLOWS
# --------------------------------------------------------------------------- #


def test_parallel_records_all_children_with_gapless_indices():
    """A parallel run records every child exactly once, indices 0..n-1."""
    registry, _ = _counter_registry()
    history = RunHistory()
    result = run_workflow(
        "<parallel><action function='a'/><action function='b'/><action function='c'/></parallel>",
        registry=registry,
        history=history,
    )
    assert result == "C"
    assert sorted(_names(history)) == ["a", "b", "c"]
    assert sorted(_orders(history)) == [0, 1, 2]
    assert len(set(_orders(history))) == 3


def test_parallel_records_true_completion_order():
    """Records are appended at call COMPLETION, not tree order."""
    registry = FunctionRegistry()
    fast_done = threading.Event()

    def slow(**kwargs):
        fast_done.wait(timeout=5)
        return "slow"

    def fast(**kwargs):
        fast_done.set()
        return "fast"

    registry.register("slow", slow)
    registry.register("fast", fast)
    history = RunHistory()
    run_workflow(
        "<parallel><action function='slow'/><action function='fast'/></parallel>",
        registry=registry,
        history=history,
    )
    # 'slow' starts first (tree order) but completes after 'fast'.
    assert _names(history) == ["fast", "slow"]


def test_nested_group_paths_reflect_the_tree():
    """Paths descend through nested sequential/parallel groups."""
    registry = FunctionRegistry()

    def echo(**kwargs):
        return 1

    registry.register("echo", echo)
    history = RunHistory()
    run_workflow(
        "<sequential><action function='echo'/>"
        "<parallel><action function='echo'/>"
        "<sequential><action function='echo'/></sequential>"
        "</parallel></sequential>",
        registry=registry,
        history=history,
    )
    assert [record.group_path for record in history] == [
        "root/action[0]",
        "root/parallel[1]/action[0]",
        "root/parallel[1]/sequential[1]/action[0]",
    ]


# --------------------------------------------------------------------------- #
# 3. DYNAMIC ADAPTATION (SPLICED ACTIONS)
# --------------------------------------------------------------------------- #


def _splice_registry():
    """A registry whose 'driver' splices a two-action group downstream."""

    def driver(**kwargs):
        return Sequential(Action("a"), Action("b"))

    registry, counts = _counter_registry()
    registry.register("driver", driver)
    return registry, counts


def test_spliced_actions_are_recorded_after_the_driver():
    """Runtime-spliced actions appear as records, downstream of the driver."""
    registry, _ = _splice_registry()
    history = RunHistory()
    result = run_workflow(
        "<sequential><action function='driver'/>"
        "<sequential><action function='c'/></sequential></sequential>",
        registry=registry,
        history=history,
    )
    assert result == "B"
    assert _names(history) == ["driver", "a", "b"]
    assert _orders(history) == [0, 1, 2]


def test_spliced_actions_are_marked_dynamic_with_spliced_paths():
    """Spliced records carry dynamic=True and paths inside the spliced group."""
    registry, _ = _splice_registry()
    history = RunHistory()
    run_workflow(
        "<sequential><action function='driver'/>"
        "<sequential><action function='c'/></sequential></sequential>",
        registry=registry,
        history=history,
    )
    driver, first, second = history.records
    assert driver.dynamic is False
    assert driver.group_path == "root/action[0]"
    assert first.dynamic is True
    assert second.dynamic is True
    assert first.group_path == "root/sequential[1]/action[0]"
    assert second.group_path == "root/sequential[1]/action[1]"


def test_spliced_actions_replay_to_the_same_final_result():
    """A spliced run replays to the same final result, spliced calls included."""
    registry, counts = _splice_registry()
    history = RunHistory()
    result = run_workflow(
        "<sequential><action function='driver'/>"
        "<sequential><action function='c'/></sequential></sequential>",
        registry=registry,
        history=history,
    )
    assert replay(history, registry) == result == "B"
    # The spliced actions really re-executed, not just the parsed ones.
    assert counts["a"] == 2 and counts["b"] == 2


def test_cancelled_group_is_not_recorded():
    """The group replaced by a splice is cancelled: its actions never record."""
    registry, _ = _splice_registry()
    history = RunHistory()
    run_workflow(
        "<sequential><action function='driver'/>"
        "<sequential><action function='c'/></sequential></sequential>",
        registry=registry,
        history=history,
    )
    assert "c" not in _names(history)


# --------------------------------------------------------------------------- #
# 4. THREAD SAFETY
# --------------------------------------------------------------------------- #


def test_history_add_is_thread_safe_under_hammering():
    """Concurrent add() calls produce every record exactly once, gapless."""
    history = RunHistory()
    threads = []
    for thread_index in range(16):

        def hammer(index=thread_index):
            for i in range(200):
                history.add(ExecutionRecord(name=f"t{index}-{i}", function="f"))

        thread = threading.Thread(target=hammer)
        threads.append(thread)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(history) == 16 * 200
    assert sorted(_orders(history)) == list(range(16 * 200))


def test_parallel_workflow_records_without_loss_under_load():
    """A wide parallel workflow records every action exactly once."""
    registry, _ = _counter_registry()
    actions = "".join(f"<action function='{name}'/>" for name in ["a", "b", "c"] * 21)
    history = RunHistory()
    run_workflow(f"<parallel>{actions}</parallel>", registry=registry, history=history)
    assert len(history) == 63
    assert sorted(_orders(history)) == list(range(63))
    assert sorted(_names(history)) == ["a"] * 21 + ["b"] * 21 + ["c"] * 21


# --------------------------------------------------------------------------- #
# 5. REPLAY
# --------------------------------------------------------------------------- #


def test_replay_reexecutes_and_returns_the_same_final_result():
    """Replay recomputes the final result by re-running the recorded calls."""
    registry, counts = _counter_registry()
    history = RunHistory()
    result = run_workflow(
        "<sequential><action function='a'/><action function='b'/></sequential>",
        registry=registry,
        history=history,
    )
    assert counts == {"a": 1, "b": 1}
    assert replay(history, registry) == result == "B"
    # Proof of re-execution, not echoing: every function ran a second time.
    assert counts == {"a": 2, "b": 2}


def test_replay_is_sequential_and_deterministic():
    """Replay executes in recorded order, one action at a time."""
    registry = FunctionRegistry()
    seen = []
    lock = threading.Lock()

    def make(name):
        def stub(**kwargs):
            with lock:
                seen.append(name)
            return name.upper()

        stub.__name__ = name
        return stub

    for name in ("a", "b", "c"):
        registry.register(name, make(name))
    history = RunHistory()
    run_workflow(
        "<parallel><action function='a'/><action function='b'/><action function='c'/></parallel>",
        registry=registry,
        history=history,
    )
    seen.clear()
    replay(history, registry)
    assert seen == _names(history)


def test_replay_per_action_results_match_the_recorded_ones():
    """Every replayed action's result equals its recorded result."""
    registry = FunctionRegistry()

    def echo(**kwargs):
        return dict(kwargs)

    registry.register("echo", echo)
    history = RunHistory()
    run_workflow(
        "<VerificationWorkflow><argument key='g' value='7'/>"
        "<sequential><action function='echo'>"
        "<argument key='x' value='1'/></action>"
        "<parallel><action function='echo'/><action function='echo'/>"
        "</parallel></sequential></VerificationWorkflow>",
        registry=registry,
        history=history,
    )
    assert replay_records(history, registry) == [record.result for record in history]


def test_replay_resolves_functions_through_the_registry():
    """Replay re-resolves names through the registry (unknown name raises)."""
    registry, _ = _counter_registry()
    history = RunHistory()
    run_workflow(
        "<sequential><action function='a'/></sequential>",
        registry=registry,
        history=history,
    )
    empty = FunctionRegistry()
    with pytest.raises(ValueError, match="unknown function: 'a'"):
        replay(history, empty)


def test_replay_of_a_failing_run_reraises_at_the_same_point():
    """A recorded exception is re-raised when its action is replayed."""

    def boom(**kwargs):
        raise RuntimeError("kaput")

    registry = FunctionRegistry()
    registry.register("a", lambda **kwargs: "A")
    registry.register("boom", boom)
    history = RunHistory()
    with pytest.raises(RuntimeError, match="kaput"):
        run_workflow(
            "<sequential><action function='a'/><action function='boom'/></sequential>",
            registry=registry,
            history=history,
        )
    assert _names(history) == ["a", "boom"]
    assert history.records[0].exception is None
    assert isinstance(history.records[1].exception, RuntimeError)
    with pytest.raises(RuntimeError, match="kaput"):
        replay_records(history, registry)


def test_replay_of_empty_workflow_returns_none():
    """An empty workflow records nothing and replays to None."""
    registry, _ = _counter_registry()
    history = RunHistory()
    assert run_workflow("<sequential/>", registry=registry, history=history) is None
    assert len(history) == 0
    assert history.final_order is None
    assert replay(history, registry) is None


def test_test_framework_records_and_replays_python_api_workflows():
    """Test_Framework(seq=..., history=...) records and replays (Listing 10)."""
    registry, _ = _counter_registry()
    history = RunHistory()
    seq = Sequential(
        Action("a"),
        Parallel(Action("b"), Action("c")),
    )
    result = Test_Framework(seq, registry=registry, history=history)
    assert result == "C"
    assert sorted(_names(history)) == ["a", "b", "c"]
    assert replay(history, registry) == result


# --------------------------------------------------------------------------- #
# 6. DEFAULT-OFF CONTRACT
# --------------------------------------------------------------------------- #


def test_history_is_opt_in_and_defaults_to_off():
    """The history parameter defaults to None on both public entry points."""
    for entry in (run_workflow, Test_Framework):
        signature = inspect.signature(entry)
        assert signature.parameters["history"].default is None


def test_without_history_the_result_is_unchanged():
    """Omitting history yields exactly the result a recorded run returns."""
    registry, _ = _splice_registry()
    xml = (
        "<sequential><action function='driver'/>"
        "<sequential><action function='c'/></sequential></sequential>"
    )
    plain = run_workflow(xml, registry=registry)
    history = RunHistory()
    recorded = run_workflow(xml, registry=registry, history=history)
    assert plain == recorded == replay(history, registry)


def test_recording_does_not_change_the_result():
    """Recording a run returns the same value as not recording it."""
    registry, _ = _counter_registry()
    xml = "<parallel><action function='a'/><action function='b'/></parallel>"
    without = run_workflow(xml, registry=registry)
    history = RunHistory()
    with_history = run_workflow(xml, registry=registry, history=history)
    assert without == with_history


# --------------------------------------------------------------------------- #
# 7. HISTORY MODULE UNITS
# --------------------------------------------------------------------------- #


def test_resolve_group_path_finds_nodes_and_rejects_foreign_ones():
    """resolve_group_path walks the tree; foreign nodes yield ''."""
    inner = Sequential(Action("a"))
    root = Sequential(Action("b"), Parallel(inner, Action("c")))
    assert resolve_group_path(root, root) == "root"
    assert resolve_group_path(root, root.children[0]) == "root/action[0]"
    assert resolve_group_path(root, root.children[1]) == "root/parallel[1]"
    assert resolve_group_path(root, inner) == "root/parallel[1]/sequential[0]"
    assert resolve_group_path(root, Action("foreign")) == ""


def test_recordable_result_normalizes_dynamic_adaptation_returns():
    """Node returns become plain descriptors; other values pass through."""
    nodes = Sequential(Action("a", x=1), Parallel(Action("b")))
    assert recordable_result(nodes) == {
        "sequential": [
            {"function": "a", "params": {"x": 1}},
            {"parallel": [{"function": "b", "params": {}}]},
        ]
    }
    assert recordable_result([Action("a")]) == [{"function": "a", "params": {}}]
    assert recordable_result(42) == 42
    assert recordable_result("plain") == "plain"
    assert recordable_result([1, 2]) == [1, 2]


def test_run_history_snapshot_semantics():
    """records/iteration/indexing return completion-ordered snapshots."""
    history = RunHistory()
    for index in range(3):
        history.add(ExecutionRecord(name=f"n{index}", function="f"))
    assert [record.name for record in history] == ["n0", "n1", "n2"]
    assert history[0].name == "n0"
    assert [record.name for record in history[1:]] == ["n1", "n2"]
    snapshot = history.records
    snapshot.append("mutated")
    assert len(history) == 3


# --------------------------------------------------------------------------- #
# 4. EVIDENCE CORRECTNESS (IMP-010 / IMP-011 / IMP-013)
# --------------------------------------------------------------------------- #


def test_record_params_hold_plain_data_not_injected_handles():
    """A dag-declaring action's record.params carries plain data only.

    The engine's injected ``dag`` kwarg (the adaptation handle) is engine
    plumbing, not call evidence: it is stripped from the recorded params and
    its evidence lives in ``record.scope``.
    """
    seen = {}

    def adapter(dag=None, **kwargs):
        seen["dag"] = dag
        return "ok"

    registry = _registry(adapter=adapter)
    history = RunHistory()
    run_workflow(
        "<sequential><action function='adapter'/></sequential>",
        registry=registry,
        history=history,
    )
    assert seen["dag"] is not None  # the handle WAS injected into the call
    record = history.records[0]
    assert "dag" not in record.params  # ... and NOT recorded as a param
    assert record.scope is not None  # its evidence lives in record.scope
    assert record.params == {}  # no globals, no upstreams: plain data only


def test_replay_warns_when_the_registry_drifted():
    """A re-registered name resolving to a different callable warns at replay.

    The record stores the resolved function's name, so a re-registration
    between run and replay (the same registry name now resolving to a
    different callable) is visible instead of silently diverging.
    """
    registry, _ = _counter_registry()
    history = RunHistory()
    run_workflow(
        "<sequential><action function='a'/></sequential>",
        registry=registry,
        history=history,
    )
    drifted = _registry()
    drifted.register("a", lambda **kwargs: "different")
    with pytest.warns(UserWarning, match="registry changed"):
        replayed = replay(history, drifted)
    assert replayed == "different"  # the replay re-runs the drifted callable


def test_record_duration_is_monotonic_and_bounded_by_the_wall_stamps():
    """``duration`` is a time.monotonic() measurement (IMP-010).

    The wall-clock ``started_at`` / ``ended_at`` stamps remain the audit
    record; the duration is taken from a monotonic clock so a wall-clock
    adjustment between the stamps cannot corrupt it.
    """
    gate = threading.Event()

    def work(**kwargs):
        assert gate.wait(timeout=5)
        return "done"

    registry = _registry(work=work)
    threading.Timer(0.05, gate.set).start()
    history = RunHistory()
    run_workflow(
        "<sequential><action function='work'/></sequential>",
        registry=registry,
        history=history,
    )
    record = history.records[0]
    wall = record.ended_at - record.started_at
    assert record.duration > 0.0
    assert record.duration <= wall + 0.2


def test_history_carries_the_run_identity():
    """Records carry the history's ``run_id``; ``source`` is the digest (IMP-011).

    ``run_id`` is a fresh uuid4 hex per history; ``source`` is the sha256 of
    the workflow XML the engine stamps at run start (``None`` before a run).
    """
    import hashlib

    registry, _ = _counter_registry()
    history = RunHistory()
    assert history.source is None  # nothing stamped before a run
    xml = "<sequential><action function='a'/></sequential>"
    run_workflow(xml, registry=registry, history=history)
    assert len(history.run_id) == 32  # a uuid4 hex
    assert history.source == hashlib.sha256(xml.encode("utf-8")).hexdigest()
    assert all(record.run_id == history.run_id for record in history)


def test_params_mode_summary_records_bulk_payloads_as_item_counts():
    """``params_mode="summary"`` records dict/list/tuple params as counts (IMP-011).

    The call itself is unchanged — the record is the history-side half of the
    by-reference split (the artifact store is the by-reference plane).
    """
    received = {}

    def bulk(**kwargs):
        received.update(kwargs)
        return "ok"

    registry = _registry(bulk=bulk)
    history = RunHistory()
    Test_Framework(
        Sequential(Action("bulk", payload=[1, 2, 3], note="x")),
        registry=registry,
        history=history,
        params_mode="summary",
    )
    assert received["payload"] == [1, 2, 3]  # the call got the full value
    assert history.records[0].params == {"payload": 3, "note": "x"}
    # Full mode (the default) records the resolved value as before.
    full = RunHistory()
    Test_Framework(
        Sequential(Action("bulk", payload=[1, 2, 3])),
        registry=registry,
        history=full,
    )
    assert full.records[0].params == {"payload": [1, 2, 3]}


def test_action_description_is_recorded():
    """The XML ``description`` attribute lands on the record (IMP-013)."""
    registry = _registry()
    registry.register("labeled", lambda **kwargs: "ok")
    history = RunHistory()
    run_workflow(
        "<sequential><action function='labeled' description='check the model'/></sequential>",
        registry=registry,
        history=history,
    )
    assert history.records[0].description == "check the model"
    # A node without one records None.
    run_workflow(
        "<sequential><action function='labeled'/></sequential>",
        registry=registry,
        history=history,
    )
    assert history.records[1].description is None


# --------------------------------------------------------------------------- #
# 5. PERSISTENCE: to_json / from_json round-trip (finding 4d)
# --------------------------------------------------------------------------- #


def test_to_json_from_json_round_trips_the_fields_that_matter():
    """A run history serializes to JSON and back, preserving everything
    that matters: records (in completion order), run_id, source,
    params_mode, final_order, and every record field."""
    registry, _ = _counter_registry()
    history = RunHistory()
    xml = "<sequential><action function='a'/><action function='b'/></sequential>"
    run_workflow(xml, registry=registry, history=history)
    assert history.final_order is not None

    document = history.to_json()
    restored = RunHistory.from_json(document)

    # Run-level identity.
    assert restored.run_id == history.run_id
    assert restored.source == history.source
    assert restored.params_mode == history.params_mode
    assert restored.final_order == history.final_order
    # Records: same count, same completion order, same fields.
    assert len(restored) == len(history)
    for original, back in zip(history, restored):
        assert back.name == original.name
        assert back.function == original.function
        assert back.params == original.params
        assert back.result == original.result
        assert back.exception is None
        assert back.started_at == original.started_at
        assert back.ended_at == original.ended_at
        assert back.order == original.order
        assert back.group_path == original.group_path
        assert back.dynamic == original.dynamic
        assert back.adaptations == original.adaptations
        assert back.scope == original.scope
        assert back.artifacts == original.artifacts
        assert back.description == original.description
        assert back.run_id == original.run_id
        assert back.duration == original.duration


def test_round_trip_preserves_dynamic_and_failed_records():
    """Spliced (dynamic) records and a recorded exception survive the
    round-trip: the exception becomes a typed placeholder (its type name
    and message preserved), the dynamic flag and order indices stay."""
    registry = _registry()
    registry.register("boom", lambda **kwargs: 1 / 0)
    history = RunHistory()
    with pytest.raises(ZeroDivisionError):
        run_workflow(
            "<sequential><action function='boom'/></sequential>",
            registry=registry,
            history=history,
        )
    restored = RunHistory.from_json(history.to_json())
    assert len(restored) == 1
    record = restored.records[0]
    assert record.name == "boom"
    assert record.exception is not None
    assert record.exception.type_name == "ZeroDivisionError"
    assert record.exception.repr  # the repr survived
    assert record.exception.message  # str(exc) survived
    assert record.result is None
    assert restored.final_order is None  # a failed run marks no final


def test_round_trip_of_a_plain_history_is_byte_stable():
    """Serializing the same history twice yields the same document
    (deterministic), and a double round-trip is a fixed point."""
    registry, _ = _counter_registry()
    history = RunHistory()
    run_workflow(
        "<sequential><action function='a'/></sequential>",
        registry=registry,
        history=history,
    )
    once = history.to_json()
    twice = history.to_json()
    assert once == twice
    assert RunHistory.from_json(once).to_json() == once


def test_non_json_params_serialize_as_placeholders_never_crash():
    """The documented policy for non-JSON-serializable params: a live
    object (the IMP-010 ``dag``-handle shape) becomes a typed
    placeholder — the serializer never crashes, and plain data in the
    SAME params dict is never dropped or altered."""

    class LiveHandle:
        """A stand-in for a live dag handle kept in a record's params."""

        def __repr__(self):
            return "<live-handle>"

    history = RunHistory()
    handle = LiveHandle()
    record = ExecutionRecord(
        name="keep",
        function="keep",
        params={"handle": handle, "count": 3, "label": "x", "nested": {"a": [1, 2]}},
        result="ok",
        run_id=history.run_id,
    )
    history.add(record)

    document = history.to_json()  # must not raise
    restored = RunHistory.from_json(document)
    params = restored.records[0].params
    # The live object comes back as its placeholder (a reference, not a
    # handle): the type name and repr survive.
    placeholder = params["handle"]
    assert placeholder.type_name == "LiveHandle"
    assert placeholder.repr == "<live-handle>"
    # Plain data in the same dict round-trips exactly.
    assert params["count"] == 3
    assert params["label"] == "x"
    assert params["nested"] == {"a": [1, 2]}
    # The placeholder is deterministic: re-serializing the restored
    # history yields the same document.
    assert restored.to_json() == document


def test_non_json_result_and_exception_serialize_as_placeholders():
    """The policy applies to every value, not just params: a non-JSON
    result and a non-JSON exception both become typed placeholders."""
    history = RunHistory()
    record = ExecutionRecord(
        name="weird",
        function="weird",
        result=object(),
        exception=ValueError("bad input"),
        run_id=history.run_id,
    )
    history.add(record)
    restored = RunHistory.from_json(history.to_json())
    back = restored.records[0]
    assert back.result.type_name == "object"
    assert back.exception.type_name == "ValueError"
    assert back.exception.message == "bad input"


def test_from_json_rejects_invalid_documents():
    """``from_json`` raises ``ValueError`` for documents that are not
    ``to_json`` documents (not JSON, not an object, missing keys)."""
    with pytest.raises(ValueError):
        RunHistory.from_json("not json at all")
    with pytest.raises(ValueError):
        RunHistory.from_json("[1, 2, 3]")
    with pytest.raises(ValueError):
        RunHistory.from_json('{"run_id": "x"}')  # no records
    with pytest.raises(ValueError):
        RunHistory.from_json('{"records": []}')  # no run_id


def test_run_level_seed_survives_the_json_round_trip():
    """The run-level ``seed`` (finding 4e) serializes and deserializes.

    A randomized campaign stamps its seed on the run history (the caller
    sets ``history.seed``); the serializer preserves it so a deserialized
    history still names the seed its scenarios were drawn from.  A history
    that used no randomization round-trips ``seed=None``.
    """
    registry, _ = _counter_registry()
    history = RunHistory()
    history.seed = 1234  # the caller stamps the campaign's seed
    run_workflow(
        "<sequential><action function='a'/></sequential>",
        registry=registry,
        history=history,
    )
    document = history.to_json()
    restored = RunHistory.from_json(document)
    assert restored.seed == 1234
    # A double round-trip is a fixed point (the seed is plain data).
    assert RunHistory.from_json(restored.to_json()).seed == 1234
    # No randomization: the seed stays None through the round-trip.
    plain = RunHistory()
    run_workflow(
        "<sequential><action function='a'/></sequential>",
        registry=registry,
        history=plain,
    )
    assert plain.seed is None
    assert RunHistory.from_json(plain.to_json()).seed is None
