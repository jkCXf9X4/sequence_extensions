"""
Tests for the shipped V&V workflow library (``sequence_extensions.workflow.library``).

The library functions of the paper "Automation Nation: Taming Complex
V&V Workflows" (16th International Modelica & FMI Conference, September
2025, Lucerne, Switzerland; DOI 10.3384/ecp12076741) are shipped in
``workflow/library.py``: the seven paper functions plus the two
objective-2 drivers (``evaluate_goal`` / ``check_convergence``).  These
tests prove they work when resolved through a registry and used in
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
    compare_parameter_sweep,
    compare_results,
    evaluate_results,
    find_files,
    find_test_cases,
    parameter_sweep,
    register_library,
    simulate,
)

from . import LISTING_5, LISTING_9

# The library function names, in registration order: the seven paper
# functions first, then the two objective-2 drivers.
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
