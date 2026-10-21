"""``flow-runner``: config-driven node selection, inputs, and exit codes.

Covers the console-script entry (``main``): loading and validating the
config, discovering nodes via the ``__node__`` marker, passing
``[inputs]`` as keyword arguments, and the exit-code contract — 0 ok,
1 run failure, 2 usage/config error.  The ``python -m`` form gets one
subprocess test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from runner import flows as runner_flows
from sequence_extensions.flow_runner import (
    RunnerConfig,
    RunnerConfigError,
    find_nodes,
    list_nodes,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"


def write_config(tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def echo_config(tmp_path):
    body = f"""
[run]
module = "runner.flows"
flow = "echo"
log = {str(tmp_path / "logs")!r}

[inputs]
value = 21
factor = 2
"""
    return write_config(tmp_path, body)


# --------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------- #
def test_find_nodes_scans_the_module():
    nodes = find_nodes(runner_flows)
    assert sorted(nodes) == ["bump", "double", "echo", "failing"]
    assert nodes["echo"].__node__ == "echo"


def test_list_nodes_shows_docstrings():
    entries = dict(list_nodes(runner_flows))
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
    log_file = next((tmp_path / "logs").glob("*.jsonl"))
    assert log_file.exists()


def test_flow_flag_overrides_selection(tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"""
[run]
module = "runner.flows"
flow = "echo"
log = {str(tmp_path / "logs")!r}

[inputs]
values = [1, 2]
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
log = {str(tmp_path / "logs")!r}
""",
    )
    assert main([str(config)]) == 1
    captured = capsys.readouterr()
    assert "flow failing: error" in captured.out
    assert "boom" in captured.err


def test_node_defaults_from_config(tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"""
[run]
module = "runner.flows"
flow = "echo"
log = {str(tmp_path / "logs")!r}

[node]
retries = 2
timeout = 5.0

[inputs]
value = 3
""",
    )
    assert main([str(config)]) == 0
    assert "flow echo: ok" in capsys.readouterr().out


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
    config = write_config(tmp_path, "[node]\nretriess = 2\n")
    assert main([str(config)]) == 2
    assert "unknown key" in capsys.readouterr().err


def test_legacy_section_migration(tmp_path, capsys):
    config = write_config(tmp_path, "[task]\nretries = 2\n")
    assert main([str(config)]) == 2
    assert "renamed in 3.0" in capsys.readouterr().err


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
    assert "echo" in err and "double" in err


def test_inputs_must_match_signature(tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"""
[run]
module = "runner.flows"
flow = "echo"
log = {str(tmp_path / "logs")!r}

[inputs]
value = 21
bogus = 3
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
    assert "do not match" in capsys.readouterr().err


# --------------------------------------------------------------- #
# RunnerConfig validation
# --------------------------------------------------------------- #
def test_config_maps_sections_to_run_options():
    cfg = RunnerConfig.from_dict(
        {
            "run": {"module": "m", "flow": "f", "max_workers": 3, "fixed_clock": True},
            "node": {"retries": 2, "timeout": 1.5},
            "inputs": {"x": 1},
        }
    )
    assert cfg.module == "m"
    assert cfg.flow == "f"
    assert cfg.options.max_workers == 3
    assert cfg.options.fixed_clock is True
    assert cfg.options.node_defaults.retries == 2
    assert cfg.options.node_defaults.timeout == 1.5
    assert cfg.inputs == {"x": 1}


def test_config_rejects_unknown_run_key():
    try:
        RunnerConfig.from_dict({"run": {"modul": "m"}})
    except RunnerConfigError as e:
        assert "unknown key" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected RunnerConfigError")


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
