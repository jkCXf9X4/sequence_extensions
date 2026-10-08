"""
Tests for the V&V workflow layer (``Action`` / ``Sequential`` / ``Parallel`` /
``Test_Framework`` / ``FunctionRegistry`` / ``parse_workflow`` /
``run_workflow``).

The workflow layer is specified by the paper "Automation Nation: Taming
Complex V&V Workflows" (16th International Modelica & FMI Conference,
September 2025, Lucerne, Switzerland; DOI 10.3384/ecp12076741).  The XML
fixtures below are the paper's Listing 5 (dynamic adaptation), Listing 9
(full workflow with global parameters) and Listing 10 (Python API).

The suite is written against the pinned public contract and is fully
deterministic: no network, no sleeps, no order dependence.  The paper's
library functions come from the test resources
(``tests/resources/workflow_stubs.py``) and are registered into a
``FunctionRegistry`` explicitly; file-backed stubs (``find_files`` /
``find_test_cases``) are driven with real files created under ``tmp_path``.
"""

import threading
from pathlib import Path

import pytest

from resources import workflow_stubs
from sequence_extensions import (
    DEFAULT_REGISTRY,
    Action,
    FunctionRegistry,
    GraphFuture,
    GraphPool,
    Parallel,
    Sequential,
    Test_Framework,
    parse_workflow,
    run_workflow,
)

# --------------------------------------------------------------------------- #
# Paper fixtures (inline string constants)
# --------------------------------------------------------------------------- #

LISTING_9 = """<VerificationWorkflow>
  <model value="./model_1"/>
  <sequential>
    <action function="find_test_cases">
      <path value="./test"/>
    </action>
    <sequential>
      <action function="parameter_sweep">
        <parameter_name value="parameter_1"/>
        <values value="5, 10, 15"/>
      </action>
      <sequential>
        <action function="simulate"/>
      </sequential>
      <action function="compare_parameter_sweep"/>
    </sequential>
    <action function="compare_results"/>
  </sequential>
</VerificationWorkflow>
"""

LISTING_5 = """<sequential>
  <action function="find_files">
    <path value="file_storage/"/>
  </action>
  <sequential>
    <action function="simulate"/>
    <action function="evaluate_results"/>
  </sequential>
</sequential>
"""

# Listing 7 (dynamic-adaptation scope): outer_action_1 may alter everything
# downstream (including the inner actions); inner_action_1 may only alter
# actions downstream within its own grouping scope (inner_action_2).
LISTING_7 = """<sequential>
  <action function="outer_action_1"/>
  <sequential>
    <action function="inner_action_1"/>
    <action function="inner_action_2"/>
  </sequential>
  <action function="outer_action_2"/>
</sequential>
"""

PAPER_FUNCTION_NAMES = [
    "find_files",
    "simulate",
    "evaluate_results",
    "find_test_cases",
    "parameter_sweep",
    "compare_parameter_sweep",
    "compare_results",
]

#: The paper's stub functions (test resources) keyed by their registry name.
PAPER_STUBS = {
    "find_files": workflow_stubs.find_files,
    "simulate": workflow_stubs.simulate,
    "evaluate_results": workflow_stubs.evaluate_results,
    "find_test_cases": workflow_stubs.find_test_cases,
    "parameter_sweep": workflow_stubs.parameter_sweep,
    "compare_parameter_sweep": workflow_stubs.compare_parameter_sweep,
    "compare_results": workflow_stubs.compare_results,
}


def _paper_registry() -> FunctionRegistry:
    """A fresh registry preloaded with the paper's seven stub functions."""
    registry = FunctionRegistry()
    for name in PAPER_FUNCTION_NAMES:
        registry.register(name, PAPER_STUBS[name])
    return registry


# --------------------------------------------------------------------------- #
# Introspection helpers (robust to the exact attribute names the engine uses)
# --------------------------------------------------------------------------- #


