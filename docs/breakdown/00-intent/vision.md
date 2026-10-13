---
id: INFO-001
type: info
title: 00-intent — Vision & Goals
summary: Vision, goal, requirements, and success criteria for sequence_extensions — an audit-first mini flow engine
date: 2026-10-13
status: current
---

# 00-intent — Vision & Goals

## Origin

The project began as the workflow layer of "Automation Nation: Taming Complex V&V Workflows" (Rosenlund, Hällqvist, Braun, Krus, 2025; `docs/references/`). The 2026-10-13 evaluation superseded that layer (`DR-005`): the package now realizes the requirements, not the paper's representation. Traceability of runs — the one surviving paper thread — is the run log.

## Vision

- Model verification that is automated, parallel, and fully auditable.
- "Verify what happened" outranks "re-run what happened": the run log is the product.
- Campaigns are ordinary Python: functions, loops, decorators. No new representation to learn.

## Goal

An audit-first, zero-dependency, embeddable mini flow engine:

- Parallelism — local thread pool, bounded; HPC speaks through recipes (a task that sbatches and polls), not adapters.
- Deterministic operations — pure tasks, declared retry and timeout policy, recorded audit trail.
- Audit — every attempt, failure, and skip lands in one JSON-lines file per run.

## Requirements

- Parallelism: independent tasks run concurrently; concurrency is bounded.
- Determinism: same code and inputs give the same verdict; policy is declared on the task.
- Audit: the run log is complete the moment a flow returns.
- Composability: tasks are functions; flows are functions; futures are edges.
- Zero runtime dependencies; Python >= 3.9.

## Out of scope

- Plan-before-execution (dry run): structurally impossible with imperative submission; removed (`DR-005`).
- Replay by re-execution: the log proves what ran; re-running is a fresh run.
- Workflow XML, node trees, adaptation, artifact store: superseded (`DR-005`).
- Batch-scheduler integration: recipes, not engine features.

## Success criteria

- A six-case simulated campaign runs parallel, retries its flaky case, and yields one verdict plus a complete audit log (acceptance test).
- Package stays small: about 1,900 lines of engine core plus ext helpers.
- The audit log is diffable, greppable, and readable without the code beside it.

## Owns

- Vision, goal, requirements, out-of-scope, success criteria.

## Excludes

- Capability catalog: `INFO-010`.
- Engine design: `INFO-011`.
- The supersession decision and its evidence: `DR-005`.
