"""
Tests for the shipped V&V workflow library (``sequence_extensions.workflow.library``).

The library functions of the paper "Automation Nation: Taming Complex
V&V Workflows" (16th International Modelica & FMI Conference, September
2025, Lucerne, Switzerland; DOI 10.3384/ecp12076741) are shipped in
``workflow/library.py``: the seven paper functions plus the two
objective-2 drivers (``evaluate_goal`` / ``check_convergence``), the
Tier 1 generic functions (``aggregate`` / ``guard`` /
``while_condition``), and the Tier 2 generic functions (``try_action`` /
``retry`` / ``fallback`` / ``regression_gate``, from
``docs/dynamic_scenarios_analysis.md`` §5).
These tests prove they work when resolved through a registry and used in
representative workflows:

* the paper's XML fixtures (``LISTING_5`` / ``LISTING_9`` from
  ``tests/resources/workflows/``) run end-to-end through the engine after
  the library is registered;
* each function is resolved by name from a registry and behaves
  deterministically;
* registration is explicit opt-in: importing the module leaves
  ``DEFAULT_REGISTRY`` empty, ``register_library()`` is idempotent, and it
  can target ``DEFAULT_REGISTRY`` or a custom ``FunctionRegistry``.

The end-to-end tests register the library into a fresh ``FunctionRegistry``
so they are independent of the paper's test stubs (which self-register in
``DEFAULT_REGISTRY`` on import of ``resources.workflow_stubs``); one test
additionally proves the engine's default-registry path.
"""

import subprocess
import sys
import warnings

import pytest

from sequence_extensions import (
    Action,
    FunctionRegistry,
    Sequential,
    Test_Framework,
    run_workflow,
)
from sequence_extensions.workflow import library
from sequence_extensions.workflow.adaptation import DAGHandle
from sequence_extensions.workflow.library import (
    aggregate,
    compare_parameter_sweep,
    compare_results,
    evaluate_results,
    fallback,
    find_files,
    find_test_cases,
    guard,
    parameter_sweep,
    register_library,
    regression_gate,
    retry,
    simulate,
    try_action,
    while_condition,
)

from . import LISTING_5, LISTING_9

# The library function names, in registration order: the seven paper
# functions first, then the two objective-2 drivers, then the Tier 1
# generic functions (aggregate / guard / while_condition), then the
# Tier 2 generic functions (try_action / retry / fallback /
# regression_gate).
PAPER_NAMES = [
    "find_files",
    "simulate",
    "evaluate_results",
    "find_test_cases",
    "parameter_sweep",
    "compare_parameter_sweep",
    "compare_results",
    "evaluate_goal",
    "check_convergence",
    "aggregate",
    "guard",
    "while_condition",
    "try_action",
    "retry",
    "fallback",
    "regression_gate",
]


def _action_tuples(nodes):
    """Return ``[(function, params)]`` for a list of Action nodes.

    ``Action`` defines no ``__eq__`` (identity only), so nodes are compared
    by their function name and parameter dict.
    """
    return [(n.function, dict(n.params)) for n in nodes]


def _library_registry():
    """A fresh registry with the library functions registered."""
    registry = FunctionRegistry()
    register_library(registry)
    return registry


def _handle_for(action, *siblings):
    """A DAGHandle for ``action`` (index 0) in a Sequential with ``siblings`` after it.

    The adaptation drivers (``find_files`` / ``parameter_sweep``) now take a
    ``dag`` handle and clone the declared following scope, so the direct-call
    tests build a minimal tree (the driver action followed by the body it
    adapts) and hand the function a real :class:`DAGHandle`.  The handle's
    recorded ops (not yet committed by an engine) are what the tests assert
    on; the end-to-end tests below prove the committed splice through the
    engine.
    """
    root = Sequential(action, *siblings)
    return DAGHandle(root, 0)


# --------------------------------------------------------------------------- #
# Registration: explicit opt-in (no import-time side effects)
# --------------------------------------------------------------------------- #


