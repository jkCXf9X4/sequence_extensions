---
id: INFO-012
type: info
title: Running flows — local and at HPC
summary: Operational shape of running a flow — bounded local pool, HPC through the recipe pattern, subprocess timeout layering
date: 2026-10-14
status: current
---

# Running flows — local and at HPC

A flow runs on one machine: its own bounded thread pool, its run log on that machine (`INFO-007`).

## Local

- Default pool: 16 workers; `max_workers=` sizes it (`CP-021`).
- Plain calls run inline in the caller's thread; `.submit()` schedules on the pool.
- CPU-bound tasks: a `ProcessGraphPool` swaps threads for processes — picklable tasks parallelize past the GIL (`CP-022`).

## At HPC

- The engine ships no scheduler integration; HPC is recipes, not adapters (`INFO-001`).
- Simulator recipe: `subprocess.run` with its own `timeout` kills a hung tool at the process level — the layer a task `timeout=` cannot reach; the task `timeout=` stays the campaign-level backstop.
- SLURM recipe: a submit task runs `sbatch --parsable` and returns the job id; a poll task runs `sacct`, with `retries` large and `retry_delay_seconds` matching the poll interval.
- A non-zero exit maps to `RuntimeError`; the run log records it, retry policy takes over.
- Determinism: same inputs, same command line, same output bytes; the run log records the result path plus sha256.

## Owns

- Operational shape of running a flow: local pool, HPC recipes.

## Excludes

- Engine semantics and limits: `INFO-011`.
- Install, test, release: `INFO-007`.
- Recipe source text: `docs/API.md`, runtime-coupled docs outside this tree.
