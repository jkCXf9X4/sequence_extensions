"""
Tests for the by-reference artifact store
(``sequence_extensions.workflow.artifacts``): the opt-in contract (zero
change without a store), minted addresses and the append-only manifest,
the scoped ``ArtifactHandle`` (own-directory writes, causal-past reads,
fan-in branch enumeration), parallel information barriers, dynamic
adaptation (spliced clones get fresh addresses), history linkage, and
deterministic replay through ``ReplayArtifacts``.
"""

import json
import threading

import pytest

from sequence_extensions import (
    Action,
    ArtifactStore,
    FunctionRegistry,
    Parallel,
    Sequential,
    Test_Framework,
    run_workflow,
)
from sequence_extensions.workflow.artifacts import (
    MANIFEST_NAME,
    ReplayArtifacts,
)
from sequence_extensions.workflow.history import RunHistory, replay
from sequence_extensions.workflow.library import (
    evaluate_goal as library_evaluate_goal,
)
from sequence_extensions.workflow.library import (
    guard as library_guard,
)
from sequence_extensions.workflow.library import (
    parameter_sweep as library_parameter_sweep,
)
from sequence_extensions.workflow.library import (
    while_condition as library_while_condition,
)

# --------------------------------------------------------------------------- #
# Shared builder: registries of small artifacts-declaring functions
# --------------------------------------------------------------------------- #


def _writer_registry() -> FunctionRegistry:
    """
    A registry of small, deterministic artifacts-declaring functions.

    ``write`` dumps its received parameters as JSON into its node
    directory and returns the root-relative pointer (the convention).
    ``read_pointer`` reads the pointer it receives by value (under the
    producing action's kwargs key, ``write``) and returns the parsed
    payload.  ``summarize_branches`` enumerates a completed parallel
    group's branches and reads one file from each.
    """
    registry = FunctionRegistry()

    def write(artifacts=None, **kwargs):
        payload = {key: value for key, value in kwargs.items() if key != "artifacts"}
        path = artifacts.out_dir() / "payload.json"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return f"{artifacts.address}/payload.json"

    def read_pointer(write=None, artifacts=None, **kwargs):
        return json.loads(artifacts.read(write))

    def summarize_branches(group=None, artifacts=None, **kwargs):
        summary = []
        for branch in artifacts.branches(group):
            # Each branch is a one-action scope; the action's directory
            # (keyed by its function name) sits one level below it.
            summary.append(json.loads(artifacts.read(branch / "write" / "payload.json")))
        return summary

    registry.register("write", write)
    registry.register("read_pointer", read_pointer)
    registry.register("summarize_branches", summarize_branches)
    return registry


def _guarded_registry() -> FunctionRegistry:
    """A one-function registry whose ``write`` works with or without a store."""

    def write(artifacts=None, **kwargs):
        if artifacts is None:
            return None
        payload = {key: value for key, value in kwargs.items() if key != "artifacts"}
        path = artifacts.out_dir() / "payload.json"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return f"{artifacts.address}/payload.json"

    registry = FunctionRegistry()
    registry.register("write", write)
    return registry


def _run(xml_or_seq, registry, tmp_path, **kwargs):
    """Run with a fresh store under ``tmp_path``; return (result, store)."""
    store = ArtifactStore(tmp_path / "run")
    runner = run_workflow if isinstance(xml_or_seq, str) else Test_Framework
    result = runner(xml_or_seq, registry=registry, artifacts=store, **kwargs)
    return result, store


# --------------------------------------------------------------------------- #
# The opt-in contract: no store, zero change
# --------------------------------------------------------------------------- #


def test_without_store_nothing_is_created_and_declaring_functions_are_guarded(
    tmp_path,
):
    """No ``artifacts=``: no run directory, no manifest; a declaring function
    that guards on ``None`` behaves exactly as before."""
    calls = []

    def guarded(artifacts=None, **kwargs):
        if artifacts is not None:
            raise AssertionError("no handle may be injected without a store")
        calls.append(dict(kwargs))
        return {"echo": kwargs.get("case")}

    registry = FunctionRegistry()
    registry.register("guarded", guarded)
    result = run_workflow(
        "<sequential>"
        '<action function="guarded">'
        '<argument key="case" value="a"/>'
        "</action>"
        '<action function="guarded">'
        '<argument key="case" value="b"/>'
        "</action>"
        "</sequential>",
        registry=registry,
    )
    assert result == {"echo": "b"}
    assert [call["case"] for call in calls] == ["a", "b"]
    assert list(tmp_path.iterdir()) == []