def _children(node):
    """Return the direct children of a group node, whatever the engine calls them."""
    for attr in ("children", "_children", "nodes", "items", "actions", "steps", "elements"):
        value = getattr(node, attr, None)
        if isinstance(value, (list, tuple)) and value:
            return list(value)
    # Fall back to the first list/tuple attribute that holds Action/Sequential/Parallel.
    for value in vars(node).values():
        if (
            isinstance(value, (list, tuple))
            and value
            and all(isinstance(x, (Action, Sequential, Parallel)) for x in value)
        ):
            return list(value)
    raise AssertionError(f"cannot find children of {node!r}")


def _params(node):
    """Return the custom parameters of an Action, whatever the engine calls them."""
    for attr in ("params", "_params", "parameters", "kwargs", "arguments", "args"):
        value = getattr(node, attr, None)
        if isinstance(value, dict):
            return dict(value)
    for value in vars(node).values():
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _function(node):
    """Return the function name of an Action, whatever the engine calls it."""
    for attr in ("function", "name", "fn", "func", "function_name"):
        value = getattr(node, attr, None)
        if isinstance(value, str):
            return value
    raise AssertionError(f"cannot find function name of {node!r}")


def _globals(node):
    """Return the global parameters attached to a parsed root, if any."""
    for attr in ("globals", "global_parameters", "global_params", "parameters", "params"):
        value = getattr(node, attr, None)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _make_recorder(names):
    """Build a registry of recording stubs, one per name, sharing one call log."""
    calls = []
    lock = threading.Lock()

    def make(name):
        def stub(**kwargs):
            with lock:
                calls.append((name, dict(kwargs)))
            return name

        stub.__name__ = name
        return stub

    registry = FunctionRegistry()
    for name in names:
        registry.register(name, make(name))
    return registry, calls


def _names_in_order(calls):
    return [name for name, _ in calls]


# --------------------------------------------------------------------------- #
# 1. PARSING — Listing 9
# --------------------------------------------------------------------------- #


def test_parse_listing_9_structure():
    """Listing 9 parses into the expected nested Sequential/Action structure."""
    root = parse_workflow(LISTING_9)
    assert isinstance(root, Sequential)

    # Global parameter <model value="./model_1"/> is captured on the root.
    assert _globals(root).get("model") == "./model_1"

    top = _children(root)
    assert len(top) == 3

    # top[0]: find_test_cases with path="./test"
    assert isinstance(top[0], Action)
    assert _function(top[0]) == "find_test_cases"
    assert _params(top[0]).get("path") == "./test"

    # top[1]: a nested Sequential of [parameter_sweep, Sequential[simulate],
    # compare_parameter_sweep]
    assert isinstance(top[1], Sequential)
    inner = _children(top[1])
    assert len(inner) == 3
    assert isinstance(inner[0], Action)
    assert _function(inner[0]) == "parameter_sweep"
    assert _params(inner[0]).get("parameter_name") == "parameter_1"
    assert _params(inner[0]).get("values") == "5, 10, 15"

    assert isinstance(inner[1], Sequential)
    sim = _children(inner[1])
    assert len(sim) == 1
    assert isinstance(sim[0], Action)
    assert _function(sim[0]) == "simulate"

    assert isinstance(inner[2], Action)
    assert _function(inner[2]) == "compare_parameter_sweep"

    # top[2]: compare_results
    assert isinstance(top[2], Action)
    assert _function(top[2]) == "compare_results"


# --------------------------------------------------------------------------- #
# 2. PARSING — Listing 5 (and <parallel> -> Parallel)
# --------------------------------------------------------------------------- #


def test_parse_listing_5_structure():
    """Listing 5 parses; find_files is followed by a nested Sequential."""
    root = parse_workflow(LISTING_5)
    assert isinstance(root, Sequential)

    top = _children(root)
    assert len(top) == 2
    assert isinstance(top[0], Action)
    assert _function(top[0]) == "find_files"
    assert _params(top[0]).get("path") == "file_storage/"

    assert isinstance(top[1], Sequential)
    inner = _children(top[1])
    assert len(inner) == 2
    assert _function(inner[0]) == "simulate"
    assert _function(inner[1]) == "evaluate_results"