def test_importing_library_leaves_default_registry_empty():
    """A fresh interpreter that imports the library still sees an empty DEFAULT_REGISTRY.

    Checked in a subprocess because the test process itself registers the
    paper's stubs in DEFAULT_REGISTRY (via the decorator, like real
    library functions would).  This is the key proof that registration is
    explicit opt-in, not import-time.
    """
    code = (
        "import sequence_extensions as se\n"
        "import sequence_extensions.workflow.library\n"
        "names = se.DEFAULT_REGISTRY.names()\n"
        "assert names == [], names\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


def test_register_library_registers_all_library_functions():
    """register_library(registry) puts every library function under its name."""
    registry = _library_registry()
    assert registry.names() == PAPER_NAMES
    for name in PAPER_NAMES:
        assert registry.get(name) is getattr(library, name)


def test_register_library_is_idempotent():
    """Calling register_library() twice is a silent no-op (no replacement warning)."""
    registry = _library_registry()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        register_library(registry)
    assert registry.names() == PAPER_NAMES


def test_register_library_into_default_registry(pristine_default_registry):
    """register_library() (no argument) registers into DEFAULT_REGISTRY, the engine's default path.

    The registry is cleared first so the call registers cleanly regardless of
    whether the paper's test stubs are already present in the test process.
    """
    pristine_default_registry._functions.clear()
    register_library()
    for name in PAPER_NAMES:
        assert pristine_default_registry.get(name) is getattr(library, name)


# --------------------------------------------------------------------------- #
# Registry resolution: each function is addressable by name
# --------------------------------------------------------------------------- #


def test_functions_resolve_through_a_registry():
    """Every paper name resolves to the shipped function via registry.get()."""
    registry = _library_registry()
    for name in PAPER_NAMES:
        assert registry.get(name) is getattr(library, name)


def test_find_files_clones_declared_scope_per_file(tmp_path):
    """find_files clones the declared following scope once per file, in sorted order.

    Phase 5 (plan §6): find_files is re-expressed via the DAG handle — it
    clones the declared downstream scope per found file and splices the
    clones in place of it, and its OWN return value (the file list) becomes
    its result.  The direct-call test asserts the recorded replace op; the
    end-to-end Listing 5 tests below prove the committed splice.
    """
    (tmp_path / "b.csv").write_text("x,y\n1,2\n")
    (tmp_path / "a.csv").write_text("x,y\n1,2\n")
    (tmp_path / "skip.txt").write_text("nope")

    body = Sequential(Action("simulate"), Action("evaluate_results"))
    driver = Action("find_files", path=str(tmp_path))
    dag = _handle_for(driver, body)

    files = find_files(path=str(tmp_path), dag=dag)
    expected_files = sorted(str(tmp_path / n) for n in ("a.csv", "b.csv"))
    assert files == expected_files  # the file list is the action's result
    # One replace op: the declared body is replaced by one clone per file.
    assert len(dag.ops) == 1
    op = dag.ops[0]
    assert op.kind == "replace" and op.target is body
    assert len(op.nodes) == 2
    for clone, expected in zip(op.nodes, expected_files):
        assert isinstance(clone, Sequential)
        assert _action_tuples(clone.children) == [
            ("simulate", {"file": expected}),
            ("evaluate_results", {"file": expected}),
        ]


def test_find_files_empty_when_no_match(tmp_path):
    """find_files returns an empty list and adapts nothing when nothing matches."""
    body = Sequential(Action("simulate"), Action("evaluate_results"))
    dag = _handle_for(Action("find_files", path=str(tmp_path)), body)
    assert find_files(path=str(tmp_path), dag=dag) == []
    assert dag.ops == []  # the declared body runs once, as declared


def test_simulate_echoes_parameters():
    """simulate returns {"simulate": <params>} for exactly the kwargs it received."""
    assert simulate() == {"simulate": {}}
    assert simulate(file="case_1.csv", model="./model_1") == {
        "simulate": {"file": "case_1.csv", "model": "./model_1"}
    }


def test_evaluate_results_summarizes_upstream_results():
    """evaluate_results counts the items of each upstream result, ignoring scalars."""
    result = evaluate_results(
        file="case_1.csv",
        model="./model_1",
        simulate={"simulate": {"file": "case_1.csv"}},
    )
    assert result == {"evaluate_results": {"simulate": 1}}


def test_find_test_cases_returns_sorted_csv_paths(tmp_path):
    """find_test_cases returns the *.csv files under path as sorted strings."""
    (tmp_path / "z.csv").write_text("x,y\n1,2\n")
    (tmp_path / "m.csv").write_text("x,y\n1,2\n")
    (tmp_path / "notes.txt").write_text("nope")
    assert find_test_cases(tmp_path) == [str(tmp_path / "m.csv"), str(tmp_path / "z.csv")]


def test_parameter_sweep_clones_declared_scope_per_value():
    """parameter_sweep clones the declared following scope once per value, in order.

    Phase 5 (plan §6): parameter_sweep is re-expressed via the DAG handle —
    it clones the declared downstream scope per sweep value and splices the
    clones in place of it, and its OWN return value (the value list) becomes
    its result.  The direct-call test asserts the recorded replace op; the
    end-to-end Listing 9 tests below prove the committed splice.
    """
    body = Sequential(Action("simulate"))
    driver = Action("parameter_sweep", parameter_name="parameter_1", values=[5, 10, 15])
    dag = _handle_for(driver, body)

    values = parameter_sweep(parameter_name="parameter_1", values=[5, 10, 15], dag=dag)
    assert values == [5, 10, 15]  # the value list is the action's result
    assert len(dag.ops) == 1
    op = dag.ops[0]
    assert op.kind == "replace" and op.target is body
    # Each clone is a copy of the declared body (a Sequential wrapping the
    # single simulate action), retuned with the sweep value.
    assert _action_tuples([c.children[0] for c in op.nodes]) == [
        ("simulate", {"parameter_1": 5}),
        ("simulate", {"parameter_1": 10}),
        ("simulate", {"parameter_1": 15}),
    ]


def test_parameter_sweep_normalizes_comma_separated_string():
    """The XML string form "5, 10, 15" is normalized to [5, 10, 15]."""
    body = Sequential(Action("simulate"))
    dag = _handle_for(Action("parameter_sweep", parameter_name="p", values="5, 10, 15"), body)
    values = parameter_sweep(parameter_name="p", values="5, 10, 15", dag=dag)
    assert values == [5, 10, 15]
    assert [c.children[0].params["p"] for c in dag.ops[0].nodes] == [5, 10, 15]


def test_parameter_sweep_requires_parameter_name():
    """parameter_sweep raises ValueError when parameter_name is missing."""
    body = Sequential(Action("simulate"))
    dag = _handle_for(Action("parameter_sweep", values=[1, 2]), body)
    with pytest.raises(ValueError, match="parameter_name"):
        parameter_sweep(values=[1, 2], dag=dag)


def test_compare_functions_summarize_upstream_results():
    """compare_parameter_sweep / compare_results count each upstream result's items."""
    sweep = {"simulate": {"parameter_1": 5}}
    assert compare_parameter_sweep(sweep=sweep) == {"compare_parameter_sweep": {"sweep": 1}}
    assert compare_results(sweep=sweep) == {"compare_results": {"sweep": 1}}


# --------------------------------------------------------------------------- #
# Representative workflows: the paper's fixtures through the engine
# --------------------------------------------------------------------------- #


def test_listing_5_runs_through_registry(tmp_path):
    """Listing 5 (dynamic adaptation) runs end-to-end: find_files splices per file.

    The fixture's ``file_storage/`` path is rewritten to a real tmp_path
    directory; find_files splices one simulate+evaluate_results pair per
    found file, and the final result is the last evaluate_results summary.
    """
    storage = tmp_path / "file_storage"
    storage.mkdir()
    for i in range(3):
        (storage / f"case_{i}.csv").write_text("x,y\n1,2\n")

    registry = _library_registry()
    xml = LISTING_5.replace("file_storage/", str(storage) + "/")
    result = run_workflow(xml, registry=registry)
    # The final result is the last spliced evaluate_results summary.
    assert isinstance(result, dict)
    assert set(result) == {"evaluate_results"}
    summary = result["evaluate_results"]
    assert isinstance(summary, dict) and summary
    # One simulate result per found file reached the final evaluate_results
    # (the engine keys repeated function names with collision suffixes),
    # proving the per-file dynamic adaptation spliced and ran.
    assert sum(1 for k in summary if k.startswith("simulate")) == 3


def test_listing_9_runs_through_registry(tmp_path):
    """Listing 9 (full use-case-1 workflow) runs end-to-end through the engine.

    The fixture's ``./test`` path is rewritten to a real tmp_path directory
    holding the test-case files; the global ``model`` parameter reaches every
    action; the sweep splices one simulate per value.
    """
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    for i in range(2):
        (test_dir / f"case_{i}.csv").write_text("x,y\n1,2\n")

    registry = _library_registry()
    xml = LISTING_9.replace('value="./test"', f'value="{test_dir}"')
    result = run_workflow(xml, registry=registry)
    # The final result is compare_results: a summary of the upstream results.
    assert isinstance(result, dict)
    assert set(result) == {"compare_results"}
    summary = result["compare_results"]
    assert summary["find_test_cases"] == 2  # one entry per test-case file
    assert summary["parameter_sweep"] == 3  # one entry per sweep value
    # compare_parameter_sweep returns a single-key dict, so its item count is 1.
    assert summary["compare_parameter_sweep"] == 1


def test_listing_10_python_api_through_registry():
    """Listing 10 (Python API) runs via Test_Framework on a registered library."""
    registry = _library_registry()
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
    result = Test_Framework(parameters=common_parameters, seq=top_seq, registry=registry)
    # The final result is the return value of the last action (compare_results).
    assert isinstance(result, dict)
    assert set(result) == {"compare_results"}


def test_listing_5_runs_on_default_registry_path(tmp_path, pristine_default_registry):
    """After register_library(), the engine's default registry path runs Listing 5.

    This proves the out-of-the-box reuse story: once the library is registered
    into DEFAULT_REGISTRY, ``run_workflow`` (no explicit ``registry=``) resolves
    the paper's functions by name.
    """
    storage = tmp_path / "file_storage"
    storage.mkdir()
    for i in range(3):
        (storage / f"case_{i}.csv").write_text("x,y\n1,2\n")

    pristine_default_registry._functions.clear()
    register_library()
    xml = LISTING_5.replace("file_storage/", str(storage) + "/")
    result = run_workflow(xml)  # no registry= -> DEFAULT_REGISTRY
    assert isinstance(result, dict)
    assert set(result) == {"evaluate_results"}
    assert sum(1 for k in result["evaluate_results"] if k.startswith("simulate")) == 3


# --------------------------------------------------------------------------- #
# Objective 2 — evaluate_goal (branching) and check_convergence (iteration)
# --------------------------------------------------------------------------- #


def _branch_registry(decide_value, default=None):
    """A registry for the evaluate_goal branching tests.

    ``decide`` returns ``{"goal": decide_value}``; the alternatives scope has
    named children alpha/beta/gamma, each running one recording action.
    ``report`` (after the alternatives) records the kwargs it received so the
    test can assert evaluate_goal's own result (the chosen name).
    """
    calls = []

    def decide(**kwargs):
        calls.append("decide")
        return {"goal": decide_value}

    def run_alpha(**kwargs):
        calls.append("run_alpha")
        return "alpha"

    def run_beta(**kwargs):
        calls.append("run_beta")
        return "beta"

    def run_gamma(**kwargs):
        calls.append("run_gamma")
        return "gamma"

    def report(**kwargs):
        calls.append(("report", dict(kwargs)))
        return kwargs.get("evaluate_goal")

    registry = FunctionRegistry()
    registry.register("decide", decide)
    registry.register("evaluate_goal", library.evaluate_goal)
    registry.register("run_alpha", run_alpha)
    registry.register("run_beta", run_beta)
    registry.register("run_gamma", run_gamma)
    registry.register("report", report)
    return registry, calls


def _branch_xml():
    return (
        "<sequential>"
        '<action function="decide"/>'
        '<action function="evaluate_goal">'
        '<argument key="upstream" value="decide"/>'
        '<argument key="field" value="goal"/>'
        "</action>"
        '<sequential name="alternatives">'
        '<sequential name="alpha"><action function="run_alpha"/></sequential>'
        '<sequential name="beta"><action function="run_beta"/></sequential>'
        '<sequential name="gamma"><action function="run_gamma"/></sequential>'
        "</sequential>"
        '<action function="report"/>'
        "</sequential>"
    )


def test_evaluate_goal_runs_chosen_alternative_only():
    """evaluate_goal selects the named alternative; the others never run."""
    registry, calls = _branch_registry("beta")
    result = run_workflow(_branch_xml(), registry=registry)
    names = [c if isinstance(c, str) else c[0] for c in calls]
    # The chosen alternative (beta) ran; alpha and gamma never ran.
    assert "run_beta" in names
    assert "run_alpha" not in names
    assert "run_gamma" not in names
    # evaluate_goal's own result (the chosen name) flowed downstream.
    report_kwargs = next(c for c in calls if isinstance(c, tuple) and c[0] == "report")
    assert report_kwargs[1]["evaluate_goal"] == "beta"
    # The final result is the last action's (report's) result.
    assert result == "beta"


def test_evaluate_goal_unknown_alternative_raises():
    """An unknown selected alternative (no default) raises ValueError."""
    registry, _ = _branch_registry("delta")  # not a named alternative
    with pytest.raises(ValueError, match="evaluate_goal"):
        run_workflow(_branch_xml(), registry=registry)


def test_evaluate_goal_default_alternative_used_when_unknown():
    """When the selected name is unknown, the default alternative is used."""
    registry, calls = _branch_registry("delta")  # "delta" is not a named alternative
    # Same workflow as the unknown-alternative test, but the evaluate_goal
    # action carries a default= parameter, so the unknown selection falls
    # back to the named default alternative (gamma).
    xml = (
        "<sequential>"
        '<action function="decide"/>'
        '<action function="evaluate_goal">'
        '<argument key="upstream" value="decide"/>'
        '<argument key="field" value="goal"/>'
        '<argument key="default" value="gamma"/>'
        "</action>"
        '<sequential name="alternatives">'
        '<sequential name="alpha"><action function="run_alpha"/></sequential>'
        '<sequential name="beta"><action function="run_beta"/></sequential>'
        '<sequential name="gamma"><action function="run_gamma"/></sequential>'
        "</sequential>"
        '<action function="report"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry)
    names = [c if isinstance(c, str) else c[0] for c in calls]
    assert "run_gamma" in names
    assert "run_alpha" not in names
    assert "run_beta" not in names
    assert result == "gamma"


def _convergence_registry(converge_after):
    """A registry for the check_convergence iteration tests.

    ``iterate`` (the body) returns ``{"converged": n >= converge_after}`` on
    its n-th call; ``check_convergence`` is the shipped driver.
    """
    state = {"n": 0}

    def iterate(**kwargs):
        state["n"] += 1
        return {"converged": state["n"] >= converge_after}

    registry = FunctionRegistry()
    registry.register("iterate", iterate)
    registry.register("check_convergence", library.check_convergence)
    return registry, state


def _convergence_xml():
    return (
        "<sequential>"
        '<action function="iterate"/>'
        '<action function="check_convergence">'
        '<argument key="upstream" value="iterate"/>'
        '<argument key="field" value="converged"/>'
        "</action>"
        "</sequential>"
    )


def test_check_convergence_iterates_until_converged():
    """check_convergence appends body copies until the field converges.

    The iteration count is unknown a priori: the body converges on its 2nd
    run, so the workflow iterates exactly twice and the summary reports it.
    """
    registry, state = _convergence_registry(converge_after=2)
    result = run_workflow(_convergence_xml(), registry=registry)
    # The body ran exactly twice (unknown a priori, discovered at runtime).
    assert state["n"] == 2
    assert result == {"converged": True, "iterations": 2}


def test_check_convergence_converges_immediately():
    """When the field is already converged, no iteration is appended."""
    registry, state = _convergence_registry(converge_after=1)
    result = run_workflow(_convergence_xml(), registry=registry)
    assert state["n"] == 1
    assert result == {"converged": True, "iterations": 1}


def test_check_convergence_runaway_hits_bound():
    """A never-converging body is terminated by the engine's dynamic-node bound.

    The body never converges, so check_convergence keeps appending copies;
    the engine's ADAPTATION_BOUND (10 000 dynamic nodes) terminates the
    runaway with a deterministic ValueError instead of hanging.
    """
    registry, _ = _convergence_registry(converge_after=float("inf"))
    with pytest.raises(ValueError, match="bound"):
        run_workflow(_convergence_xml(), registry=registry)


# --------------------------------------------------------------------------- #
# Tier 1 generic functions — aggregate (pure), guard (conditional),
# while_condition (numeric-tolerance iteration)
# --------------------------------------------------------------------------- #


def _tier1_registry():
    """A fresh registry with the library functions registered."""
    return _library_registry()


def _guard_registry(field_value):
    """A registry for the guard tests: ``probe`` returns one field value."""
    calls = []

    def probe(**kwargs):
        calls.append("probe")
        return {"ok": field_value}

    def body_ran(**kwargs):
        calls.append("body")
        return "BODY RAN"

    def report(**kwargs):
        calls.append("report")
        return {
            "saw_guard": kwargs.get("guard"),
            "body": kwargs.get("body_ran"),
        }

    registry = _tier1_registry()
    registry.register("probe", probe)
    registry.register("body_ran", body_ran)
    registry.register("report", report)
    return registry, calls


def _guard_xml(on_fail=None):
    """A guard workflow: probe, guard, the guarded body, a trailing report."""
    on_fail_arg = (
        f'<argument key="on_fail" value="{on_fail}"/>' if on_fail else ""
    )
    return (
        "<sequential>"
        '<action function="probe"/>'
        '<action function="guard">'
        '<argument key="upstream" value="probe"/>'
        '<argument key="field" value="ok"/>'
        '<argument key="op" value="eq"/>'
        '<argument key="value" value="True"/>'
        f"{on_fail_arg}"
        "</action>"
        '<sequential><action function="body_ran"/></sequential>'
        '<action function="report"/>'
        "</sequential>"
    )


# ----------------------------- aggregate ---------------------------------- #


def test_aggregate_reduces_all_collision_suffixed_results():
    """aggregate sums the field of every suffixed upstream result."""
    result = aggregate(
        "simulate",
        "error",
        "sum",
        simulate={"error": 1},
        simulate_2={"error": 2},
        simulate_3={"error": 4},
        model="./model_1",  # globals and non-results are ignored
    )
    assert result == {"aggregate": {"op": "sum", "count": 3, "value": 7}}


def test_aggregate_numeric_and_boolean_ops():
    """max / min / mean / count / all / any reduce as documented."""
    kwargs = {
        "simulate": {"v": 4},
        "simulate_2": {"v": 1},
        "simulate_3": {"v": 3},
    }
    assert aggregate("simulate", "v", "max", **kwargs) == {
        "aggregate": {"op": "max", "count": 3, "value": 4}
    }
    assert aggregate("simulate", "v", "min", **kwargs) == {
        "aggregate": {"op": "min", "count": 3, "value": 1}
    }
    assert aggregate("simulate", "v", "mean", **kwargs) == {
        "aggregate": {"op": "mean", "count": 3, "value": 8 / 3}
    }
    # count reads no field values at all.
    assert aggregate("simulate", "v", "count", **kwargs) == {
        "aggregate": {"op": "count", "count": 3, "value": 3}
    }
    flags = {
        "simulate": {"passed": True},
        "simulate_2": {"passed": True},
    }
    assert aggregate("simulate", "passed", "all", **flags) == {
        "aggregate": {"op": "all", "count": 2, "value": True}
    }
    flags["simulate_2"] = {"passed": False}
    assert aggregate("simulate", "passed", "any", **flags) == {
        "aggregate": {"op": "any", "count": 2, "value": True}
    }
    assert aggregate("simulate", "passed", "all", **flags) == {
        "aggregate": {"op": "all", "count": 2, "value": False}
    }


def test_aggregate_empty_reductions():
    """Zero values: count 0, numeric value None, all True, any False."""
    assert aggregate("simulate", "v", "count", model="m") == {
        "aggregate": {"op": "count", "count": 0, "value": 0}
    }
    for op in ("sum", "max", "min", "mean"):
        assert aggregate("simulate", "v", op, model="m") == {
            "aggregate": {"op": op, "count": 0, "value": None}
        }
    assert aggregate("simulate", "v", "all", model="m") == {
        "aggregate": {"op": "all", "count": 0, "value": True}
    }
    assert aggregate("simulate", "v", "any", model="m") == {
        "aggregate": {"op": "any", "count": 0, "value": False}
    }


def test_aggregate_groups_by_key():
    """With key, each group is reduced separately, keyed by the key value."""
    result = aggregate(
        "simulate",
        "error",
        "mean",
        key="case",
        simulate={"error": 1, "case": "a"},
        simulate_2={"error": 3, "case": "a"},
        simulate_3={"error": 5, "case": "b"},
    )
    assert result == {
        "aggregate": {
            "op": "mean",
            "count": 3,
            "groups": {"a": {"count": 2, "value": 2.0}, "b": {"count": 1, "value": 5.0}},
        }
    }


def test_aggregate_rejects_bad_op_and_missing_field():
    """An unknown op or a missing field raises ValueError."""
    with pytest.raises(ValueError, match="unknown op"):
        aggregate("simulate", "v", "median", simulate={"v": 1})
    with pytest.raises(ValueError, match="no field"):
        aggregate("simulate", "missing", "sum", simulate={"v": 1})
    with pytest.raises(ValueError, match="not a mapping"):
        aggregate("simulate", "v", "sum", simulate="not a mapping")
    with pytest.raises(ValueError, match="no field"):
        aggregate("simulate", "v", "sum", key="case", simulate={"v": 1})


def test_aggregate_runs_end_to_end_after_a_sweep():
    """A sweep's per-value results aggregate into one summary downstream."""
    registry = _tier1_registry()
    values = []

    def simulate_sweep(**kwargs):
        values.append(kwargs["parameter_1"])
        return {"simulate": dict(kwargs), "error": kwargs["parameter_1"] ** 2}

    registry.register("simulate_sweep", simulate_sweep)
    xml = (
        "<sequential>"
        '<action function="parameter_sweep">'
        '<argument key="parameter_name" value="parameter_1"/>'
        '<argument key="values" value="1, 2, 3"/>'
        "</action>"
        '<sequential><action function="simulate_sweep"/></sequential>'
        '<action function="aggregate">'
        '<argument key="upstream" value="simulate_sweep"/>'
        '<argument key="field" value="error"/>'
        '<argument key="op" value="=" />'
        "</action>"
        "</sequential>"
    )
    # The op above is invalid on purpose?  No: use a valid one.
    xml = xml.replace('value="=" ', 'value="sum"')
    result = run_workflow(xml, registry=registry)
    assert result == {"aggregate": {"op": "sum", "count": 3, "value": 14}}
    assert values == [1, 2, 3]


# ------------------------------- guard ------------------------------------ #


def test_guard_passes_and_body_runs():
    """When the predicate holds, the declared scope runs unchanged."""
    registry, calls = _guard_registry(field_value=True)
    result = run_workflow(_guard_xml(), registry=registry)
    assert "body" in calls  # the body ran exactly once
    assert result == {
        "saw_guard": {"guard": {"passed": True, "op": "eq"}},
        "body": "BODY RAN",
    }


def test_guard_skip_replaces_body_with_empty_group():
    """When the predicate fails, the body never runs (skip = empty group)."""
    registry, calls = _guard_registry(field_value=False)
    result = run_workflow(_guard_xml(), registry=registry)
    assert "body" not in calls  # the body never ran
    # The guard's own result flowed downstream; the body's did not.
    assert result == {
        "saw_guard": {"guard": {"passed": False, "op": "eq"}},
        "body": None,
    }


def test_guard_on_fail_raises():
    """on_fail='fail' aborts the run with a clear ValueError."""
    registry, calls = _guard_registry(field_value=False)
    with pytest.raises(ValueError, match="guard"):
        run_workflow(_guard_xml(on_fail="fail"), registry=registry)
    assert "body" not in calls


def test_guard_unknown_on_fail_raises():
    """An unknown on_fail mode raises ValueError before any adaptation."""
    registry, _ = _guard_registry(field_value=False)
    with pytest.raises(ValueError, match="on_fail"):
        run_workflow(_guard_xml(on_fail="explode"), registry=registry)


def test_guard_comparison_ops():
    """The full op set evaluates against the latest upstream field."""
    body = Sequential(Action("body_ran"))
    cases = [
        ("eq", 5, True),
        ("eq", 6, False),
        ("ne", 6, True),
        ("lt", 6, True),
        ("le", 5, True),
        ("gt", 4, True),
        ("ge", 5, True),
        ("in", [1, 5], True),
        ("not_in", [2], True),
    ]
    for op, value, expected in cases:
        dag = _handle_for(
            Action("guard", upstream="probe", field="n", op=op, value=value), body
        )
        result = guard(
            upstream="probe", field="n", op=op, value=value, dag=dag, probe={"n": 5}
        )
        assert result == {"guard": {"passed": expected, "op": op}}, (op, value)
        # A passing guard adapts nothing; a failing one replaces the body.
        assert len(dag.ops) == (0 if expected else 1)
    # contains: the field (left) contains the value (right).
    dag = _handle_for(
        Action("guard", upstream="probe", field="tags", op="contains", value="a"), body
    )
    result = guard(
        upstream="probe", field="tags", op="contains", value="a",
        dag=dag, probe={"tags": ["a", "b"]},
    )
    assert result == {"guard": {"passed": True, "op": "contains"}}
    assert dag.ops == []


def test_guard_coerces_xml_string_operands():
    """XML string operands ('0.1', 'True') compare numerically/booleanly."""
    body = Sequential(Action("body_ran"))
    dag = _handle_for(
        Action("guard", upstream="probe", field="residual", op="lt", value="0.1"), body
    )
    result = guard(
        upstream="probe",
        field="residual",
        op="lt",
        value="0.1",
        dag=dag,
        probe={"residual": 0.05},
    )
    assert result == {"guard": {"passed": True, "op": "lt"}}
    dag2 = _handle_for(
        Action("guard", upstream="probe", field="ok", op="eq", value="True"), body
    )
    result2 = guard(
        upstream="probe", field="ok", op="eq", value="True", dag=dag2, probe={"ok": True}
    )
    assert result2 == {"guard": {"passed": True, "op": "eq"}}


def test_guard_missing_upstream_raises():
    """No upstream result named upstream is a ValueError (driver contract)."""
    body = Sequential(Action("body_ran"))
    dag = _handle_for(Action("guard", upstream="probe", field="ok", op="eq", value=1), body)
    with pytest.raises(ValueError, match="no upstream result"):
        guard(upstream="probe", field="ok", op="eq", value=1, dag=dag, model="m")


def test_guard_unknown_op_raises():
    """An unknown comparison op raises ValueError."""
    body = Sequential(Action("body_ran"))
    dag = _handle_for(Action("guard", upstream="probe", field="ok", op="~=", value=1), body)
    with pytest.raises(ValueError, match="unknown op"):
        guard(upstream="probe", field="ok", op="~=", value=1, dag=dag, probe={"ok": 1})


# --------------------------- while_condition ------------------------------ #


def _while_registry(residuals):
    """A registry for the while_condition tests.

    ``iterate`` (the body) returns the next residual of ``residuals`` on
    each call (a fixed, deterministic sequence); when the list is
    exhausted it keeps returning the last value.
    """
    state = {"n": 0}

    def iterate(**kwargs):
        index = min(state["n"], len(residuals) - 1)
        state["n"] += 1
        return {"residual": residuals[index]}

    registry = _tier1_registry()
    registry.register("iterate", iterate)
    return registry, state


def _while_xml(**extra):
    """A while_condition workflow: the body precedes the check in its scope."""
    arguments = "".join(
        f'<argument key="{key}" value="{value}"/>' for key, value in extra.items()
    )
    return (
        "<sequential>"
        '<action function="iterate"/>'
        '<action function="while_condition">'
        '<argument key="upstream" value="iterate"/>'
        '<argument key="field" value="residual"/>'
        '<argument key="op" value="lt"/>'
        '<argument key="threshold" value="0.1"/>'
        f"{arguments}"
        "</action>"
        "</sequential>"
    )


def test_while_condition_iterates_until_below_tolerance():
    """The body repeats while the residual fails the threshold comparison."""
    # Residuals: 1.0 (fail) -> one append; 0.05 (pass) -> 2 body runs.
    # (Like check_convergence, a single append converges cleanly; two or
    # more appends copy earlier check pairs too, so the already-scheduled
    # copies run once more after convergence — the copy-to-end over-run.)
    registry, state = _while_registry([1.0, 0.05])
    result = run_workflow(_while_xml(), registry=registry)
    assert state["n"] == 2
    assert result == {"converged": True, "iterations": 2}


def test_while_condition_satisfied_immediately():
    """When the first residual already satisfies the comparison, one run."""
    registry, state = _while_registry([0.01])
    result = run_workflow(_while_xml(), registry=registry)
    assert state["n"] == 1
    assert result == {"converged": True, "iterations": 1}


def test_while_condition_stops_at_max_iterations():
    """A never-satisfied condition stops at the user-facing cap."""
    registry, state = _while_registry([10.0])  # never below 0.1
    result = run_workflow(_while_xml(max_iterations=3), registry=registry)
    # The body ran the cap's worth of times; the cap is recorded.
    assert state["n"] == 4  # 1 initial + 3 appended iterations
    assert result == {"converged": False, "iterations": 4, "max_iterations": 3}


def test_while_condition_max_iterations_one():
    """A cap of 1 stops after the first body run."""
    registry, state = _while_registry([10.0])
    result = run_workflow(_while_xml(max_iterations=1), registry=registry)
    # The cap is checked before any append: the body ran once (as
    # declared), the cap stopped the iteration, nothing was appended.
    assert state["n"] == 1
    assert result == {"converged": False, "iterations": 1, "max_iterations": 1}


def test_while_condition_without_cap_hits_engine_bound():
    """Without a cap, a never-satisfied condition hits ADAPTATION_BOUND."""
    registry, _ = _while_registry([10.0])
    with pytest.raises(ValueError, match="bound"):
        run_workflow(_while_xml(), registry=registry)


def test_while_condition_comparison_ops_and_boundaries():
    """Every comparison op evaluates; the boundary is inclusive for le/ge."""
    registry = FunctionRegistry()
    registry.register("while_condition", library.while_condition)
    cases = [
        ("lt", 0.1, 0.1, False),  # 0.1 < 0.1 is False -> iterate
        ("le", 0.1, 0.1, True),  # 0.1 <= 0.1 is True -> satisfied
        ("gt", 0.1, 0.1, False),
        ("ge", 0.1, 0.1, True),
        ("eq", 0.1, 0.1, True),
        ("ne", 0.1, 0.1, False),
    ]
    for op, threshold, residual, expected in cases:
        body = Action("iterate")
        check = Action(
            "while_condition",
            upstream="iterate",
            field="residual",
            op=op,
            threshold=threshold,
            max_iterations=1,
        )
        root = Sequential(body, check)
        dag = DAGHandle(root, 1)
        result = while_condition(
            upstream="iterate",
            field="residual",
            op=op,
            threshold=threshold,
            max_iterations=1,
            dag=dag,
            iterate={"residual": residual},
        )
        if expected:
            assert result == {"converged": True, "iterations": 1}, (op, threshold)
            assert dag.ops == []
        else:
            # Not satisfied and the cap (1) is reached: no append, cap recorded.
            assert result == {
                "converged": False,
                "iterations": 1,
                "max_iterations": 1,
            }, (op, threshold)


def test_while_condition_appends_body_and_check_copies():
    """A failing check appends body copies plus a fresh check copy."""
    body = Action("iterate")
    check = Action(
        "while_condition",
        upstream="iterate",
        field="residual",
        op="lt",
        threshold=0.1,
    )
    root = Sequential(body, check)
    dag = DAGHandle(root, 1)
    result = while_condition(
        upstream="iterate",
        field="residual",
        op="lt",
        threshold=0.1,
        dag=dag,
        iterate={"residual": 1.0},
    )
    assert result == {"converged": False, "iterations": 1}
    assert len(dag.ops) == 1
    op = dag.ops[0]
    assert op.kind == "append"
    # The appended nodes: a copy of the body + a fresh copy of the check.
    assert len(op.nodes) == 2
    assert op.nodes[0].function == "iterate"
    assert op.nodes[1].function == "while_condition"
    assert op.nodes[1].params["threshold"] == 0.1


def test_while_condition_requires_preceding_body():
    """A check with no preceding body in its scope raises ValueError."""
    check = Action(
        "while_condition",
        upstream="iterate",
        field="residual",
        op="lt",
        threshold=0.1,
    )
    root = Sequential(check)  # nothing precedes the check
    dag = DAGHandle(root, 0)
    with pytest.raises(ValueError, match="preceded"):
        while_condition(
            upstream="iterate",
            field="residual",
            op="lt",
            threshold=0.1,
            dag=dag,
            iterate={"residual": 1.0},
        )


def test_while_condition_missing_upstream_and_bad_op_raise():
    """No upstream result / unknown op raise ValueError."""
    check = Action(
        "while_condition", upstream="iterate", field="residual", op="lt", threshold=0.1
    )
    root = Sequential(Action("iterate"), check)
    dag = DAGHandle(root, 1)
    with pytest.raises(ValueError, match="no upstream result"):
        while_condition(
            upstream="iterate",
            field="residual",
            op="lt",
            threshold=0.1,
            dag=dag,
            model="m",
        )
    with pytest.raises(ValueError, match="unknown op"):
        while_condition(
            upstream="iterate",
            field="residual",
            op="~=",
            threshold=0.1,
            dag=dag,
            iterate={"residual": 1.0},
        )


def test_while_condition_coerces_xml_string_threshold_and_cap():
    """XML string threshold/max_iterations compare numerically."""
    body = Action("iterate")
    check = Action(
        "while_condition",
        upstream="iterate",
        field="residual",
        op="lt",
        threshold="0.1",
        max_iterations="2",
    )
    root = Sequential(body, check)
    dag = DAGHandle(root, 1)
    result = while_condition(
        upstream="iterate",
        field="residual",
        op="lt",
        threshold="0.1",
        max_iterations="2",
        dag=dag,
        iterate={"residual": 1.0},
    )
    # Not satisfied, cap not yet reached (1 < 2): append happens.
    assert result == {"converged": False, "iterations": 1}
    assert dag.ops[0].kind == "append"


def test_tier1_functions_replay_deterministically():
    """A while_condition run replays to the same final result."""
    from sequence_extensions.workflow.history import RunHistory, replay

    registry, _ = _while_registry([1.0, 0.05])
    history = RunHistory()
    result = run_workflow(_while_xml(), registry=registry, history=history)
    assert result == {"converged": True, "iterations": 2}
    # Replay re-executes the recorded calls (ReplayHandle: writes no-ops)
    # and returns the same final result.
    assert replay(history, registry) == result


# --------------------------------------------------------------------------- #
# Tier 2 generic functions — try_action (error capture), retry (re-run),
# fallback (first-success), regression_gate (V&V gate)
# --------------------------------------------------------------------------- #


# ----------------------------- try_action --------------------------------- #


def test_try_action_returns_ok_on_success():
    """A successful wrapped call returns ok=True with the result and no error."""
    registry = _library_registry()
    registry.register("good", lambda **kwargs: "the result")
    assert try_action("good", registry=registry) == {
        "ok": True,
        "result": "the result",
        "error": None,
    }


def test_try_action_captures_exception_as_data():
    """A wrapped exception is captured as data (ok=False, error=str(exc))."""
    registry = _library_registry()

    def boom(**kwargs):
        raise RuntimeError("kaboom")

    registry.register("boom", boom)
    assert try_action("boom", registry=registry) == {
        "ok": False,
        "result": None,
        "error": "kaboom",
    }


def test_try_action_unregistered_function_raises():
    """An unresolvable function name is a workflow error, not a captured failure."""
    registry = _library_registry()
    with pytest.raises(ValueError, match="unknown function"):
        try_action("nope", registry=registry)


def test_try_action_passes_params_through():
    """The wrapped call receives exactly the params mapping (nothing else)."""
    registry = _library_registry()
    seen = {}

    def echo(**kwargs):
        seen.update(kwargs)
        return "ok"

    registry.register("echo", echo)
    result = try_action("echo", params={"a": 1, "b": "x"}, registry=registry)
    assert result == {"ok": True, "result": "ok", "error": None}
    assert seen == {"a": 1, "b": "x"}


def test_try_action_ignores_extra_kwargs():
    """Globals and upstream results are ignored: the wrapped call gets only params."""
    registry = _library_registry()
    seen = {}

    def echo(**kwargs):
        seen.update(kwargs)
        return "ok"

    registry.register("echo", echo)
    try_action(
        "echo",
        params={"a": 1},
        registry=registry,
        model="./model_1",
        simulate={"simulate": {"file": "case_1.csv"}},
    )
    assert seen == {"a": 1}


def test_try_action_runs_end_to_end_through_registry():
    """A try_action wrapping a failing function yields data a downstream action reads.

    The engine passes no registry to functions, so the registry is supplied as a
    global parameter (the engine's globals reach every action's kwargs).
    """
    registry = _library_registry()
    calls = []

    def boom(**kwargs):
        calls.append("boom")
        raise RuntimeError("kaboom")

    def report(**kwargs):
        return {"saw": kwargs.get("try_action")}

    registry.register("boom", boom)
    registry.register("report", report)
    xml = (
        "<sequential>"
        '<action function="try_action">'
        '<argument key="name" value="boom"/>'
        "</action>"
        '<action function="report"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry, parameters={"registry": registry})
    assert calls == ["boom"]  # the wrapped function ran exactly once
    assert result == {"saw": {"ok": False, "result": None, "error": "kaboom"}}


# ------------------------------- retry ------------------------------------ #


def _retry_handle(check_params, n_body=1):
    """A DAGHandle for a retry check preceded by ``n_body`` body actions.

    The retry check sits at the scope end (the copy-to-end convention), so the
    handle's index is the check's position (after the body).
    """
    body = [Action("flaky") for _ in range(n_body)]
    check = Action("retry", **check_params)
    root = Sequential(*body, check)
    return DAGHandle(root, len(body))


def test_retry_acceptable_result_adapts_nothing():
    """An acceptable (ok=True) try_action outcome returns ok and adapts nothing."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=3,
        flaky={"ok": True, "result": 1, "error": None},
    )
    assert result == {"ok": True, "attempts": 1}
    assert dag.ops == []


def test_retry_unacceptable_result_appends_body_and_check():
    """An unacceptable (ok=False) outcome appends body copies + a fresh check."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=3,
        flaky={"ok": False, "result": None, "error": "x"},
    )
    assert result == {"ok": False, "attempts": 1}
    assert len(dag.ops) == 1
    op = dag.ops[0]
    assert op.kind == "append"
    # The appended nodes: a copy of the body + a fresh copy of the check.
    assert len(op.nodes) == 2
    assert op.nodes[0].function == "flaky"
    assert op.nodes[1].function == "retry"
    assert op.nodes[1].params["max_attempts"] == 3


def test_retry_exhausts_at_max_attempts():
    """At the cap, the retry returns the exhausted summary and adapts nothing."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=3,
        flaky={"ok": False, "result": None, "error": "x"},
        flaky_2={"ok": False, "result": None, "error": "x"},
        flaky_3={"ok": False, "result": None, "error": "x"},
    )
    assert result == {"ok": False, "attempts": 3, "max_attempts": 3}
    assert dag.ops == []


def test_retry_max_attempts_one_exhausts_immediately():
    """A cap of 1 stops after the first failure (no append)."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 1})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=1,
        flaky={"ok": False, "result": None, "error": "x"},
    )
    assert result == {"ok": False, "attempts": 1, "max_attempts": 1}
    assert dag.ops == []


def test_retry_on_field_predicate_retries_while_it_holds():
    """on='field': unacceptable iff the predicate HOLDS (retries while it holds)."""
    # Predicate ok == False HOLDS for ok=False -> unacceptable -> append.
    dag = _retry_handle(
        {
            "upstream": "flaky",
            "max_attempts": 3,
            "on": "field",
            "field": "ok",
            "op": "eq",
            "value": False,
        }
    )
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=3,
        on="field",
        field="ok",
        op="eq",
        value=False,
        flaky={"ok": False},
    )
    assert result == {"ok": False, "attempts": 1}
    assert len(dag.ops) == 1
    # Predicate ok == False does NOT hold for ok=True -> acceptable -> no ops.
    dag2 = _retry_handle(
        {
            "upstream": "flaky",
            "max_attempts": 3,
            "on": "field",
            "field": "ok",
            "op": "eq",
            "value": False,
        }
    )
    result2 = retry(
        dag=dag2,
        upstream="flaky",
        max_attempts=3,
        on="field",
        field="ok",
        op="eq",
        value=False,
        flaky={"ok": True},
    )
    assert result2 == {"ok": True, "attempts": 1}
    assert dag2.ops == []