def test_without_store_artifacts_stays_an_ordinary_parameter_name(tmp_path):
    """Without a store, a parameter named ``artifacts`` flows normally."""
    received = {}

    def legacy(artifacts=None, **kwargs):
        received["artifacts"] = artifacts
        return artifacts

    registry = FunctionRegistry()
    registry.register("legacy", legacy)
    result = run_workflow(
        "<sequential>"
        '<action function="legacy">'
        '<argument key="artifacts" value="user value"/>'
        "</action>"
        "</sequential>",
        registry=registry,
    )
    assert result == "user value"
    assert received["artifacts"] == "user value"
    assert list(tmp_path.iterdir()) == []


def test_store_with_undeclaring_functions_changes_no_results(tmp_path):
    """A store never changes what non-declaring functions receive or return."""
    seen = []

    def plain(**kwargs):
        seen.append(dict(kwargs))
        return {"plain": True}

    registry = FunctionRegistry()
    registry.register("plain", plain)
    xml = (
        "<sequential>"
        '<action function="plain">'
        '<argument key="case" value="a"/>'
        "</action>"
        '<action function="plain">'
        '<argument key="case" value="b"/>'
        "</action>"
        "</sequential>"
    )
    without = run_workflow(xml, registry=registry)
    result, store = _run(xml, registry, tmp_path)
    # Same result, same received parameters — the store only mints evidence.
    assert without == result == {"plain": True}
    assert [p["case"] for p in seen[2:]] == ["a", "b"] == [p["case"] for p in seen[:2]]
    # But every action was minted and manifested.
    assert [entry["address"] for entry in store.entries()] == ["plain", "plain_2"]


def test_injected_handle_wins_over_same_named_parameter(tmp_path):
    """With a store, ``artifacts`` is reserved: the handle wins (like ``dag``)."""
    registry = _writer_registry()
    result, store = _run(
        "<sequential>"
        '<action function="write">'
        '<argument key="artifacts" value="user value"/>'
        "</action>"
        "</sequential>",
        registry,
        tmp_path,
    )
    assert result == "write/payload.json"
    assert (store.root / "write" / "payload.json").exists()


# --------------------------------------------------------------------------- #
# Minting: addresses and the append-only manifest
# --------------------------------------------------------------------------- #


def test_root_action_address_is_the_function_name(tmp_path):
    """A root action's directory is its function name under the run root."""
    registry = _writer_registry()
    result, store = _run(Sequential(Action("write", case="a")), registry, tmp_path)
    assert result == "write/payload.json"
    assert store.root.name == "run"
    assert (store.root / "write" / "payload.json").is_file()
    assert (store.root / MANIFEST_NAME).is_file()


def test_repeated_function_gets_collision_suffix(tmp_path):
    """The kwargs vocabulary in path space: ``write``, ``write_2``."""
    registry = _writer_registry()
    _, store = _run(
        Sequential(Action("write", case="a"), Action("write", case="b")),
        registry,
        tmp_path,
    )
    assert (store.root / "write" / "payload.json").is_file()
    assert (store.root / "write_2" / "payload.json").is_file()
    assert [e["address"] for e in store.entries()] == ["write", "write_2"]


def test_named_scope_is_a_path_prefix_and_unnamed_scopes_use_their_kind(tmp_path):
    """Named scopes address by name; unnamed ones by kind (sequential)."""
    registry = _writer_registry()
    xml = (
        "<sequential>"
        '<scope type="sequential" name="prepare">'
        '<action function="write" stage="named"/>'
        "</scope>"
        '<scope type="sequential">'
        '<action function="write" stage="unnamed"/>'
        "</scope>"
        "</sequential>"
    )
    _, store = _run(xml, registry, tmp_path)
    assert (store.root / "prepare" / "write" / "payload.json").is_file()
    assert (store.root / "sequential" / "write" / "payload.json").is_file()


def test_manifest_records_walk_order_and_own_params(tmp_path):
    """Manifest entries: seq, address, function, the action's OWN params, dynamic."""
    registry = _writer_registry()
    _, store = _run(
        Sequential(Action("write", case="a"), Action("write", case="b")),
        registry,
        tmp_path,
    )
    entries = store.entries()
    assert [e["seq"] for e in entries] == [0, 1]
    assert [e["function"] for e in entries] == ["write", "write"]
    assert [e["params"] for e in entries] == [{"case": "a"}, {"case": "b"}]
    assert [e["dynamic"] for e in entries] == [False, False]
    # The manifest carries the action's own parameters only — never the
    # merged kwargs, so it cannot echo upstream results.
    assert all("write" not in e["params"] for e in entries)


