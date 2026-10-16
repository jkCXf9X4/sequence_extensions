"""External configuration: TOML loading, validation, and per-call resolution.

Covers :mod:`sequence_extensions.config` (the ``Config`` object, its
loaders and constraint checks) and the resolution contract across the
engine: an explicit decorator keyword wins, the active config fills the
unset ones, and the built-in defaults hold without a config — including
in pool worker threads, timeout attempt threads, and process workers
(policy is resolved in the parent and pickled with the task).
"""

from __future__ import annotations

import pickle
import time
from pathlib import Path

import pytest

from sequence_extensions.config import (
    UNSET,
    Config,
    ConfigError,
    FlowConfig,
    PoolConfig,
    RunConfig,
    TaskConfig,
    active_config,
    configure,
    reset_config,
    use_config,
)
from sequence_extensions.flow import ProcessGraphPool, flow, task
from sequence_extensions.flow.runlog import RunLog
from sequence_extensions.flow.task import TaskTimeoutError
from sequence_extensions.graph import GraphPool

# --------------------------------------------------------------- #
# Module-level tasks and flows: decorated at import time, so every
# configure() below happens *after* decoration — the deferred-resolution
# contract under test.
# --------------------------------------------------------------- #
_state = {"calls": 0}


@task
def flaky():
    """Fail unless the call number divides by three."""
    _state["calls"] += 1
    if _state["calls"] % 3:
        raise ValueError(f"fail #{_state['calls']}")
    return _state["calls"]


@task(timeout=5.0)
def outer():
    """Call flaky() inside the timeout attempt thread."""
    return flaky()


@flow
def plain(value):
    """Return the value unchanged."""
    return value


@pytest.fixture(autouse=True)
def _clean_state():
    _state["calls"] = 0
    # Anything a test configures must not leak into the next one.
    configure(Config())
    yield
    configure(Config())


# --------------------------------------------------------------- #
# Config object and sections
# --------------------------------------------------------------- #
def test_defaults_match_the_built_ins():
    cfg = Config()
    assert cfg.flow == FlowConfig(max_workers=16, log="runs", summary=False)
    assert cfg.task == TaskConfig(retries=0, retry_delay_seconds=0.0, timeout=None)
    assert cfg.pool == PoolConfig(graph_max_workers=16, process_max_workers=None)
    assert cfg.run == RunConfig(module=None, flow=None)
    assert cfg.inputs == {}


def test_sections_validate_on_construction():
    with pytest.raises(ValueError, match="retries must be an integer"):
        TaskConfig(retries="two")
    with pytest.raises(ValueError, match="retries must be >= 0"):
        TaskConfig(retries=-1)
    with pytest.raises(ValueError, match="timeout must be > 0"):
        TaskConfig(timeout=0)
    with pytest.raises(ValueError, match="max_workers must be >= 1"):
        FlowConfig(max_workers=0)
    with pytest.raises(ValueError, match="summary must be true or false"):
        FlowConfig(summary="yes")
    with pytest.raises(ValueError, match="log must be a directory path"):
        FlowConfig(log=3)
    with pytest.raises(ValueError, match="process_max_workers must be >= 1"):
        PoolConfig(process_max_workers=0)
    with pytest.raises(ValueError, match="module must be a non-empty string"):
        RunConfig(module="")
    with pytest.raises(ValueError, match="inputs must be a table"):
        Config(inputs=[1, 2])


def test_empty_log_string_means_disabled():
    assert FlowConfig(log="").log is None  # the TOML spelling: TOML has no null
    assert FlowConfig(log="out/runs").log == "out/runs"
    assert FlowConfig().log == "runs"


def test_config_error_is_a_value_error():
    assert issubclass(ConfigError, ValueError)


# --------------------------------------------------------------- #
# from_toml / from_dict
# --------------------------------------------------------------- #
def test_from_toml_full_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[run]
module = "mypackage.flows"
flow = "campaign"

[inputs]
items = [1, 2, 3]
mode = "fast"

[flow]
max_workers = 8
log = "output/runs"
summary = true

[task]
retries = 2
retry_delay_seconds = 0.5
timeout = 30