def test_retry_non_try_action_result_always_acceptable():
    """A result that is not a try_action outcome is always acceptable on='error'."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=3,
        flaky={"residual": 0.5},
    )
    assert result == {"ok": True, "attempts": 1}
    assert dag.ops == []


def test_retry_unknown_on_raises():
    """An unknown on mode raises ValueError before any upstream read."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3, "on": "bogus"})
    with pytest.raises(ValueError, match="unknown on"):
        retry(
            dag=dag,
            upstream="flaky",
            max_attempts=3,
            on="bogus",
            flaky={"ok": True, "error": None},
        )


def test_retry_on_field_requires_field():
    """on='field' without a field parameter raises ValueError."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3, "on": "field"})
    with pytest.raises(ValueError, match="field"):
        retry(
            dag=dag,
            upstream="flaky",
            max_attempts=3,
            on="field",
            flaky={"ok": False},
        )


def test_retry_requires_preceding_body():
    """A check with no preceding body in its scope raises ValueError."""
    check = Action("retry", upstream="flaky", max_attempts=3)
    dag = DAGHandle(Sequential(check), 0)
    with pytest.raises(ValueError, match="preceded"):
        retry(
            dag=dag,
            upstream="flaky",
            max_attempts=3,
            flaky={"ok": False, "result": None, "error": "x"},
        )


def test_retry_missing_upstream_raises():
    """No upstream result named upstream is a ValueError."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3})
    with pytest.raises(ValueError, match="no upstream result"):
        retry(dag=dag, upstream="flaky", max_attempts=3, model="m")