def test_store_refuses_a_second_run_and_an_occupied_root(tmp_path):
    """One store per run: a reused store or an occupied root raises."""
    registry = _writer_registry()
    store = ArtifactStore(tmp_path / "run")
    Test_Framework(Sequential(Action("write")), registry=registry, artifacts=store)
    with pytest.raises(ValueError, match="already ran"):
        Test_Framework(Sequential(Action("write")), registry=registry, artifacts=store)
    fresh = ArtifactStore(tmp_path / "run")
    with pytest.raises(ValueError, match="manifest"):
        Test_Framework(Sequential(Action("write")), registry=registry, artifacts=fresh)


def test_addresses_are_deterministic_across_runs(tmp_path):
    """Two runs of the same workflow mint identical addresses."""
    registry = _writer_registry()
    seq = Sequential(Sequential(Action("write", case="x")), Action("read_pointer"))
    addresses = []
    for index in range(2):
        store = ArtifactStore(tmp_path / f"run{index}")
        Test_Framework(seq, registry=registry, artifacts=store)
        addresses.append([e["address"] for e in store.entries()])
    assert addresses[0] == addresses[1] == [
        "sequential/write",
        "read_pointer",
    ]


def test_parallel_branch_addresses_are_deterministic(tmp_path):
    """Concurrently-walked branches mint the same addresses every run.

    The manifest's global sequence numbers may interleave across
    independent branches (they record execution), but every ADDRESS —
    derived from walk order, not scheduling — is identical run to run.
    """
    registry = _writer_registry()
    workflow = Sequential(
        Parallel(
            Sequential(Action("write", case="a"), Action("write", case="b")),
            Sequential(Action("write", case="c"), Action("write", case="d")),
        ),
    )
    address_sets = []
    for index in range(3):
        store = ArtifactStore(tmp_path / f"run{index}")
        Test_Framework(workflow, registry=registry, artifacts=store)
        address_sets.append({e["address"] for e in store.entries()})
    assert address_sets[0] == address_sets[1] == address_sets[2] == {
        "parallel/sequential/write",
        "parallel/sequential/write_2",
        "parallel/sequential_2/write",
        "parallel/sequential_2/write_2",
    }


# --------------------------------------------------------------------------- #
# The handle: writes, causal-past reads, pointers by value
# --------------------------------------------------------------------------- #


def test_downstream_reads_upstream_pointer(tmp_path):
    """The pointer flows by value through kwargs; the read is scope-checked."""
    registry = _writer_registry()
    result, store = _run(
        Sequential(Action("write", case="a"), Action("read_pointer")),
        registry,
        tmp_path,
    )
    # read_pointer received write's result (the pointer) as the ``write``
    # kwarg and read it through the store.
    assert result == {"case": "a"}
    assert (store.root / "write" / "payload.json").is_file()


def test_absolute_pointer_is_read_when_under_the_root(tmp_path):
    """A pointer returned as an absolute path (``out_dir()``-based) reads too."""

    def writer(artifacts=None, **kwargs):
        path = artifacts.out_dir() / "data.txt"
        path.write_text("payload", encoding="utf-8")
        return str(path)

    def reader(writer=None, artifacts=None, **kwargs):
        return artifacts.read(writer).decode()

    registry = FunctionRegistry()
    registry.register("writer", writer)
    registry.register("reader", reader)
    result, _ = _run(
        Sequential(Action("writer"), Action("reader")), registry, tmp_path
    )
    assert result == "payload"


def test_read_of_the_own_directory_after_write(tmp_path):
    """A function may read back what it wrote into its own directory."""

    def roundtrip(artifacts=None, **kwargs):
        path = artifacts.out_dir() / "note.txt"
        path.write_text("note", encoding="utf-8")
        return artifacts.read(f"{artifacts.address}/note.txt").decode()

    registry = FunctionRegistry()
    registry.register("roundtrip", roundtrip)
    result, _ = _run(Sequential(Action("roundtrip")), registry, tmp_path)
    assert result == "note"


def test_read_outside_the_causal_past_raises(tmp_path):
    """A fabricated path the action never received is rejected."""

    def intruder(artifacts=None, **kwargs):
        try:
            artifacts.read("not_minted/payload.json")
        except ValueError as exc:
            return f"rejected: {exc}"
        return "leaked"

    registry = _writer_registry()
    registry.register("intruder", intruder)
    result, _ = _run(Sequential(Action("intruder")), registry, tmp_path)
    assert result.startswith("rejected")


def test_read_outside_the_store_root_raises(tmp_path):
    """An absolute path outside the run root is rejected."""

    def escape(artifacts=None, **kwargs):
        try:
            artifacts.read("/etc/hostname")
        except ValueError as exc:
            return f"rejected: {exc}"
        return "leaked"

    registry = FunctionRegistry()
    registry.register("escape", escape)
    result, _ = _run(Sequential(Action("escape")), registry, tmp_path)
    assert result.startswith("rejected")


