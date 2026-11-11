---
id: CP-033
type: capability
title: Override an input for a whole node kind
date: 2026-11-11
status: current
summary: One edited plan document sets a value for every node of a kind; explicit values written in code keep winning
---

# Override an input for a whole node kind

## Scenario

- An operator who knows what to change but not where it lands asks: "set
  tolerance to 0.7 for every evaluation in this run."
- The override applies to every node of that kind in the graph; the value
  flows into each occurrence; explicit values written in code keep winning.

## Acceptance

- Editing one value in the plan document changes the input for every node
  sharing that name.
- A parameter the code passes explicitly is never overridden by the document.
- An unknown node or parameter name in the override is rejected before the run
  starts, never mid-run.

## Evidence

- `tests/flow/test_plan_document.py`

## Owns

- The per-node-kind tuning need: one change, every occurrence, code stays in
  charge.

## Excludes

- How overrides merge into a run: `RunOptions.parameters` per `IMP-023`.
- The file-driven run options and node defaults: `CP-026`.