---
id: CP-018
type: capability
title: UC-18 Order dependent tasks — general DAG
summary: tasks may depend on other tasks in any shape, joins and diamonds included; a dependent task receives its dependency's result; cycles are rejected at declaration
date: 2026-10-14
status: current
---

# UC-18 Order dependent tasks — general DAG

## Scenario

- Evaluate needs the simulation result; aggregate needs every evaluation. A join needs two independent upstreams.
- The dependency shape is whatever the work needs: fan-out, fan-in, diamonds.
- A dependency must finish before its dependent starts.

## Acceptance

- A dependent task never starts before its dependency finishes.
- A dependent task receives its dependency's result as its input.
- A circular dependency is rejected when declared, not at deadlock.

## Evidence

- `tests/flow/test_task.py::test_submit_future_argument_becomes_dependency`
- `tests/flow/test_task.py::test_submit_future_as_keyword_argument`
- `tests/graph/test_graph_future.py` — substrate edge semantics and cycle detection.

## Owns

- The task-ordering need and its dependency-safety acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Independent tasks at the same time: `CP-017`.
- A failed dependency's effect on dependents: `CP-020`.