# --------------------------------------------------------------------------- #
# Parallel groups: information barriers and branch enumeration
# --------------------------------------------------------------------------- #


def test_parallel_branches_write_distinct_directories(tmp_path):
    """Same function in two branches: distinct addresses, no clobbering."""

    def writer(artifacts=None, tag=None, **kwargs):
        path = artifacts.out_dir() / "tag.txt"
        path.write_text(str(tag), encoding="utf-8")
        return f"{artifacts.address}/tag.txt"

    registry = FunctionRegistry()
    registry.register("writer", writer)
    _, store = _run(
        Sequential(
            Parallel(Sequential(Action("writer", tag="a")), Sequential(Action("writer", tag="b")))
        ),
        registry,
        tmp_path,
    )
    left = store.root / "parallel" / "sequential" / "writer" / "tag.txt"
    right = store.root / "parallel" / "sequential_2" / "writer" / "tag.txt"
    assert left.read_text() == "a" and right.read_text() == "b"


def test_parallel_sibling_cannot_read_a_branch_artifact(tmp_path):
    """The barrier is structural: a sibling's known address is rejected."""
    registry = _writer_registry()

    def intruder(artifacts=None, **kwargs):
        # Branch A's writer minted parallel/sequential/write — branch B's
        # function knows the path but its causal past excludes it.
        try:
            artifacts.read("parallel/sequential/write/payload.json")
        except ValueError:
            return "rejected"
        return "leaked"

    registry.register("intruder", intruder)
    result, _ = _run(
        Sequential(
            Parallel(
                Sequential(Action("write", case="a")),
                Sequential(Action("intruder")),
            )
        ),
        registry,
        tmp_path,
    )
    assert result == "rejected"


def test_direct_parallel_actions_are_readable_downstream(tmp_path):
    """One-level flattening: a parallel group's direct action children flow on."""

    def writer(artifacts=None, tag=None, **kwargs):
        path = artifacts.out_dir() / "tag.txt"
        path.write_text(str(tag), encoding="utf-8")
        return f"{artifacts.address}/tag.txt"

    def reader(writer=None, writer_2=None, artifacts=None, **kwargs):
        return [artifacts.read(writer).decode(), artifacts.read(writer_2).decode()]

    registry = FunctionRegistry()
    registry.register("writer", writer)
    registry.register("reader", reader)
    result, store = _run(
        Sequential(
            Parallel(Action("writer", tag="a"), Action("writer", tag="b")),
            Action("reader"),
        ),
        registry,
        tmp_path,
    )
    assert result == ["a", "b"]
    # Direct action children mint under the parallel group's own path.
    assert (store.root / "parallel" / "writer" / "tag.txt").read_text() == "a"
    assert (store.root / "parallel" / "writer_2" / "tag.txt").read_text() == "b"


def test_branches_enumerates_a_completed_group_in_child_order(tmp_path):
    """Fan-in: a downstream action enumerates and compares the branches."""
    registry = _writer_registry()
    result, store = _run(
        Sequential(
            Parallel(
                Sequential(Action("write", case="left")),
                Sequential(Action("write", case="right")),
            ),
            Action("summarize_branches", group="parallel"),
        ),
        registry,
        tmp_path,
    )
    assert result == [{"case": "left"}, {"case": "right"}]
    # The branch directories, in child order:
    assert store.root.joinpath("parallel", "sequential").is_dir()
    assert store.root.joinpath("parallel", "sequential_2").is_dir()


def test_branches_concatenate_all_groups_of_the_same_name(tmp_path):
    """Every completed group named ``name`` contributes, in causal order."""
    registry = _writer_registry()
    result, _ = _run(
        Sequential(
            Parallel(
                Sequential(Action("write", case="round1-left")),
                Sequential(Action("write", case="round1-right")),
                name="solvers",
            ),
            Parallel(
                Sequential(Action("write", case="round2-left")),
                Sequential(Action("write", case="round2-right")),
                name="solvers",
            ),
            Action("summarize_branches", group="solvers"),
        ),
        registry,
        tmp_path,
    )
    assert result == [
        {"case": "round1-left"},
        {"case": "round1-right"},
        {"case": "round2-left"},
        {"case": "round2-right"},
    ]


def test_branches_inside_a_group_cannot_see_the_group_itself(tmp_path):
    """A branch cannot enumerate its own (still running) group."""
    registry = _writer_registry()

    def premature(group=None, artifacts=None, **kwargs):
        try:
            artifacts.branches(group)
        except ValueError:
            return "rejected"
        return "leaked"

    registry.register("premature", premature)
    result, _ = _run(
        Sequential(
            Parallel(
                Sequential(Action("write")),
                Sequential(Action("premature", group="parallel")),
            )
        ),
        registry,
        tmp_path,
    )
    assert result == "rejected"


