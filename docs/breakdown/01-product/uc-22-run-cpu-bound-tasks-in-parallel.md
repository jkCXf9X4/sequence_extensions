---
id: CP-022
type: capability
title: UC-22 Run CPU-bound tasks in parallel
summary: compute-heavy tasks run on several cores of one machine at the same time, without rewriting the campaign or losing its record
date: 2026-10-14
status: current
---

# UC-22 Run CPU-bound tasks in parallel

## Scenario

- A campaign of pure-Python computations sees no speedup from many threads: one process serializes compute-bound work.
- The need is several cores at work — same campaign, same complete record, one machine.

## Acceptance

- Two compute-heavy tasks on two cores beat the one-core wall time by a wide margin.
- The record is complete the moment the campaign returns, including attempts that ran in other processes.
- A task whose dependency failed never starts; it gets one record marking it skipped.
- A budget failure from another process still names its task and its attempt.
- Work that cannot be moved to another process is recorded skipped at once.

## Evidence

- `tests/flow/test_process_pool.py` — results, retry and error record replay, dependency skip, dispatch failure, timeout transport, exit cancellation, wall-time gain.

## Owns

- The several-cores need and its wall-time and record acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Thread-mode concurrency and limits: `CP-017`, `CP-021`.
- Running beyond one machine: `INFO-012`.
