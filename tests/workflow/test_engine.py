"""
Tests for the workflow execution engine (``sequence_extensions.workflow.engine``):
``run_workflow`` / ``Test_Framework`` and execution semantics — sequential
ordering, parallel concurrency and fan-in, global-parameter propagation,
dynamic adaptation (splicing), scope restriction, and single execution.
"""

import threading
from pathlib import Path

from sequence_extensions import (
    Action,
    FunctionRegistry,
    Sequential,
    Test_Framework,
    run_workflow,
)

from . import LISTING_7, LISTING_9, _make_recorder, _names_in_order

# --------------------------------------------------------------------------- #
# 5. PYTHON API — Listing 10
# --------------------------------------------------------------------------- #


def test_listing_10_python_api_returns_final_result():
    """Listing 10 runs via Test_Framework(parameters=..., seq=...) and returns a result."""
    common_parameters = {"model": "./model_1"}
    simulate_seq = Sequential(Action("simulate"))
    sweep_seq = Sequential(
        Action("parameter_sweep", parameter_name="parameter_1", values=[5, 10, 15]),
        simulate_seq,
        Action("compare_parameter_sweep"),
    )
    top_seq = Sequential(
        Action("find_test_cases", path="./test"),
        sweep_seq,
        Action("compare_results"),
    )
    # The paper stubs self-register in DEFAULT_REGISTRY, so the engine's
    # default registry path is used (no explicit registry=).
    result = Test_Framework(parameters=common_parameters, seq=top_seq)
    # The final result is the return value of the last action (compare_results).
    assert result is not None