[pool]
graph_max_workers = 4
process_max_workers = 2
""",
        encoding="utf-8",
    )
    cfg = Config.from_toml(path)
    assert cfg.run == RunConfig(module="mypackage.flows", flow="campaign")
    assert cfg.inputs == {"items": [1, 2, 3], "mode": "fast"}
    assert cfg.flow == FlowConfig(max_workers=8, log="output/runs", summary=True)
    assert cfg.task == TaskConfig(retries=2, retry_delay_seconds=0.5, timeout=30)
    assert cfg.pool == PoolConfig(graph_max_workers=4, process_max_workers=2)


def test_from_toml_partial_and_empty_files(tmp_path):
    partial = tmp_path / "partial.toml"
    partial.write_text("[task]\nretries = 3\n", encoding="utf-8")
    cfg = Config.from_toml(partial)
    assert cfg.task.retries == 3
    assert cfg.flow == FlowConfig()  # untouched section keeps defaults

    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    assert Config.from_toml(empty) == Config()


def test_from_toml_empty_log_disables_logging(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[flow]\nlog = ""\n', encoding="utf-8")
    assert Config.from_toml(path).flow.log is None


def test_from_toml_errors_carry_the_path(tmp_path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(ConfigError, match="cannot read config file"):
        Config.from_toml(missing)

    broken = tmp_path / "broken.toml"
    broken.write_text("[task\nretries = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        Config.from_toml(broken)

    unknown_section = tmp_path / "section.toml"
    unknown_section.write_text("[flo]\nmax_workers = 8\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown section"):
        Config.from_toml(unknown_section)

    unknown_key = tmp_path / "key.toml"
    unknown_key.write_text("[task]\nretriess = 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown key.*retriess.*retries"):
        Config.from_toml(unknown_key)

    bad_value = tmp_path / "bad.toml"
    bad_value.write_text("[task]\nretries = -1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="retries must be >= 0"):
        Config.from_toml(bad_value)

    wrong_type = tmp_path / "type.toml"
    wrong_type.write_text("[flow]\nsummary = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="summary must be true or false"):
        Config.from_toml(wrong_type)


def test_from_dict_validates_and_prefixes_errors():
    cfg = Config.from_dict({"task": {"retries": 4}}, where="my.toml")
    assert cfg.task.retries == 4

    with pytest.raises(ConfigError, match="my.toml"):
        Config.from_dict({"task": {"retries": -1}}, where="my.toml")
    with pytest.raises(ConfigError, match="must be a table"):
        Config.from_dict("nope")
    with pytest.raises(ConfigError, match=r"\[task\] must be a table"):
        Config.from_dict({"task": [1]})
    with pytest.raises(ConfigError, match=r"\[inputs\] must be a table"):
        Config.from_dict({"inputs": 3})


# --------------------------------------------------------------- #
# configure / active_config / reset_config / use_config
# --------------------------------------------------------------- #
def test_configure_install_and_reset():
    assert active_config() == Config()  # no config installed
    token = configure(Config(task=TaskConfig(retries=7)))
    assert active_config().task.retries == 7
    reset_config(token)
    assert active_config() == Config()

    with pytest.raises(TypeError, match="expects a Config"):
        configure({"task": {"retries": 1}})


def test_use_config_scopes_the_configuration():
    with use_config(Config(task=TaskConfig(retries=9))) as cfg:
        assert active_config() is cfg
    assert active_config() == Config()


# --------------------------------------------------------------- #
# Per-call resolution: explicit keyword > active config > built-in
# --------------------------------------------------------------- #
def test_task_resolves_config_after_import():
    # flaky was decorated at import time; configure() runs after.
    with pytest.raises(ValueError, match="fail #1"):  # built-in default: 0 retries
        flaky()
    _state["calls"] = 0

    with use_config(Config(task=TaskConfig(retries=2))):
        assert flaky() == 3  # fails twice, succeeds on the third attempt


def test_explicit_task_keyword_beats_config():
    counter = {"n": 0}

    def body():
        counter["n"] += 1
        raise ValueError("always fails")

    strict = task(body, retries=0)
    with use_config(Config(task=TaskConfig(retries=5))):
        with pytest.raises(ValueError, match="always fails"):
            strict()
    assert counter["n"] == 1  # config's 5 retries ignored: explicit 0 wins


def test_task_timeout_resolves_from_config():
    sleeper = task(lambda: time.sleep(0.5))
    with use_config(Config(task=TaskConfig(timeout=0.05))):
        with pytest.raises(TaskTimeoutError):
            sleeper()


def test_config_reaches_tasks_inside_timeout_threads():
    # outer has an explicit timeout, so its body (a direct flaky() call)
    # runs in the attempt thread — the config snapshot must be restored
    # there or flaky would resolve the built-in default and fail.
    with use_config(Config(task=TaskConfig(retries=2))):
        assert outer() == 3
    _state["calls"] = 0


def test_pickle_roundtrips_policy_values():
    strict = task(lambda: "ok", retries=2, retry_delay_seconds=0.25, timeout=12.0)
    clone = pickle.loads(pickle.dumps(strict))
    assert (clone.retries, clone.retry_delay_seconds, clone.timeout) == (2, 0.25, 12.0)

    bare = task(lambda: "ok")
    clone = pickle.loads(pickle.dumps(bare))
    assert clone.retries is UNSET  # the sentinel survives a roundtrip


def test_flow_resolves_log_workers_and_summary(tmp_path):
    log_dir = tmp_path / "out"
    cfg = Config(
        flow=FlowConfig(max_workers=2, log=str(log_dir), summary=True),
        task=TaskConfig(retries=2),
    )
    with use_config(cfg):
        result = plain(list(range(20)))
    assert result == list(range(20))
    log_path = Path(plain.last_run["log"])
    assert log_path.parent == log_dir
    assert plain.last_run["status"] == "ok"
    assert plain.last_run["run_id"].startswith("plain-")
    records = RunLog.records(log_path)
    start = records[0]
    assert start["record"] == "run_start"
    assert start["args"] == [{"type": "list", "len": 20}]  # summary mode resolved


def test_flow_without_config_and_with_disabled_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plain(1)
    assert Path(plain.last_run["log"]).parent.name == "runs"  # built-in default

    with use_config(Config(flow=FlowConfig(log=""))):  # "" disables
        plain(2)
    assert plain.last_run["log"] is None


def test_flow_explicit_keywords_beat_config(tmp_path):
    explicit = flow(lambda x: x, log=tmp_path / "explicit")
    with use_config(Config(flow=FlowConfig(max_workers=99, log="not-here", summary=True))):
        explicit(1)
    assert Path(explicit.last_run["log"]).parent == tmp_path / "explicit"


def test_flow_marker_and_last_run_shape():
    assert plain.__flow__ == "plain"
    assert plain.last_run["flow"] == "plain"
    assert isinstance(plain.last_run["duration_ms"], int)


def test_failing_flow_records_error_status(tmp_path):
    boom = flow(lambda: 1 / 0, log=tmp_path)
    with pytest.raises(ZeroDivisionError):
        boom()
    assert boom.last_run["status"] == "error"
    assert boom.last_run["log"] is not None


def test_pools_resolve_construction_defaults():
    with use_config(Config(pool=PoolConfig(graph_max_workers=3, process_max_workers=2))):
        assert GraphPool().max_workers == 3
        assert ProcessGraphPool().max_workers == 2
    assert GraphPool().max_workers == 16  # built-in default, no config
    assert ProcessGraphPool().max_workers is None  # executor default (CPU count)

    with use_config(Config(pool=PoolConfig(graph_max_workers=3))):
        assert GraphPool(max_workers=8).max_workers == 8  # explicit wins


def test_process_pool_task_uses_configured_retries(tmp_path):
    calls = {"n": 0}

    def body():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("first call fails")
        return "ok"

    unstable = task(body)
    pool = ProcessGraphPool(max_workers=1)
    run = flow(lambda: unstable.submit().result(), pool=pool, log=tmp_path)
    with pytest.raises(ValueError, match="first call fails"):
        run()  # built-in default: no retries

    calls["n"] = 0
    pool2 = ProcessGraphPool(max_workers=1)
    run2 = flow(lambda: unstable.submit().result(), pool=pool2, log=tmp_path)
    with use_config(Config(task=TaskConfig(retries=1))):
        assert run2() == "ok"  # policy resolved in the parent, pickled to the worker


def test_unset_sentinel_is_opaque():
    assert repr(UNSET) == "UNSET"
    assert UNSET is not None
