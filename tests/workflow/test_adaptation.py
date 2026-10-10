"""
Tests for dynamic adaptation through the scoped DAG handle
(``sequence_extensions.workflow.adaptation``) exercised THROUGH THE ENGINE
(``run_workflow`` / ``Test_Framework``), plus the objective-2 drivers
(``evaluate_goal`` branching, ``check_convergence`` iteration) at engine
level, the history/replay handle contract, and the Phase-7 integration
fixture (``scope_integration.xml``).

These tests complement ``test_library.py`` (which drives the library
functions by direct call with a hand-built handle) and ``test_engine.py``
(which pins the return-nodes splice protocol and the Listing-7 scope
cases): here the handle's write ops, write rules, and the engine's commit
protocol are proven end-to-end on workflows the engine actually walks.

Coverage (plan §10 Phase 7):

* (b) handle ops + write rules through the engine: replace / adjust /
  copy / append happy paths; out-of-scope writes -> ValueError;
  already-executed targets -> ValueError; parallel-scope children get
  READ-ONLY handles (every write op raises); the one-mechanism rule
  (a function that declares ``dag`` AND returns nodes -> ValueError).
* (c) branch-by-selection at engine level via ``<scope>``: the chosen
  alternative runs, the others NEVER run (side-effect tracking), unknown
  alternative -> ValueError, the default alternative works.
* (d) iterate-until-converged with an unknown iteration count at engine
  level (through XML).
* (e) at-most-once across copied iterations: every copied action runs
  exactly once (run counts asserted).
* (f) history/replay with a handle: an adapting run records its
  adaptations as plain, JSON-serializable data; replay reproduces the
  result deterministically; replay writes are no-ops (ReplayHandle unit
  contract).
* (h) the ``scope_integration.xml`` fixture: <scope> + template + handle
  drivers + history in one document.
"""

from __future__ import annotations

import json
import threading

import pytest

from resources import workflows
from sequence_extensions import (
    Action,
    FunctionRegistry,
    Sequential,
    run_workflow,
)
from sequence_extensions.workflow.history import (
    ReplayHandle,
    RunHistory,
    replay,
)
from sequence_extensions.workflow.library import (
    check_convergence,
    evaluate_goal,
)

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _registry_with(names, **overrides):
    """A FunctionRegistry with a recording stub per name.

    Every stub appends its name to a shared, lock-protected call log and
    returns its name (so results are traceable).  ``overrides`` maps a
    name to a custom function (e.g. an adapting driver).
    """
    calls: list[str] = []
    lock = threading.Lock()

    def make(name):
        def stub(**kwargs):
            with lock:
                calls.append(name)
            return name

        stub.__name__ = name
        return stub

    registry = FunctionRegistry()
    for name in names:
        registry.register(name, overrides.get(name, make(name)))
    return registry, calls


# --------------------------------------------------------------------------- #
# (b) Handle ops — happy paths THROUGH THE ENGINE
# --------------------------------------------------------------------------- #


