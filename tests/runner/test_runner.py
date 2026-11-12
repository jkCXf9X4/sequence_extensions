"""``flow-runner``: plan-file runs, node selection, and exit codes.

Covers the console-script entry (``main``): loading a ``flow-plan/2`` JSON
document, discovering nodes via the ``__node__`` marker, ``--flow`` and
auto-selection, ``--log``, stdin, and the exit-code contract — 0 ok,
1 run failure, 2 usage/config error.  The ``python -m`` form gets one
subprocess test.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

from runner import flows as runner_flows
from sequence_extensions.flow_runner import find_nodes, main

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"

DEFAULT_OPTIONS = {
    "max_workers": 16,
    "summary": False,
    "fixed_clock": False,
    "retries": 0,
    "retry_delay_seconds": 0.0,
    "timeout": None,
}


# --------------------------------------------------------------- #
# Plan fixtures
# --------------------------------------------------------------- #
def param(name, value, *, type="", required=False, default=None):
    return {
        "name": name,
        "type": type,
        "required": required,
        "default": default,
        "value": value,
    }


def node_entry(name, params=()):
    return {
        "id": 0,
        "name": name,
        "kind": "node",
        "path": [name],
        "instance": 1,
        "policy": {"retries": 0, "retry_delay_seconds": 0.0, "timeout": None},
        "params": list(params),
    }


def plan_document(*, parameters=(), nodes=(), edges=(), options=None, schema="flow-plan/2"):
    return {
        "schema": schema,
        "parameters": list(parameters),
        "nodes": list(nodes),
        "edges": list(edges),
        "options": {**DEFAULT_OPTIONS, **(options or {})},
    }


def write_plan(tmp_path, document, name="plan.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def echo_plan(tmp_path, *, value=21, factor=2, options=None):
    return write_plan(
        tmp_path,
        plan_document(
            parameters=[
                param("value", value, type="int", required=True),
                param("factor", factor, type="int", default=1),
            ],
            nodes=[
                node_entry(
                    "echo",
                    [param("value", value, type="int"), param("factor", factor)],
                )
            ],
            options=options,
        ),
    )


def failing_plan(tmp_path):
    return write_plan(
        tmp_path,
        plan_document(nodes=[node_entry("failing")]),
    )


def run_plan(plan, flow, *, log=None, module="runner.flows"):
    argv = [str(plan), "--module", module]
    if flow is not None:
        argv += ["--flow", flow]
    if log is not None:
        argv += ["--log", str(log)]
    return main(argv)


# --------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------- #
def test_find_nodes_scans_the_module():
    nodes = find_nodes(runner_flows)
    assert sorted(nodes) == ["bump", "double", "echo", "failing"]
    assert nodes["echo"].__node__ == "echo"


# --------------------------------------------------------------- #
# Running
# --------------------------------------------------------------- #
def test_runs_the_selected_flow(tmp_path, capsys):
    plan = echo_plan(tmp_path)
    logs = tmp_path / "logs"
    assert run_plan(plan, "echo", log=logs) == 0
    out = capsys.readouterr().out
    assert "flow echo: ok" in out
    assert "result: 42" in out
    assert f"log: {logs}" in out
    log_file = next(logs.glob("*.jsonl"))
    assert log_file.exists()


def test_auto_selects_the_only_node(tmp_path, capsys):
    (tmp_path / "singleflow.py").write_text(
        "from sequence_extensions.flow import node\n"
        "@node\n"
        "def solo():\n"
        "    return 7\n",
        encoding="utf-8",
    )
    plan = write_plan(tmp_path, plan_document())
    sys.path.insert(0, str(tmp_path))
    try:
        assert main([str(plan), "--module", "singleflow", "--log", str(tmp_path / "logs")]) == 0
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("singleflow", None)
    out = capsys.readouterr().out
    assert "flow solo: ok" in out
    assert "result: 7" in out


def test_flow_flag_overrides_selection(tmp_path, capsys):
    plan = write_plan(
        tmp_path,
        plan_document(
            parameters=[param("values", [1, 2], type="list", required=True)],
            nodes=[node_entry("double", [param("values", [1, 2], type="list")])],
        ),
    )
    assert main([str(plan), "--module", "runner.flows", "--flow", "double"]) == 0
    assert "result: [2, 3]" in capsys.readouterr().out


def test_plan_from_stdin(tmp_path, capsys, monkeypatch):
    plan = echo_plan(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(plan.read_text(encoding="utf-8")))
    assert main(["-", "--module", "runner.flows", "--flow", "echo", "--log", str(tmp_path)]) == 0
    assert "result: 42" in capsys.readouterr().out


def test_options_come_from_the_plan(tmp_path, capsys):
    plan = echo_plan(tmp_path, options={"max_workers": 3, "fixed_clock": True})
    assert run_plan(plan, "echo", log=tmp_path) == 0
    assert "flow echo: ok" in capsys.readouterr().out

def test_list_flag_prints_flows(capsys):
    assert main(["--module", "runner.flows", "--list"]) == 0
    out = capsys.readouterr().out
    assert "flows in runner.flows:" in out
    assert "echo" in out and "Echo value times factor." in out
    assert "double" in out


def test_failing_flow_exits_one(tmp_path, capsys):
    plan = failing_plan(tmp_path)
    assert run_plan(plan, "failing", log=tmp_path) == 1
    captured = capsys.readouterr()
    assert "flow failing: error" in captured.out
    assert "boom" in captured.err


def test_node_policy_from_the_plan(tmp_path, capsys):
    document = plan_document(
        parameters=[param("value", 3, type="int", required=True)],
        nodes=[
            {
                "id": 0,
                "name": "echo",
                "kind": "node",
                "path": ["echo"],
                "instance": 1,
                "policy": {"retries": 2, "retry_delay_seconds": 0.0, "timeout": 5.0},
                "params": [param("value", 3, type="int")],
            }
        ],
    )
    plan = write_plan(tmp_path, document)
    assert run_plan(plan, "echo", log=tmp_path) == 0
    assert "flow echo: ok" in capsys.readouterr().out


# --------------------------------------------------------------- #
# Usage and config errors: exit code 2
# --------------------------------------------------------------- #
def test_missing_plan_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json"), "--module", "runner.flows"]) == 2
    assert "cannot read plan file" in capsys.readouterr().err


def test_invalid_json(tmp_path, capsys):
    plan = tmp_path / "plan.json"
    plan.write_text("{not json", encoding="utf-8")
    assert main([str(plan), "--module", "runner.flows"]) == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_wrong_schema(tmp_path, capsys):
    plan = write_plan(tmp_path, plan_document(schema="flow-plan/1"))
    assert main([str(plan), "--module", "runner.flows"]) == 2
    assert "expected schema 'flow-plan/2'" in capsys.readouterr().err


def test_missing_plan_argument(tmp_path, capsys):
    assert main(["--module", "runner.flows"]) == 2
    assert "no plan given" in capsys.readouterr().err


def test_module_not_importable(tmp_path, capsys):
    plan = echo_plan(tmp_path)
    assert main([str(plan), "--module", "no.such.module"]) == 2
    assert "cannot import module" in capsys.readouterr().err


def test_no_flow_selected(tmp_path, capsys):
    plan = echo_plan(tmp_path)
    assert main([str(plan), "--module", "runner.flows"]) == 2
    err = capsys.readouterr().err
    assert "no flow selected" in err
    assert "echo" in err and "double" in err


def test_unknown_flow_lists_alternatives(tmp_path, capsys):
    plan = echo_plan(tmp_path)
    assert main([str(plan), "--module", "runner.flows", "--flow", "nope"]) == 2
    err = capsys.readouterr().err
    assert "no flow 'nope'" in err
    assert "echo" in err and "double" in err


def test_missing_required_input(tmp_path, capsys):
    plan = write_plan(
        tmp_path,
        plan_document(
            parameters=[param("value", None, type="int", required=True)],
            nodes=[],
        ),
    )
    assert main([str(plan), "--module", "runner.flows", "--flow", "echo"]) == 2
    assert "missing required root parameter" in capsys.readouterr().err


# --------------------------------------------------------------- #
# python -m entry point
# --------------------------------------------------------------- #
def test_python_m_entry(tmp_path):
    plan = echo_plan(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(TESTS_DIR)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sequence_extensions.flow_runner",
            str(plan),
            "--module",
            "runner.flows",
            "--flow",
            "echo",
            "--log",
            str(tmp_path / "logs"),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
    )
    assert result.returncode == 0
    assert "result: 42" in result.stdout
