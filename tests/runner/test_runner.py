"""``flow-runner``: config-driven flow selection, inputs, and exit codes.

Covers the console-script entry (``main``): loading and validating the
config, discovering flows via the ``__flow__`` marker, passing
``[inputs]`` as keyword arguments, and the exit-code contract — 0 ok,
1 flow failure, 2 usage/config error.  The ``python -m`` form gets one
subprocess test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from runner import flows as runner_flows
from sequence_extensions.config import Config
from sequence_extensions.flow_runner import find_flows, list_flows, main

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"


@pytest.fixture(autouse=True)
def _reset_config():
    """main() installs the loaded config process-wide; keep tests isolated."""
    from sequence_extensions.config import configure

    configure(Config())
    yield
    configure(Config())


def write_config(tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def echo_config(tmp_path):
    body = f"""
[run]
module = "runner.flows"
flow = "echo"

[inputs]
value = 21
factor = 2

[flow]
log = {str(tmp_path / "logs")!r}
"""
    return write_config(tmp_path, body)


# --------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------- #
def test_find_flows_scans_the_module():
    flows = find_flows(runner_flows)
    assert sorted(flows) == ["double", "echo", "failing"]
    assert flows["echo"].__flow__ == "echo"


def test_list_flows_shows_docstrings():
    entries = dict(list_flows(runner_flows))
    assert entries["echo"] == "Echo value times factor."
    assert entries["failing"] == "Fail on purpose."


# --------------------------------------------------------------- #
# Running
# --------------------------------------------------------------- #
def test_runs_the_selected_flow(tmp_path, capsys):
    config = echo_config(tmp_path)
    assert main([str(config)]) == 0
    out = capsys.readouterr().out
    assert "flow echo: ok" in out
    assert "result: 42" in out
    assert f"log: {tmp_path / 'logs'}" in out
    log_file = Path(runner_flows.echo.last_run["log"])
    assert log_file.exists()


def test_flow_flag_overrides_selection(tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"""
[run]
module = "runner.flows"
flow = "echo"

[inputs]
values = [1, 2]

[flow]
log = {str(tmp_path / "logs")!r}
""",
    )
    assert main([str(config), "--flow", "double"]) == 0
    assert "result: [2, 3]" in capsys.readouterr().out


def test_list_flag_prints_flows(tmp_path, capsys):
    config = echo_config(tmp_path)
    assert main([str(config), "--list"]) == 0
    out = capsys.readouterr().out
    assert "flows in runner.flows:" in out
    assert "echo" in out and "Echo value times factor." in out
    assert "double" in out


def test_failing_flow_exits_one(tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"""
[run]
module = "runner.flows"
flow = "failing"

[flow]
log = {str(tmp_path / "logs")!r}
""",
    )
    assert main([str(config)]) == 1
    captured = capsys.readouterr()
    assert "flow failing: error" in captured.out
    assert "boom" in captured.err  # the traceback


# --------------------------------------------------------------- #
# Usage and config errors: exit code 2
# --------------------------------------------------------------- #
def test_missing_config_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.toml")]) == 2
    assert "cannot read config file" in capsys.readouterr().err


def test_invalid_toml(tmp_path, capsys):
    config = write_config(tmp_path, "[run\n")
    assert main([str(config)]) == 2
    assert "invalid TOML" in capsys.readouterr().err


def test_unknown_key(tmp_path, capsys):
    config = write_config(tmp_path, "[task]\nretriess = 2\n")
    assert main([str(config)]) == 2
    assert "unknown key" in capsys.readouterr().err


def test_no_module_configured(tmp_path, capsys):
    config = write_config(tmp_path, '[run]\nflow = "echo"\n')
    assert main([str(config)]) == 2
    assert "[run].module" in capsys.readouterr().err


def test_module_not_importable(tmp_path, capsys):
    config = write_config(tmp_path, '[run]\nmodule = "no.such.module"\nflow = "x"\n')
    assert main([str(config)]) == 2
    assert "cannot import module" in capsys.readouterr().err


def test_no_flow_selected(tmp_path, capsys):
    config = write_config(tmp_path, '[run]\nmodule = "runner.flows"\n')
    assert main([str(config)]) == 2
    assert "no flow selected" in capsys.readouterr().err


def test_unknown_flow_lists_alternatives(tmp_path, capsys):
    config = echo_config(tmp_path)
    assert main([str(config), "--flow", "nope"]) == 2
    err = capsys.readouterr().err
    assert "no flow 'nope'" in err
    assert "echo" in err and "double" in err  # the available flows


def test_inputs_must_match_signature(tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"""
[run]
module = "runner.flows"
flow = "echo"

[inputs]
value = 21
bogus = 3

[flow]
log = {str(tmp_path / "logs")!r}
""",
    )
    assert main([str(config)]) == 2
    assert "do not match" in capsys.readouterr().err


def test_missing_required_input(tmp_path, capsys):
    config = write_config(
        tmp_path,
        """
[run]
module = "runner.flows"
flow = "echo"
""",
    )
    assert main([str(config)]) == 2
    assert "do not match" in capsys.readouterr().err  # missing 'value'


# --------------------------------------------------------------- #
# python -m entry point
# --------------------------------------------------------------- #
def test_python_m_entry(tmp_path):
    config = echo_config(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(TESTS_DIR)}
    result = subprocess.run(
        [sys.executable, "-m", "sequence_extensions.flow_runner", str(config)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
    )
    assert result.returncode == 0
    assert "result: 42" in result.stdout