def test_parse_parallel_group():
    """A <parallel> group parses to a Parallel node with its actions in order."""
    xml = '<parallel><action function="a"/><action function="b"/></parallel>'
    root = parse_workflow(xml)
    assert isinstance(root, Parallel)
    children = _children(root)
    assert len(children) == 2
    assert _function(children[0]) == "a"
    assert _function(children[1]) == "b"


# --------------------------------------------------------------------------- #
# 3. PARSING REJECTION — invalid XML
# --------------------------------------------------------------------------- #


def test_parse_rejects_wrong_root():
    """A root element that is not <VerificationWorkflow> is rejected."""
    with pytest.raises(ValueError):
        parse_workflow("<notaworkflow><sequential/></notaworkflow>")


def test_parse_rejects_zero_top_level_groupings():
    """A <VerificationWorkflow> with no top-level grouping is rejected."""
    with pytest.raises(ValueError):
        parse_workflow('<VerificationWorkflow><model value="m"/></VerificationWorkflow>')


def test_parse_rejects_multiple_top_level_groupings():
    """A <VerificationWorkflow> with two top-level groupings is rejected."""
    xml = (
        "<VerificationWorkflow>"
        "<sequential><action function='a'/></sequential>"
        "<parallel><action function='b'/></parallel>"
        "</VerificationWorkflow>"
    )
    with pytest.raises(ValueError):
        parse_workflow(xml)


def test_parse_rejects_action_without_function():
    """An <action> missing its function attribute is rejected."""
    xml = "<sequential><action/></sequential>"
    with pytest.raises(ValueError):
        parse_workflow(xml)


def test_parse_rejects_unknown_nesting_element():
    """An unknown element inside a grouping is rejected."""
    xml = "<sequential><bogus/></sequential>"
    with pytest.raises(ValueError):
        parse_workflow(xml)


def test_parse_rejects_param_without_value():
    """An action param child missing its value attribute is rejected."""
    xml = "<sequential><action function='a'><path/></action></sequential>"
    with pytest.raises(ValueError):
        parse_workflow(xml)


# --------------------------------------------------------------------------- #
# 4. REGISTRY
# --------------------------------------------------------------------------- #


def test_default_registry_is_empty_by_default():
    """DEFAULT_REGISTRY is empty; workflow functions are registered explicitly."""
    assert DEFAULT_REGISTRY.names() == []


def test_registry_register_get_names():
    """.register / .get / .names work on a fresh FunctionRegistry."""
    registry = FunctionRegistry()

    def my_fn(**kwargs):
        return "ok"

    registry.register("my_fn", my_fn)
    assert "my_fn" in registry.names()
    assert registry.get("my_fn") is my_fn


def test_unknown_action_name_raises_clear_error():
    """An unknown function name at run time raises a ValueError naming it."""
    xml = "<sequential><action function='definitely_not_a_function'/></sequential>"
    with pytest.raises(ValueError, match="definitely_not_a_function"):
        run_workflow(xml)


# --------------------------------------------------------------------------- #
# 5. PYTHON API — Listing 10
# --------------------------------------------------------------------------- #


def test_listing_10_python_api_returns_final_result():
    """Listing 10 runs via Test_Framework(parameters=..., seq=...) and returns a result."""
    common_parameters = {"model": "./model_1"}
    simulate_seq = Sequential(Action("simulate"))
    sweep_seq = Sequential(
        Action("parameter_sweep", parameter="parameter_1", values=[5, 10, 15]),
        simulate_seq,
        Action("compare_parameter_sweep"),
    )
    top_seq = Sequential(
        Action("find_test_cases", path="./test"),
        sweep_seq,
        Action("compare_results"),
    )
    result = Test_Framework(parameters=common_parameters, seq=top_seq, registry=_paper_registry())
    # The final result is the return value of the last action (compare_results).
    assert result is not None


