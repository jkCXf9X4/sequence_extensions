---
id: IMP-018
type: imp
title: Pickle payload tier for run-log values
summary: jsonable falls back to str() for values JSON cannot express; an optional deferred pickle sidecar would preserve full structure
date: 2026-10-14
status: current
---

# Pickle payload tier for run-log values

Candidate, not selected. Deferred by `DR-005` (Phase 5: on demand only).

## Pain

- `jsonable` serializes what JSON knows and falls back to `str(value)`
  for the rest — the log loses structure for exotic results (custom
  objects, arrays).
- The convention (return a `Path`; log path plus sha256, `CP-020`)
  covers the real cases; structured inline values are a convenience.

## Proposal

- An optional deferred pickle tier: a non-JSON value is pickled to a
  sidecar file next to the log; the record carries path plus sha256, the
  same shape as the Path convention.
- Pickle stays a payload cache for rare manual re-execution, never the
  record itself (opaque, version-fragile, unsafe on untrusted logs).

## Cost

- `SCHEMA_VERSION` bump and reader support in `RunLog.records`.
- Pickles are not stable across Python versions — audit value decays.
- Determinism review: unpickling must never run on an untrusted log.

## Evidence

- `DR-005` Phase 5 defers this explicitly.
- No current failing use case; the `str()` fallback is lossy but truthful.
