---
id: CP-028
type: capability
title: UC-28 Start runs from a shell or pipeline
summary: make, CI, cron, and batch scripts start flows through flow-runner, select the root with --flow, branch on exit codes, keep the run log as the artifact
date: 2026-10-16
status: current
---

# UC-28 Start runs from a shell or pipeline

## Scenario

- A Makefile, CI job, cron entry, or batch script starts a flow; no driver script per run.
- One plan document per environment or variant carries the inputs, node policy, and run options; the pipeline picks the file.
- The pipeline names the module and selects the root on the command line; the plan never stores the selection.
- The pipeline branches on the outcome and archives the run log as its artifact.
- An operator lists what can run before running anything.

## Acceptance

- `flow-runner PLAN.json --module MODULE` starts the selected root node; `--flow NAME` selects it when the module has several, and `--log DIR` overrides the log location.
- Root inputs arrive as keyword arguments from the plan's `parameters`.
- Exit codes carry the verdict: 0 success, 1 run failure, 2 usage or config error.
- `--list` enumerates the nodes in the module and needs no plan; `--flow` names the root.
- A bad plan (invalid JSON, wrong schema, a plan that does not fit the flow) or an unknown flow fails with exit 2; no node has run.
- The account line names status and log path; the run log is complete when the process exits.

## Evidence

- `tests/runner/test_runner.py`

## Owns

- The incorporation need: shells, pipelines, and schedulers start runs, choose the root externally, and branch on exit codes.

## Excludes

- Plan format, precedence, and inputs: `CP-026`.
- Embedding as a library: `CP-027`.
- Running at HPC: `INFO-012`.
- Install and release steps: `INFO-007`.