def test_retry_backoff_fixed_pauses_delay():
    """backoff='fixed' pauses delay seconds between attempts (sleep hook)."""
    slept = []
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3, "delay": 0.5})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=3,
        delay=0.5,
        backoff="fixed",
        sleep=lambda pause: slept.append(pause),
        flaky={"ok": False, "result": None, "error": "x"},
    )
    assert result == {"ok": False, "attempts": 1}
    assert slept == [0.5]


def test_retry_backoff_linear_pauses_delay_times_attempts():
    """backoff='linear' pauses delay * attempts seconds (sleep hook)."""
    slept = []
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 5, "delay": 0.5})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=5,
        delay=0.5,
        backoff="linear",
        sleep=lambda pause: slept.append(pause),
        flaky={"ok": False, "result": None, "error": "x"},
        flaky_2={"ok": False, "result": None, "error": "x"},
    )
    assert result == {"ok": False, "attempts": 2}
    assert slept == [1.0]  # 0.5 * 2 attempts


def test_retry_zero_delay_pauses_nothing():
    """delay=0.0 (the default) never invokes the sleep hook."""
    slept = []
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts=3,
        delay=0.0,
        sleep=lambda pause: slept.append(pause),
        flaky={"ok": False, "result": None, "error": "x"},
    )
    assert result == {"ok": False, "attempts": 1}
    assert slept == []