def test_branches_unknown_name_raises(tmp_path):
    """Enumerating a group that never completed raises."""
    registry = _writer_registry()

    def asker(group=None, artifacts=None, **kwargs):
        try:
            artifacts.branches(group)
        except ValueError as exc:
            return f"rejected: {exc}"
        return "leaked"

    registry.register("asker", asker)
    result, _ = _run(
        Sequential(Action("asker", group="nope")), registry, tmp_path
    )
    assert result.startswith("rejected")


# --------------------------------------------------------------------------- #
# Dynamic adaptation: clones mint fresh addresses
# --------------------------------------------------------------------------- #


def test_parameter_sweep_clones_get_distinct_addresses(tmp_path):
    """Each sweep clone is a fresh scope: per-clone directories, all preserved."""
    registry = FunctionRegistry()
    registry.register("parameter_sweep", library_parameter_sweep)

    def simulate(parameter_1=None, artifacts=None, **kwargs):
        path = artifacts.out_dir() / "result.json"
        path.write_text(json.dumps({"parameter_1": parameter_1}), encoding="utf-8")
        return f"{artifacts.address}/result.json"

    registry.register("simulate", simulate)
    result, store = _run(
        Sequential(
            Action("parameter_sweep", parameter_name="parameter_1", values=[5, 10, 15]),
            Sequential(Action("simulate")),
        ),
        registry,
        tmp_path,
    )
    # The final action in execution order is the LAST clone's simulate,
    # so the run's result is that clone's pointer.
    assert result == "sequential_3/simulate/result.json"
    # The declared body was replaced by three clones: sequential,
    # sequential_2, sequential_3 — each with its own simulate directory.
    clones = ["sequential", "sequential_2", "sequential_3"]
    for clone in clones:
        payload = json.loads(
            (store.root / clone / "simulate" / "result.json").read_text()
        )
        assert "parameter_1" in payload
    values = [
        json.loads((store.root / c / "simulate" / "result.json").read_text())["parameter_1"]
        for c in clones
    ]
    assert values == [5, 10, 15]


def test_downstream_of_a_sweep_reads_the_clone_pointers(tmp_path):
    """Clone results fan in by value; the store follows the by-value flow."""
    registry = FunctionRegistry()
    registry.register("parameter_sweep", library_parameter_sweep)

    def simulate(parameter_1=None, artifacts=None, **kwargs):
        path = artifacts.out_dir() / "result.json"
        path.write_text(json.dumps({"parameter_1": parameter_1}), encoding="utf-8")
        return f"{artifacts.address}/result.json"

    def collect(simulate=None, simulate_2=None, simulate_3=None, artifacts=None, **kwargs):
        return [
            json.loads(artifacts.read(pointer))["parameter_1"]
            for pointer in (simulate, simulate_2, simulate_3)
        ]

    registry.register("simulate", simulate)
    registry.register("collect", collect)
    result, _ = _run(
        Sequential(
            Action("parameter_sweep", parameter_name="parameter_1", values=[5, 10, 15]),
            Sequential(Action("simulate")),
            Action("collect"),
        ),
        registry,
        tmp_path,
    )
    assert result == [5, 10, 15]


def test_return_nodes_splice_mints_and_flows(tmp_path):
    """The return-nodes protocol: spliced actions mint, pointers flow on."""
    registry = _writer_registry()

    def adapter(**kwargs):
        # The old protocol: return nodes spliced in place of the next sibling.
        return [
            Sequential(Action("write", case="spliced-1")),
            Sequential(Action("write", case="spliced-2")),
        ]

    def collect(adapter=None, artifacts=None, **kwargs):
        # The actor's runtime result is the ordered list of the spliced
        # nodes' results; each spliced node is a GROUP, whose result is
        # its own ordered list of action results — the pointers, by value.
        pointers = [pointer for group_result in adapter for pointer in group_result]
        return [json.loads(artifacts.read(pointer))["case"] for pointer in pointers]

    registry.register("adapter", adapter)
    registry.register("collect", collect)
    seq = Sequential(
        Action("adapter"),
        Sequential(Action("write", case="declared")),  # replaced, never runs
        Action("collect"),
    )
    result, store = _run(seq, registry, tmp_path)
    assert result == ["spliced-1", "spliced-2"]
    # The spliced clones minted under the parent's path with suffixes;
    # the replaced declared body never minted.
    addresses = [e["address"] for e in store.entries()]
    assert addresses == ["adapter", "sequential/write", "sequential_2/write", "collect"]
    assert all(e["dynamic"] for e in store.entries()[1:3])


