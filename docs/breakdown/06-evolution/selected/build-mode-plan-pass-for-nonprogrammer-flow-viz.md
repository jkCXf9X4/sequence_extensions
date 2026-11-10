---
id: IMP-023
type: imp
title: Build-mode plan pass: pre-execution flow graph for non-programmers
summary: Running a composite body with a construct-only submit yields the pre-execution DAG for flow visualization and per-node input defaults; requires a deliberate INFO-001 vision change
date: 2026-11-10
status: proposed
---

# Build-mode plan pass: pre-execution flow graph for non-programmers

Candidate, not selected. Captures the 2026-11-10 design discussion; conflicts
with `INFO-001` line 52 and needs a deliberate vision change first.

## Pain

- Non-programmers cannot visualize a predefined flow or tune its inputs: flows
  are plain Python callables; the graph exists only as it executes.
- Edges are implicit (futures as args), never serialized; the run log records
  executed `path`/`parent_attempt` chains, not explicit DAG edges.
- `INFO-001` line 52 declares plan-before-execution out of scope.

## Proposal

- Build-mode plan pass: run a composite body once with a construct-only `submit`
  (records the edge, returns the future, never schedules) to yield the full DAG
  for that run before any leaf executes.
- Works because a body is pure orchestration: `submit` plus deterministic stdlib.
  A fan-out comprehension expands to N nodes when the list is concrete inline.
- Parameter customization: per-node default inputs merged at submit (missing
  kwargs filled from a registry keyed by node name); the top-card form renders
  the root's signature via introspection.
- Log: the build pass emits a `plan` record (nodes, edges, params, policy) so the
  log carries plan plus trace and is diffable; build stays a read-only pre-pass,
  not a second execution model, keeping plain code and the one node primitive.

## Cost

- Requires softening `INFO-001` line 52; body must stay pure orchestration and
  parameters must be known up front.
- Fan-out expansion only when the iterated list is concrete inside the body; wrap
  the producer in a future and the fan-out collapses to a single node.
- Body runs twice (build, then execute); plan equals execution only for stable
  inputs.
- A direct heavy call inside a body (not via `submit`) runs during visualization.

## Evidence

- `FlowFuture`/`GraphFuture` have no `__iter__`/`__getitem__`; `.result()` in a
  body is rejected by design (`flow/_futures.py:62-65`; tests `test_nested.py:242`,
  `test_node.py:448`).
- Edges are captured at construction (`graph/graph_future.py:97-98`); args resolve
  before the body runs (`graph_future.py:289-302`).
- The run log records `path`/`parent_attempt`, not explicit edges
  (`flow/_records.py`).
- `INFO-001` line 52 declares the capability out of scope; `INFO-011` documents
  the one-primitive engine.
- `DR-005` superseded an older node-tree layer; this proposal keeps plain code, so
  it corrects only the "impossible" claim, not the model.