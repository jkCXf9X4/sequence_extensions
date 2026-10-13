"""
End-to-end tests for the CLI (``sequence_extensions.cli`` / ``__main__``).

The CLI is exercised through :func:`sequence_extensions.cli.main` (in-process,
capturing its logging) and once through ``python -m sequence_extensions``
(subprocess, proving the ``__main__`` entry point).  Coverage: the success
path (exit 0, history JSON written, campaign log lines emitted), the failure
path (non-zero exit, error logged, partial history still written), the
``--artifacts-dir`` evidence, ``--dry-run``, an unreadable workflow file, and
the ``--help`` option surface.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sequence_extensions.cli import build_parser, main

SUCCESS_XML = """\
<VerificationWorkflow>
  <scope type="sequential">
    <action function="simulate">
      <argument key="label" value="cli"/>
    </action>
    <action function="evaluate_results"/>
  </scope>
</VerificationWorkflow>
"""

FAILURE_XML = """\
<scope type="sequential">
  <action function="no_such_function"/>
</scope>
"""


@pytest.fixture
def cli_env(tmp_path):
    """Workflow XML files on disk plus the output paths for a CLI run."""
    success = tmp_path / "success.xml"
    success.write_text(SUCCESS_XML, encoding="utf-8")
    failure = tmp_path / "failure.xml"
    failure.write_text(FAILURE_XML, encoding="utf-8")
    return {
        "tmp": tmp_path,
        "success": success,
        "failure": failure,
        "history_out": tmp_path / "out" / "history.json",
        "artifacts_dir": tmp_path / "artifacts",
    }


def _run_cli(env, *args):
    """Invoke main() and return (exit_code, caplog text)."""
    code = main(list(args))
    return code


def test_success_exit_zero_history_and_logs(cli_env, caplog):
    code = _run_cli(cli_env, str(cli_env["success"]), "--history-out", str(cli_env["history_out"]))
    assert code == 0

    # History JSON written and well-formed, with the run's records.
    document = json.loads(cli_env["history_out"].read_text(encoding="utf-8"))
    assert document["run_id"]
    assert document["final_order"] == 1  # two actions, final is the second
    assert [r["name"] for r in document["records"]] == ["simulate", "evaluate_results"]

    # Campaign-level log lines: start (path + options) and completion
    # (record count + duration + run id).
    text = caplog.text
    assert "starting workflow" in text and str(cli_env["success"]) in text
    assert "completed in" in text and "2 action record(s)" in text
    assert f"run_id={document['run_id']}" in text
    assert "history written to" in text


def test_failure_exit_nonzero_error_logged_partial_history(cli_env, caplog):
    code = _run_cli(cli_env, str(cli_env["failure"]), "--history-out", str(cli_env["history_out"]))
    assert code != 0

    text = caplog.text
    assert "failed after" in text
    assert "ValueError" in text

    # A failed run still leaves the partial history as evidence.
    document = json.loads(cli_env["history_out"].read_text(encoding="utf-8"))
    assert document["final_order"] is None
    assert document["records"] == []


def test_artifacts_dir_leaves_manifest(cli_env, caplog):
    code = _run_cli(
        cli_env,
        str(cli_env["success"]),
        "--artifacts-dir",
        str(cli_env["artifacts_dir"]),
        "--history-out",
        str(cli_env["history_out"]),
    )
    assert code == 0
    manifest = cli_env["artifacts_dir"] / "manifest.jsonl"
    assert manifest.is_file()
    lines = [line for line in manifest.read_text(encoding="utf-8").splitlines() if line]
    header = json.loads(lines[0])  # the run header (run identity + start time)
    # The store was constructed with the run's history, so the manifest
    # header names the same run as the history document.
    document = json.loads(cli_env["history_out"].read_text(encoding="utf-8"))
    assert header["run_id"] == document["run_id"]
    entries = [json.loads(line) for line in lines[1:]]
    assert [e["function"] for e in entries] == ["simulate", "evaluate_results"]
    assert "artifacts written to" in caplog.text


def test_dry_run_exit_zero_and_history_recorded(cli_env, caplog):
    code = _run_cli(cli_env, str(cli_env["success"]), "--dry-run", "--history-out", str(cli_env["history_out"]))
    assert code == 0
    document = json.loads(cli_env["history_out"].read_text(encoding="utf-8"))
    assert len(document["records"]) == 2  # plan mode still records what WOULD run
    assert "completed in" in caplog.text


def test_missing_workflow_file_exit_one(cli_env, caplog):
    code = _run_cli(cli_env, str(cli_env["tmp"] / "nope.xml"))
    assert code == 1
    assert "cannot read workflow file" in caplog.text


def test_help_lists_run_options():
    help_text = build_parser().format_help()
    for option in (
        "workflow",
        "-v",
        "-q",
        "--params-mode",
        "--max-workers",
        "--adaptation-bound",
        "--action-timeout",
        "--fail-fast",
        "--dry-run",
        "--history-out",
        "--artifacts-dir",
    ):
        assert option in help_text


def test_python_minus_m_entry_point(cli_env):
    """``python -m sequence_extensions`` runs the same CLI (subprocess)."""
    src = Path(__file__).resolve().parents[2] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sequence_extensions",
            str(cli_env["success"]),
            "--history-out",
            str(cli_env["history_out"]),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "completed in" in completed.stderr
    document = json.loads(cli_env["history_out"].read_text(encoding="utf-8"))
    assert document["final_order"] == 1