def test_named_sweep_scope_prefixes_clone_addresses(tmp_path):
    """A named scope around a sweep prefixes every clone's address."""
    registry = FunctionRegistry()
    registry.register("parameter_sweep", library_parameter_sweep)

    def simulate(parameter_1=None, artifacts=None, **kwargs):
        path = artifacts.out_dir() / "result.json"
        path.write_text("{}", encoding="utf-8")
        return f"{artifacts.address}/result.json"

    registry.register("simulate", simulate)
    xml = (
        '<sequential>'
        '<scope type="sequential" name="sweep">'
        '<action function="parameter_sweep">'
        '<argument key="parameter_name" value="p"/>'
        '<argument key="values" value="1, 2"/>'
        "</action>"
        '<scope type="sequential">'
        '<action function="simulate"/>'
        "</scope>"
        "</scope>"
        "</sequential>"
    )
    _, store = _run(xml, registry, tmp_path)
    assert (store.root / "sweep" / "sequential" / "simulate" / "result.json").is_file()
    assert (store.root / "sweep" / "sequential_2" / "simulate" / "result.json").is_file()


# --------------------------------------------------------------------------- #
# Driver corpus (IMP-007 verification): structural derivation equals the
# engine-countered addresses across every adaptation mechanic — the
# expectations below were minted by the engine-side implementation and
# are reproduced position for position by the store-side derivation.
# --------------------------------------------------------------------------- #


def test_iteration_driver_appended_copies_mint_successive_addresses(tmp_path):
    """while_condition's copy-to-end rounds: fresh, suffixed addresses."""
    registry = FunctionRegistry()
    registry.register("while_condition", library_while_condition)

    def body(artifacts=None, **kwargs):
        path = artifacts.out_dir() / "state.txt"
        path.write_text("pending", encoding="utf-8")
        return {"residual": 1.0}  # never below threshold

    registry.register("body", body)
    result, store = _run(
        Sequential(
            Action("body"),
            Action(
                "while_condition",
                upstream="body",
                field="residual",
                op="lt",
                threshold=0.5,
                max_iterations=3,
            ),
        ),
        registry,
        tmp_path,
    )
    assert result == {"converged": False, "iterations": 4, "max_iterations": 3}
    # ``repeat()`` copies the whole preceding prefix (the shipped
    # copy-to-end semantics: each round's copy set contains the earlier
    # rounds), so the cap leaves one already-appended round to run —
    # the same shape the library's own max_iterations test pins.  Every
    # appended copy preserved, suffixed by its rank among same-function
    # siblings.
    assert [e["address"] for e in store.entries()] == [
        "body",
        "while_condition",
        "body_2",
        "while_condition_2",
        "body_3",
        "while_condition_3",
        "body_4",
        "while_condition_4",
    ]
    # The appended copies are dynamic; the declared pair is not.
    assert [e["dynamic"] for e in store.entries()] == [
        False,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
    ]
    for address in ("body", "body_2", "body_3"):
        assert (store.root / address / "state.txt").is_file()


def test_guard_skipped_body_never_mints(tmp_path):
    """guard's skip: the replaced body is absent from the manifest."""
    registry = FunctionRegistry()
    registry.register("guard", library_guard)

    def decide(**kwargs):
        return {"ok": False}

    def body(artifacts=None, **kwargs):
        raise AssertionError("the guarded body must never run")

    registry.register("decide", decide)
    registry.register("body", body)
    _, store = _run(
        Sequential(
            Action("decide"),
            Action("guard", upstream="decide", field="ok", op="eq", value="True"),
            Sequential(Action("body")),
        ),
        registry,
        tmp_path,
    )
    # The declared body was replaced by an empty group (which walks
    # without minting); only the decision and the guard executed.
    assert [e["address"] for e in store.entries()] == ["decide", "guard"]


def test_branch_driver_selected_alternative_mints_under_its_name(tmp_path):
    """evaluate_goal's select: the chosen alternative keeps its name."""
    registry = FunctionRegistry()
    registry.register("evaluate_goal", library_evaluate_goal)

    def decide(**kwargs):
        return {"goal": "beta"}

    def run_alpha(artifacts=None, **kwargs):
        raise AssertionError("the unselected alternative must never run")

    def run_beta(artifacts=None, **kwargs):
        path = artifacts.out_dir() / "result.txt"
        path.write_text("beta", encoding="utf-8")
        return f"{artifacts.address}/result.txt"

    def collect(run_beta=None, artifacts=None, **kwargs):
        return artifacts.read(run_beta).decode()

    registry.register("decide", decide)
    registry.register("run_alpha", run_alpha)
    registry.register("run_beta", run_beta)
    registry.register("collect", collect)
    xml = (
        "<sequential>"
        '<action function="decide"/>'
        '<action function="evaluate_goal">'
        '<argument key="upstream" value="decide"/>'
        '<argument key="field" value="goal"/>'
        "</action>"
        '<sequential name="alternatives">'
        '<sequential name="alpha"><action function="run_alpha"/></sequential>'
        '<sequential name="beta"><action function="run_beta"/></sequential>'
        "</sequential>"
        '<action function="collect"/>'
        "</sequential>"
    )
    result, store = _run(xml, registry, tmp_path)
    assert result == "beta"
    # The selected alternative replaced the alternatives group in place,
    # so its action mints under the alternative's own name; alpha never
    # minted, and the fan-in read flows through the by-value pointer.
    assert [e["address"] for e in store.entries()] == [
        "decide",
        "evaluate_goal",
        "beta/run_beta",
        "collect",
    ]


