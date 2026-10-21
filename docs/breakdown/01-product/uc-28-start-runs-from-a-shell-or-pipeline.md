---
id: CP-028
type: capability
title: UC-28 Start runs from a shell or pipeline
summary: make, CI, cron, and batch scripts start flows through flow-runner, branch on exit codes, keep the run log as the artifact
date: 2026-10-16
status: current
---

# UC-28 Start runs from a shell or pipeline

## Scenario

- A Makefile, CI job, cron entry, or batch script starts a flow; no driver script per run.
- One TOML per environment tunes the run; the pipeline picks the file.
- The pipeline branches on the outcome and archives the run log as its artifact.
- An operator lists what can run before running anything.

## Acceptance

- `flow-runner config.toml` starts the selected root node; `[inputs]` pass as keyword arguments.
- Exit codes carry the verdict: 0 success, 1 run failure, 2 usage or config error.
- `--list` enumerates the nodes in the module; `--flow NAME` overrides the selection.
- A bad config fails at load with file, section, and key named; no node has run.
- The account line names status and log path; the run log is complete when the process exits.

## Evidence

- `tests/runner/test_runner.py`

## Owns

- The incorporation need: shells, pipelines, and schedulers start runs and branch on exit codes.

## Excludes

- Config file format, precedence, and flow selection: `CP-026`.
- Embedding as a library: `CP-027`.
- Running at HPC: `INFO-012`.
- Install and release steps: `INFO-007`.
