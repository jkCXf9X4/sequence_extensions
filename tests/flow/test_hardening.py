"""Regression probes for the stress-hardening findings.

Every test here maps to one item in the stress report: it fails on the
pre-hardening code (some by hanging, so the probes run behind a deadline) and
passes once the fix is in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from sequence_extensions import GraphFuture, GraphPool, list_ext
from sequence_extensions.flow import (
    ProcessGraphPool,
    RunLog,
    RunOptions,
    execute_flow,
    gather,
    jsonable,
    node,
)


def _within(seconds, fn):
    """Run ``fn`` on a daemon thread; fail instead of hanging the suite."""
    box = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"probe did not finish within {seconds}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ---------------------------------------------------------------- #
# C1 - a run must never hang on attempt finalization/logging
# ---------------------------------------------------------------- #
def test_cyclic_result_returns_and_is_marked(tmp_path):
    @node
    def cyclic():
        value = {}
        value["self"] = value
        return value

    run = _within(5, lambda: execute_flow(cyclic, options=RunOptions(log=tmp_path)))
    assert run.status == "ok"
    records = RunLog.records(run.log)
    node_record = next(r for r in records if r["record"] == "node")
    assert node_record["result"]["self"] == {"type": "dict", "cycle": True}


def test_cyclic_result_without_a_log_does_not_hang():
    @node
    def cyclic():
        value = []
        value.append(value)
        return value

    run = _within(5, lambda: execute_flow(cyclic, options=RunOptions(log=None)))
    assert run.status == "ok"


def test_deep_result_is_marked_instead_of_crashing(tmp_path):
    @node
    def deep():
        value = []
        for _ in range(1200):
            value = [value]
        return value

    run = _within(5, lambda: execute_flow(deep, options=RunOptions(log=tmp_path)))
    assert run.status == "ok"
    raw = Path(run.log).read_text()
    assert "depth_exceeded" in raw


def test_unencodable_surrogate_result_is_logged(tmp_path):
    @node
    def surrogate():
        return "bad \ud800 text"

    run = _within(5, lambda: execute_flow(surrogate, options=RunOptions(log=tmp_path)))
    assert run.status == "ok"
    lines = Path(run.log).read_text().splitlines()
    assert all(json.loads(line) for line in lines)


def test_non_utf8_path_result_is_logged(tmp_path):
    @node
    def weird_path():
        return Path(tmp_path) / "bad_\udcff_name"

    run = _within(5, lambda: execute_flow(weird_path, options=RunOptions(log=tmp_path)))
    assert run.status == "ok"
    assert any(
        "bad_" in str(record.get("result", "")) for record in RunLog.records(run.log)
    )


def test_broken_str_result_is_described(tmp_path):
    class Bad:
        def __str__(self):
            raise RuntimeError("broken __str__")

    @node
    def bad():
        return Bad()

    run = _within(5, lambda: execute_flow(bad, options=RunOptions(log=tmp_path)))
    assert run.status == "ok"
    node_record = next(r for r in RunLog.records(run.log) if r["record"] == "node")
    assert node_record["result"] == "<unprintable Bad>"


def test_submitted_cyclic_child_does_not_hang(tmp_path):
    @node
    def cyclic():
        value = {}
        value["self"] = value
        return value

    @node
    def root():
        return cyclic.submit()

    run = _within(5, lambda: execute_flow(root, options=RunOptions(log=tmp_path)))
    assert run.status == "ok"
    assert run.failed_nodes == ()


def test_log_write_failure_fails_the_run_instead_of_hanging(tmp_path, monkeypatch):
    @node
    def one():
        return 1

    original = RunLog.write

    def fail_node_record(self, record):
        if record.get("record") == "node":
            raise OSError("disk full")
        return original(self, record)

    monkeypatch.setattr(RunLog, "write", fail_node_record)
    with pytest.raises(RuntimeError, match="run-log write failed"):
        _within(5, lambda: execute_flow(one, options=RunOptions(log=tmp_path)))


# ---------------------------------------------------------------- #
# C2 - zero-delay retries are iterative, not recursive
# ---------------------------------------------------------------- #
def test_many_zero_delay_retries_do_not_recurse():
    calls = {"n": 0}

    @node(retries=2000)
    def always_fails():
        calls["n"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _within(10, lambda: execute_flow(always_fails, options=RunOptions(log=None)))
    assert calls["n"] == 2001


def test_many_zero_delay_retries_can_succeed_on_the_last_attempt():
    calls = {"n": 0}

    @node(retries=2000)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2001:
            raise RuntimeError("not yet")
        return calls["n"]

    run = _within(10, lambda: execute_flow(flaky, options=RunOptions(log=None)))
    assert run.result == 2001


def test_retries_of_an_already_failed_future_do_not_recurse():
    from concurrent.futures import Future

    calls = {"n": 0}

    @node(retries=1000)
    def pre_failed():
        calls["n"] += 1
        future = Future()
        future.set_exception(RuntimeError("pre-failed"))
        return future

    with pytest.raises(RuntimeError, match="pre-failed"):
        _within(10, lambda: execute_flow(pre_failed, options=RunOptions(log=None)))
    assert calls["n"] == 1001


# ---------------------------------------------------------------- #
# H1 - process-mode node aliases are unique
# ---------------------------------------------------------------- #
_LAM1 = node(lambda x: x + 1, name="lam1")
_LAM2 = node(lambda x: x + 10, name="lam2")


@node
def _root_lambdas():
    return gather([_LAM1.submit(0), _LAM2.submit(0)])


def _make_node(k, name):
    @node(name=name)
    def inner(x):
        return x + k

    return inner


_FACTORY_A = _make_node(1, "factory_a")
_FACTORY_B = _make_node(10, "factory_b")


@node
def _root_factories():
    return gather([_FACTORY_A.submit(0), _FACTORY_B.submit(0)])


def test_process_lambdas_execute_their_own_function(tmp_path):
    with ProcessGraphPool(max_workers=2) as pool:
        run = _within(
            20,
            lambda: execute_flow(_root_lambdas, options=RunOptions(pool=pool, log=tmp_path)),
        )
    assert run.result == [1, 10]
    results = {
        r["node"]: r["result"]
        for r in RunLog.records(run.log)
        if r["record"] == "node" and r["node"] in {"lam1", "lam2"}
    }
    assert results == {"lam1": 1, "lam2": 10}


def test_process_factory_closures_execute_their_own_function(tmp_path):
    with ProcessGraphPool(max_workers=2) as pool:
        run = _within(
            20,
            lambda: execute_flow(
                _root_factories, options=RunOptions(pool=pool, log=tmp_path)
            ),
        )
    assert run.result == [1, 10]
    results = {
        r["node"]: r["result"]
        for r in RunLog.records(run.log)
        if r["record"] == "node" and r["node"] in {"factory_a", "factory_b"}
    }
    assert results == {"factory_a": 1, "factory_b": 10}


# ---------------------------------------------------------------- #
# H2 - GraphFuture settles BaseException instead of staying pending
# ---------------------------------------------------------------- #
def _raise_system_exit():
    raise SystemExit(3)


def test_graph_future_settles_system_exit():
    with GraphPool(max_workers=2) as pool:
        gf = GraphFuture(_raise_system_exit)
        with pytest.raises(RuntimeError, match="SystemExit"):
            _within(5, lambda: pool.result(gf, timeout=2))
        assert gf.done()


# ---------------------------------------------------------------- #
# D1 - fixed_clock stays byte-identical across processes
# ---------------------------------------------------------------- #
_FIXED_DICT_SCRIPT = r"""
import os
from pathlib import Path
from sequence_extensions.flow import node, execute_flow, RunOptions