def test_retry_unknown_backoff_raises():
    """An unknown backoff mode raises ValueError."""
    dag = _retry_handle({"upstream": "flaky", "max_attempts": 3, "delay": 0.5})
    with pytest.raises(ValueError, match="unknown backoff"):
        retry(
            dag=dag,
            upstream="flaky",
            max_attempts=3,
            delay=0.5,
            backoff="exponential",
            sleep=lambda pause: None,
            flaky={"ok": False, "result": None, "error": "x"},
        )


def test_retry_coerces_xml_string_cap_and_delay():
    """XML string max_attempts/delay are coerced (numeric cap, numeric pause)."""
    slept = []
    dag = _retry_handle({"upstream": "flaky", "max_attempts": "3", "delay": "0.5"})
    result = retry(
        dag=dag,
        upstream="flaky",
        max_attempts="3",
        delay="0.5",
        sleep=lambda pause: slept.append(pause),
        flaky={"ok": False, "result": None, "error": "x"},
    )
    # Not yet at the cap (1 < 3): append happens, and the pause is numeric.
    assert result == {"ok": False, "attempts": 1}
    assert dag.ops[0].kind == "append"
    assert slept == [0.5]


def test_retry_retries_flaky_body_end_to_end():
    """A flaky body wrapped in try_action is retried until ok, end-to-end.

    The body is a literal ``try_action`` action wrapping a flaky registered
    function (the documented retry pattern: the wrapper turns the failure
    into data, ``retry`` re-runs the body while ``ok`` is falsy).  The
    copy-to-end over-run (documented for ``while_condition``) means the body
    runs extra times after the result becomes acceptable, so a body that
    fails twice then succeeds runs 4 times total.
    """
    state = {"n": 0}

    def flaky(**kwargs):
        state["n"] += 1
        if state["n"] <= 2:
            raise RuntimeError(f"fail {state['n']}")
        return "success"

    registry = _library_registry()
    registry.register("flaky", flaky)
    xml = (
        "<sequential>"
        '<action function="try_action">'
        '<argument key="name" value="flaky"/>'
        "</action>"
        '<action function="retry">'
        '<argument key="upstream" value="try_action"/>'
        '<argument key="max_attempts" value="3"/>'
        "</action>"
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry, parameters={"registry": registry})
    # The body ran 4 times (2 failures + 1 success + 1 over-run).
    assert state["n"] == 4
    assert result == {"ok": True, "attempts": 4}