def test_concurrent_branch_mutation_leaves_a_running_flank_settled(tmp_path):
    """Freeze theorem (IMP-007): branch B adapts its own subtree while
    branch A's action is mid-call; A's call-entry derivation still reads
    the shared pre-group past, undisturbed."""
    a_entered = threading.Event()
    b_returning = threading.Event()
    reads: list[str] = []

    def upstream(artifacts=None, **kwargs):
        path = artifacts.out_dir() / "note.txt"
        path.write_text("shared", encoding="utf-8")
        return f"{artifacts.address}/note.txt"

    def reader_a(upstream=None, artifacts=None, **kwargs):
        # The handle's causal-past view was derived at call entry, on
        # this thread, before the function body started.
        a_entered.set()
        b_returning.wait(timeout=10)  # hold the call across B's adaptation
        reads.append(artifacts.read(upstream).decode())
        return "done"

    def adapter_b(dag=None, **kwargs):
        a_entered.wait(timeout=10)  # A is mid-call when B adapts
        dag.skip()  # the surgery lands at B's return (the commit protocol)
        b_returning.set()
        return {"skipped": True}

    def never_b(**kwargs):
        raise AssertionError("the skipped body must never run")

    registry = FunctionRegistry()
    registry.register("upstream", upstream)
    registry.register("reader_a", reader_a)
    registry.register("adapter_b", adapter_b)
    registry.register("never_b", never_b)
    _, store = _run(
        Sequential(
            Action("upstream"),
            Parallel(
                Sequential(Action("reader_a")),
                Sequential(Action("adapter_b"), Sequential(Action("never_b"))),
            ),
        ),
        registry,
        tmp_path,
    )
    assert reads == ["shared"]
    # B's own subtree was emptied; nothing of it leaked into the past.
    addresses = [e["address"] for e in store.entries()]
    assert "never_b" not in addresses
    assert set(addresses) == {
        "upstream",
        "parallel/sequential/reader_a",
        "parallel/sequential_2/adapter_b",
    }


# --------------------------------------------------------------------------- #
# History linkage and replay
# --------------------------------------------------------------------------- #


def test_records_carry_the_minted_address(tmp_path):
    """ExecutionRecord.artifacts points into the manifest (None without a store)."""
    registry = _writer_registry()
    history = RunHistory()
    store = ArtifactStore(tmp_path / "run")
    Test_Framework(
        Sequential(Action("write", case="a"), Action("read_pointer")),
        registry=registry,
        history=history,
        artifacts=store,
    )
    assert [r.artifacts for r in history] == ["write", "read_pointer"]
    # Without a store: the field stays None.
    history2 = RunHistory()
    Test_Framework(
        Sequential(Action("write", case="a")),
        registry=_guarded_registry(),
        history=history2,
    )
    assert all(r.artifacts is None for r in history2)


def test_replay_reproduces_pointer_results(tmp_path):
    """Replay recomputes the same pointers (original directories reused)."""
    registry = _writer_registry()
    history = RunHistory()
    store = ArtifactStore(tmp_path / "run")
    original = Test_Framework(
        Sequential(Action("write", case="a"), Action("read_pointer")),
        registry=registry,
        history=history,
        artifacts=store,
    )
    assert original == {"case": "a"}
    replayed = replay(history, registry, artifacts=store)
    assert replayed == original


def test_replay_branches_work_through_the_manifest(tmp_path):
    """A replayed fan-in consumer enumerates branches from the manifest."""
    registry = _writer_registry()
    history = RunHistory()
    store = ArtifactStore(tmp_path / "run")
    original = Test_Framework(
        Sequential(
            Parallel(
                Sequential(Action("write", case="left")),
                Sequential(Action("write", case="right")),
            ),
            Action("summarize_branches", group="parallel"),
        ),
        registry=registry,
        history=history,
        artifacts=store,
    )
    replayed = replay(history, registry, artifacts=store)
    assert replayed == original == [{"case": "left"}, {"case": "right"}]