@node
def d():
    return {k: 1 for k in {"alpha", "beta", "gamma", "delta"}}

@node
def root():
    return d.submit()

run = execute_flow(root, options=RunOptions(log=os.environ["OUT"], fixed_clock=True))
print(Path(run.log).read_bytes().hex())
"""


def test_fixed_clock_dict_order_is_hash_seed_independent(tmp_path):
    script = tmp_path / "fixed_prog.py"
    script.write_text(_FIXED_DICT_SCRIPT)
    repo_src = Path(__file__).resolve().parents[2] / "src"
    outputs = []
    for seed in ("0", "1"):
        env = dict(
            os.environ,
            PYTHONHASHSEED=seed,
            OUT=str(tmp_path / seed),
            PYTHONPATH=str(repo_src),
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout.strip())
    assert outputs[0] == outputs[1]


def test_jsonable_mixed_set_is_deterministic():
    value = {1, "a", 2.5, None}
    first = jsonable(value)
    second = jsonable(value)
    assert first == second
    assert set(map(str, first)) == {"1", "a", "2.5", "None"}


# ---------------------------------------------------------------- #
# D2 - concurrent fixed-clock runs cannot clobber one log
# ---------------------------------------------------------------- #
@pytest.mark.flaky_timing
def test_concurrent_fixed_clock_runs_are_rejected(tmp_path):
    gate = threading.Event()

    @node
    def slow():
        gate.wait(5)
        return 1

    outcomes = []

    def go():
        try:
            execute_flow(slow, options=RunOptions(log=tmp_path, fixed_clock=True))
            outcomes.append("ok")
        except BaseException as exc:  # noqa: BLE001 - asserted below
            outcomes.append(type(exc).__name__)

    first = threading.Thread(target=go)
    first.start()
    deadline = time.time() + 5
    while not list(Path(tmp_path).glob("*.jsonl")) and time.time() < deadline:
        time.sleep(0.01)
    second = threading.Thread(target=go)
    second.start()
    time.sleep(0.1)
    gate.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(outcomes) == ["RuntimeError", "ok"]


# ---------------------------------------------------------------- #
# D3 - diff counts repeated identical executions
# ---------------------------------------------------------------- #
def _synthetic_log(node_records):
    return [
        {"record": "run_start", "run_id": "r", "node": "root", "args": [], "kwargs": {}},
        *node_records,
        {"record": "run_end", "run_id": "r", "status": "ok", "result": "done"},
    ]


def _synthetic_work(seq):
    return {
        "record": "node",
        "run_id": "r",
        "node": "work",
        "path": ["root", "work"],
        "attempt": 1,
        "parent_attempt": None,
        "status": "ok",
        "args": [5],
        "kwargs": {},
        "result": 10,
        "seq": seq,
    }


def test_diff_sees_a_changed_number_of_identical_calls():
    three = _synthetic_log([_synthetic_work(2), _synthetic_work(3), _synthetic_work(4)])
    four = _synthetic_log(
        [_synthetic_work(2), _synthetic_work(3), _synthetic_work(4), _synthetic_work(5)]
    )
    report = RunLog.diff(three, four)
    assert report["equal"] is False
    assert report["only_left"] == []
    assert len(report["only_right"]) == 1
    assert report["only_right"][0]["occurrence"] == 3


def test_diff_identical_executions_are_a_multiset_not_a_sequence():
    left = _synthetic_log([_synthetic_work(2), _synthetic_work(3)])
    right = _synthetic_log([_synthetic_work(3), _synthetic_work(2)])
    assert RunLog.diff(left, right)["equal"] is True


def test_diff_reordered_repeats_with_different_results_still_align():
    first = _synthetic_work(2)
    first["result"] = 1
    second = _synthetic_work(3)
    second["result"] = 2
    left = _synthetic_log([first, second])
    right = _synthetic_log([second, first])
    assert RunLog.diff(left, right)["equal"] is True


# ---------------------------------------------------------------- #
# D4 - the log is strict JSON
# ---------------------------------------------------------------- #
def test_non_finite_floats_are_strict_json(tmp_path):
    @node
    def weird():
        return {"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf")}

    run = execute_flow(weird, options=RunOptions(log=tmp_path))
    raw = Path(run.log).read_text()
    assert "NaN" not in raw and "Infinity" not in raw

    def reject(token):
        raise ValueError(token)

    for line in raw.splitlines():
        json.loads(line, parse_constant=reject)
    node_record = next(r for r in RunLog.records(run.log) if r["record"] == "node")
    assert node_record["result"] == {
        "nan": {"float": "nan"},
        "inf": {"float": "inf"},
        "ninf": {"float": "-inf"},
    }


# ---------------------------------------------------------------- #
# D5 - fire-and-forget failures are visible on the Run
# ---------------------------------------------------------------- #
def test_fire_and_forget_failure_is_listed_in_failed_nodes(tmp_path):
    @node
    def bad():
        raise ValueError("forgotten")

    @node
    def root():
        bad.submit()
        return "ok"

    run = execute_flow(root, options=RunOptions(log=tmp_path))
    assert run.status == "ok"
    assert run.failed_nodes == (("root", "bad"),)
    end = next(r for r in RunLog.records(run.log) if r["record"] == "run_end")
    assert end["failed_nodes"] == [["root", "bad"]]


def test_retried_then_successful_node_is_not_a_failure(tmp_path):
    calls = {"n": 0}

    @node(retries=1)
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("once")
        return 1

    run = execute_flow(flaky, options=RunOptions(log=tmp_path))
    assert run.status == "ok"
    assert run.failed_nodes == ()


# ---------------------------------------------------------------- #
# O1 - a node belongs to exactly one pool
# ---------------------------------------------------------------- #
def test_cross_pool_bind_is_rejected_without_cancelling_the_owner():
    gate = threading.Event()

    def slow():
        gate.wait(5)
        return 42

    a = GraphFuture(slow)
    owner = GraphPool(max_workers=2)
    other = GraphPool(max_workers=2)
    owner.bind(a)
    try:
        with pytest.raises(ValueError, match="another GraphPool"):
            other.bind(a)
        gate.set()
        assert owner.result(a, timeout=5) == 42
    finally:
        gate.set()
        owner.__exit__(None, None, None)
        other.__exit__(None, None, None)


# ---------------------------------------------------------------- #
# O3 - intersect/union preserve order and support unhashables
# ---------------------------------------------------------------- #
def test_intersect_preserves_order_and_dedupes():
    assert list(list_ext(["b", "a", "c"]).intersect(["c", "a", "d"])) == ["a", "c"]
    assert list(list_ext([1, 1, 2]).intersect([2, 1])) == [1, 2]


def test_intersect_supports_unhashable_items():
    assert list(list_ext([[1], [2]]).intersect([[2]])) == [[2]]


def test_union_preserves_first_occurrence_order():
    assert list(list_ext(["b", "a"]).union(["z", "y"])) == ["b", "a", "z", "y"]
    assert list(list_ext([1, 1, 2]).union([2, 3])) == [1, 2, 3]


def test_union_orders_a_set_operand_deterministically():
    assert list(list_ext([1, 2]).union({3, 0})) == [1, 2, 0, 3]


# ---------------------------------------------------------------- #
# O4 - log dict keys do not silently collide
# ---------------------------------------------------------------- #
def test_jsonable_disambiguates_dict_key_collisions():
    assert jsonable({1: "int", "1": "str"}) == {"1": "int", "1#str": "str"}
    assert jsonable({1: "a"}) == {"1": "a"}


# ---------------------------------------------------------------- #
# O5 - gather understands mappings and tuple subclasses
# ---------------------------------------------------------------- #
def test_gather_resolves_mapping_proxy(tmp_path):
    from types import MappingProxyType

    @node
    def one(x):
        return x

    @node
    def root():
        return gather(MappingProxyType({"a": one.submit(1)}))

    run = execute_flow(root, options=RunOptions(log=tmp_path))
    assert run.result == {"a": 1}


def test_gather_resolves_user_dict(tmp_path):
    from collections import UserDict

    @node
    def one(x):
        return x

    @node
    def root():
        return gather(UserDict({"a": one.submit(1)}))

    run = execute_flow(root, options=RunOptions(log=tmp_path))
    assert run.result == {"a": 1}


def test_gather_keeps_orderable_tuple_subclass(tmp_path):
    class Pair(tuple):
        pass

    @node
    def one(x):
        return x

    @node
    def root():
        return gather(Pair((one.submit(1), one.submit(2))))

    run = execute_flow(root, options=RunOptions(log=tmp_path))
    assert type(run.result) is Pair
    assert run.result == (1, 2)


# ---------------------------------------------------------------- #
# O7 - futures/helpers outside a run fail loudly, not silently
# ---------------------------------------------------------------- #
def test_gather_outside_a_run_raises():
    with pytest.raises(RuntimeError, match="active run"):
        gather([])


def test_unbound_graph_future_result_raises():
    gf = GraphFuture(lambda: 1)
    with pytest.raises(RuntimeError, match="not bound"):
        gf.result()


# ---------------------------------------------------------------- #
# O9 - filter(node=...) is documented to include run_start
# ---------------------------------------------------------------- #
def test_filter_node_includes_run_start_unless_record_is_node():
    records = _synthetic_log([_synthetic_work(2)])
    assert len(RunLog.filter(records, node="root")) == 1  # the run_start
    assert len(RunLog.filter(records, node="work")) == 1  # the node record
    assert len(RunLog.filter(records, node="work", record="node")) == 1


# ---------------------------------------------------------------- #
# O2/O8 - flow-runner: options parameter and import-time failures
# ---------------------------------------------------------------- #
def _write_runner_module(tmp_path):
    (tmp_path / "optmod.py").write_text(
        "from sequence_extensions.flow import node\n"
        "@node\n"
        "def opt(options):\n"
        "    return options\n"
        "@node\n"
        "def pair(x, options, y=0):\n"
        "    return [x, options, y]\n"
        "@node\n"
        "def kwonly(*, options):\n"
        "    return options\n"
    )


def test_runner_passes_an_options_parameter_positionally(tmp_path):
    from sequence_extensions.flow_runner import main

    _write_runner_module(tmp_path)
    (tmp_path / "cfg.toml").write_text(
        "[run]\nmodule='optmod'\nflow='opt'\nlog=''\n[inputs]\noptions=7\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        assert main([str(tmp_path / "cfg.toml")]) == 0
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("optmod", None)


def test_runner_passes_options_after_other_positional_inputs(tmp_path):
    from sequence_extensions.flow_runner import main

    _write_runner_module(tmp_path)
    (tmp_path / "cfg.toml").write_text(
        "[run]\nmodule='optmod'\nflow='pair'\nlog=''\n"
        "[inputs]\nx=1\noptions=2\ny=3\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        assert main([str(tmp_path / "cfg.toml")]) == 0
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("optmod", None)


def test_runner_rejects_keyword_only_options_as_usage_error(tmp_path):
    from sequence_extensions.flow_runner import main

    _write_runner_module(tmp_path)
    (tmp_path / "cfg.toml").write_text(
        "[run]\nmodule='optmod'\nflow='kwonly'\nlog=''\n[inputs]\noptions=4\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        assert main([str(tmp_path / "cfg.toml")]) == 2
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("optmod", None)


def test_runner_import_time_exception_is_a_usage_error(tmp_path):
    from sequence_extensions.flow_runner import main

    (tmp_path / "boommod.py").write_text("raise RuntimeError('import boom')\n")
    (tmp_path / "cfg.toml").write_text("[run]\nmodule='boommod'\nflow='x'\n")
    sys.path.insert(0, str(tmp_path))
    try:
        assert main([str(tmp_path / "cfg.toml")]) == 2
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("boommod", None)


# ---------------------------------------------------------------- #
# D2b - POSIX process-level lock for a fixed reference log
# ---------------------------------------------------------------- #
def test_fixed_clock_lock_is_cross_process(tmp_path):
    fcntl = pytest.importorskip("fcntl")
    assert fcntl is not None

    @node
    def slow():
        return 1

    script = tmp_path / "holder.py"
    script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "from sequence_extensions.flow import RunLog\n"
        "log = RunLog(Path(sys.argv[1]), fixed_clock=True)\n"
        "log.open()\n"
        "print('ready', flush=True)\n"
        "time.sleep(10)\n"
        "log.close()\n"
    )
    log_path = tmp_path / "slow-fixed.jsonl"
    repo_src = Path(__file__).resolve().parents[2] / "src"
    env = dict(os.environ, PYTHONPATH=str(repo_src))
    holder = subprocess.Popen(
        [sys.executable, str(script), str(log_path)],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        with pytest.raises(RuntimeError, match="another process"):
            execute_flow(slow, options=RunOptions(log=tmp_path, fixed_clock=True))
    finally:
        holder.terminate()
        holder.wait(timeout=5)


# ---------------------------------------------------------------- #
# E1 - an engine fault while finalizing settles instead of hanging
# ---------------------------------------------------------------- #
@pytest.mark.parametrize("fault_type", [RuntimeError, KeyboardInterrupt])
def test_finish_fault_settles_the_outcome_instead_of_hanging(fault_type):
    """A callback/timer finalizer that raises must settle the outcome.

    ``_finish_safely`` is the timer/callback entry point; an engine error
    there (or a non-``Exception`` ``BaseException``) becomes the outcome's
    exception, so the drain cannot wait on an unsettled future.
    """
    from sequence_extensions.flow._attempt import _AttemptRunner
    from sequence_extensions.flow._context import AttemptToken

    @node
    def leaf():
        return 1

    runner = _AttemptRunner(
        leaf,
        (),
        {},
        None,
        parent_token=None,
        run_attempt_token=None,
        retries=0,
        delay=0.0,
        timeout=None,
    )

    def faulting_finish(*args, **kwargs):
        raise fault_type("engine fault")

    runner._finish = faulting_finish
    retry = runner._finish_safely(1, "ok", 1, AttemptToken(), "started", time.perf_counter())
    assert retry is False
    with pytest.raises(RuntimeError, match="engine fault"):
        runner.outcome.result(timeout=1)
