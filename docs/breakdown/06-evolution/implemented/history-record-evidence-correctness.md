---
id: IMP-010
type: imp
title: History record evidence correctness
summary: Strip reserved kwargs from record params, verify replay registry drift, time durations monotonic
date: 2026-10-12
status: current
---

# History record evidence correctness

Second of five patch batches from the 2026-10-12 implementation review. Build order:
IMP-009 first, then IMP-010, IMP-011, IMP-012, IMP-013.

## Pain

- `ExecutionRecord.params` is not plain data: for any `dag`-declaring function,
  `record.params["dag"]` is a live `DAGHandle` with a mutable op log.
  Verified with a `dag`-declaring function and `history=RunHistory()`.
- `history.py` docstring promises "the exact kwargs the function was actually
  called with" as comparable evidence; a live handle breaks comparability and
  serialization, and pins the scope snapshot in memory.
- `replay_records` already pops `dag` and `walk_context` on the way back in;
  the stored handle is ballast on replay.
- Replay re-resolves `record.name` through the live registry and never compares
  the resolved function to `record.function` (the resolved `__name__`, already
  recorded). A re-registration between run and replay silently diverges the replay.
- `started_at` / `ended_at` use `time.time()`; durations are not monotonic.

## Change

- `engine.py` `_record_call`: strip reserved kwargs (`dag`, `walk_context`,
  `artifacts`) when building `params=dict(kwargs)`; the evidence already lives
  structurally in `record.scope` and `record.artifacts`.
- `history.py` `replay_records`: after `fn = reg.get(record.name)`, compare
  `getattr(fn, "__name__", ...)` with `record.function`; on mismatch, warn
  naming the record order and both names.
- Timestamps: keep wall-clock `started_at` / `ended_at` for audit stamps; add a
  `time.monotonic()`-based duration field; document which field serves which
  purpose.

## Verification

- `tests/workflow/test_history.py`: record `params` contain no handle objects
  for a `dag`-declaring function; replay with a re-registered name warns.
- Suite green; `pb check --strict` green.