def test_handle_replace_next_group_through_engine():
    """A handle replace() of the next sibling group is committed by the engine.

    The driver (which declares ``dag``) reads the declared downstream group
    and replaces it with two fresh actions.  The engine commits the op at
    the driver's return: the declared group never runs, and the injected
    actions run in its place.
    """

    def driver(dag, **kwargs):
        body = dag.following_group()
        dag.replace(body, [Action("injected_1"), Action("injected_2")])
        return "driver_done"

    registry, calls = _registry_with(
        ["driver", "declared", "injected_1", "injected_2", "tail"], driver=driver
    )
    xml = (
        "<sequential>"
        '<action function="driver"/>'
        "<sequential><action function='declared'/></sequential>"
        '<action function="tail"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry)
    # The declared group was replaced: it never ran.
    assert "declared" not in calls
    # The injected actions ran in its place, in order, before the tail.
    assert "injected_1" in calls and "injected_2" in calls
    assert calls.index("injected_1") < calls.index("injected_2") < calls.index("tail")
    # The final result is the last action's (tail's) result.
    assert result == "tail"


def test_handle_adjust_next_action_through_engine():
    """A handle adjust() retunes the next action's parameters in place.

    The driver adjusts the following action's ``level`` parameter; the
    adjusted action runs with the new value (the engine applies the op at
    commit, before the action is walked).
    """
    received: dict = {}

    def driver(dag, **kwargs):
        target = dag.following()[0]
        dag.adjust(target, level="fine")
        return "driver_done"

    def tune(level=None, **kwargs):
        received["level"] = level
        return "tuned"

    registry, calls = _registry_with(["driver", "tune"], driver=driver, tune=tune)
    xml = (
        "<sequential>"
        '<action function="driver"/>'
        '<action function="tune"><argument key="level" value="coarse"/></action>'
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    # The adjust overwrote the declared parameter value.
    assert received["level"] == "fine"


def test_handle_copy_and_append_through_engine():
    """A handle copy() + append() clones the next action and runs the copy.

    The driver clones the following action (with a parameter override) and
    appends the clone at the scope end.  The original action runs once, and
    the appended copy runs once more — each node at most once.
    """
    tags: list = []

    def driver(dag, **kwargs):
        clone = dag.copy(dag.following()[0], tag="copy")
        dag.append(clone)
        return "driver_done"

    def work(tag=None, **kwargs):
        tags.append(tag)
        return "worked"

    registry, calls = _registry_with(["driver", "work"], driver=driver, work=work)
    xml = (
        "<sequential>"
        '<action function="driver"/>'
        '<action function="work"><argument key="tag" value="original"/></action>'
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    # The original ran with its declared tag; the appended copy ran with the
    # override tag.  ``work`` ran exactly twice in total — once per node
    # (the original and its copy), proving at-most-once across the copy.
    assert tags == ["original", "copy"]


def test_handle_append_at_scope_end_through_engine():
    """A handle append() adds fresh actions at the end of the driver's scope.

    The driver appends a new action after the declared tail; the appended
    action runs last and becomes the run's final result.
    """

    def driver(dag, **kwargs):
        dag.append(Action("appended"))
        return "driver_done"

    registry, calls = _registry_with(["driver", "tail", "appended"], driver=driver)
    xml = (
        "<sequential>"
        '<action function="driver"/>'
        '<action function="tail"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry)
    # The appended action ran after the declared tail and is the final result.
    assert calls.index("tail") < calls.index("appended")
    assert result == "appended"


# --------------------------------------------------------------------------- #
# (b) Handle write rules — rejections THROUGH THE ENGINE
# --------------------------------------------------------------------------- #


def test_handle_out_of_scope_write_raises():
    """A write onto a node outside the driver's own scope raises ValueError.

    The driver (in the outer scope) tries to replace a node that lives in a
    SIBLING group's subtree — outside its own grouping scope.  The handle
    validates eagerly, so the run fails with ValueError and nothing is
    adapted.
    """
    def driver(dag, **kwargs):
        # The following sibling is a group; its child is in scope.  But a
        # node in a DIFFERENT (earlier) group is not: the driver's scope is
        # the root group, and the preceding group's subtree is outside it.
        preceding = dag.preceding()
        assert preceding, "test setup: driver must have a preceding sibling"
        out_of_scope = preceding[0].children[0]
        dag.replace(out_of_scope, [Action("injected")])
        return "driver_done"

    registry, calls = _registry_with(
        ["first", "driver", "inner_target", "injected"], driver=driver
    )
    xml = (
        "<sequential>"
        "<sequential><action function='first'/></sequential>"
        '<action function="driver"/>'
        "<sequential><action function='inner_target'/></sequential>"
        "</sequential>"
    )
    with pytest.raises(ValueError, match="scope"):
        run_workflow(xml, registry=registry)
    # The out-of-scope write was rejected: the injected node never ran, and
    # the run aborted at the driver (the following group never got walked).
    assert "injected" not in calls
    assert "inner_target" not in calls


def test_handle_preceding_sibling_write_raises():
    """replace()/adjust() on a preceding ACTION sibling raise (out of scope).

    A driver may only adapt its FOLLOWING siblings (and their subtrees).  A
    preceding action sibling is not a writable target for replace/adjust, so
    the handle rejects the op with a scope error.  (Copying a preceding
    sibling IS allowed — the copy-to-end iteration form — but that is
    ``copy``/``append``, not ``replace``/``adjust``.)
    """
    for op in ("replace", "adjust"):

        def driver(dag, _op=op, **kwargs):
            preceding = dag.preceding()[0]  # the action that ran before the driver
            if _op == "replace":
                dag.replace(preceding, [Action("injected")])
            else:
                dag.adjust(preceding, level="x")
            return "driver_done"

        registry, _ = _registry_with(["first", "driver", "injected"], driver=driver)
        xml = (
            "<sequential>"
            '<action function="first"/>'
            '<action function="driver"/>'
            "</sequential>"
        )
        with pytest.raises(ValueError, match="scope"):
            run_workflow(xml, registry=registry)


def test_handle_write_on_executed_target_raises():
    """A write onto an already-executed (spliced) node raises ValueError.

    ``splicer`` uses the return-nodes protocol to splice a node in place of
    the following group; the spliced node runs and is marked executed.  A
    later handle driver in the same scope then tries to replace that
    already-executed spliced node — rejected, because an executed node is
    not adaptable.
    """

    def splicer(**kwargs):
        return Action("spliced")  # return-nodes protocol (no dag)

    def driver(dag, **kwargs):
        # preceding() = [splicer, spliced]; the spliced node already ran.
        executed = dag.preceding()[1]
        dag.replace(executed, [Action("injected")])
        return "driver_done"

    registry, calls = _registry_with(
        ["splicer", "target", "spliced", "driver", "injected"],
        splicer=splicer,
        driver=driver,
    )
    xml = (
        "<sequential>"
        '<action function="splicer"/>'
        "<sequential><action function='target'/></sequential>"
        '<action function="driver"/>'
        "</sequential>"
    )
    with pytest.raises(ValueError, match="executed"):
        run_workflow(xml, registry=registry)


def test_handle_parallel_scope_is_read_only():
    """Children of a Parallel scope get a READ-ONLY handle: every write raises.

    The driver runs inside a <parallel> group.  Its handle is read-only
    (finding F4): replace / adjust / append all raise ValueError, and the
    run fails.  Reads still work (the driver can see its siblings).
    """
    seen: dict = {}

    def driver(dag, **kwargs):
        seen["read_only"] = dag.read_only
        seen["siblings"] = [type(s).__name__ for s in dag.following()]
        dag.append(Action("injected"))  # must raise: read-only handle
        return "driver_done"

    registry, calls = _registry_with(["driver", "sibling", "injected"], driver=driver)
    xml = (
        "<parallel>"
        '<action function="driver"/>'
        '<action function="sibling"/>'
        "</parallel>"
    )
    with pytest.raises(ValueError, match="read-only"):
        run_workflow(xml, registry=registry)
    # The handle was read-only and the driver could still read its siblings.
    assert seen["read_only"] is True
    assert seen["siblings"] == ["Action"]


def test_handle_parallel_read_only_replace_and_adjust_raise():
    """replace() and adjust() also raise on a read-only (parallel) handle."""
    for op in ("replace", "adjust"):

        def driver(dag, _op=op, **kwargs):
            if _op == "replace":
                dag.replace(dag.following()[0], [Action("injected")])
            else:
                dag.adjust(dag.following()[0], level="x")
            return "driver_done"

        registry, _ = _registry_with(["driver", "sibling", "injected"], driver=driver)
        xml = (
            "<parallel>"
            '<action function="driver"/>'
            '<action function="sibling"/>'
            "</parallel>"
        )
        with pytest.raises(ValueError, match="read-only"):
            run_workflow(xml, registry=registry)


def test_one_mechanism_dag_and_return_nodes_raises():
    """A function that declares dag AND returns nodes raises ValueError.

    The engine enforces one adaptation mechanism per action: a function
    that both receives a handle and returns workflow node(s) is rejected
    (the handle and the return-nodes protocol are mutually exclusive).
    """

    def driver(dag, **kwargs):
        return Action("injected")  # illegal: also declares dag

    registry, calls = _registry_with(["driver", "declared", "injected"], driver=driver)
    xml = (
        "<sequential>"
        '<action function="driver"/>'
        "<sequential><action function='declared'/></sequential>"
        "</sequential>"
    )
    with pytest.raises(ValueError, match="dag"):
        run_workflow(xml, registry=registry)


# --------------------------------------------------------------------------- #
# (c) Branch-by-selection at ENGINE level via <scope> (objective 2)
# --------------------------------------------------------------------------- #


def _branch_xml_with_scope():
    """A branching workflow written with <scope> (not the <sequential> alias).

    The alternatives scope is a <scope type="sequential"> whose children are
    the NAMED alternative branches.  This is the engine-level form of the
    Phase-5 library tests, which used the <sequential> alias spelling.
    """
    return (
        "<scope type=\"sequential\">"
        '<action function="decide"/>'
        '<action function="evaluate_goal">'
        '<argument key="upstream" value="decide"/>'
        '<argument key="field" value="goal"/>'
        "</action>"
        '<scope type="sequential" name="alternatives">'
        '<scope type="sequential" name="alpha"><action function="run_alpha"/></scope>'
        '<scope type="sequential" name="beta"><action function="run_beta"/></scope>'
        '<scope type="sequential" name="gamma"><action function="run_gamma"/></scope>'
        "</scope>"
        '<action function="report"/>'
        "</scope>"
    )


def _branch_registry_with_scope(decide_value, default=None):
    """A registry for the <scope>-based branching tests (side-effect tracking)."""
    calls: list = []
    lock = threading.Lock()

    def record(name):
        def stub(**kwargs):
            with lock:
                calls.append(name)
            return name

        stub.__name__ = name
        return stub

    def decide(**kwargs):
        with lock:
            calls.append("decide")
        return {"goal": decide_value}

    def report(**kwargs):
        with lock:
            calls.append(("report", dict(kwargs)))
        return kwargs.get("evaluate_goal")

    registry = FunctionRegistry()
    registry.register("decide", decide)
    registry.register("evaluate_goal", evaluate_goal)
    registry.register("run_alpha", record("run_alpha"))
    registry.register("run_beta", record("run_beta"))
    registry.register("run_gamma", record("run_gamma"))
    registry.register("report", report)
    return registry, calls


def test_branch_chosen_alternative_runs_others_never_via_scope():
    """The chosen alternative runs; the others NEVER run (side-effect proof).

    Written with <scope>: evaluate_goal selects the named child of the
    alternatives scope; the unselected alternatives are removed from the
    live tree at commit, so their actions never execute.
    """
    registry, calls = _branch_registry_with_scope("beta")
    result = run_workflow(_branch_xml_with_scope(), registry=registry)
    names = [c if isinstance(c, str) else c[0] for c in calls]
    assert "run_beta" in names
    assert "run_alpha" not in names
    assert "run_gamma" not in names
    # evaluate_goal's own result (the chosen name) flowed downstream.
    report_kwargs = next(c for c in calls if isinstance(c, tuple) and c[0] == "report")
    assert report_kwargs[1]["evaluate_goal"] == "beta"
    assert result == "beta"


def test_branch_unknown_alternative_raises_via_scope():
    """An unknown selected alternative (no default) raises ValueError."""
    registry, _ = _branch_registry_with_scope("delta")
    with pytest.raises(ValueError, match="evaluate_goal"):
        run_workflow(_branch_xml_with_scope(), registry=registry)


def test_branch_default_alternative_used_via_scope():
    """When the selected name is unknown, the default alternative is used."""
    registry, calls = _branch_registry_with_scope("delta")
    xml = (
        "<scope type=\"sequential\">"
        '<action function="decide"/>'
        '<action function="evaluate_goal">'
        '<argument key="upstream" value="decide"/>'
        '<argument key="field" value="goal"/>'
        '<argument key="default" value="gamma"/>'
        "</action>"
        '<scope type="sequential" name="alternatives">'
        '<scope type="sequential" name="alpha"><action function="run_alpha"/></scope>'
        '<scope type="sequential" name="beta"><action function="run_beta"/></scope>'
        '<scope type="sequential" name="gamma"><action function="run_gamma"/></scope>'
        "</scope>"
        '<action function="report"/>'
        "</scope>"
    )
    result = run_workflow(xml, registry=registry)
    names = [c if isinstance(c, str) else c[0] for c in calls]
    assert "run_gamma" in names
    assert "run_alpha" not in names
    assert "run_beta" not in names
    assert result == "gamma"


# --------------------------------------------------------------------------- #
# (d) Iterate-until-converged with an unknown count at ENGINE level
# --------------------------------------------------------------------------- #


def _convergence_xml_with_scope():
    """An iteration workflow written with <scope> (copy-to-end pattern).

    The body (``iterate``) is followed by the ``check_convergence`` driver
    at the scope end.  While the field is not converged, the driver appends
    a copy of the body plus a fresh copy of itself — the iteration count is
    unknown a priori and discovered at runtime.
    """
    return (
        "<scope type=\"sequential\">"
        '<action function="iterate"/>'
        '<action function="check_convergence">'
        '<argument key="upstream" value="iterate"/>'
        '<argument key="field" value="converged"/>'
        "</action>"
        "</scope>"
    )


def _convergence_registry_with_scope(converge_after):
    """A registry for the <scope>-based iteration tests (run-count tracking)."""
    state = {"n": 0}
    lock = threading.Lock()

    def iterate(**kwargs):
        with lock:
            state["n"] += 1
        return {"converged": state["n"] >= converge_after}

    registry = FunctionRegistry()
    registry.register("iterate", iterate)
    registry.register("check_convergence", check_convergence)
    return registry, state


def test_iterate_until_converged_unknown_count_via_scope():
    """The iteration count is unknown a priori and discovered at runtime.

    Written with <scope>: check_convergence appends body copies until the
    field converges.  The body's convergence threshold (3) is not the run
    count — the copy-to-end pattern re-copies the growing preceding scope
    (each appended check re-copies every preceding sibling, including prior
    copies), so the body runs more than 3 times.  The invariants that
    matter: the run terminates, the reported iteration count equals the
    ACTUAL number of body runs, and it is at least the convergence
    threshold.  The exact count (4) is pinned to keep the test
    deterministic.
    """
    registry, state = _convergence_registry_with_scope(converge_after=3)
    result = run_workflow(_convergence_xml_with_scope(), registry=registry)
    # The run terminated (converged) and the count was discovered live.
    assert result["converged"] is True
    # The reported iteration count equals the actual number of body runs.
    assert result["iterations"] == state["n"]
    # It ran at least until the convergence threshold (unknown a priori).
    assert state["n"] >= 3
    # Pinned exact deterministic count for this threshold.
    assert state["n"] == 4


def test_iterate_converges_immediately_via_scope():
    """When the field is already converged, no iteration is appended."""
    registry, state = _convergence_registry_with_scope(converge_after=1)
    result = run_workflow(_convergence_xml_with_scope(), registry=registry)
    assert state["n"] == 1
    assert result == {"converged": True, "iterations": 1}


# --------------------------------------------------------------------------- #
# (e) At-most-once across copied iterations (run counts)
# --------------------------------------------------------------------------- #


def test_at_most_once_across_copied_iterations():
    """Every copied action runs exactly once across the whole run.

    The iteration body is a single ``iterate`` action followed by the
    ``check_convergence`` driver.  The copy-to-end pattern appends fresh
    copies of the body (and the check) each iteration, so the live tree
    grows.  The at-most-once guarantee is structural: the walker never
    re-walks a node.  The proof: after the run, the number of times each
    function was CALLED equals the number of DISTINCT nodes of that
    function present in the final (mutated) tree — i.e. every node,
    original or copy, ran exactly once (no node re-walked, none skipped).
    """
    from sequence_extensions import Test_Framework

    counts: dict = {}
    lock = threading.Lock()
    state = {"n": 0}

    def iterate(**kwargs):
        with lock:
            state["n"] += 1
            counts["iterate"] = counts.get("iterate", 0) + 1
        return {"converged": state["n"] >= 3}

    def check_counting(upstream, field, *, dag, **kwargs):
        with lock:
            counts["check_convergence"] = counts.get("check_convergence", 0) + 1
        return check_convergence(upstream=upstream, field=field, dag=dag, **kwargs)

    registry = FunctionRegistry()
    registry.register("iterate", iterate)
    registry.register("check_convergence", check_counting)

    root = Sequential(
        Action("iterate"),
        Action("check_convergence", upstream="iterate", field="converged"),
    )
    result = Test_Framework(seq=root, registry=registry)

    # Count the DISTINCT nodes of each function in the final (mutated) tree.
    def count_nodes(group, name):
        total = 0
        for child in group.children:
            if isinstance(child, Action):
                total += 1 if child.function == name else 0
            else:
                total += count_nodes(child, name)
        return total

    # Every node that exists ran exactly once: call count == node count.
    assert counts["iterate"] == count_nodes(root, "iterate")
    assert counts["check_convergence"] == count_nodes(root, "check_convergence")
    # The run terminated and the count was discovered live (>= threshold).
    assert result["converged"] is True
    assert result["iterations"] == state["n"] >= 3


# --------------------------------------------------------------------------- #
# (f) History / replay with a handle
# --------------------------------------------------------------------------- #


def test_adapting_run_records_adaptations_as_plain_data():
    """An adapting run records its committed ops as plain, JSON-serializable data.

    The driver (which declares ``dag``) replaces the following group.  With
    history on, the driver's ExecutionRecord carries an ``adaptations`` list
    of plain op descriptors (kind / target / nodes / params) and a thin
    ``scope`` snapshot (index + sibling descriptors).  Both are plain data:
    JSON-serializable, no node objects.
    """

    def driver(dag, **kwargs):
        body = dag.following_group()
        dag.replace(body, [Action("injected_1"), Action("injected_2")])
        return "driver_done"

    registry, _ = _registry_with(
        ["driver", "declared", "injected_1", "injected_2"], driver=driver
    )
    xml = (
        "<sequential>"
        '<action function="driver"/>'
        "<sequential><action function='declared'/></sequential>"
        "</sequential>"
    )
    history = RunHistory()
    run_workflow(xml, registry=registry, history=history)

    driver_record = next(r for r in history.records if r.name == "driver")
    # The committed op is recorded as plain data.
    assert len(driver_record.adaptations) == 1
    op = driver_record.adaptations[0]
    assert op["kind"] == "replace"
    assert op["target"]["kind"] == "sequential"
    assert [n["function"] for n in op["nodes"]] == ["injected_1", "injected_2"]
    # The scope snapshot is a thin, plain descriptor (index + siblings).
    assert driver_record.scope is not None
    assert driver_record.scope["index"] == 0
    assert isinstance(driver_record.scope["siblings"], list)
    # Plain data: the whole record's adaptation fields are JSON-serializable.
    json.dumps({"adaptations": driver_record.adaptations, "scope": driver_record.scope})
    # The spliced (dynamic) actions are recorded as their own records.
    dynamic = [r for r in history.records if r.dynamic]
    assert sorted(r.name for r in dynamic) == ["injected_1", "injected_2"]


def test_replay_of_adapting_run_reproduces_result_deterministically():
    """Replaying an adapting run reproduces the original final result.

    The replay re-injects a ReplayHandle (reads from the materialized scope
    snapshot, writes are no-ops), so the driver re-executes deterministically
    and the run's final result is reproduced — recomputed, not echoed.
    """
    run_count = {"n": 0}

    def driver(dag, **kwargs):
        run_count["n"] += 1
        body = dag.following_group()
        dag.replace(body, [Action("injected_1"), Action("injected_2")])
        return "driver_done"

    def injected_1(**kwargs):
        return "i1"

    def injected_2(**kwargs):
        return "i2"

    registry = FunctionRegistry()
    registry.register("driver", driver)
    registry.register("declared", lambda **k: "declared")
    registry.register("injected_1", injected_1)
    registry.register("injected_2", injected_2)
    xml = (
        "<sequential>"
        '<action function="driver"/>'
        "<sequential><action function='declared'/></sequential>"
        "</sequential>"
    )
    history = RunHistory()
    original = run_workflow(xml, registry=registry, history=history)
    assert original == "i2"  # the final action's (injected_2's) result
    assert run_count["n"] == 1
    # Replay re-executes the driver (a second time) and reproduces the result.
    replayed = replay(history, registry)
    assert replayed == original == "i2"
    assert run_count["n"] == 2  # proof of re-execution, not echoing


def test_replay_handle_reads_from_snapshot_and_writes_are_noops():
    """ReplayHandle: reads from the materialized snapshot; writes are no-ops.

    The unit contract of the replay handle: reads (following / preceding /
    following_group) are served from a fake tree materialized from the
    record's scope snapshot (group siblings become placeholder-filled
    groups preserving the child COUNT); write ops (replace / adjust /
    append) are no-ops that mutate nothing; copy / adjusted are functional
    (they clone the fake target).
    """
    # A scope snapshot as the engine records it: the FULL sibling list of
    # the acting action's parent group (the acting action itself is at
    # ``index``), with group siblings recorded as a child COUNT.  Here the
    # driver is at index 0, followed by a group sibling with 2 children.
    scope = {
        "index": 0,
        "siblings": [
            {"kind": "action", "function": "driver"},
            {"kind": "sequential", "children": 2},
        ],
    }
    handle = ReplayHandle(scope)
    # Reads: the fake tree has the recorded siblings; following() is the
    # siblings AFTER the acting action's index.
    following = handle.following()
    assert len(following) == 1
    assert isinstance(following[0], Sequential)
    # The group sibling preserves the child COUNT (as placeholders).
    assert len(following[0].children) == 2
    # following_group() returns the first following sibling (the group).
    group = handle.following_group()
    assert group is following[0]
    # Writes are no-ops: they raise nothing and mutate nothing.
    handle.replace(group, [Action("injected")])
    handle.adjust(following[0], level="x")
    handle.append([Action("appended")])
    # The fake tree is unchanged by the no-op writes.
    assert len(handle.scope.children) == 2
    assert handle.scope.children[1] is group
    # copy / adjusted are functional: they clone the (fake) target.
    clone = handle.copy(group.children[0], level="y")
    assert isinstance(clone, Action)
    assert clone.params.get("level") == "y"
    # adjusted() clones the first following sibling (the group) with overrides.
    adjusted = handle.adjusted(level="z")
    assert isinstance(adjusted, Sequential)
    assert adjusted.children[0].params.get("level") == "z"


# --------------------------------------------------------------------------- #
# (h) Integration fixture: <scope> + template + handle drivers + history
# --------------------------------------------------------------------------- #


def test_scope_integration_fixture(tmp_path):
    """The scope_integration.xml fixture: <scope> + template + handle + history.

    One document composes every Phase-7 feature:
    * a <scope type="sequential"> root (the explicit grouping form);
    * a <template> whose body is a <scope type="sequential"> (a template
      body written with <scope>), expanded at one <use-template> site;
    * a handle driver (find_files) that clones the declared downstream
      scope once per found file (objective 1, through the engine);
    * history recording, which captures the spliced (dynamic) actions.

    The fixture's file_storage/ path is rewritten to a real tmp_path
    directory holding the found files; find_files splices one
    simulate+evaluate_results pair per file, and the final compare_results
    summarizes them.
    """
    storage = tmp_path / "file_storage"
    storage.mkdir()
    for i in range(3):
        (storage / f"case_{i}.csv").write_text("x,y\n1,2\n")

    registry = FunctionRegistry()
    from sequence_extensions.workflow.library import register_library

    register_library(registry)

    xml = workflows.load("scope_integration.xml").replace(
        "file_storage/", str(storage) + "/"
    )
    history = RunHistory()
    result = run_workflow(xml, registry=registry, history=history)

    # The final result is compare_results: a summary of the upstream results.
    assert isinstance(result, dict)
    assert set(result) == {"compare_results"}
    summary = result["compare_results"]
    # One simulate result per found file reached the final compare_results
    # (the engine keys repeated function names with collision suffixes),
    # proving the per-file handle adaptation spliced and ran.
    assert sum(1 for k in summary if k.startswith("simulate")) == 3
    assert sum(1 for k in summary if k.startswith("evaluate_results")) == 3

    # History: the spliced (dynamic) actions are recorded, one simulate and
    # one evaluate_results per found file (3 each), plus find_files and
    # compare_results.
    dynamic = [r for r in history.records if r.dynamic]
    dynamic_names = sorted(r.name for r in dynamic)
    assert dynamic_names == [
        "evaluate_results",
        "evaluate_results",
        "evaluate_results",
        "simulate",
        "simulate",
        "simulate",
    ]
    # The find_files driver recorded its committed adaptation (plain data).
    find_files_record = next(r for r in history.records if r.name == "find_files")
    assert len(find_files_record.adaptations) == 1
    assert find_files_record.adaptations[0]["kind"] == "replace"
    # The run is replayable: replaying reproduces the final result.
    assert replay(history, registry) == result
