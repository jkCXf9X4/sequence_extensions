"""Tests for the flow-plan/2 document interface: plan, manifest, override, run, diff.

One schema serves every plan use case (``IMP-023``): the plan document
(UC-A), the manifest — a projection minus values (UC-B), the override — the
same document with values set (UC-C), re-plan and compare (UC-D), the diff
(UC-E), and execution of the document as the authoritative plan (UC-F).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sequence_extensions.flow import (
    NodePolicy,
    NodeTimeoutError,
    Run,
    RunOptions,
    apply_override,
    diff_plans,
    execute_flow,
    execute_plan,
    gather,
    jsonable,
    node,
    plan_document,
    plan_manifest,
)

_DEFAULT_OPTIONS = {
    "max_workers": 16,
    "summary": False,
    "fixed_clock": False,
    "retries": 0,
    "retry_delay_seconds": 0.0,
    "timeout": None,
}


def _make_campaign():
    """The supported inline fan-out shape from the design discussion."""

    ran = {"simulate": 0, "evaluate": 0, "verdict": 0}

    @node
    def simulate(case: Path, out_dir: Path) -> Path:
        ran["simulate"] += 1
        return out_dir / (case.stem + ".sim")

    @node
    def evaluate(sim: Path, tolerance: float, out_dir: Path) -> Path:
        ran["evaluate"] += 1
        return out_dir / (sim.stem + ".eval")

    @node
    def verdict(evals: list[Path], out_dir: Path) -> Path:
        ran["verdict"] += 1
        return out_dir / "verdict.txt"

    @node
    def campaign(cases_dir: Path, tolerance: float, out_dir: Path) -> Path:
        cases = sorted(cases_dir.glob("*.csv"))
        sims = [simulate.submit(c, out_dir) for c in cases]
        evals = [evaluate.submit(s, tolerance, out_dir) for s in sims]
        return verdict.submit(gather(evals), out_dir)

    return campaign, ran


def _write_cases(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_text("x")


def test_plan_document_returns_the_v2_document(tmp_path):
    """plan_document() returns the flow-plan/2 document without running anything."""
    _write_cases(tmp_path, "a.csv", "b.csv", "c.csv")
    campaign, ran = _make_campaign()
    out_dir = tmp_path / "out"
    logs_dir = tmp_path / "logs"

    doc = plan_document(campaign, tmp_path, 0.5, out_dir, options=RunOptions(log=logs_dir))

    assert doc["schema"] == "flow-plan/2"
    assert "root" not in doc  # flow selection is external to the document
    assert doc["parameters"] == [
        {"name": "cases_dir", "type": "Path", "required": True, "default": None, "value": tmp_path},
        {"name": "tolerance", "type": "float", "required": True, "default": None, "value": 0.5},
        {"name": "out_dir", "type": "Path", "required": True, "default": None, "value": out_dir},
    ]
    assert [n["id"] for n in doc["nodes"]] == list(range(8))
    assert [n["name"] for n in doc["nodes"]] == [
        "simulate",
        "evaluate",
        "simulate",
        "evaluate",
        "simulate",
        "evaluate",
        "gather",
        "verdict",
    ]
    assert [n["kind"] for n in doc["nodes"]] == [
        "node",
        "node",
        "node",
        "node",
        "node",
        "node",
        "gather",
        "node",
    ]
    assert all(n["path"] == [n["name"]] for n in doc["nodes"])
    assert [n["instance"] for n in doc["nodes"]] == [1, 1, 2, 2, 3, 3, 1, 1]
    assert all(
        n["policy"] == {"retries": 0, "retry_delay_seconds": 0.0, "timeout": None}
        for n in doc["nodes"]
    )
    assert doc["edges"] == [
        {"from": 1, "to": 0},
        {"from": 3, "to": 2},
        {"from": 5, "to": 4},
        {"from": 6, "to": 1},
        {"from": 6, "to": 3},
        {"from": 6, "to": 5},
        {"from": 7, "to": 6},
    ]
    # Options are always concrete; run-only fields (log) never appear.
    assert doc["options"] == _DEFAULT_OPTIONS
    # Nothing ran, and no run log was written.
    assert ran == {"simulate": 0, "evaluate": 0, "verdict": 0}
    assert not logs_dir.exists()


def test_plan_document_options_reflect_run_options(tmp_path):
    """The document carries the six concrete option fields, never run code concerns."""
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()

    doc = plan_document(
        campaign,
        tmp_path,
        0.5,
        tmp_path / "out",
        options=RunOptions(
            max_workers=4,
            summary=True,
            retries=1,
            retry_delay_seconds=0.25,
            timeout=30.0,
            log=None,
        ),
    )

    assert doc["options"] == {
        "max_workers": 4,
        "summary": True,
        "fixed_clock": False,
        "retries": 1,
        "retry_delay_seconds": 0.25,
        "timeout": 30.0,
    }


def test_plan_document_node_params_exclude_dependency_edges(tmp_path):
    """A future argument is an edge, not a settable parameter; gather has none."""
    _write_cases(tmp_path, "a.csv", "b.csv")
    campaign, _ran = _make_campaign()
    out_dir = tmp_path / "out"

    doc = plan_document(campaign, tmp_path, 0.5, out_dir)

    evaluate = [n for n in doc["nodes"] if n["name"] == "evaluate"][0]
    # ``sim`` was submitted as a future: it is an edge, absent from params.
    assert [p["name"] for p in evaluate["params"]] == ["tolerance", "out_dir"]
    assert evaluate["params"][0] == {
        "name": "tolerance",
        "type": "float",
        "required": True,
        "default": None,
        "value": 0.5,
    }
    simulate = [n for n in doc["nodes"] if n["name"] == "simulate"][0]
    assert simulate["params"][0]["name"] == "case"
    assert simulate["params"][0]["value"] == tmp_path / "a.csv"
    gather_node = [n for n in doc["nodes"] if n["name"] == "gather"][0]
    assert gather_node["kind"] == "gather"
    assert gather_node["params"] == []
    verdict = [n for n in doc["nodes"] if n["name"] == "verdict"][0]
    assert [p["name"] for p in verdict["params"]] == ["out_dir"]


def test_plan_document_root_parameters_carry_bound_values_and_defaults(tmp_path):
    """Root parameters report the bound value, or the default when omitted."""
    @node
    def flow(cases_dir: Path, tolerance: float = 0.5, *, label: str = "run"):
        return None

    doc = plan_document(flow, tmp_path)

    assert doc["parameters"] == [
        {"name": "cases_dir", "type": "Path", "required": True, "default": None, "value": tmp_path},
        {"name": "tolerance", "type": "float", "required": False, "default": 0.5, "value": 0.5},
        {"name": "label", "type": "str", "required": False, "default": "run", "value": "run"},
    ]

    explicit = plan_document(flow, tmp_path, tolerance=0.9)
    assert explicit["parameters"][1]["value"] == 0.9


def test_plan_document_is_deterministic(tmp_path):
    """Same flow and inputs give an identical document."""
    _write_cases(tmp_path, "a.csv", "b.csv")
    campaign, _ran = _make_campaign()

    first = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")
    second = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    assert first == second


def test_plan_manifest_strips_values_and_keeps_everything_else(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    out_dir = tmp_path / "out"
    doc = plan_document(campaign, tmp_path, 0.5, out_dir)

    manifest = plan_manifest(doc)

    assert manifest["schema"] == "flow-plan/2"
    assert "root" not in manifest
    assert manifest["edges"] == doc["edges"]
    assert manifest["options"] == doc["options"]
    assert manifest["nodes"][0]["policy"] == doc["nodes"][0]["policy"]
    assert manifest["parameters"] == [
        {"name": "cases_dir", "type": "Path", "required": True, "default": None},
        {"name": "tolerance", "type": "float", "required": True, "default": None},
        {"name": "out_dir", "type": "Path", "required": True, "default": None},
    ]
    # The manifest is a projection: values gone, defaults kept.
    for p in manifest["parameters"]:
        assert "value" not in p
    for entry in manifest["nodes"]:
        for p in entry["params"]:
            assert "value" not in p
    assert manifest["nodes"][0]["params"][0] == {
        "name": "case",
        "type": "Path",
        "required": True,
        "default": None,
    }


def test_apply_override_sets_root_parameter_values_without_mutating_the_document(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    doc = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    overridden = apply_override(doc, {"parameters": [{"name": "tolerance", "value": 0.9}]})

    assert overridden is not doc
    assert overridden["parameters"][1]["value"] == 0.9
    assert overridden["parameters"][0]["value"] == doc["parameters"][0]["value"]
    # The input document is untouched.
    assert doc["parameters"][1]["value"] == 0.5
    assert overridden["nodes"] == doc["nodes"]
    assert overridden["edges"] == doc["edges"]


def test_apply_override_node_reaches_every_occurrence_of_the_name(tmp_path):
    _write_cases(tmp_path, "a.csv", "b.csv")
    campaign, _ran = _make_campaign()
    out_dir = tmp_path / "out"
    doc = plan_document(campaign, tmp_path, 0.5, out_dir)

    overridden = apply_override(
        doc,
        {"nodes": [{"name": "evaluate", "params": [{"name": "tolerance", "value": 0.7}]}]},
    )

    evaluates = [n for n in overridden["nodes"] if n["name"] == "evaluate"]
    assert len(evaluates) == 2
    for n in evaluates:
        assert {p["name"]: p["value"] for p in n["params"]}["tolerance"] == 0.7
    # Other nodes are untouched, and so is the input document.
    sims = [n for n in overridden["nodes"] if n["name"] == "simulate"]
    assert all(p["name"] != "tolerance" for n in sims for p in n["params"])
    assert doc["nodes"][1]["params"][0]["value"] == 0.5


def test_apply_override_merges_node_policy_before_validating(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    doc = plan_document(
        campaign,
        tmp_path,
        0.5,
        tmp_path / "out",
        options=RunOptions(node_defaults=NodePolicy(retries=1, retry_delay_seconds=0.5)),
    )

    overridden = apply_override(
        doc, {"nodes": [{"name": "evaluate", "policy": {"retries": 2}}]}
    )

    evaluates = [n for n in overridden["nodes"] if n["name"] == "evaluate"]
    for n in evaluates:
        assert n["policy"] == {
            "retries": 2,
            "retry_delay_seconds": 0.5,
            "timeout": None,
        }
    # The partial merge does not touch the input document.
    assert doc["nodes"][1]["policy"]["retries"] == 1


def test_apply_override_merges_options_partially(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    doc = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    overridden = apply_override(doc, {"options": {"max_workers": 4}})

    assert overridden["options"] == {**_DEFAULT_OPTIONS, "max_workers": 4}
    assert doc["options"] == _DEFAULT_OPTIONS


def test_apply_override_unknown_names_and_keys_raise_valueerror(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    doc = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    with pytest.raises(ValueError, match="unknown node"):
        apply_override(doc, {"nodes": [{"name": "missing", "params": []}]})
    with pytest.raises(ValueError, match="unknown parameter"):
        apply_override(
            doc, {"nodes": [{"name": "evaluate", "params": [{"name": "nope", "value": 1}]}]}
        )
    with pytest.raises(ValueError, match="unknown root parameter"):
        apply_override(doc, {"parameters": [{"name": "nope", "value": 1}]})
    with pytest.raises(ValueError, match="unknown policy key"):
        apply_override(doc, {"nodes": [{"name": "evaluate", "policy": {"nope": 1}}]})
    with pytest.raises(ValueError, match="unknown option key"):
        apply_override(doc, {"options": {"nope": 1}})


def test_apply_override_validates_the_merged_policy(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    doc = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    with pytest.raises(ValueError, match="retries"):
        apply_override(doc, {"nodes": [{"name": "evaluate", "policy": {"retries": -1}}]})


def test_injection_fills_missing_defaults_and_code_wins():
    """RunOptions.parameters fills omitted node params; explicit code keeps its value."""
    @node
    def compute(x: int, scale: float = 1.0) -> float:
        return x * scale

    @node
    def flow(x: int, y: int):
        return gather([compute.submit(x), compute.submit(y, 2.0)])

    run = execute_flow(flow, 10, 20, options=RunOptions(parameters={"compute": {"scale": 3.0}}))

    assert isinstance(run, Run)
    assert run.result == [30.0, 40.0]  # 10*3.0 (registry), 20*2.0 (code wins)


def test_plan_document_reflects_overrides_and_diff_reports_them():
    """UC-D: plan -> override -> re-plan -> diff shows what the override reaches."""
    @node
    def compute(x: int, scale: float = 1.0) -> int:
        return x * scale

    @node
    def flow(x: int, y: int = 1):
        return gather([compute.submit(x), compute.submit(y)])

    old = plan_document(flow, 2)
    new = plan_document(flow, 2, options=RunOptions(parameters={"compute": {"scale": 4.0}}))

    computes = [n for n in new["nodes"] if n["name"] == "compute"]
    assert all({p["name"]: p["value"] for p in n["params"]}["scale"] == 4.0 for n in computes)
    assert {p["name"]: p["value"] for p in old["nodes"][0]["params"]}["scale"] == 1.0

    diff = diff_plans(old, new)
    changed = [c for c in diff["changes"] if c["kind"] == "param_changed"]
    assert len(changed) == 2  # one per occurrence
    assert all(
        c["name"] == "scale" and c["field"] == "value" and c["old"] == 1.0 and c["new"] == 4.0
        for c in changed
    )


def test_plan_document_root_override_reaches_the_document():
    """A root override fills the root call and shows up in the document."""
    @node
    def compute(x: int, scale: float = 1.0) -> int:
        return x * scale

    @node
    def flow(x: int, scale: float = 1.0):
        return gather([compute.submit(x, scale)])

    doc = plan_document(flow, 2, options=RunOptions(parameters={"flow": {"scale": 9.0}}))

    assert {p["name"]: p["value"] for p in doc["parameters"]}["scale"] == 9.0
    assert {p["name"]: p["value"] for p in doc["nodes"][0]["params"]}["scale"] == 9.0


def test_plan_document_policy_prefers_node_policies_over_node_defaults(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()

    doc = plan_document(
        campaign,
        tmp_path,
        0.5,
        tmp_path / "out",
        options=RunOptions(
            node_defaults=NodePolicy(retries=2, timeout=10.0),
            node_policies={"verdict": NodePolicy(retries=5, retry_delay_seconds=1.0)},
        ),
    )

    by_name = {n["name"]: n["policy"] for n in doc["nodes"]}
    assert by_name["simulate"] == {"retries": 2, "retry_delay_seconds": 0.0, "timeout": 10.0}
    assert by_name["evaluate"] == {"retries": 2, "retry_delay_seconds": 0.0, "timeout": 10.0}
    assert by_name["verdict"] == {"retries": 5, "retry_delay_seconds": 1.0, "timeout": None}


def test_diff_plans_identical_documents_compare_equal(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()

    doc = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")
    again = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    assert diff_plans(doc, again) == {"equal": True, "changes": []}


def test_diff_plans_reports_root_parameter_changes():
    @node
    def flow(x: int = 1):
        return None

    old = plan_document(flow)
    new = apply_override(old, {"parameters": [{"name": "x", "value": 5}]})

    diff = diff_plans(old, new)

    assert not diff["equal"]
    assert diff["changes"] == [
        {"kind": "parameter_changed", "name": "x", "field": "value", "old": 1, "new": 5}
    ]


def test_diff_plans_reports_option_changes(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    old = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")
    new = apply_override(old, {"options": {"max_workers": 4}})

    diff = diff_plans(old, new)

    assert diff["changes"] == [
        {"kind": "option_changed", "name": "max_workers", "old": 16, "new": 4}
    ]


def test_diff_plans_reports_node_and_edge_changes(tmp_path):
    _write_cases(tmp_path, "a.csv")
    campaign, _ran = _make_campaign()
    single = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    _write_cases(tmp_path, "b.csv")
    double = plan_document(campaign, tmp_path, 0.5, tmp_path / "out")

    added = diff_plans(single, double)
    assert not added["equal"]
    kinds = [c["kind"] for c in added["changes"]]
    assert "node_added" in kinds and "edge_added" in kinds
    # Node identity is (name, path, instance): the fan-out adds a second
    # simulate/evaluate pair; the single gather and verdict keep instance 1.
    added_nodes = [c for c in added["changes"] if c["kind"] == "node_added"]
    assert {c["node"]["name"] for c in added_nodes} == {"simulate", "evaluate"}
    added_edges = [c for c in added["changes"] if c["kind"] == "edge_added"]
    assert {(c["from"], c["to"]) for c in added_edges} == {(4, 1), (4, 3), (5, 4)}
    removed_edges = [c for c in added["changes"] if c["kind"] == "edge_removed"]
    assert {(c["from"], c["to"]) for c in removed_edges} == {(2, 1)}

    removed = diff_plans(double, single)
    removed_kinds = [c["kind"] for c in removed["changes"]]
    assert "node_removed" in removed_kinds and "edge_removed" in removed_kinds
    removed_nodes = [c for c in removed["changes"] if c["kind"] == "node_removed"]
    assert {c["node"]["name"] for c in removed_nodes} == {"simulate", "evaluate"}


# ---------------------------------------------------------------- #
# execute_plan: the document is the runnable plan
# ---------------------------------------------------------------- #
def test_execute_plan_round_trips_through_json(tmp_path):
    """jsonable -> json -> execute_plan runs the document as imported."""
    _write_cases(tmp_path, "a.csv", "b.csv")
    campaign, ran = _make_campaign()
    out_dir = tmp_path / "out"
    document = json.loads(json.dumps(jsonable(plan_document(campaign, tmp_path, 0.5, out_dir))))

    run = execute_plan(campaign, document, options=RunOptions(log=None))

    assert isinstance(run, Run)
    assert run.result == out_dir / "verdict.txt"
    assert ran == {"simulate": 2, "evaluate": 2, "verdict": 1}


def test_execute_plan_decodes_paths_from_json(tmp_path):
    seen = {}

    @node
    def leaf(p: Path) -> str:
        seen["is_path"] = isinstance(p, Path)
        return p.name

    @node
    def flow(root: Path):
        return leaf.submit(root)

    document = json.loads(json.dumps(jsonable(plan_document(flow, tmp_path))))
    run = execute_plan(flow, document, options=RunOptions(log=None))

    assert seen["is_path"] is True
    assert run.result == tmp_path.name


def test_execute_plan_binds_a_root_parameter_named_options():
    """The reserved keyword travels positionally so a root input named options works."""

    @node
    def flow(options: int):
        return options * 2

    document = json.loads(json.dumps(jsonable(plan_document(flow, 21))))

    assert execute_plan(flow, document, options=RunOptions(log=None)).result == 42


def test_execute_plan_rejects_wrong_or_missing_schema():
    @node
    def flow():
        return None

    with pytest.raises(ValueError, match="schema"):
        execute_plan(flow, {"schema": "flow-plan/1"}, options=RunOptions(log=None))
    with pytest.raises(ValueError, match="schema"):
        execute_plan(flow, {}, options=RunOptions(log=None))


def test_execute_plan_missing_required_root_parameter_raises():
    @node
    def flow(a: int, b: int):
        return a + b

    document = plan_document(flow, 1, 2)
    document["parameters"][0]["value"] = None
    document["parameters"][1]["value"] = None

    with pytest.raises(ValueError, match=r"missing required root parameter\(s\): a, b"):
        execute_plan(flow, document, options=RunOptions(log=None))


def test_execute_plan_applies_the_documents_node_policy():
    calls = {"n": 0}

    @node(retries=0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("first")
        return "ok"

    @node
    def flow():
        return flaky.submit()

    document = plan_document(
        flow, options=RunOptions(node_policies={"flaky": NodePolicy(retries=1)})
    )
    assert {n["name"]: n["policy"] for n in document["nodes"]}["flaky"]["retries"] == 1

    decoded = json.loads(json.dumps(jsonable(document)))
    run = execute_plan(flow, decoded, options=RunOptions(log=None))

    assert run.result == "ok"
    assert calls["n"] == 2


@pytest.mark.flaky_timing
def test_execute_plan_applies_document_options():
    @node
    def slow():
        time.sleep(0.2)

    document = plan_document(slow)
    document["options"]["timeout"] = 0.05

    with pytest.raises(NodeTimeoutError):
        execute_plan(slow, document, options=RunOptions(log=None))


@pytest.mark.flaky_timing
def test_execute_plan_explicit_options_overlay_document_options():
    @node
    def slow():
        time.sleep(0.2)

    document = plan_document(slow)
    assert document["options"]["timeout"] is None

    with pytest.raises(NodeTimeoutError):
        execute_plan(slow, document, options=RunOptions(log=None, timeout=0.05))
