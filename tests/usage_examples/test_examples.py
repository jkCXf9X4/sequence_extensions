"""The runnable examples are part of the test suite.

Every module under ``examples/`` is executed here and checked against the
behaviour the usage documentation promises.  In-process where the example has
a ``main()``, as a subprocess for the CLI example.  If an example drifts from
the library, these tests fail before the documentation can rot.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from examples import campaign as campaign_example
from examples import graph_futures, policies, process_pool, run_log, sequences
from sequence_extensions.flow import RunLog

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"


def test_sequences_example(capsys):
    result = sequences.main()
    out = capsys.readouterr().out

    assert result["finished"] == ["c1", "c2", "c3"]
    assert result["scores"] == [0.82, 0.91, 0.74]
    assert result["mean"] == pytest.approx((0.82 + 0.91 + 0.74) / 3)
    assert result["moving"] == [0.865, 0.825]
    assert result["by_case"] == {"c1": 0.82, "c2": 0.91, "c3": 0.74}
    assert result["passing"] == {"c1": 0.82, "c2": 0.91}
    assert result["best"].key == "c2"
    assert result["best"].value == 0.91
    assert result["stages"] == [2, 4, 8, 16, 32]
    assert result["metadata"] == {"solver": "mock", "cases": 4}
    assert "passing:  c1 : 0.82, c2 : 0.91" in out


def test_graph_futures_example(capsys):
    result = graph_futures.main()
    out = capsys.readouterr().out

    assert result == {
        "diamond": 50,
        "chained": 20,
        "plain_future": 20,
        "error": "ZeroDivisionError",
        "timeout": "TimeoutError",
    }
    assert "diamond:  50" in out
    assert "chained:  20" in out
    assert "plain:    20" in out


def test_campaign_example_runs_and_logs(tmp_path, capsys):
    out = tmp_path / "campaign"
    result = campaign_example.main(["--out", str(out), "--workers", "3"])
    run = result["run"]

    assert run.status == "ok"
    assert run.result["cases"] == 4
    assert run.result["passed"] == 2
    assert run.result["mean_score"] == pytest.approx(0.78)
    assert result["retried"] == 4
    assert run.log.exists()

    summary = result["summary"]
    assert summary["status"] == "ok"
    assert {tuple(entry["path"]) for entry in summary["nodes"]} == {
        ("campaign",),
        ("campaign", "count_cases"),
        ("campaign", "simulate"),
        ("campaign", "evaluate"),
        ("campaign", "summarize"),
    }

    records = RunLog.records(run.log)
    assert records[0]["record"] == "run_start"
    assert records[-1]["record"] == "run_end"
    assert records[-1]["status"] == "ok"

    # Every case failed its first attempt and succeeded on the retry.
    by_case = {}
    for record in RunLog.filter(records, record="node", node="simulate"):
        by_case.setdefault(Path(record["args"][0]["path"]).name, []).append(record["status"])
    assert by_case == {
        "c1.csv": ["error", "ok"],
        "c2.csv": ["error", "ok"],
        "c3.csv": ["error", "ok"],
        "c4.csv": ["error", "ok"],
    }

    # A returned Path is logged as path plus content hash, not payload.
    sim_ok = next(
        record for record in RunLog.filter(records, record="node", node="simulate", status="ok")
    )
    assert sim_ok["result"]["path"].endswith(".json")
    assert sim_ok["result"]["sha256"]
    assert "retried: 4 simulate attempts" in capsys.readouterr().out


def test_policies_example(tmp_path, capsys):
    result = policies.main(["--out", str(tmp_path)])

    assert result["retry"]["result"] == 3
    assert result["retry"]["statuses"] == ["error", "error", "ok"]
    assert result["defaults"]["result"] == 2
    assert result["defaults"]["statuses"] == ["error", "ok"]
    assert result["timeout"]["error"] == "NodeTimeoutError"
    assert result["timeout"]["node"] == "too_slow"
    assert result["timeout"]["statuses"] == ["timeout"]
    assert result["failure"]["error"] == "deliberate failure"
    assert result["failure"]["run_status"] == "error"
    assert result["failure"]["skip_reason"] == "dependency failed"
    assert result["run_timeout"]["error"] == "NodeTimeoutError"
    assert result["run_timeout"]["run_status"] == "timeout"
    assert result["run_timeout"]["run_end_status"] == "timeout"
    assert result["run_retry"]["result"] == 2
    assert result["run_retry"]["logs"] == 2
    out = capsys.readouterr().out
    assert "retries:     ['error', 'error', 'ok']" in out
    assert "run retries: 2 (2 logs)" in out


def test_run_log_example(tmp_path, capsys):
    result = run_log.main(["--out", str(tmp_path)])

    assert result["identical"] is True
    assert result["diff"] == {"equal": True, "only_left": [], "only_right": [], "changed": []}
    assert result["records"][0]["record"] == "run_start"
    assert result["records"][-1]["record"] == "run_end"
    assert len(result["squares"]) == 6
    assert result["summary"]["run_id"] == "log_demo-fixed"
    assert result["summary"]["status"] == "ok"
    assert result["summary_args"] == {"type": "list", "len": 20}
    assert result["quiet_log"] is None
    assert "fixed logs byte-identical: True" in capsys.readouterr().out


def test_process_pool_example(tmp_path, capsys):
    result = process_pool.main(["--out", str(tmp_path), "--size", "200000"])

    assert result["run"].status == "ok"
    assert len(result["result"]) == 4
    assert len(set(result["result"])) == 1
    assert result["result"][0] > 0
    assert result["workers"]
    assert all(worker.startswith("proc-") for worker in result["workers"])
    assert Path(result["log"]).exists()
    assert "workers: ['proc-" in capsys.readouterr().out


def test_flow_runner_example(tmp_path):
    run_dir = tmp_path / "flow_runner"
    shutil.copytree(
        EXAMPLES / "flow_runner",
        run_dir,
        ignore=shutil.ignore_patterns("_out", "__pycache__"),
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "src"), str(run_dir)]),
    }
    command = [sys.executable, "-m", "sequence_extensions.flow_runner", "campaign.toml"]

    listed = subprocess.run(
        [*command, "--list"], cwd=run_dir, env=env, capture_output=True, text=True, timeout=60
    )
    assert listed.returncode == 0, listed.stderr
    assert "flows in flows:" in listed.stdout
    assert "campaign" in listed.stdout
    assert "Run every case through simulate and evaluate" in listed.stdout

    result = subprocess.run(
        command, cwd=run_dir, env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "flow campaign: ok" in result.stdout
    assert "result:" in result.stdout

    verdict = json.loads(result.stdout.rsplit("result: ", 1)[1].strip())
    assert verdict == {"cases": 4, "passed": 2, "mean": 1.565}

    logs = sorted((run_dir / "_out" / "runs").glob("*.jsonl"))
    assert len(logs) == 1
    records = RunLog.records(logs[0])
    assert records[-1]["record"] == "run_end" and records[-1]["status"] == "ok"
    retried = RunLog.filter(records, record="node", node="simulate", status="error")
    assert len(retried) == 4
