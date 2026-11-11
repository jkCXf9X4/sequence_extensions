---
id: CP-034
type: capability
title: See an override's effect before the run
date: 2026-11-11
status: current
summary: A before/after view — which nodes an override reaches and what each receives — from re-planning and comparing the plan documents
---

# See an override's effect before the run

## Scenario

- An operator deciding whether a change is safe asks: "show me which nodes
  this override reaches and what each will receive."
- The answer is a before/after view: each changed node, its old value, its new
  value; unchanged nodes visibly unchanged.

## Acceptance

- Re-planning with the override produces a plan document that differs from the
  baseline exactly where the override lands.
- The before/after comparison shows the old and new value per changed input.
- The comparison is deterministic: same flow and inputs, same result.

## Evidence

- `tests/flow/test_plan_document.py`

## Owns

- The pre-run safety need: see exactly what a change will do before committing
  to it.

## Excludes

- Diffing completed runs: `CP-025`.
- The "old value" being the default, not a past run's value: `IMP-023` cost.