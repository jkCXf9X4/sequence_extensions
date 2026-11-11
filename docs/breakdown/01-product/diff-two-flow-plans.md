---
id: CP-035
type: capability
title: Diff two flow plans
date: 2026-11-11
status: current
summary: A plain-data diff of two plan documents — added, removed, or re-wired nodes and changed defaults; identical plans compare equal
---

# Diff two flow plans

## Scenario

- A reviewer comparing a flow before and after a code or input change asks:
  "show what changed: added, removed, or re-wired nodes, changed defaults."
- The answer is a plain-data diff of the two plans; identical plans compare
  equal.

## Acceptance

- The diff reports added, removed, or re-wired nodes and changed defaults, as
  plain data.
- Two identical plan documents diff to "equal" with no changes.
- The diff is deterministic: the same pair of plans gives the same result.

## Evidence

- `tests/flow/test_plan_document.py`

## Owns

- The plan-comparison need: see what changed between two plans of the same
  flow.

## Excludes

- Diffing completed runs: `CP-025`.
- Stable node identity across reordering: an open strain, tracked in
  `IMP-023`.