"""
Tests for the shipped V&V workflow library (``sequence_extensions.workflow.library``).

The seven library functions of the paper "Automation Nation: Taming Complex
V&V Workflows" (16th International Modelica & FMI Conference, September
2025, Lucerne, Switzerland; DOI 10.3384/ecp12076741) are shipped in
``workflow/library.py``.  These tests prove they work when resolved through
a registry and used in representative workflows:

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

# The paper's seven library function names, in the paper's order.
PAPER_NAMES = [
    "find_files",
    "simulate",
    "evaluate_results",
    "find_test_cases",
    "parameter_sweep",
    "compare_parameter_sweep",
    "compare_results",
]


def _action_tuples(nodes):
    """Return ``[(function, params)]`` for a list of Action nodes.

    ``Action`` defines no ``__eq__`` (identity only), so nodes are compared
    by their function name and parameter dict.
    """
    return [(n.function, dict(n.params)) for n in nodes]


def _library_registry():
    """A fresh registry with the seven library functions registered."""
    registry = FunctionRegistry()
    register_library(registry)
    return registry


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


def test_register_library_registers_all_seven():
    """register_library(registry) puts the seven functions under their paper names."""
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


def test_find_files_returns_sorted_per_file_pairs(tmp_path):
    """find_files returns one simulate+evaluate_results pair per file, in sorted order."""
    (tmp_path / "b.csv").write_text("x,y\n1,2\n")
    (tmp_path / "a.csv").write_text("x,y\n1,2\n")
    (tmp_path / "skip.txt").write_text("nope")

    nodes = find_files(tmp_path)
    assert len(nodes) == 2
    expected_files = sorted(str(tmp_path / n) for n in ("a.csv", "b.csv"))
    for node, expected in zip(nodes, expected_files):
        assert isinstance(node, Sequential)
        assert _action_tuples(node.children) == [
            ("simulate", {"file": expected}),
            ("evaluate_results", {"file": expected}),
        ]


def test_find_files_empty_when_no_match(tmp_path):
    """find_files returns an empty list when nothing matches the pattern."""
    assert find_files(tmp_path) == []


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


def test_parameter_sweep_returns_one_simulate_per_value():
    """parameter_sweep returns one simulate action per value, in order."""
    actions = parameter_sweep(parameter_name="parameter_1", values=[5, 10, 15])
    assert _action_tuples(actions) == [
        ("simulate", {"parameter_1": 5}),
        ("simulate", {"parameter_1": 10}),
        ("simulate", {"parameter_1": 15}),
    ]


def test_parameter_sweep_normalizes_comma_separated_string():
    """The XML string form "5, 10, 15" is normalized to [5, 10, 15]."""
    actions = parameter_sweep(parameter_name="p", values="5, 10, 15")
    assert [a.params["p"] for a in actions] == [5, 10, 15]


def test_parameter_sweep_requires_parameter_name():
    """parameter_sweep raises ValueError when parameter_name is missing."""
    with pytest.raises(ValueError, match="parameter_name"):
        parameter_sweep(values=[1, 2])


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