def test_replay_without_a_store_raises_for_artifacts_records(tmp_path):
    """Replaying an artifacts run without passing the store fails loudly."""
    registry = _writer_registry()
    history = RunHistory()
    store = ArtifactStore(tmp_path / "run")
    Test_Framework(
        Sequential(Action("write", case="a")),
        registry=registry,
        history=history,
        artifacts=store,
    )
    with pytest.raises(ValueError, match="artifact store"):
        replay(history, registry)


def test_replayartifacts_read_is_manifest_scoped(tmp_path):
    """Replay reads any minted address (the run is over) and rejects the rest."""
    registry = _writer_registry()
    store = ArtifactStore(tmp_path / "run")
    Test_Framework(
        Sequential(Action("write", case="a")), registry=registry, artifacts=store
    )
    handle = ReplayArtifacts(store, "write")
    assert handle.out_dir() == store.root / "write"
    assert json.loads(handle.read("write/payload.json")) == {"case": "a"}
    with pytest.raises(ValueError):
        handle.read("never_minted/payload.json")


# --------------------------------------------------------------------------- #
# The full campaign: layout parity with the design sketch
# --------------------------------------------------------------------------- #


def test_campaign_layout_matches_the_design(tmp_path):
    """A mini-campaign: writer, sweep, named parallel group, fan-in compare."""
    registry = FunctionRegistry()
    registry.register("parameter_sweep", library_parameter_sweep)

    def find_cases(path=None, artifacts=None, **kwargs):
        listing = artifacts.out_dir() / "cases.json"
        listing.write_text(json.dumps([f"{path}/case_a", f"{path}/case_b"]), encoding="utf-8")
        return f"{artifacts.address}/cases.json"

    def simulate(parameter_1=None, artifacts=None, **kwargs):
        path = artifacts.out_dir() / "result.json"
        path.write_text(json.dumps({"value": parameter_1}), encoding="utf-8")
        return f"{artifacts.address}/result.json"

    def compare(group=None, artifacts=None, **kwargs):
        values = []
        for branch in artifacts.branches(group):
            # Each solvers clone runs a single simulate action, so the
            # branch directory IS the action's directory.
            values.append(json.loads(artifacts.read(branch / "result.json")))
        return values

    registry.register("find_cases", find_cases)
    registry.register("simulate", simulate)
    registry.register("compare", compare)

    xml = (
        "<sequential>"
        '<action function="find_cases">'
        '<argument key="path" value="./models"/>'
        "</action>"
        '<scope type="sequential" name="sweep">'
        '<action function="parameter_sweep">'
        '<argument key="parameter_name" value="parameter_1"/>'
        '<argument key="values" value="1, 2"/>'
        "</action>"
        '<scope type="parallel" name="solvers">'
        '<action function="simulate"/>'
        "</scope>"
        "</scope>"
        '<action function="compare">'
        '<argument key="group" value="solvers"/>'
        "</action>"
        "</sequential>"
    )
    result, store = _run(xml, registry, tmp_path)
    # The sweep replaced the solvers group with two clones; the fan-in
    # consumer compared both clones' simulate results.
    assert result == [{"value": 1}, {"value": 2}]
    # The executed layout, exactly as addressed:
    assert (store.root / "find_cases" / "cases.json").is_file()
    assert (store.root / "sweep" / "solvers" / "simulate" / "result.json").is_file()
    assert (store.root / "sweep" / "solvers_2" / "simulate" / "result.json").is_file()
    manifest = [e["address"] for e in store.entries()]
    assert manifest == [
        "find_cases",
        "sweep/parameter_sweep",
        "sweep/solvers/simulate",
        "sweep/solvers_2/simulate",
        "compare",
    ]


def test_template_bodies_mint_under_the_use_site(tmp_path):
    """Template expansion is invisible: instantiated bodies mint normally."""
    registry = _writer_registry()
    xml = (
        "<VerificationWorkflow>"
        '<template name="produce">'
        '<scope type="sequential">'
        '<action function="write">'
        '<argument key="case" value="{tag}"/>'
        "</action>"
        "</scope>"
        "</template>"
        "<sequential>"
        '<use-template name="produce"><argument key="tag" value="one"/></use-template>'
        '<use-template name="produce"><argument key="tag" value="two"/></use-template>'
        "</sequential>"
        "</VerificationWorkflow>"
    )
    _, store = _run(xml, registry, tmp_path)
    assert (store.root / "sequential" / "write" / "payload.json").is_file()
    assert (store.root / "sequential_2" / "write" / "payload.json").is_file()
