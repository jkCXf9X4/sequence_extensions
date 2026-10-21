---
id: INFO-001
type: info
title: 00-intent — Vision & Goals
summary: Vision, goal, requirements, and success criteria — parallel, deterministic, audited campaign execution, local or at HPC
date: 2026-10-14
status: current
---

# 00-intent — Vision & Goals

## Vision

- Parallel, deterministic, fully audited campaign execution — local or at HPC.
- "Verify what happened" outranks "re-run what happened": the run log is the product.
- Campaigns are ordinary Python: functions, loops, decorators. No representation to learn.

## Goal

A zero-dependency, embeddable mini flow engine:

- Parallelism, local and bounded:
  - worker threads by default (`CP-017`, `CP-021`)
  - worker processes for CPU-bound tasks (`CP-022`)
  - flows run side by side in one process (`CP-023`)
- HPC through recipes, not adapters (`INFO-012`):
  - a task that sbatches and polls
  - the engine ships no scheduler integration
- Deterministic operations:
  - retry, backoff, and timeout declared on the task (`CP-019`)
  - same code and inputs give the same verdict
- Audit (`CP-020`):
  - every attempt, failure, and skip in one JSON-lines file per run
  - the log is complete the moment a flow returns

## Requirements

- Independent tasks run concurrently; concurrency is bounded.
- The run log is complete the moment a flow returns.
- Zero runtime dependencies; Python >= 3.11.

## Out of scope

- Plan-before-execution (dry run): structurally impossible with imperative submission.
- Replay by re-execution: the log proves what ran; re-running is a fresh run.
- Distributed execution: recipes only — no scheduler adapters, no cluster runtime.
- Workflow XML, node trees, adaptation, artifact store.

## Success criteria

- A six-case simulated campaign runs parallel, retries its flaky case, and yields one verdict plus a complete audit log (acceptance test).
- Package stays small: about 4,000 lines of engine core plus ext helpers.
- The audit log is diffable, greppable, and readable without the code beside it.

## Owns

- Vision, goal, requirements, out-of-scope, success criteria.

## Excludes

- Capability catalog: `INFO-010`.
- Engine design: `INFO-011`.
- Direction pointers and open candidates: `INFO-013`.
- Recorded decisions: the archive, per `DR-006`.
