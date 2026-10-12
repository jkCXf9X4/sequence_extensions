---
id: IMP-012
type: imp
title: Engine resource configuration and parallel exception contract
summary: Expose max_workers and adaptation bound per run, make the executor pluggable, catch BaseException in parallel result collection
date: 2026-10-12
status: current
---

# Engine resource configuration and parallel exception contract

Fourth of five patch batches from the 2026-10-12 implementation review. Build order:
IMP-009 first, then IMP-010, IMP-011, IMP-012, IMP-013.

## Pain

- `GraphPool` hardcodes a `ThreadPoolExecutor`; threads give no speed-up for
  GIL-bound simulation code — the paper's resource-utilization requirement.
  The speed-up tests pass via `threading.Barrier` waits (I/O-style); the suite
  is structurally blind to the gap.
- `max_workers` (default 16) and `ADAPTATION_BOUND` (10 000) are not configurable
  per run: a 20 000-point `parameter_sweep` dies at the bound; license-limited
  parallelism is untunable from the workflow layer.
- The parallel walk collects per-future errors with `except Exception`
  (`engine.py` `_walk_parallel`); a `BaseException` such as `KeyboardInterrupt`
  from an action propagates at `future.result()`, skips the joins of the
  remaining child threads, and breaks the documented first-failure-in-child-order
  after all children settle contract. The sequential path records and re-raises
  `BaseException` correctly (`_walk_child_thread` catches `BaseException`).

## Change

- `run_workflow` / `Test_Framework` gain `max_workers=None` and
  `adaptation_bound=None`; `None` keeps the current defaults. The engine passes
  `max_workers` to `GraphPool` and the bound to `_Engine`.
- Executor seam: `executor=None` argument; a caller-supplied `GraphPool`
  instance wins over `max_workers`. Docstring states the GIL caveat and points
  at a process-pool variant as future work (the pool itself is deferred; this
  change exposes the seam and documents it).
- `engine.py` `_walk_parallel`: collect `BaseException` in the per-future loop,
  matching `_walk_child_thread`; re-raise in child order after all children
  settle.

## Verification

- `tests/workflow/test_engine.py` / `test_scaling.py`: `max_workers` and
  `adaptation_bound` plumbed through the XML and Python API paths; a parallel
  action raising `KeyboardInterrupt` still settles all children, then re-raises.
- Suite green; `pb check --strict` green.