# ------------------------------ fallback ---------------------------------- #


def test_fallback_success_replaces_all_following_siblings():
    """A successful check replaces every following sibling with an empty group."""
    alt_b = Action("alt_b")
    check_b = Action("fallback", upstream="alt_b", field="ok", ok_value=True)
    alt_c = Action("alt_c")
    check_c = Action("fallback", upstream="alt_c", field="ok", ok_value=True)
    check_a = Action("fallback", upstream="alt_a", field="ok", ok_value=True)
    root = Sequential(Action("alt_a"), check_a, alt_b, check_b, alt_c, check_c)
    dag = DAGHandle(root, 1)
    result = fallback(
        dag=dag, upstream="alt_a", field="ok", ok_value=True, alt_a={"ok": True}
    )
    assert result == {"fallback": {"ok": True}}
    # One replace op per following sibling, each an empty Sequential.
    assert len(dag.ops) == 4
    for op, target in zip(dag.ops, (alt_b, check_b, alt_c, check_c)):
        assert op.kind == "replace"
        assert op.target is target
        assert len(op.nodes) == 1
        assert isinstance(op.nodes[0], Sequential)
        assert op.nodes[0].children == []


def test_fallback_failure_adapts_nothing():
    """A failed check adapts nothing (the next alternative runs)."""
    alt_b = Action("alt_b")
    check_b = Action("fallback", upstream="alt_b", field="ok", ok_value=True)
    check_a = Action("fallback", upstream="alt_a", field="ok", ok_value=True)
    root = Sequential(Action("alt_a"), check_a, alt_b, check_b)
    dag = DAGHandle(root, 1)
    result = fallback(
        dag=dag, upstream="alt_a", field="ok", ok_value=True, alt_a={"ok": False}
    )
    assert result == {"fallback": {"ok": False}}
    assert dag.ops == []