def test_parameter_sweep_normalizes_string_to_list():
    """The string "5, 10, 15" is normalized to [5, 10, 15] before the stub runs."""
    received = {}

    def sweep(parameter_name=None, values=None, **kwargs):
        received["values"] = values
        return values

    registry = FunctionRegistry()
    registry.register("parameter_sweep", sweep)
    xml = (
        "<sequential>"
        '<action function="parameter_sweep">'
        '<argument key="parameter_name" value="parameter_1"/>'
        '<argument key="values" value="5, 10, 15"/>'
        "</action>"
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    assert received["values"] == [5, 10, 15]


# --------------------------------------------------------------------------- #
# 6. SEMANTICS — <sequential> strict order
# --------------------------------------------------------------------------- #


def test_sequential_strict_order():
    """Children of a <sequential> run in child order."""
    registry, calls = _make_recorder(["a", "b", "c"])
    xml = (
        "<sequential>"
        '<action function="a"/>'
        '<action function="b"/>'
        '<action function="c"/>'
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    assert _names_in_order(calls) == ["a", "b", "c"]


# --------------------------------------------------------------------------- #
# 7. SEMANTICS — <parallel> concurrency + fan-in
# --------------------------------------------------------------------------- #


def test_parallel_children_run_concurrently():
    """Two children that block on a barrier only complete if run in parallel."""
    barrier = threading.Barrier(2)

    def block_a(**kwargs):
        barrier.wait(timeout=5)
        return "a"

    def block_b(**kwargs):
        barrier.wait(timeout=5)
        return "b"

    registry = FunctionRegistry()
    registry.register("block_a", block_a)
    registry.register("block_b", block_b)
    xml = '<parallel><action function="block_a"/><action function="block_b"/></parallel>'
    # If the children ran serially the barrier would never be satisfied and
    # barrier.wait would raise BrokenBarrierError (timeout) -> the test fails.
    run_workflow(xml, registry=registry)


def test_parallel_results_fan_in_to_downstream():
    """A downstream action receives the results of a Parallel group's children."""
    received = {}

    def left(**kwargs):
        return 10

    def right(**kwargs):
        return 32

    def combine(**kwargs):
        received.update(kwargs)
        return sum(v for v in kwargs.values() if isinstance(v, int))

    registry = FunctionRegistry()
    registry.register("left", left)
    registry.register("right", right)
    registry.register("combine", combine)
    xml = (
        "<sequential>"
        "<parallel>"
        '<action function="left"/>'
        '<action function="right"/>'
        "</parallel>"
        '<action function="combine"/>'
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    # The fan-in must deliver both children's results to the downstream action.
    assert 10 in received.values()
    assert 32 in received.values()


# --------------------------------------------------------------------------- #
# 8. SEMANTICS — global-parameter propagation + override
# --------------------------------------------------------------------------- #


def test_global_parameters_propagate_and_override():
    """Globals reach every action; an action's own param overrides the global."""
    received = {}

    def record(**kwargs):
        received.setdefault("calls", []).append(dict(kwargs))
        return None

    registry = FunctionRegistry()
    registry.register("a", record)
    registry.register("b", record)
    xml = (
        "<VerificationWorkflow>"
        '<argument key="model" value="global_model"/>'
        "<sequential>"
        '<action function="a"/>'
        '<action function="b"><argument key="model" value="own_model"/></action>'
        "</sequential>"
        "</VerificationWorkflow>"
    )
    run_workflow(xml, registry=registry)
    calls = received["calls"]
    assert len(calls) == 2
    # Global reaches the action that does not override it.
    assert calls[0].get("model") == "global_model"
    # The action's own param wins over the global of the same name.
    assert calls[1].get("model") == "own_model"


# --------------------------------------------------------------------------- #
# 9. SEMANTICS — dynamic adaptation (splicing)
# --------------------------------------------------------------------------- #


def test_dynamic_adaptation_splices_per_file(tmp_path):
    """find_files returns per-file simulate+evaluate_results nodes that run once each."""
    storage = tmp_path / "file_storage"
    storage.mkdir()
    for i in range(3):
        (storage / f"case_{i}.csv").write_text("x,y\n1,2\n")

    simulate_calls = []
    evaluate_calls = []

    def find_files(path, pattern="*.csv", **kwargs):
        import glob

        files = sorted(glob.glob(str(Path(path) / pattern)))
        nodes = []
        for f in files:
            nodes.append(Sequential(Action("simulate", file=f), Action("evaluate_results", file=f)))
        return nodes

    def simulate(file=None, **kwargs):
        simulate_calls.append(file)
        return file

    def evaluate_results(file=None, **kwargs):
        evaluate_calls.append(file)
        return file

    registry = FunctionRegistry()
    registry.register("find_files", find_files)
    registry.register("simulate", simulate)
    registry.register("evaluate_results", evaluate_results)

    xml = (
        "<sequential>"
        f'<action function="find_files"><argument key="path" value="{storage}"/></action>'
        "<sequential>"
        '<action function="simulate"/>'
        '<action function="evaluate_results"/>'
        "</sequential>"
        "</sequential>"
    )

    run_workflow(xml, registry=registry)
    # The spliced actions executed once per found file.
    assert len(simulate_calls) == 3
    assert len(evaluate_calls) == 3
    assert set(simulate_calls) == set(evaluate_calls)


# --------------------------------------------------------------------------- #
# 10. SEMANTICS — scope restriction (Listing 7)
# --------------------------------------------------------------------------- #


def test_scope_restriction_inner_may_replace_next_action_sibling():
    """An inner action may splice its next ACTION sibling (Listing 7, F1 fix).

    inner_action_1 returns a node that replaces its next sibling
    inner_action_2 — an ACTION, not a group.  The paper explicitly allows
    this ("inner_action_1 can only alter actions downstream within its
    grouping scope, more specifically inner_action_2"), so the splice
    succeeds: injected_outer runs in inner_action_2's place (which never
    runs), and the outer scope is untouched.
    """
    calls = []

    def inner_action_1(**kwargs):
        # Replace the next sibling (inner_action_2, an action) in-scope.
        calls.append("inner_action_1")
        return Action("injected_outer")

    def inner_action_2(**kwargs):
        calls.append("inner_action_2")
        return "inner2"

    def outer_action_1(**kwargs):
        calls.append("outer_action_1")
        return "outer1"

    def outer_action_2(**kwargs):
        calls.append("outer_action_2")
        return "outer2"

    def injected_outer(**kwargs):
        calls.append("injected_outer")
        return "injected"

    registry = FunctionRegistry()
    registry.register("outer_action_1", outer_action_1)
    registry.register("outer_action_2", outer_action_2)
    registry.register("inner_action_1", inner_action_1)
    registry.register("inner_action_2", inner_action_2)
    registry.register("injected_outer", injected_outer)

    result = run_workflow(LISTING_7, registry=registry)

    # The spliced action ran in inner_action_2's place; inner_action_2 never
    # ran; the outer scope (outer_action_2) still runs after the inner one.
    assert "injected_outer" in calls
    assert "inner_action_2" not in calls
    # The outer scope is untouched: both outer actions ran, in order.
    assert "outer_action_1" in calls and "outer_action_2" in calls
    assert calls.index("outer_action_1") < calls.index("outer_action_2")
    assert result == "outer2"


def test_scope_restriction_outer_may_affect_inner():
    """An outer action may adapt a following group's subtree (Listing 7).

    The paper: "outer_action_1 can alter everything downstream, including
    the inner actions."  Here outer_action_1 (a handle driver) reaches into
    the FOLLOWING inner group's subtree and adjusts an inner action's
    parameter — the outer case of Listing 7.  The inner action runs with the
    adjusted value, proving the outer action's write landed inside the
    following group's subtree (in scope for the outer action).
    """
    received = {}

    def outer_action_1(dag, **kwargs):
        # The following sibling is the inner group; reach into its subtree
        # and adjust the second inner action's parameter (in scope: an outer
        # action may alter everything downstream, including inner actions).
        inner_group = dag.following_group()
        dag.adjust(inner_group.children[1], level="retuned")
        return "outer1"

    def inner_action_1(**kwargs):
        return "inner1"

    def inner_action_2(level=None, **kwargs):
        received["level"] = level
        return "inner2"

    def outer_action_2(**kwargs):
        return "outer2"

    registry = FunctionRegistry()
    registry.register("outer_action_1", outer_action_1)
    registry.register("outer_action_2", outer_action_2)
    registry.register("inner_action_1", inner_action_1)
    registry.register("inner_action_2", inner_action_2)

    # Must run without raising: the outer action's write into the following
    # group's subtree is in scope.
    run_workflow(LISTING_7, registry=registry)
    # The inner action ran with the outer action's adjustment.
    assert received["level"] == "retuned"


# --------------------------------------------------------------------------- #
# 11. SEMANTICS — each action executes at most once
# --------------------------------------------------------------------------- #


def test_each_action_executes_at_most_once():
    """No action is invoked more than once (no feedback loops)."""
    registry, calls = _make_recorder(["a", "b", "c"])
    xml = (
        "<sequential>"
        '<action function="a"/>'
        '<action function="b"/>'
        '<action function="c"/>'
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    counts = {}
    for name, _ in calls:
        counts[name] = counts.get(name, 0) + 1
    assert counts == {"a": 1, "b": 1, "c": 1}


# --------------------------------------------------------------------------- #
# 13. run_workflow end-to-end on Listing 9
# --------------------------------------------------------------------------- #


def test_run_workflow_listing_9_end_to_end(tmp_path):
    """run_workflow(xml, registry=..., parameters=...) on Listing 9 returns a final result."""
    # Provide a real ./test directory so find_test_cases has something to glob.
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    (test_dir / "case_1.csv").write_text("x,y\n1,2\n")

    # Rewrite the path in Listing 9 to the tmp_path so the stub finds the file.
    # The paper stubs (test resources) self-register in DEFAULT_REGISTRY, so
    # the engine's default registry path is used (no explicit registry=).
    xml = LISTING_9.replace("./test", str(test_dir))
    result = run_workflow(xml, parameters={"model": "./model_1"})
    assert result is not None