def test_parameter_sweep_normalizes_string_to_list():
    """The string "5, 10, 15" is normalized to [5, 10, 15] before the stub runs."""
    received = {}

    def sweep(parameter_name=None, parameter=None, values=None, **kwargs):
        received["values"] = values
        return values

    registry = FunctionRegistry()
    registry.register("parameter_sweep", sweep)
    xml = (
        "<sequential>"
        '<action function="parameter_sweep">'
        '<parameter_name value="parameter_1"/>'
        '<values value="5, 10, 15"/>'
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
        '<model value="global_model"/>'
        "<sequential>"
        '<action function="a"/>'
        '<action function="b"><model value="own_model"/></action>'
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
        f'<action function="find_files"><path value="{storage}"/></action>'
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


def test_scope_restriction_inner_cannot_affect_outer_siblings():
    """An inner action may only splice within its own grouping scope (Listing 7).

    inner_action_1 returns a node that would add an action to the outer scope
    (a sibling of the inner group).  That out-of-scope splice must be rejected
    with a ValueError.
    """

    def inner_action_1(**kwargs):
        # Attempt to inject an action into the outer scope (out of scope).
        return Action("injected_outer")

    def inner_action_2(**kwargs):
        return "inner2"

    def outer_action_1(**kwargs):
        return "outer1"

    def outer_action_2(**kwargs):
        return "outer2"

    def injected_outer(**kwargs):
        return "injected"

    registry = FunctionRegistry()
    registry.register("outer_action_1", outer_action_1)
    registry.register("outer_action_2", outer_action_2)
    registry.register("inner_action_1", inner_action_1)
    registry.register("inner_action_2", inner_action_2)
    registry.register("injected_outer", injected_outer)

    with pytest.raises(ValueError):
        run_workflow(LISTING_7, registry=registry)


def test_scope_restriction_outer_may_affect_inner():
    """An outer action may splice downstream, including into inner groups (Listing 7)."""

    def outer_action_1(**kwargs):
        # Add an action downstream within the outer scope (allowed).
        return Action("extra")

    def inner_action_1(**kwargs):
        return "inner1"

    def inner_action_2(**kwargs):
        return "inner2"

    def outer_action_2(**kwargs):
        return "outer2"

    def extra(**kwargs):
        return "extra"

    registry = FunctionRegistry()
    registry.register("outer_action_1", outer_action_1)
    registry.register("outer_action_2", outer_action_2)
    registry.register("inner_action_1", inner_action_1)
    registry.register("inner_action_2", inner_action_2)
    registry.register("extra", extra)

    # Must run without raising: the outer action's splice is in scope.
    run_workflow(LISTING_7, registry=registry)


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
# 12. EXISTING BEHAVIOR PRESERVED — GraphFuture / GraphPool
# --------------------------------------------------------------------------- #


def test_graph_future_pool_smoke():
    """Chaining two GraphFutures through a GraphPool returns the final value."""

    def double(x):
        return x * 2

    def add(x, y):
        return x + y

    with GraphPool(max_workers=4) as pool:
        a = GraphFuture(double, 5)
        b = GraphFuture(add, a, 1)
        assert pool.result(b) == 11


# --------------------------------------------------------------------------- #
# 13. run_workflow end-to-end on Listing 9
# --------------------------------------------------------------------------- #


def test_run_workflow_listing_9_end_to_end(tmp_path):
    """run_workflow(xml, registry=..., parameters=...) on Listing 9 returns a final result."""
    # Provide a real ./test directory so find_test_cases has something to glob.
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    (test_dir / "case_1.csv").write_text("x,y\n1,2\n")

    # Build a registry from the paper stubs (test resources).
    registry = _paper_registry()

    # Rewrite the path in Listing 9 to the tmp_path so the stub finds the file.
    xml = LISTING_9.replace("./test", str(test_dir))
    result = run_workflow(xml, registry=registry, parameters={"model": "./model_1"})
    assert result is not None