def test_fallback_missing_upstream_raises():
    """No upstream result named upstream is a ValueError."""
    check_a = Action("fallback", upstream="alt_a", field="ok", ok_value=True)
    root = Sequential(Action("alt_a"), check_a, Action("alt_b"))
    dag = DAGHandle(root, 1)
    with pytest.raises(ValueError, match="no upstream result"):
        fallback(dag=dag, upstream="alt_a", field="ok", ok_value=True, model="m")


def test_fallback_non_mapping_result_raises():
    """A non-mapping upstream result is a ValueError."""
    check_a = Action("fallback", upstream="alt_a", field="ok", ok_value=True)
    root = Sequential(Action("alt_a"), check_a, Action("alt_b"))
    dag = DAGHandle(root, 1)
    with pytest.raises(ValueError, match="not a mapping"):
        fallback(
            dag=dag, upstream="alt_a", field="ok", ok_value=True, alt_a="not a mapping"
        )


def test_fallback_missing_field_raises():
    """A missing field in the upstream result is a ValueError."""
    check_a = Action("fallback", upstream="alt_a", field="ok", ok_value=True)
    root = Sequential(Action("alt_a"), check_a, Action("alt_b"))
    dag = DAGHandle(root, 1)
    with pytest.raises(ValueError, match="no field"):
        fallback(
            dag=dag, upstream="alt_a", field="ok", ok_value=True, alt_a={"other": 1}
        )


def _fallback_chain_xml():
    """A fallback chain: three alternatives, each followed by its own check.

    The alternatives return a string ``status`` field (the XML form cannot
    pass a boolean ``ok_value``, so the success predicate is a string
    comparison).
    """
    return (
        "<sequential>"
        '<action function="alt_a"/>'
        '<action function="fallback">'
        '<argument key="upstream" value="alt_a"/>'
        '<argument key="field" value="status"/>'
        '<argument key="ok_value" value="success"/>'
        "</action>"
        '<action function="alt_b"/>'
        '<action function="fallback">'
        '<argument key="upstream" value="alt_b"/>'
        '<argument key="field" value="status"/>'
        '<argument key="ok_value" value="success"/>'
        "</action>"
        '<action function="alt_c"/>'
        '<action function="fallback">'
        '<argument key="upstream" value="alt_c"/>'
        '<argument key="field" value="status"/>'
        '<argument key="ok_value" value="success"/>'
        "</action>"
        "</sequential>"
    )


def _fallback_chain_registry(a_status, b_status, c_status):
    """A registry for the fallback chain tests: each alternative returns a status."""
    calls = []

    def alt_a(**kwargs):
        calls.append("A")
        return {"status": a_status}

    def alt_b(**kwargs):
        calls.append("B")
        return {"status": b_status}

    def alt_c(**kwargs):
        calls.append("C")
        return {"status": c_status}

    registry = _library_registry()
    registry.register("alt_a", alt_a)
    registry.register("alt_b", alt_b)
    registry.register("alt_c", alt_c)
    return registry, calls


def test_fallback_first_alternative_succeeds():
    """When the first alternative succeeds, only it runs (the rest are emptied)."""
    registry, calls = _fallback_chain_registry("success", "success", "success")
    run_workflow(_fallback_chain_xml(), registry=registry)
    assert calls == ["A"]  # only the first alternative ran


def test_fallback_chain_second_alternative_succeeds():
    """When the first fails and the second succeeds, A and B run; C never runs."""
    registry, calls = _fallback_chain_registry("failure", "success", "success")
    run_workflow(_fallback_chain_xml(), registry=registry)
    assert calls == ["A", "B"]  # A and B ran; C never ran


def _try_action_action(fn_name):
    """A try_action action wrapping the registered function ``fn_name``."""
    return Action("try_action", name=fn_name)


