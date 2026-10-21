"""RunOptions and NodePolicy: validation and default-resolution rules."""

from __future__ import annotations

import pytest

from sequence_extensions.flow import UNSET, NodePolicy, RunOptions
from sequence_extensions.graph import GraphPool


def test_run_options_defaults_are_unset():
    options = RunOptions()
    assert options.name is None
    assert options.max_workers is UNSET
    assert options.log is UNSET
    assert options.summary is UNSET
    assert options.fixed_clock is UNSET
    assert options.pool is None
    assert options.retries is UNSET
    assert options.timeout is UNSET
    assert options.node_defaults is UNSET


def test_node_policy_validates():
    assert NodePolicy().retries == 0
    assert NodePolicy(retries=2, retry_delay_seconds=0.5, timeout=30).timeout == 30
    with pytest.raises(ValueError, match="retries"):
        NodePolicy(retries=-1)
    with pytest.raises(ValueError, match="retry_delay_seconds"):
        NodePolicy(retry_delay_seconds=-0.5)
    with pytest.raises(ValueError, match="timeout"):
        NodePolicy(timeout=0)
    with pytest.raises(ValueError, match="retries must be an integer"):
        NodePolicy(retries="two")


def test_run_options_validate_explicit_values():
    with pytest.raises(ValueError, match="max_workers"):
        RunOptions(max_workers=0)
    with pytest.raises(ValueError, match="summary"):
        RunOptions(summary="yes")
    with pytest.raises(ValueError, match="fixed_clock"):
        RunOptions(fixed_clock="yes")
    with pytest.raises(ValueError, match="log"):
        RunOptions(log=3)
    with pytest.raises(ValueError, match="pool"):
        RunOptions(pool="not-a-pool")
    with pytest.raises(ValueError, match="retries"):
        RunOptions(retries=-1)
    with pytest.raises(ValueError, match="retries must be an integer"):
        RunOptions(retries=2.0)
    with pytest.raises(ValueError, match="timeout"):
        RunOptions(timeout=0)
    with pytest.raises(ValueError, match="node_defaults"):
        RunOptions(node_defaults={"retries": 1})


def test_empty_log_string_means_disabled():
    assert RunOptions(log="").log is None


def test_resolve_fills_built_ins_at_the_root():
    resolved = RunOptions().resolve("campaign")
    assert resolved.name == "campaign"
    assert resolved.max_workers == 16
    assert resolved.log == "runs"
    assert resolved.summary is False
    assert resolved.fixed_clock is False
    assert resolved.retries == 0
    assert resolved.retry_delay_seconds == 0.0
    assert resolved.timeout is None
    assert resolved.node_defaults is None


def test_resolve_keeps_explicit_values_and_fills_defaults():
    resolved = RunOptions(
        max_workers=1,
        log=None,
        summary=True,
        fixed_clock=True,
        retries=2,
        node_defaults=NodePolicy(retries=1),
    ).resolve("inner")
    assert resolved.name == "inner"
    assert resolved.max_workers == 1
    assert resolved.log is None
    assert resolved.summary is True
    assert resolved.fixed_clock is True
    assert resolved.retries == 2
    assert resolved.retry_delay_seconds == 0.0
    assert resolved.timeout is None
    assert resolved.node_defaults == NodePolicy(retries=1)


def test_resolve_keeps_a_caller_pool():
    pool = GraphPool(max_workers=1)
    resolved = RunOptions(pool=pool).resolve("inner")
    assert resolved.pool is pool
