---
id: IMP-017
type: imp
title: Process-pool executor for CPU-bound tasks
summary: Flow parallelism is threads only; the GIL serializes CPU-bound task bodies; a ProcessGraphPool behind the same pool= seam would fix it
date: 2026-10-14
status: current
---

# Process-pool executor for CPU-bound tasks

Candidate, not selected. Deferred by `DR-005` (Phase 5: on demand only).

## Pain

- `flow` parallelism is threads only: a `GraphPool` wraps a
  `ThreadPoolExecutor`.
- The GIL serializes CPU-bound task bodies, so a campaign of pure-Python
  computations sees no speedup from `submit()`.
- The current V&V case does not hit this: simulators are subprocesses
  (`INFO-001` — HPC through recipes), so threads suffice.

## Proposal

- A `ProcessGraphPool` behind the same `pool=` seam `@flow` already
  accepts (`CP-021`): same bind/result surface as `GraphPool`.
- Tasks must be picklable: module-level functions, picklable arguments.
- Run-log attempt records move to future completion in the parent (a
  worker cannot write the shared `RunLog` across a process boundary), or
  cross via a queue.

## Cost

- Picklability requirements documented and enforced (decoration-time
  check impossible; failure surfaces at submit).
- Result transport cost for large returns (mitigated by the
  return-a-`Path` convention, `CP-020`).
- Windows and macOS spawn semantics; the `_context` `ContextVar`
  restoration path is thread-specific and needs a process counterpart.

## Evidence

- `DR-005` Phase 5 defers this explicitly.
- No current failing use case; raised as capacity, not pain.