def test_fallback_error_triggered_chain_via_try_action():
    """An error-triggered chain: a try_action wrapping a failing function.

    The first alternative (a try_action wrapping a failing function) fails
    (ok=False), so the chain falls through to the second alternative (a
    try_action wrapping a succeeding function), which succeeds (ok=True).
    The third alternative never runs.  The XML form works too: ``ok_value``
    is coerced from its string form, so ``ok_value="True"`` compares against
    the boolean ``ok`` field.
    """
    calls = []

    def boom(**kwargs):
        calls.append("boom")
        raise RuntimeError("boom failed")

    def good(**kwargs):
        calls.append("good")
        return "good result"

    def third(**kwargs):
        calls.append("third")
        return "third result"

    registry = _library_registry()
    registry.register("boom", boom)
    registry.register("good", good)
    registry.register("third", third)
    seq = Sequential(
        _try_action_action("boom"),
        Action("fallback", upstream="try_action", field="ok", ok_value=True),
        _try_action_action("good"),
        Action("fallback", upstream="try_action", field="ok", ok_value=True),
        _try_action_action("third"),
    )
    Test_Framework(seq=seq, registry=registry, parameters={"registry": registry})
    assert calls == ["boom", "good"]  # boom and good ran; third never ran


def test_fallback_coerces_xml_string_ok_value():
    """A boolean ok_value passed as an XML string compares against the bool field."""
    alt_b = Action("alt_b")
    check_b = Action("fallback", upstream="alt_b", field="ok", ok_value="True")
    check_a = Action("fallback", upstream="alt_a", field="ok", ok_value="True")
    root = Sequential(Action("alt_a"), check_a, alt_b, check_b)
    dag = DAGHandle(root, 1)
    # ok_value="True" (the XML string form) coerces to True: success.
    result = fallback(
        dag=dag, upstream="alt_a", field="ok", ok_value="True", alt_a={"ok": True}
    )
    assert result == {"fallback": {"ok": True}}
    assert len(dag.ops) == 2  # both following siblings emptied
    # The uncoerced string never equals the boolean field: failure.
    dag2 = DAGHandle(root, 1)
    result2 = fallback(
        dag=dag2, upstream="alt_a", field="ok", ok_value="nope", alt_a={"ok": True}
    )
    assert result2 == {"fallback": {"ok": False}}
    assert dag2.ops == []


# --------------------------- regression_gate ------------------------------ #


def test_regression_gate_all_within_tolerance_passes():
    """Every value within tolerance passes (count n, no deviations)."""
    result = regression_gate(
        "simulate", 1.0, "value", 0.1, simulate={"value": 1.05}, simulate_2={"value": 0.95}
    )
    assert result == {"regression_gate": {"passed": True, "count": 2, "deviations": {}}}


def test_regression_gate_tolerance_boundary_exact():
    """The tolerance boundary is inclusive: abs diff == tolerance passes.

    (The brief's example, value=1.1 baseline=1.0 tolerance=0.1, is a
    floating-point trap: abs(1.1 - 1.0) == 0.10000000000000009 > 0.1, so it
    fails.  A floating-point-safe boundary is used instead.)
    """
    # abs(1.5 - 1.0) == 0.5 == tolerance -> passes (boundary is inclusive).
    assert regression_gate("simulate", 1.0, "value", 0.5, simulate={"value": 1.5}) == {
        "regression_gate": {"passed": True, "count": 1, "deviations": {}}
    }
    # abs(1.5000001 - 1.0) == 0.5000001 > 0.5 -> fails (just outside).
    with pytest.raises(ValueError, match="regression"):
        regression_gate("simulate", 1.0, "value", 0.5, simulate={"value": 1.5000001})


def test_regression_gate_regression_raises():
    """A value outside tolerance raises ValueError (fail-fast gate)."""
    with pytest.raises(ValueError, match="regression"):
        regression_gate("simulate", 1.0, "value", 0.1, simulate={"value": 2.0})


def test_regression_gate_report_mode_returns_deviations():
    """on_regression='report' returns the verdict with per-result deviations."""
    result = regression_gate(
        "simulate",
        1.0,
        "value",
        0.1,
        on_regression="report",
        simulate={"value": 1.05},
        simulate_2={"value": 2.0},
        simulate_3={"value": 0.95},
    )
    assert result == {
        "regression_gate": {
            "passed": False,
            "count": 3,
            "deviations": {"simulate_2": 2.0},
        }
    }


def test_regression_gate_zero_results_passes_trivially():
    """With zero results, the gate passes trivially (count 0)."""
    result = regression_gate("simulate", 1.0, "value", 0.1, model="m")
    assert result == {"regression_gate": {"passed": True, "count": 0, "deviations": {}}}


def test_regression_gate_non_numeric_comparison():
    """A non-numeric field is compared by equality (string field == baseline)."""
    assert regression_gate(
        "simulate", "ok", "status", simulate={"status": "ok"}, simulate_2={"status": "ok"}
    ) == {"regression_gate": {"passed": True, "count": 2, "deviations": {}}}
    with pytest.raises(ValueError, match="regression"):
        regression_gate("simulate", "ok", "status", simulate={"status": "bad"})


def test_regression_gate_coerces_xml_string_baseline():
    """A numeric baseline passed as an XML string compares numerically."""
    # Without coercion the string baseline would fall to equality and fail.
    assert regression_gate(
        "simulate", "1.0", "value", 0.5, simulate={"value": 1.2}
    ) == {"regression_gate": {"passed": True, "count": 1, "deviations": {}}}
    with pytest.raises(ValueError, match="regression"):
        regression_gate("simulate", "1.0", "value", 0.5, simulate={"value": 2.0})


def test_regression_gate_non_mapping_result_raises():
    """A non-mapping upstream result is a ValueError."""
    with pytest.raises(ValueError, match="not a mapping"):
        regression_gate("simulate", 1.0, "value", simulate="not a mapping")


def test_regression_gate_missing_field_raises():
    """A missing field in the upstream result is a ValueError."""
    with pytest.raises(ValueError, match="no field"):
        regression_gate("simulate", 1.0, "value", simulate={"other": 1})


def test_regression_gate_unknown_on_regression_raises():
    """An unknown on_regression mode raises ValueError."""
    with pytest.raises(ValueError, match="unknown on_regression"):
        regression_gate("simulate", 1.0, "value", on_regression="explode")


def test_regression_gate_sweep_one_deviation_raises():
    """A sweep where one result deviates from the baseline raises (fail-fast)."""
    registry = _library_registry()

    def simulate_gate(**kwargs):
        # The third sweep value deviates from the baseline.
        status = "bad" if kwargs["parameter_1"] == 3 else "ok"
        return {"status": status}

    registry.register("simulate_gate", simulate_gate)
    xml = (
        "<sequential>"
        '<action function="parameter_sweep">'
        '<argument key="parameter_name" value="parameter_1"/>'
        '<argument key="values" value="1, 2, 3"/>'
        "</action>"
        '<sequential><action function="simulate_gate"/></sequential>'
        '<action function="regression_gate">'
        '<argument key="upstream" value="simulate_gate"/>'
        '<argument key="baseline" value="ok"/>'
        '<argument key="field" value="status"/>'
        "</action>"
        "</sequential>"
    )
    with pytest.raises(ValueError, match="regression"):
        run_workflow(xml, registry=registry)


def test_regression_gate_sweep_all_within_passes():
    """A sweep where all results match the baseline passes; downstream sees the verdict."""
    registry = _library_registry()

    def simulate_gate(**kwargs):
        return {"status": "ok"}

    def report(**kwargs):
        return {"saw": kwargs.get("regression_gate")}

    registry.register("simulate_gate", simulate_gate)
    registry.register("report", report)
    xml = (
        "<sequential>"
        '<action function="parameter_sweep">'
        '<argument key="parameter_name" value="parameter_1"/>'
        '<argument key="values" value="1, 2, 3"/>'
        "</action>"
        '<sequential><action function="simulate_gate"/></sequential>'
        '<action function="regression_gate">'
        '<argument key="upstream" value="simulate_gate"/>'
        '<argument key="baseline" value="ok"/>'
        '<argument key="field" value="status"/>'
        "</action>"
        '<action function="report"/>'
        "</sequential>"
    )
    result = run_workflow(xml, registry=registry)
    assert result == {
        "saw": {"regression_gate": {"passed": True, "count": 3, "deviations": {}}}
    }
