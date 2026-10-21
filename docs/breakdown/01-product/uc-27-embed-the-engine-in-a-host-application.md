---
id: CP-027
type: capability
title: UC-27 Embed the engine in a host application
summary: host application calls execute_flow with per-call RunOptions, reads the returned Run — no service, no global configuration, no dependencies
date: 2026-10-16
status: current
---

# UC-27 Embed the engine in a host application

## Scenario

- A service, notebook, or analysis application owns the process; runs are one component among others.
- The host passes run options at the call site; there is no global configuration to install or reset.
- The host calls `execute_flow`, then reads the returned `Run` without parsing the run log.
- The host archives run logs beside its own data, or turns run logging off.

## Acceptance

- `execute_flow(node, ..., options=RunOptions(...))` is the only run entry point; no import-order constraint and no process-wide configuration.
- A successful call returns a `Run` with `result`, `run_id`, `node`, `status`, `log`, `duration_ms`, `attempt`, and `error`; a failure raises with `.run` attached.
- Per-tenant or per-request settings are different `RunOptions` values; `node_defaults` carries per-request node policy.
- The host picks the log directory per call; `log=None` disables run logging.
- Runs run side by side in the host process (`CP-023`); CPU-bound work runs on `ProcessGraphPool` (`CP-022`).
- No runtime dependencies, no background service: the host deploys one import (`INFO-002`).

## Evidence

- `tests/flow/test_run.py`
- `tests/flow/test_options.py`

## Owns

- The incorporation need: a larger Python application embeds the engine as a library and reads verdicts programmatically.

## Excludes

- Run options and node-default mechanics: `INFO-011`.
- CLI launch: `CP-028`.
- Running at HPC: `INFO-012`.
