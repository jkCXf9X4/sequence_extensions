---
id: CP-031
type: capability
title: See a flow before it runs
date: 2026-11-11
status: current
summary: The complete pre-execution task graph, fan-out width, and parameter values, as one plan document; nothing executed, no log written
---

# See a flow before it runs

## Scenario

- A non-programmer handed a predefined campaign asks: "show me what this run
  will do before it starts" — which tasks, in which order, how wide each
  fan-out.
- The answer is a complete picture of the run's task graph and fan-out width,
  with nothing executed, no data touched, no log written.

## Acceptance

- One plan document lists every node in bind order, its kind, its policy, and
  its incoming dependencies as explicit edges.
- The document is deterministic: the same flow and inputs give the same plan.
- The run's body executes nothing beyond pure orchestration during planning.

## Evidence

- `tests/flow/test_plan_document.py`

## Owns

- The pre-execution visibility need: complete graph, fan-out width, and
  parameter surface before any node runs.

## Excludes

- How the plan pass works: `INFO-011` and `IMP-023`.
- The run-log view of what a run did: `CP-024`.