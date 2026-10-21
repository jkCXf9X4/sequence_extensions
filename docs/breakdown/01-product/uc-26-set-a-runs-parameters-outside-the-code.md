---
id: CP-026
type: capability
title: UC-26 Set a run's parameters outside the code
date: 2026-10-16
status: current
summary: run options and node defaults live in one TOML file; explicit decorator keywords keep winning; the file launches the run without a code change
---

# UC-26 Set a run's parameters outside the code

## Scenario

- An operator tunes retries, timeout, worker count, and log directory for tonight's campaign. No Python edit allowed.
- The operator also picks which root node runs and what inputs it gets — same file, no driver script.
- A developer keeps explicit keywords in code. File-driven defaults must not override them.

## Acceptance

- One TOML file sets run options (`[run]`) and per-run node defaults (`[node]`); omitted keys keep built-in defaults.
- Explicit `@node` keyword beats `RunOptions.node_defaults`; node defaults beat the built-in default.
- The file maps to `RunOptions` at load time; there is no process-wide configuration and no import-order constraint.
- Unknown key or bad value fails at load; the message names the file, section, and key.
- `flow-runner <file>` runs the selected node, passes `[inputs]` as keyword arguments, exits 0 on success, 1 on run failure, 2 on usage or config error.

## Evidence

- `tests/flow/test_options.py`
- `tests/runner/test_runner.py`

## Owns

- The file-driven-parameters need: run options and node defaults in one TOML file, keyword-first precedence, CLI launch.

## Excludes

- How resolution works: `INFO-011`.
- The decision and its alternatives: `DR-017` (supersedes `DR-015`).
