---
id: CP-027
type: capability
title: UC-27 Embed the engine in a host application
summary: host application calls flows as functions, installs config at startup, reads the verdict programmatically — no service, no dependencies
date: 2026-10-16
status: current
---

# UC-27 Embed the engine in a host application

## Scenario

- A service, notebook, or analysis application owns the process; flows are one component among others.
- The host installs engine defaults at startup; decorator modules stay untouched.
- The host calls flows like functions, then reads the verdict without parsing the run log.
- The host archives run logs beside its own data, or turns run logging off.

## Acceptance

- `configure()` after import reaches module-level decorators; no import-order constraint.
- A flow call returns the campaign's results; `flow.last_run` carries `run_id`, `status`, `log`, `duration_ms`.
- Worker threads inherit the active configuration; `use_config` scopes one to a block; `reset_config` restores defaults.
- The host picks the log directory per flow or per config; `log = ""` disables run logging.
- Flows run side by side in the host process (`CP-023`); CPU-bound work runs on `ProcessGraphPool` (`CP-022`).
- No runtime dependencies, no background service: the host deploys one import (`INFO-002`).

## Evidence

- `tests/flow/test_config.py`
- `tests/flow/test_flow.py`

## Owns

- The incorporation need: a larger Python application embeds the engine as a library and reads verdicts programmatically.

## Excludes

- Config precedence and resolution mechanics: `INFO-011`.
- CLI launch: `CP-028`.
- Running at HPC: `INFO-012`.
