---
id: IMP-011
type: imp
title: Run identity and by-reference history params
summary: Add run id and workflow digest to RunHistory, cap recorded param depth with a summary mode
date: 2026-10-12
status: current
---

# Run identity and by-reference history params

Third of five patch batches from the 2026-10-12 implementation review. Build order:
IMP-009 first, then IMP-010, IMP-011, IMP-012, IMP-013.

## Pain

- No run identity: `RunHistory` carries no run id, no digest of the workflow
  XML, no registry fingerprint; two runs are indistinguishable in their records.
- The paper's audit story ("stakeholders can audit exactly how a simulation
  result was obtained") needs the workflow identity. Git-in-archive version
  control stays out of scope per `INFO-001`; the gap must close inside the
  history layer instead.
- Recorded `params` embed all upstream results; a chain of n dict-returning
  actions costs O(n^2) history memory. Conflicts with the paper's
  stable-under-scaling criterion.

## Change

- `RunHistory` gains `run_id` (uuid4) and `source` (sha256 hex digest of the
  workflow XML); `engine.run()` stamps both at start; `ExecutionRecord` carries
  `run_id`.
- `run_workflow` / `Test_Framework` gain `params_mode` (`"full"` default,
  `"summary"`); `"summary"` replaces dict, list and tuple param values with item
  counts (the shape `library.py` `_summary` emits). Deterministic, small.
  Default `"full"` keeps zero behavior change.
- The artifact store (IMP-005) stays the by-reference plane for bulk payloads;
  `params_mode="summary"` is the history-side half of that split.

## Verification

- `tests/workflow/test_history.py`: run id present and unique per run; summary
  mode shrinks records; replay unaffected in `"full"` mode.
- Suite green; `pb check --strict` green.
