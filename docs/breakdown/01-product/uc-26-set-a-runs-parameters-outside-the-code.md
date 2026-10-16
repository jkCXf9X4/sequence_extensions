---
id: CP-026
type: capability
title: UC-26 Set a run's parameters outside the code
date: 2026-10-16
status: current
summary: engine parameters and flow selection live in one TOML file; explicit keywords keep winning; the file launches the run without a code change
---

# UC-26 Set a run's parameters outside the code

## Scenario

- An operator tunes retries, timeout, worker count, and log directory for tonight's campaign. No Python edit allowed.
- The operator also picks which flow runs and what inputs it gets — same file, no driver script.
- A developer keeps explicit keywords in code. Config must not override them.

## Acceptance

- One TOML file sets flow, task, and pool defaults; omitted keys keep built-in defaults.
- Explicit decorator keyword beats config value; config beats built-in default.
- Config installed after import still reaches module-level decorators (call-time resolution).
- Unknown key or bad value fails at load, message names file, section, key.
- `flow-runner <file>` runs the selected flow, passes `[inputs]` as keyword arguments, exits 0 on success, 1 on flow failure, 2 on usage or config error.

## Evidence

- `tests/flow/test_config.py`
- `tests/runner/test_runner.py`

## Owns

- The external-configuration need: file-driven parameters, keyword-first precedence, CLI launch.

## Excludes

- How resolution works: `INFO-011`.
- The decision and its alternatives: `DR-015`.
